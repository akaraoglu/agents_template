from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import socket
import stat
import subprocess
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import Field

from ..canonical import canonical_sha256
from ..catalog import Catalog
from ..evidence import workspace_manifest
from ..models import ContextPack, PermissionOperation, PermissionResource, RoleInstance
from .base import (
    DefectPacket,
    DraftTurn,
    PreflightReceipt,
    ProbeResult,
    RenderedContext,
    RuntimeBackendError,
    RuntimeModel,
    RuntimeOutputError,
    RuntimePreflightError,
    RuntimeSessionError,
    STAGE_SEMANTIC_ADAPTER,
    SemanticResponse,
    StageSemantic,
)


PINNED_CODEX_VERSION = "0.146.1"
PINNED_SYSTEMD_VERSION = "255"
DEFAULT_CODEX_EXECUTABLE = Path("/home/linuxbrew/.linuxbrew/bin/codex")
DEFAULT_SYSTEMD_RUN = Path("/usr/bin/systemd-run")
DEFAULT_SYSTEMCTL = Path("/usr/bin/systemctl")
DEFAULT_OLLAMA_ENDPOINT = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "qwen3.6-27b:latest"
CATALOG_MODEL = "qwen3.6-27b"
MAX_GUIDANCE_BYTES = 16 * 1024
_SAFE_PATH = "/usr/bin:/bin"
_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_CODEX_TARGET = "x86_64-unknown-linux-musl"
_CODEX_PLATFORM_PACKAGE = "codex-linux-x64"


class _FilePin(RuntimeModel):
    path: str
    device: int
    inode: int
    mode: int
    owner: int
    group: int
    digest: str = Field(pattern=_DIGEST_PATTERN)


class _ExecutableMaterial(RuntimeModel):
    source: _FilePin
    source_chain: tuple[_FilePin, ...] = Field(min_length=1)
    source_chain_digest: str = Field(pattern=_DIGEST_PATTERN)
    runtime: _FilePin


class _RuntimeMaterial(RuntimeModel):
    source_profile_digest: str = Field(pattern=_DIGEST_PATTERN)
    source_profile_device: int
    source_profile_inode: int
    source_catalog_digest: str = Field(pattern=_DIGEST_PATTERN)
    source_catalog_device: int
    source_catalog_inode: int
    selected_record_digest: str = Field(pattern=_DIGEST_PATTERN)
    selected_context_window: int | None = Field(default=None, gt=0)
    config_digest: str = Field(pattern=_DIGEST_PATTERN)
    profile_digest: str = Field(pattern=_DIGEST_PATTERN)
    catalog_digest: str = Field(pattern=_DIGEST_PATTERN)
    effective_config: dict[str, Any]
    effective_config_digest: str = Field(pattern=_DIGEST_PATTERN)


class _SystemdMaterial(RuntimeModel):
    systemd_run: _FilePin
    systemctl: _FilePin
    version: str = Field(min_length=1)


class CodexSessionInfo(RuntimeModel):
    thread_id: str = Field(min_length=1)
    source_executable: _FilePin
    source_chain: tuple[_FilePin, ...] = Field(min_length=1)
    source_chain_digest: str = Field(pattern=_DIGEST_PATTERN)
    runtime_executable: _FilePin
    executable_version: str = Field(min_length=1)
    systemd: _SystemdMaterial
    logical_profile: str = Field(min_length=1)
    material: _RuntimeMaterial
    model: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    ollama_model: str = Field(min_length=1)
    ollama_model_digest: str = Field(pattern=_DIGEST_PATTERN)
    backend_id: str = Field(min_length=1)
    role_instance_id: str = Field(min_length=1)
    role_instance_digest: str = Field(pattern=_DIGEST_PATTERN)
    context_digest: str = Field(pattern=_DIGEST_PATTERN)
    workspace: str = Field(min_length=1)
    canary_root: str = Field(min_length=1)
    private_codex_home: str = Field(min_length=1)
    outer_sandbox: Literal[
        "host-parent-native-workspace-write", "host-parent-native-read-only"
    ]
    command_config: tuple[str, ...]
    phase: Literal["draft", "resume", "feedback", "candidate"]
    turn: int = Field(ge=1)


class _ProcessResult(RuntimeModel):
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_seconds: float


class CodexRuntimeAdapter:
    """Fail-closed host Codex adapter using its native command sandbox."""

    def __init__(
        self,
        *,
        catalog: Catalog,
        executable: str | Path = DEFAULT_CODEX_EXECUTABLE,
        profile: str = "qwen36-27b",
        codex_home: str | Path | None = None,
        timeout_seconds: int = 600,
        overall_timeout_seconds: int | None = 3600,
        ollama_endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
        ollama_model: str = DEFAULT_OLLAMA_MODEL,
        expected_version: str = PINNED_CODEX_VERSION,
        test_executable_root: str | Path | None = None,
        _test_only_allow_executable_root: bool = False,
        _test_only_systemd_root: str | Path | None = None,
    ) -> None:
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        if overall_timeout_seconds is not None and overall_timeout_seconds < 1:
            raise ValueError("overall_timeout_seconds must be positive")
        supplied = Path(executable).expanduser()
        source_home = Path(codex_home or Path.home() / ".codex").expanduser()
        if not supplied.is_absolute() or not source_home.is_absolute():
            raise ValueError("Codex executable and source home must be absolute paths")
        if test_executable_root is not None and not _test_only_allow_executable_root:
            raise ValueError("test_executable_root is available only to the internal fake harness")
        if _test_only_systemd_root is not None and not _test_only_allow_executable_root:
            raise ValueError("_test_only_systemd_root is available only to the internal fake harness")
        self.catalog = catalog
        self.executable = supplied
        self.profile = profile
        self.source_codex_home = source_home
        self.timeout_seconds = timeout_seconds
        self.overall_timeout_seconds = overall_timeout_seconds
        self.ollama_endpoint = ollama_endpoint.rstrip("/")
        self.ollama_model = ollama_model
        self.expected_version = expected_version
        self.test_executable_root = (
            Path(test_executable_root).expanduser() if test_executable_root is not None else None
        )
        systemd_root = (
            Path(_test_only_systemd_root).expanduser()
            if _test_only_systemd_root is not None else DEFAULT_SYSTEMD_RUN.parent
        )
        if not systemd_root.is_absolute():
            raise ValueError("systemd tool root must be absolute")
        self._systemd_run = systemd_root / DEFAULT_SYSTEMD_RUN.name
        self._systemctl = systemd_root / DEFAULT_SYSTEMCTL.name
        self._test_systemd = _test_only_systemd_root is not None
        self._executable_cache_owner = tempfile.TemporaryDirectory(
            prefix="codexteam-v2-private-bin-", dir="/tmp"
        )
        Path(self._executable_cache_owner.name).chmod(0o700)
        self._started = time.monotonic()
        self._sessions: dict[str, CodexSessionInfo] = {}
        self._roles: dict[str, RoleInstance] = {}
        self._role_executables: dict[str, _ExecutableMaterial] = {}
        self._role_material: dict[str, _RuntimeMaterial] = {}
        self._preflight_sources: dict[str, tuple[_FilePin, _FilePin, str]] = {}
        self._systemd_material: _SystemdMaterial | None = None
        self._systemd_probes: tuple[ProbeResult, ...] | None = None

    @property
    def sessions(self) -> dict[str, str]:
        return {
            role.stage_id: session.thread_id
            for session in self._sessions.values()
            if (role := self._roles.get(session.thread_id)) is not None
        }

    def _remaining_timeout(self) -> int:
        if self.overall_timeout_seconds is None:
            return self.timeout_seconds
        remaining = self.overall_timeout_seconds - (time.monotonic() - self._started)
        if remaining <= 0:
            raise RuntimeBackendError("Codex canary overall timeout expired")
        return max(1, min(self.timeout_seconds, int(remaining)))

    @staticmethod
    def _read_pinned(
        path: Path, label: str, *, owners: set[int],
        allow_owner_group_write_data: bool = False,
    ) -> tuple[bytes, _FilePin]:
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        except OSError as exc:
            raise RuntimePreflightError(f"{label} is unavailable or is a symlink") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimePreflightError(f"{label} must be a regular file")
            if metadata.st_uid not in owners:
                raise RuntimePreflightError(f"{label} has an untrusted owner")
            if metadata.st_mode & stat.S_IWOTH:
                raise RuntimePreflightError(f"{label} must not be world writable")
            if allow_owner_group_write_data:
                if metadata.st_uid == 0:
                    if metadata.st_mode & stat.S_IWGRP:
                        raise RuntimePreflightError(f"{label} must not be group writable")
                elif metadata.st_uid == os.getuid():
                    current_groups = {os.getgid(), os.getegid(), *os.getgroups()}
                    if metadata.st_gid not in current_groups:
                        raise RuntimePreflightError(
                            f"{label} group is not one of the current user's groups"
                        )
                else:
                    raise RuntimePreflightError(f"{label} must be owned by the current user")
            elif metadata.st_mode & stat.S_IWGRP:
                raise RuntimePreflightError(f"{label} must not be group writable")
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            content = b"".join(chunks)
        finally:
            os.close(descriptor)
        return content, _FilePin(
            path=str(path), device=metadata.st_dev, inode=metadata.st_ino,
            mode=stat.S_IMODE(metadata.st_mode), owner=metadata.st_uid,
            group=metadata.st_gid,
            digest=hashlib.sha256(content).hexdigest(),
        )

    @staticmethod
    def _read_owned_source_material(path: Path, label: str) -> tuple[bytes, _FilePin]:
        return CodexRuntimeAdapter._read_pinned(
            path, label, owners={0, os.getuid()}, allow_owner_group_write_data=True,
        )

    def _pin_executable(self, supplied: Path, label: str, *, root_only: bool = False) -> _FilePin:
        try:
            resolved = supplied.resolve(strict=True)
        except OSError as exc:
            raise RuntimePreflightError(f"{label} is unavailable") from exc
        _, pin = self._read_pinned(
            resolved, label, owners={0} if root_only else {0, os.getuid()}
        )
        return pin

    @staticmethod
    def _json_object(content: bytes, label: str) -> dict[str, Any]:
        try:
            value = json.loads(content)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimePreflightError(f"{label} is not valid JSON") from exc
        if not isinstance(value, dict):
            raise RuntimePreflightError(f"{label} must contain a JSON object")
        return value

    @staticmethod
    def _validate_x64_linux_elf(content: bytes) -> None:
        if (
            len(content) < 20
            or content[:4] != b"\x7fELF"
            or content[4] != 2
            or content[5] != 1
            or int.from_bytes(content[18:20], "little") != 62
        ):
            raise RuntimePreflightError("Codex package target is not an x86_64 Linux binary")

    @staticmethod
    def _source_chain_digest(source_chain: tuple[_FilePin, ...]) -> str:
        return canonical_sha256(source_chain)

    def _source_executable(self) -> tuple[bytes, _FilePin, tuple[_FilePin, ...], str]:
        try:
            supplied = self.executable.resolve(strict=True)
        except OSError as exc:
            raise RuntimePreflightError("Codex executable is unavailable") from exc
        if supplied.suffix == ".js":
            launcher_bytes, launcher_pin = self._read_owned_source_material(
                supplied, "Codex source executable",
            )
        else:
            launcher_bytes, launcher_pin = self._read_pinned(
                supplied, "Codex source executable", owners={0, os.getuid()},
            )
        first_line = launcher_bytes.splitlines()[0] if launcher_bytes else b""
        if supplied.suffix != ".js" and b"node" not in first_line:
            if self.test_executable_root is None:
                self._validate_x64_linux_elf(launcher_bytes)
            source_chain = (launcher_pin,)
            return (
                launcher_bytes, launcher_pin, source_chain,
                self._source_chain_digest(source_chain),
            )
        if supplied.name != "codex.js" or supplied.parent.name != "bin":
            raise RuntimePreflightError("Codex JS launcher is outside the known package structure")
        package_root = supplied.parent.parent
        package_bytes, package_pin = self._read_owned_source_material(
            package_root / "package.json", "Codex launcher package metadata",
        )
        package = self._json_object(package_bytes, "Codex launcher package metadata")
        if (
            package.get("name") != "@openai/codex"
            or package.get("version") != self.expected_version
            or package.get("bin") != {"codex": "bin/codex.js"}
        ):
            raise RuntimePreflightError("Codex JS launcher package metadata is not pinned")
        platform_root = package_root / "node_modules" / "@openai" / _CODEX_PLATFORM_PACKAGE
        target_bytes, target_pin = self._read_owned_source_material(
            platform_root / "package.json", "Codex platform package metadata",
        )
        target = self._json_object(target_bytes, "Codex platform package metadata")
        if (
            target.get("name") != "@openai/codex"
            or target.get("version") != f"{self.expected_version}-linux-x64"
            or target.get("os") != ["linux"]
            or target.get("cpu") != ["x64"]
        ):
            raise RuntimePreflightError("Codex platform package is not the pinned x86_64 Linux target")
        native = platform_root / "vendor" / _CODEX_TARGET / "bin" / "codex"
        content, pin = self._read_owned_source_material(
            native, "Codex source executable",
        )
        self._validate_x64_linux_elf(content)
        source_chain = (launcher_pin, package_pin, target_pin, pin)
        return content, pin, source_chain, self._source_chain_digest(source_chain)

    @staticmethod
    def _private_directory(parent: Path, name: str) -> Path:
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            descriptor = os.open(
                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
            )
            try:
                metadata = os.fstat(descriptor)
                if metadata.st_uid != os.getuid():
                    raise RuntimeSessionError("private executable directory has an unexpected owner")
                os.fchmod(descriptor, 0o700)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise RuntimeSessionError("private executable directory is unavailable") from exc
        finally:
            os.close(parent_fd)
        return parent / name

    def _pin_runtime_executable(self, path: Path) -> _FilePin:
        try:
            _, pin = self._read_pinned(path, "private Codex executable", owners={os.getuid()})
        except RuntimePreflightError as exc:
            raise RuntimeSessionError(str(exc)) from exc
        if pin.mode != 0o500:
            raise RuntimeSessionError("private Codex executable mode must be 0500")
        return pin

    def _stage_private_executable(
        self, runtime: Path, source_bytes: bytes, source: _FilePin, *,
        source_chain: tuple[_FilePin, ...], source_chain_digest: str,
    ) -> _ExecutableMaterial:
        directory = self._private_directory(runtime, "bin")
        target = directory / "codex"
        try:
            runtime_pin = self._pin_runtime_executable(target)
        except RuntimeSessionError:
            if os.path.lexists(target):
                raise
            runtime_pin = None
        if runtime_pin is not None:
            if runtime_pin.digest != source.digest:
                raise RuntimeSessionError("private Codex executable digest differs from source")
            return _ExecutableMaterial(
                source=source, source_chain=source_chain,
                source_chain_digest=source_chain_digest, runtime=runtime_pin,
            )
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptor = -1
        created = False
        try:
            descriptor = os.open(
                "codex", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o500, dir_fd=directory_fd,
            )
            created = True
            os.fchmod(descriptor, 0o500)
            view = memoryview(source_bytes)
            while view:
                written = os.write(descriptor, view)
                if written == 0:
                    raise OSError("short write while staging Codex executable")
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.fsync(directory_fd)
        except OSError as exc:
            if created:
                try:
                    os.unlink("codex", dir_fd=directory_fd)
                except OSError:
                    pass
            raise RuntimeSessionError("could not stage private Codex executable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(directory_fd)
        runtime_pin = self._pin_runtime_executable(target)
        if runtime_pin.digest != source.digest:
            raise RuntimeSessionError("private Codex executable digest differs from source")
        return _ExecutableMaterial(
            source=source, source_chain=source_chain,
            source_chain_digest=source_chain_digest, runtime=runtime_pin,
        )

    def _prepare_role_executable(self, workspace: Path, role: RoleInstance) -> _ExecutableMaterial:
        content, source, source_chain, source_chain_digest = self._source_executable()
        material = self._stage_private_executable(
            self._executable_dir(workspace, role), content, source,
            source_chain=source_chain, source_chain_digest=source_chain_digest,
        )
        self._role_executables[role.role_instance_id] = material
        return material

    @staticmethod
    def _same_pin(observed: _FilePin, expected: _FilePin, label: str) -> None:
        if observed != expected:
            raise RuntimeSessionError(f"{label} identity changed")

    def _same_source_chain(
        self, observed: tuple[_FilePin, ...], observed_digest: str,
        expected: tuple[_FilePin, ...], expected_digest: str,
    ) -> None:
        if self._source_chain_digest(observed) != observed_digest:
            raise RuntimeSessionError("Codex source chain digest is invalid")
        if observed != expected or observed_digest != expected_digest:
            raise RuntimeSessionError("Codex source chain identity changed")

    @staticmethod
    def _clean_environment(codex_home: str) -> dict[str, str]:
        environment = {
            "PATH": _SAFE_PATH,
            "HOME": f"{codex_home}/home",
            "CODEX_HOME": codex_home,
            "XDG_CONFIG_HOME": f"{codex_home}/xdg/config",
            "XDG_CACHE_HOME": f"{codex_home}/xdg/cache",
            "XDG_DATA_HOME": f"{codex_home}/xdg/data",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        runtime = f"/run/user/{os.getuid()}"
        environment["XDG_RUNTIME_DIR"] = runtime
        environment["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime}/bus"
        return environment

    def _systemd_environment(self) -> dict[str, str]:
        return self._clean_environment("/nonexistent-codex-home")

    def _pin_systemd(self) -> _SystemdMaterial:
        owners = {os.getuid()} if self._test_systemd else {0}
        _, run = self._read_pinned(
            self._systemd_run, "systemd-run executable", owners=owners
        )
        _, control = self._read_pinned(
            self._systemctl, "systemctl executable", owners=owners
        )
        versions: list[str] = []
        for pin, label in ((run, "systemd-run"), (control, "systemctl")):
            try:
                completed = subprocess.run(
                    (pin.path, "--version"), stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False,
                    env=self._systemd_environment(), timeout=10, check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise RuntimePreflightError(f"{label} version probe failed") from exc
            first = completed.stdout.splitlines()[0] if completed.stdout else ""
            if completed.returncode != 0 or re.match(
                rf"^systemd {re.escape(PINNED_SYSTEMD_VERSION)}(?:\s|$)", first
            ) is None:
                raise RuntimePreflightError(
                    f"{label} version mismatch: expected systemd {PINNED_SYSTEMD_VERSION!s}"
                )
            versions.append(first)
        if versions[0] != versions[1]:
            raise RuntimePreflightError("systemd-run and systemctl versions differ")
        material = _SystemdMaterial(
            systemd_run=run, systemctl=control, version=PINNED_SYSTEMD_VERSION,
        )
        self._systemd_material = material
        return material

    def _require_systemd(self, expected: _SystemdMaterial | None = None) -> _SystemdMaterial:
        observed = self._pin_systemd()
        pinned = expected or self._systemd_material
        if pinned is not None and observed != pinned:
            raise RuntimeSessionError("pinned systemd executable identity changed")
        return observed

    @staticmethod
    def _scope_unit(role_id: str, turn: str) -> str:
        role = re.sub(r"[^a-z0-9]", "-", role_id.lower()).strip("-")[:24] or "role"
        phase = re.sub(r"[^a-z0-9]", "-", turn.lower()).strip("-")[:18] or "turn"
        nonce = secrets.token_hex(6)
        return f"ctv2-{role}-{phase}-{nonce}"[:63].rstrip("-")

    @staticmethod
    def _scope_name(unit: str) -> str:
        return f"{unit}.scope"

    def _scope_argv(self, unit: str, command: list[str]) -> list[str]:
        material = self._systemd_material or self._require_systemd()
        return [
            material.systemd_run.path, "--user", "--scope", "--quiet", f"--unit={unit}",
            "--property=KillMode=control-group",
            "--property=CollectMode=inactive-or-failed", "--", *command,
        ]

    def _systemctl_run(self, *args: str) -> subprocess.CompletedProcess[str]:
        material = self._systemd_material or self._require_systemd()
        try:
            return subprocess.run(
                (material.systemctl.path, "--user", *args), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False,
                env=self._systemd_environment(), timeout=5, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeBackendError("HIGH: user-systemd control command failed") from exc

    def _scope_state(self, unit: str) -> tuple[str, str, str]:
        completed = self._systemctl_run(
            "show", self._scope_name(unit), "--property=LoadState",
            "--property=ActiveState", "--property=SubState",
        )
        if completed.returncode != 0:
            raise RuntimeBackendError(
                "HIGH: could not verify user-systemd scope state: " + completed.stderr.strip()
            )
        values = {}
        for line in completed.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value
        try:
            return values["LoadState"], values["ActiveState"], values["SubState"]
        except KeyError as exc:
            raise RuntimeBackendError("HIGH: user-systemd scope state was incomplete") from exc

    def _wait_scope_inactive(self, unit: str, *, timeout: float = 5.0) -> tuple[bool, str]:
        deadline = time.monotonic() + timeout
        last = "unknown"
        while True:
            load, active, sub = self._scope_state(unit)
            last = f"LoadState={load},ActiveState={active},SubState={sub}"
            if load == "not-found" or active == "inactive":
                return True, last
            if time.monotonic() >= deadline:
                return False, last
            time.sleep(0.05)

    def _kill_scope(self, unit: str) -> str:
        completed = self._systemctl_run(
            "kill", "--kill-whom=all", "--signal=SIGKILL", self._scope_name(unit)
        )
        if completed.returncode != 0 and "not loaded" not in completed.stderr.lower():
            return f"kill-failed:{completed.returncode}:{completed.stderr.strip()}"
        return "kill-requested" if completed.returncode == 0 else "already-gone"

    def _reset_scope(self, unit: str) -> None:
        for args in (
            ("reset-failed", self._scope_name(unit)),
            ("clean", self._scope_name(unit), "--what=all"),
        ):
            try:
                self._systemctl_run(*args)
            except RuntimeBackendError:
                pass

    def _containment_probe(self) -> tuple[ProbeResult, ...]:
        if self._systemd_probes is not None:
            return self._systemd_probes
        self._require_systemd()
        environment = self._systemd_environment()
        normal_unit = self._scope_unit("probe", "normal")
        try:
            normal = subprocess.run(
                self._scope_argv(
                    normal_unit, ["/usr/bin/python3", "-c", "print('scope-ok')"]
                ),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, shell=False, env=environment, timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._kill_scope(normal_unit)
            gone, state = self._wait_scope_inactive(normal_unit)
            if gone:
                self._reset_scope(normal_unit)
            raise RuntimePreflightError(
                f"user-systemd normal scope probe could not run (cleanup={state})"
            ) from exc
        normal_inactive, normal_state = self._wait_scope_inactive(normal_unit)
        if normal.returncode != 0 or normal.stdout.strip() != "scope-ok" or not normal_inactive:
            self._kill_scope(normal_unit)
            gone, state = self._wait_scope_inactive(normal_unit)
            if gone:
                self._reset_scope(normal_unit)
            raise RuntimePreflightError(
                f"user-systemd normal scope probe failed ({normal_state}; cleanup={state})"
            )
        self._reset_scope(normal_unit)

        marker_fd, marker_name = tempfile.mkstemp(prefix="codexteam-v2-scope-probe-", dir="/tmp")
        os.close(marker_fd)
        marker = Path(marker_name)
        marker.unlink()
        detached_unit = self._scope_unit("probe", "detached")
        script = (
            "import subprocess,sys\n"
            "subprocess.Popen(['/usr/bin/setsid','/usr/bin/sh','-c',"
            "'sleep .35; printf bad > \"$1\"','sh',sys.argv[1]],"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
        )
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                self._scope_argv(
                    detached_unit, ["/usr/bin/python3", "-c", script, str(marker)]
                ),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, shell=False, env=environment,
            )
            process.communicate(timeout=5)
        except BaseException as exc:
            self._kill_scope(detached_unit)
            if process is not None:
                process.communicate()
            gone, state = self._wait_scope_inactive(detached_unit)
            if gone:
                self._reset_scope(detached_unit)
            marker.unlink(missing_ok=True)
            raise RuntimePreflightError(
                f"user-systemd detached scope probe failed (cleanup={state})"
            ) from exc
        cleanup = self._kill_scope(detached_unit)
        gone, state = self._wait_scope_inactive(detached_unit)
        if gone:
            self._reset_scope(detached_unit)
        time.sleep(0.5)
        escaped = marker.exists()
        marker.unlink(missing_ok=True)
        if not gone or escaped:
            raise RuntimePreflightError(
                "user-systemd did not contain a detached setsid descendant "
                f"({cleanup}; {state}; marker={escaped})"
            )
        self._systemd_probes = (
            ProbeResult(
                operation=PermissionOperation.EXECUTE, resource=PermissionResource.PROCESS,
                status="passed",
                evidence_summary="Pinned user-systemd ran a normal transient scope and returned output.",
            ),
            ProbeResult(
                operation=PermissionOperation.EXECUTE, resource=PermissionResource.PROCESS,
                status="passed",
                evidence_summary=(
                    "KillMode=control-group contained a detached setsid descendant; "
                    "the scope became inactive and its delayed marker was absent."
                ),
            ),
        )
        return self._systemd_probes

    def _version(self, pin: _FilePin) -> str:
        try:
            completed = subprocess.run(
                (pin.path, "--version"), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False,
                env=self._clean_environment("/nonexistent-codex-home"),
                timeout=min(10, self._remaining_timeout()), check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimePreflightError("Codex version probe failed") from exc
        observed = completed.stdout.strip()
        expected = f"codex-cli {self.expected_version}"
        if completed.returncode != 0 or observed != expected:
            raise RuntimePreflightError(
                f"Codex version mismatch: expected {expected!r}, observed {observed!r}"
            )
        return self.expected_version

    def _source_material(self) -> tuple[bytes, _FilePin, bytes, _FilePin, dict[str, Any], str]:
        if not self.profile or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for character in self.profile
        ):
            raise RuntimePreflightError("Codex profile name is invalid")
        profile_bytes, profile_pin = self._read_pinned(
            self.source_codex_home / f"{self.profile}.config.toml",
            "Codex source profile", owners={0, os.getuid()},
        )
        try:
            values = tomllib.loads(profile_bytes.decode("utf-8"))
        except (UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise RuntimePreflightError("Codex source profile is not valid TOML") from exc
        if values.get("model") != CATALOG_MODEL:
            raise RuntimePreflightError("Codex source profile differs from the pinned role model")
        if values.get("model_provider") != "ollama_local":
            raise RuntimePreflightError("Codex source profile provider must be ollama_local")
        catalog_value = values.get("model_catalog_json")
        if not isinstance(catalog_value, str) or not Path(catalog_value).is_absolute():
            raise RuntimePreflightError("Codex source profile must name an absolute model catalog")
        catalog_bytes, catalog_pin = self._read_pinned(
            Path(catalog_value), "Codex source model catalog", owners={os.getuid()},
            allow_owner_group_write_data=True,
        )
        try:
            catalog_value_json = json.loads(catalog_bytes)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimePreflightError("Codex source model catalog is not valid JSON") from exc
        models = catalog_value_json.get("models") if isinstance(catalog_value_json, dict) else None
        selected = [item for item in models or () if isinstance(item, dict) and item.get("slug") == CATALOG_MODEL]
        if len(selected) != 1:
            raise RuntimePreflightError("Codex source catalog must contain exactly one qwen3.6-27b record")
        record = selected[0]
        if record.get("slug") != CATALOG_MODEL:
            raise RuntimePreflightError("selected catalog record slug must be qwen3.6-27b")
        provider_values: list[Any] = []
        pending: list[Any] = [record]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                provider_values.extend(
                    item for key, item in value.items() if "provider" in key.lower()
                )
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        if record.get("provider") != "ollama_local" or any(
            value not in (None, "ollama_local") for value in provider_values
        ):
            raise RuntimePreflightError("selected catalog record provider must be ollama_local")
        if record.get("enabled") is not True:
            raise RuntimePreflightError("selected catalog record must be enabled")
        context_values = {
            key: record[key] for key in ("context_window", "max_context_window")
            if key in record
        }
        if any(type(value) is not int or value <= 0 for value in context_values.values()):
            raise RuntimePreflightError("selected catalog context windows must be positive integers")
        if len(context_values) == 2 and len(set(context_values.values())) != 1:
            raise RuntimePreflightError("selected catalog context windows must be equal")
        levels = record.get("supported_reasoning_levels")
        if not isinstance(levels, list) or not any(
            isinstance(level, dict) and level.get("effort") == "medium" for level in levels
        ):
            raise RuntimePreflightError("selected catalog record does not support medium reasoning")
        record_digest = canonical_sha256(record)
        safe_fields = {
            "slug", "display_name", "description", "provider", "enabled",
            "shell_type", "visibility", "supported_in_api", "priority",
            "base_instructions", "model_messages", "supports_reasoning_summaries",
            "default_reasoning_summary", "support_verbosity", "default_verbosity",
            "apply_patch_tool_type", "truncation_policy", "supports_parallel_tool_calls",
            "context_window", "max_context_window", "effective_context_window_percent",
        }
        filtered = {key: record[key] for key in safe_fields if key in record}
        filtered["supported_reasoning_levels"] = [
            level for level in levels
            if isinstance(level, dict) and level.get("effort") == "medium"
        ]
        filtered["experimental_supported_tools"] = []
        filtered["input_modalities"] = ["text"]
        filtered["supports_search_tool"] = False
        filtered_catalog = json.dumps(
            {"models": [filtered]}, sort_keys=True, separators=(",", ":")
        ).encode("utf-8") + b"\n"
        return profile_bytes, profile_pin, catalog_bytes, catalog_pin, filtered, record_digest

    def _effective_config(
        self, role: RoleInstance, *, private_codex_home: Path | None = None
    ) -> dict[str, Any]:
        resolved = self._resolved(role)
        if resolved.model_profile.reasoning_effort != "medium":
            raise RuntimePreflightError("Codex ModelProfile reasoning must be medium")
        if resolved.model_profile.model != CATALOG_MODEL:
            raise RuntimePreflightError("Codex ModelProfile must pin qwen3.6-27b")
        filesystem = {":root": "read"}
        if private_codex_home is not None:
            filesystem = {
                ":root": "read",
                str(Path.home()): "none",
                str(private_codex_home.parents[4] / ".codexteam"): "none",
                self._role_executables[role.role_instance_id].runtime.path: "read",
                str(private_codex_home.parents[4] / "project"): (
                    "write" if self._role_can_write_product(role) else "read"
                ),
            }
        return {
            "model": CATALOG_MODEL,
            "model_provider": "ollama_local",
            "model_catalog_json": str(
                (private_codex_home / "model-catalog.json")
                if private_codex_home is not None else Path("model-catalog.json")
            ),
            "model_reasoning_effort": "medium",
            "model_verbosity": "medium",
            "approval_policy": "never",
            "default_permissions": "codexteam-direct",
            "permissions.codexteam-direct.filesystem": filesystem,
            "permissions.codexteam-direct.network.enabled": False,
            "web_search": "disabled",
            "history.persistence": "none",
            "features.memories": False,
            "features.multi_agent": False,
            "features.apps": False,
            "features.hooks": False,
            "features.browser_use": False,
            "features.in_app_browser": False,
            "features.computer_use": False,
            "features.image_generation": False,
            "features.plugins": False,
            "features.plugin_sharing": False,
            "features.skill_search": False,
            "features.workspace_dependencies": False,
            "check_for_update_on_startup": False,
            "analytics.enabled": False,
            "feedback.enabled": False,
            "model_providers.ollama_local.name": "Ollama localhost only",
            "model_providers.ollama_local.base_url": "http://127.0.0.1:11434/v1",
            "model_providers.ollama_local.wire_api": "responses",
            "mcp_servers": {},
            "hooks": {},
        }

    @staticmethod
    def _toml_literal(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return json.dumps(value, separators=(",", ":"))

    def _config_args(self, config: dict[str, Any]) -> tuple[str, ...]:
        args: list[str] = []
        for key in sorted(config):
            # Encode the special :root key as one inline TOML table. A dotted
            # override such as filesystem.":root" makes the quotes part of the
            # filesystem path in Codex 0.146.1.
            if key == "permissions.codexteam-direct.filesystem":
                filesystem = config[key]
                if not isinstance(filesystem, dict) or not filesystem:
                    raise RuntimePreflightError("Codex filesystem profile must name a root")
                entries = ",".join(
                    f"{self._toml_literal(path)}={self._toml_literal(access)}"
                    for path, access in sorted(filesystem.items())
                )
                args.extend((
                    "-c",
                    f"permissions.codexteam-direct.filesystem={{{entries}}}",
                ))
                continue
            args.extend(("-c", f"{key}={self._toml_literal(config[key])}"))
        return tuple(args)

    def _resolved(self, role: RoleInstance):
        return self.catalog.resolve_agent_spec(
            role.agent_spec.definition_id, role.agent_spec.definition_version
        )

    def _validate_role(self, role: RoleInstance) -> None:
        resolved = self._resolved(role)
        if role.backend.definition_id != "codex" or resolved.backend.backend_id != "codex":
            raise RuntimePreflightError("RoleInstance is not pinned to the Codex backend")
        self._effective_config(role)

    def _runtime_dir(self, workspace: Path, role: RoleInstance) -> Path:
        root = workspace.resolve(strict=True)
        if not root.is_dir():
            raise RuntimeSessionError("workspace must be a directory")
        current = root
        parts = (".codexteam", "v2", "runtime", role.role_instance_id)
        for index, part in enumerate(parts):
            current = current / part
            try:
                current.mkdir(mode=0o700 if index >= 2 else 0o755)
            except FileExistsError:
                pass
            try:
                metadata = current.lstat()
            except OSError as exc:
                raise RuntimeSessionError("runtime directory is unavailable") from exc
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                raise RuntimeSessionError("runtime path must contain only real directories")
            if metadata.st_uid != os.getuid():
                raise RuntimeSessionError("runtime directory has an unexpected owner")
            if index >= 2:
                current.chmod(0o700)
        return current

    def _executable_dir(self, workspace: Path, role: RoleInstance) -> Path:
        workspace.resolve(strict=True)
        cache = Path(self._executable_cache_owner.name)
        return self._private_directory(cache, role.role_instance_id)

    @staticmethod
    def _atomic_write(directory: Path, name: str, content: bytes, *, mode: int = 0o600) -> None:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        temporary = f".{name}.{secrets.token_hex(8)}.tmp"
        descriptor = -1
        try:
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                mode, dir_fd=directory_fd,
            )
            os.fchmod(descriptor, mode)
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written == 0:
                    raise OSError(f"short write while writing {name}")
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
        except OSError as exc:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except OSError:
                pass
            raise RuntimeSessionError(f"could not atomically write {name}") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(directory_fd)

    @staticmethod
    def _read_private(directory: Path, name: str, *, mode: int = 0o600) -> bytes:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
            try:
                metadata = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or stat.S_IMODE(metadata.st_mode) != mode
                    or metadata.st_uid != os.getuid()
                ):
                    raise RuntimeSessionError(f"{name} is not a private current-user regular file")
                chunks: list[bytes] = []
                while chunk := os.read(descriptor, 1024 * 1024):
                    chunks.append(chunk)
                return b"".join(chunks)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise RuntimeSessionError(f"{name} is unavailable") from exc
        finally:
            os.close(directory_fd)

    def _generate_private_home(
        self, workspace: Path, role: RoleInstance, *,
        expected_source: tuple[_FilePin, _FilePin, str] | None = None,
    ) -> tuple[_RuntimeMaterial, tuple[_FilePin, _FilePin, str]]:
        _, source_profile, _, source_catalog, filtered, record_digest = self._source_material()
        source_pin = (source_profile, source_catalog, record_digest)
        if expected_source is not None and source_pin != expected_source:
            raise RuntimePreflightError("Codex source profile or model catalog identity changed since preflight")
        directory = self._runtime_dir(workspace, role)
        home = directory / "codex-home"
        try:
            home.mkdir(mode=0o700)
        except FileExistsError:
            pass
        metadata = home.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise RuntimeSessionError("private Codex home is not a current-user directory")
        home.chmod(0o700)
        for relative in ("home", "xdg", "xdg/config", "xdg/cache", "xdg/data"):
            path = home / relative
            try:
                path.mkdir(mode=0o700)
            except FileExistsError:
                pass
            metadata = path.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or metadata.st_uid != os.getuid()
            ):
                raise RuntimeSessionError("private Codex home contains an unsafe directory")
            path.chmod(0o700)
        filtered_catalog = json.dumps(
            {"models": [filtered]}, sort_keys=True, separators=(",", ":")
        ).encode("utf-8") + b"\n"
        config = self._effective_config(role, private_codex_home=home)
        filesystem = config["permissions.codexteam-direct.filesystem"]
        config_lines = [
            f'model = "{CATALOG_MODEL}"',
            'model_provider = "ollama_local"',
            f'model_catalog_json = "{config["model_catalog_json"]}"',
            'model_reasoning_effort = "medium"',
            'model_verbosity = "medium"',
            'approval_policy = "never"',
            'default_permissions = "codexteam-direct"',
            'web_search = "disabled"',
            'file_opener = "none"',
            'check_for_update_on_startup = false',
            '',
            '[history]',
            'persistence = "none"',
            '',
            '[permissions.codexteam-direct.filesystem]',
            *(f'{json.dumps(path)} = "{access}"' for path, access in sorted(filesystem.items())),
            '',
            '[permissions.codexteam-direct.network]',
            'enabled = false',
            '',
            '[features]',
            'memories = false',
            'multi_agent = false',
            'apps = false',
            'hooks = false',
            'browser_use = false',
            'in_app_browser = false',
            'computer_use = false',
            'image_generation = false',
            'plugins = false',
            'plugin_sharing = false',
            'skill_search = false',
            'workspace_dependencies = false',
            '',
            '[model_providers.ollama_local]',
            'name = "Ollama localhost only"',
            'base_url = "http://127.0.0.1:11434/v1"',
            'wire_api = "responses"',
            '',
        ]
        config_bytes = "\n".join(config_lines).encode("utf-8")
        logical_profile = (
            f'model = "{CATALOG_MODEL}"\nmodel_provider = "ollama_local"\n'
            'model_reasoning_effort = "medium"\nmodel_verbosity = "medium"\n'
        ).encode("utf-8")
        self._atomic_write(home, "config.toml", config_bytes, mode=0o400)
        self._atomic_write(home, f"{self.profile}.config.toml", logical_profile, mode=0o400)
        self._atomic_write(home, "model-catalog.json", filtered_catalog, mode=0o400)
        material = _RuntimeMaterial(
            source_profile_digest=source_profile.digest,
            source_profile_device=source_profile.device,
            source_profile_inode=source_profile.inode,
            source_catalog_digest=source_catalog.digest,
            source_catalog_device=source_catalog.device,
            source_catalog_inode=source_catalog.inode,
            selected_record_digest=record_digest,
            selected_context_window=filtered.get("context_window", filtered.get("max_context_window")),
            config_digest=hashlib.sha256(config_bytes).hexdigest(),
            profile_digest=hashlib.sha256(logical_profile).hexdigest(),
            catalog_digest=hashlib.sha256(filtered_catalog).hexdigest(),
            effective_config=config,
            effective_config_digest=canonical_sha256(config),
        )
        return material, source_pin

    def _validate_private_home(
        self, workspace: Path, role: RoleInstance, expected: _RuntimeMaterial
    ) -> None:
        home = self._runtime_dir(workspace, role) / "codex-home"
        profile = self._read_private(home, f"{self.profile}.config.toml", mode=0o400)
        catalog = self._read_private(home, "model-catalog.json", mode=0o400)
        config = self._read_private(home, "config.toml", mode=0o400)
        if hashlib.sha256(config).hexdigest() != expected.config_digest:
            raise RuntimeSessionError("private Codex config digest changed")
        if hashlib.sha256(profile).hexdigest() != expected.profile_digest:
            raise RuntimeSessionError("private Codex profile digest changed")
        if hashlib.sha256(catalog).hexdigest() != expected.catalog_digest:
            raise RuntimeSessionError("private Codex catalog digest changed")
        try:
            values = tomllib.loads(config.decode("utf-8"))
        except (UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise RuntimeSessionError("private Codex config is malformed") from exc
        if (
            values.get("model") != CATALOG_MODEL
            or values.get("model_provider") != "ollama_local"
            or values.get("model_reasoning_effort") != "medium"
            or values.get("model_verbosity") != "medium"
            or values.get("approval_policy") != "never"
            or values.get("web_search") != "disabled"
        ):
            raise RuntimeSessionError("private Codex config effective values changed")
        if canonical_sha256(expected.effective_config) != expected.effective_config_digest:
            raise RuntimeSessionError("recorded effective Codex config digest changed")

    def _ollama_digest(self, selected_context_window: int | None = None) -> str:
        if self.ollama_endpoint != DEFAULT_OLLAMA_ENDPOINT or self.ollama_model != DEFAULT_OLLAMA_MODEL:
            raise RuntimePreflightError("Ollama endpoint and model must use the pinned localhost values")
        request = urllib.request.Request(f"{self.ollama_endpoint}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=min(10, self._remaining_timeout())) as response:
                payload = json.load(response)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            raise RuntimePreflightError("Ollama availability probe failed") from exc
        models = payload.get("models", ()) if isinstance(payload, dict) else ()
        matches = [
            item for item in models
            if isinstance(item, dict)
            and item.get("name") == self.ollama_model
        ]
        if len(matches) != 1 or not isinstance(matches[0].get("digest"), str):
            raise RuntimePreflightError("Ollama did not expose one exact model digest")
        digest = matches[0]["digest"]
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise RuntimePreflightError("Ollama returned an invalid model digest")
        if selected_context_window is not None:
            show = urllib.request.Request(
                f"{self.ollama_endpoint}/api/show", method="POST",
                data=json.dumps({"model": self.ollama_model}, separators=(",", ":")).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(
                    show, timeout=min(10, self._remaining_timeout())
                ) as response:
                    show_payload = json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code in {404, 405, 501}:
                    return digest
                raise RuntimePreflightError("Ollama model metadata probe failed") from exc
            except (OSError, ValueError, urllib.error.URLError) as exc:
                raise RuntimePreflightError("Ollama model metadata probe failed") from exc
            model_info = show_payload.get("model_info") if isinstance(show_payload, dict) else None
            contexts = [
                value for key, value in (model_info.items() if isinstance(model_info, dict) else ())
                if (key == "context_length" or key.endswith(".context_length"))
                and type(value) is int and value > 0
            ]
            if not contexts:
                raise RuntimePreflightError("Ollama model metadata omitted a positive context length")
            if max(contexts) < selected_context_window:
                raise RuntimePreflightError(
                    "Ollama model context length is smaller than the selected catalog context"
                )
        return digest

    def _role_can_write_product(self, role: RoleInstance) -> bool:
        for rule in self._resolved(role).permission_policy.rules:
            if (
                rule.effect == "allow"
                and rule.operation == PermissionOperation.WRITE
                and rule.resource == PermissionResource.PROJECT_PATH
            ):
                return True
        return False

    def _sandbox_capability_probe(
        self, role: RoleInstance, workspace: Path, executable: _FilePin
    ) -> tuple[ProbeResult, ...]:
        root = workspace.resolve(strict=True)
        product = (root / "project").resolve(strict=True)
        runtime = self._runtime_dir(workspace, role)
        home = runtime / "codex-home"
        material = self._role_material.get(role.role_instance_id)
        if material is None:
            raise RuntimePreflightError("private Codex config was not prepared for capability probe")
        before = workspace_manifest(product).root_digest
        product_writable = self._role_can_write_product(role)
        product_probe = product / ".codexteam-v2-sandbox-probe"
        detached_probe = product / ".codexteam-v2-detached-probe"
        control_probe = root / ".codexteam/v2/state/probe"
        runtime_probe = runtime / "probe"
        if any(os.path.lexists(path) for path in (product_probe, detached_probe, control_probe, runtime_probe)):
            raise RuntimePreflightError("Codex sandbox product probe path already exists")
        script = (
            "import json,os,socket,subprocess,sys\n"
            "def readable(path):\n"
            " try:\n"
            "  fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW);os.close(fd);return True\n"
            " except OSError:return False\n"
            "def writable(path):\n"
            " try:\n"
            "  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd);os.unlink(path);return True\n"
            " except OSError:return False\n"
            "result={'control_read':readable(sys.argv[6]),'runtime_read':readable(sys.argv[7]),"
            "'control_write':writable(sys.argv[2]),'runtime_write':writable(sys.argv[3]),"
            "'network_connect':False,'product_write':writable(sys.argv[4])}\n"
            "try:\n"
            " connection=socket.create_connection(('127.0.0.1',int(sys.argv[1])),timeout=1);connection.close();result['network_connect']=True\n"
            "except OSError:pass\n"
            "subprocess.Popen(['/bin/sh','-c','sleep .2; printf bad > \"$1\"','sh',sys.argv[5]],"
            " stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)\n"
            "print(json.dumps(result,sort_keys=True))\n"
        )
        command = [
            executable.path, "sandbox", "-C", str(product), "-P", "codexteam-direct",
            *self._config_args(material.effective_config),
            "--sandbox-state-disable-network", "--", "/usr/bin/python3", "-c", script,
        ]
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        command.extend((
            str(listener.getsockname()[1]), str(control_probe), str(runtime_probe),
            str(product_probe), str(detached_probe), str(root / ".codexteam"), str(runtime),
        ))
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, shell=False, cwd=product,
                env=self._clean_environment(str(home)),
                timeout=min(15, self._remaining_timeout()), check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimePreflightError("Codex sandbox capability probe failed") from exc
        finally:
            listener.close()
        time.sleep(0.4)
        detached_created = detached_probe.exists()
        for path in (product_probe, detached_probe, control_probe, runtime_probe):
            path.unlink(missing_ok=True)
        if completed.returncode != 0:
            raise RuntimePreflightError(
                f"Codex sandbox capability probe exited {completed.returncode}: {completed.stderr.strip()}"
            )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimePreflightError("Codex sandbox capability probe returned invalid JSON") from exc
        expected = {
            "control_read": False,
            "runtime_read": False,
            "control_write": False,
            "runtime_write": False,
            "network_connect": False,
            "product_write": product_writable,
        }
        if result != expected or detached_created:
            raise RuntimePreflightError(
                "Codex sandbox capability probe did not enforce the expected policy: "
                f"{result!r}, detached_write={detached_created}"
            )
        if workspace_manifest(product).root_digest != before:
            raise RuntimePreflightError("Codex sandbox capability probe changed the product manifest")
        return (
            ProbeResult(
                operation=PermissionOperation.WRITE, resource=PermissionResource.PROJECT_STATE,
                status="passed", evidence_summary="Native Codex sandbox denied .codexteam control-state writes.",
            ),
            ProbeResult(
                operation=PermissionOperation.WRITE, resource=PermissionResource.PROCESS,
                status="passed", evidence_summary="Native Codex sandbox denied the exact host role runtime write.",
            ),
            ProbeResult(
                operation=PermissionOperation.READ, resource=PermissionResource.NETWORK,
                status="passed", evidence_summary="Native Codex sandbox denied a localhost connection.",
            ),
            ProbeResult(
                operation=PermissionOperation.WRITE, resource=PermissionResource.PROJECT_PATH,
                status="passed",
                evidence_summary=(
                    "Native Codex sandbox allowed and cleaned one product write."
                    if product_writable else
                    "Native Codex read-only sandbox denied one product write."
                ),
            ),
            ProbeResult(
                operation=PermissionOperation.EXECUTE, resource=PermissionResource.PROCESS,
                status="passed",
                evidence_summary="A detached delayed command did not outlive the native sandbox.",
            ),
        )

    def _probe_workspace(
        self, role: RoleInstance, workspace: Path, executable: _FilePin
    ) -> tuple[ProbeResult, ...]:
        root = workspace.resolve(strict=True)
        if not root.is_dir():
            raise RuntimePreflightError("workspace must be a directory")
        resolved = self._resolved(role)
        operations = {
            operation for capability in resolved.capabilities for operation in capability.required_operations
        }
        resources = {
            resource for capability in resolved.capabilities for resource in capability.required_resources
        }
        probes: list[ProbeResult] = []
        before = workspace_manifest(root).root_digest
        if PermissionOperation.READ in operations:
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            os.close(descriptor)
            probes.append(ProbeResult(
                operation=PermissionOperation.READ, resource=PermissionResource.PROJECT_PATH,
                status="passed", evidence_summary="Opened the workspace without following symlinks.",
            ))
        if PermissionOperation.EXECUTE in operations:
            probes.append(ProbeResult(
                operation=PermissionOperation.EXECUTE, resource=PermissionResource.PROCESS,
                status="passed", evidence_summary="Pinned private Codex executable identity.",
            ))
        if PermissionOperation.SEND in operations:
            probes.append(ProbeResult(
                operation=PermissionOperation.SEND, resource=PermissionResource.MAILBOX,
                status="passed", evidence_summary="The adapter returns typed semantic responses.",
            ))
        if PermissionResource.EVIDENCE in resources:
            probes.append(ProbeResult(
                operation=PermissionOperation.WRITE, resource=PermissionResource.EVIDENCE,
                status="passed", evidence_summary="Evidence remains kernel-owned.",
            ))
        probes.extend(self._sandbox_capability_probe(role, workspace, executable))
        if workspace_manifest(root).root_digest != before:
            raise RuntimePreflightError("adapter preflight changed the workspace manifest")
        return tuple(probes)

    def preflight(
        self, role_instance: RoleInstance, context_pack: ContextPack, workspace: Path
    ) -> PreflightReceipt:
        self._validate_role(role_instance)
        systemd_probes = self._containment_probe()
        executable = self._prepare_role_executable(workspace, role_instance)
        self._version(executable.runtime)
        material, source_pin = self._generate_private_home(workspace, role_instance)
        self._role_material[role_instance.role_instance_id] = material
        self._preflight_sources[role_instance.role_instance_id] = source_pin
        self._ollama_digest(material.selected_context_window)
        probes = systemd_probes + self._probe_workspace(
            role_instance, workspace, executable.runtime
        )
        resolved = self._resolved(role_instance)
        return PreflightReceipt(
            role_instance_digest=role_instance.resolved_digest,
            context_pack_digest=context_pack.digest,
            catalog_digest=self.catalog.catalog_lock()["catalog_digest"],
            workspace=str(workspace.resolve(strict=True)), backend_id="codex",
            observed_capabilities=tuple(item.capability_id for item in resolved.capabilities),
            probes=probes,
            enforcement_limitations=tuple(filter(None, (
                "The pinned parent Codex is trusted and runs at host level to reach localhost Ollama; its native command sandbox is the model-command boundary.",
                "The current-user source model catalog is group writable by one of the user's groups; its pinned data is validated and filtered into a private 0600 one-record catalog, never executed."
                if source_pin[1].mode & stat.S_IWGRP else "",
            ))),
        )

    def dry_run_plan(self, workspace: Path, *, capability_probe_passed: bool = False) -> dict[str, Any]:
        systemd = self._require_systemd()
        self._containment_probe()
        source_bytes, source, source_chain, source_chain_digest = self._source_executable()
        with tempfile.TemporaryDirectory(prefix="codexteam-v2-dry-run-", dir="/tmp") as temporary:
            executable = self._stage_private_executable(
                Path(temporary), source_bytes, source,
                source_chain=source_chain, source_chain_digest=source_chain_digest,
            )
            version = self._version(executable.runtime)
        _, source_profile, _, source_catalog, filtered, record_digest = self._source_material()
        selected_context = filtered.get("context_window", filtered.get("max_context_window"))
        model_digest = self._ollama_digest(selected_context)
        return {
            "backend": "codex", "source_executable_digest": source.digest,
            "source_executable_group_writable": bool(source.mode & stat.S_IWGRP),
            "source_chain_digest": source_chain_digest,
            "source_chain_file_digests": tuple(pin.digest for pin in source_chain),
            "runtime_executable": "<private-executable-cache>/codex",
            "runtime_executable_digest": source.digest,
            "systemd_version": systemd.version,
            "systemd_run_digest": systemd.systemd_run.digest,
            "systemctl_digest": systemd.systemctl.digest,
            "version": version, "logical_profile": self.profile,
            "source_profile_digest": source_profile.digest,
            "source_catalog_digest": source_catalog.digest,
            "source_catalog_group_writable": bool(source_catalog.mode & stat.S_IWGRP),
            "selected_record_digest": record_digest, "model": CATALOG_MODEL,
            "ollama_model": self.ollama_model, "ollama_model_digest": model_digest,
            "provider": "ollama_local", "workspace": "<workspace>",
            "private_codex_home": "<private-runtime>/codex-home",
            "outer_sandbox": "transient user scope with native Codex command sandbox",
            "effective_config": "<redacted; digest recorded per role>",
            "capability_probe_passed": capability_probe_passed, "model_calls": False,
            "command_previews": (
                f"/usr/bin/systemd-run --user --scope --quiet --unit=<unique-safe-unit> --property=KillMode=control-group --property=CollectMode=inactive-or-failed -- <private-executable-cache>/codex exec --profile {self.profile} -C <workspace>/project -s workspace-write <explicit-safe-config> --json -",
                f"/usr/bin/systemd-run --user --scope --quiet --unit=<unique-safe-unit> --property=KillMode=control-group --property=CollectMode=inactive-or-failed -- <private-executable-cache>/codex exec resume -m {CATALOG_MODEL} -c sandbox_mode=\"workspace-write|read-only\" <explicit-safe-config> --json <exact-thread-id> -",
            ),
        }

    def _guidance(self, role: RoleInstance) -> tuple[tuple[str, str, str], ...]:
        selected: list[tuple[str, str, str]] = []
        total = 0
        for module in self._resolved(role).guidance_modules:
            path = self.catalog.root / module.path
            content_bytes = path.read_bytes()
            digest = hashlib.sha256(content_bytes).hexdigest()
            if digest != module.digest:
                raise RuntimePreflightError(f"guidance content mismatch: {module.path}")
            total += len(content_bytes)
            if total > MAX_GUIDANCE_BYTES:
                raise RuntimePreflightError("selected guidance exceeds the live prompt budget")
            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RuntimePreflightError("selected guidance is not UTF-8") from exc
            selected.append((module.path, digest, content))
        return tuple(selected)

    def _permissions(self, role: RoleInstance) -> str:
        rules = [
            f"{rule.effect} {rule.operation.value} {rule.resource.value}:{rule.resource_pattern}"
            for rule in self._resolved(role).permission_policy.rules
        ]
        return f"assignment scope: {', '.join(role.assignment_scope)}; effective role rules: {'; '.join(rules)}"

    @staticmethod
    def _stage_objective(stage: str) -> str:
        return {
            "discovery": "Inspect README.md and request exactly both optional stages, architecture and ux.",
            "architecture": "Create docs/architecture/CLI.md. Specify one Python stdlib CLI module, iterative Fibonacci, integer argv input, exact stdout, and separate unit/integration tests. Change no other file.",
            "ux": "Create docs/design/CLI.md. Specify the exact command `python3 src/fib.py 7`, exact stdout `13\\n`, integer input behavior, and concise invalid-input behavior. Change no other file.",
            "implementation": "Create src/fib.py and tests/test_fib_unit.py only. Implement an importable iterative fibonacci(n: int) and a stdlib CLI reading argv[1]; input 7 must print exactly `13\\n`. The unit file must assert fibonacci(7) == 13 without third-party dependencies.",
            "verification": "Create tests/integration/test_cli.py only. Use Python stdlib subprocess, derive src/fib.py from __file__, assert return code 0, stderr empty, and stdout exactly `13\\n` for argument 7, then print `13\\n` so the verification contract can compare exact stdout.",
            "assurance": "Audit the implementation and verification evidence for security and privacy risk without changing files.",
            "review": "Independently decide whether the acceptance criterion and evidence justify ACCEPT without changing files.",
        }[stage]

    def _context_prompt(self, role: RoleInstance, context: RenderedContext, phase: str) -> str:
        items = [{
            "category": item.category, "summary": item.summary, "locator": item.locator,
            "content": item.content, "sha256": item.content_digest, "intended_use": item.intended_use,
        } for item in context.items]
        guidance = [
            {"path": path, "sha256": digest, "content": content}
            for path, digest, content in self._guidance(role)
        ]
        return (
            "[CODEXTEAM V2 LIVE TURN]\n"
            f"Role instance: {role.role_instance_id}\nStage: {role.stage_id}\nPhase: {phase}\n"
            f"Objective: {self._stage_objective(role.stage_id)}\nPermissions: {self._permissions(role)}\n"
            + (
                "Assurance and review decisions must use the supplied implementation candidate, accepted verification receipt criterion evidence, and assurance report when present.\n"
                if role.stage_id in {"assurance", "review"}
                else ""
            )
            +
            "Live command paths are relative to this product root. Kernel assignment scope remains project/**.\n"
            f"Rendered context digest: {context.rendered_digest}\n"
            "Use only the bounded context and selected guidance below.\n"
            f"Context items:\n{json.dumps(items, indent=2, sort_keys=True)}\n"
            f"Selected guidance:\n{json.dumps(guidance, indent=2, sort_keys=True)}\n"
        )

    @staticmethod
    def _response_protocol() -> str:
        return (
            "Complete the objective within the permissions. Return only the raw JSON object text, with no markdown fences, commentary, or other prose, matching this schema:\n"
            + json.dumps(SemanticResponse.model_json_schema(mode="validation"), sort_keys=True) + "\n"
        )

    @staticmethod
    def _candidate_model(stage: str):
        from .base import SemanticAssurance, SemanticCandidate, SemanticDiscovery, SemanticReview
        return {"discovery": SemanticDiscovery, "assurance": SemanticAssurance, "review": SemanticReview}.get(stage, SemanticCandidate)

    def _candidate_protocol(self, role: RoleInstance) -> str:
        model = self._candidate_model(role.stage_id)
        suffix = (
            'Request exactly ["architecture", "ux"] in requested_optional_stages.\n'
            if role.stage_id == "discovery" else
            "Include a security_privacy pass disposition with no findings.\n"
            if role.stage_id == "assurance" else
            "Use decision ACCEPT only if implementation and evidence satisfy the requirement.\n"
            if role.stage_id == "review" else
            "Report the active stage exactly and the files or checks actually completed.\n"
        )
        return (
            "This is a strictly read-only reporting turn. Do not mutate the workspace. Return only the raw JSON object text, with no markdown fences, commentary, or other prose, matching this schema:\n"
            + json.dumps(model.model_json_schema(mode="validation"), sort_keys=True)
            + "\nUse stage-appropriate evidence: discovery=analysis, architecture/ux=artifact, implementation=artifact or analysis, verification=test_output, assurance/review=review.\n"
            + suffix
        )

    @staticmethod
    def _parse_final_message(message: str) -> dict[str, Any]:
        stripped = message.strip()
        if stripped.startswith("```"):
            fenced = re.fullmatch(r"```json\r?\n(.*)\r?\n```", stripped, flags=re.DOTALL)
            if fenced is None:
                raise RuntimeOutputError("final Codex agent message is not raw JSON or one JSON fence")
            stripped = fenced.group(1)
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise RuntimeOutputError("final Codex agent message is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise RuntimeOutputError("final Codex agent message is not a JSON object")
        return parsed

    @staticmethod
    def _parse_events(
        stdout: str, *, initial: bool, expected_thread: str | None = None
    ) -> tuple[str | None, dict[str, Any]]:
        thread_ids: list[str] = []
        messages: list[str] = []
        failures: list[str] = []
        completed = 0
        for line_number, raw in enumerate(stdout.splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeOutputError(f"invalid Codex JSONL at line {line_number}") from exc
            if not isinstance(event, dict):
                raise RuntimeOutputError(f"invalid Codex JSONL object at line {line_number}")
            event_type = event.get("type")
            if event_type == "thread.started":
                value = event.get("thread_id")
                if not isinstance(value, str) or not value.strip():
                    raise RuntimeOutputError("Codex thread.started omitted thread_id")
                thread_ids.append(value.strip())
            elif event_type == "item.completed":
                item = event.get("item")
                if isinstance(item, dict):
                    if item.get("type") == "agent_message":
                        text = item.get("text")
                        if isinstance(text, str) and text.strip():
                            messages.append(text)
                    elif item.get("type") == "error":
                        failures.append(str(item.get("message") or item.get("error") or "item.completed error"))
            elif event_type == "turn.completed":
                completed += 1
            elif event_type in {"turn.failed", "error"}:
                failures.append(str(event.get("message") or event.get("error") or event_type))
        if failures:
            raise RuntimeBackendError("Codex reported failure: " + "; ".join(failures))
        if completed < 1:
            raise RuntimeBackendError("Codex JSONL did not report turn.completed")
        if initial and len(thread_ids) != 1:
            raise RuntimeSessionError("initial Codex turn must emit exactly one thread.started")
        if not initial and any(thread != expected_thread for thread in thread_ids):
            raise RuntimeSessionError("Codex continuation emitted a conflicting thread ID")
        if not messages:
            raise RuntimeOutputError("Codex returned no final agent message")
        return (thread_ids[0] if thread_ids else None), CodexRuntimeAdapter._parse_final_message(messages[-1])

    @staticmethod
    def _semantic_response(value: dict[str, Any]) -> SemanticResponse:
        try:
            return SemanticResponse.model_validate_json(json.dumps(value), strict=True)
        except ValueError as exc:
            raise RuntimeOutputError(f"malformed runtime SemanticResponse: {exc}") from exc

    @staticmethod
    def _stage_semantic(value: dict[str, Any]) -> StageSemantic:
        try:
            return STAGE_SEMANTIC_ADAPTER.validate_json(json.dumps(value), strict=True)
        except ValueError as exc:
            raise RuntimeOutputError(f"malformed runtime stage semantic: {exc}") from exc

    def _command(
        self, role: RoleInstance, product: Path, executable: _FilePin, *,
        session: CodexSessionInfo | None, read_only: bool
    ) -> list[str]:
        home = self._runtime_dir(product.parent, role) / "codex-home"
        config = self._effective_config(role, private_codex_home=home)
        config["sandbox_mode"] = "read-only" if read_only else "workspace-write"
        common = [
            "--ignore-user-config", "--ignore-rules",
            "--strict-config", *self._config_args(config), "--skip-git-repo-check", "--json",
        ]
        if session is None:
            return [
                executable.path, "exec", "--profile", self.profile, "-m", CATALOG_MODEL,
                "-C", str(product), "-s", "read-only" if read_only else "workspace-write",
                *common, "-",
            ]
        return [executable.path, "exec", "resume", "-m", CATALOG_MODEL, *common, session.thread_id, "-"]

    def _write_turn_file(self, directory: Path, name: str, text: str) -> None:
        self._atomic_write(directory, name, text.encode("utf-8"))

    def _write_turn_diagnostic(
        self, directory: Path, stem: str, *, unit: str, cleanup: str,
    ) -> None:
        content = json.dumps(
            {"cleanup_result": cleanup, "scope_unit": self._scope_name(unit)},
            sort_keys=True, separators=(",", ":"),
        ) + "\n"
        self._write_turn_file(directory, f"{stem}.scope.json", content)

    def _run(
        self, role: RoleInstance, workspace: Path, prompt: str, directory: Path, stem: str,
        *, session: CodexSessionInfo | None, read_only: bool,
    ) -> tuple[str | None, dict[str, Any]]:
        material = self._role_executables.get(role.role_instance_id)
        if material is None:
            raise RuntimeSessionError("private Codex executable was not prepared for this role")
        expected_source = session.source_executable if session is not None else material.source
        expected_source_chain = session.source_chain if session is not None else material.source_chain
        expected_source_chain_digest = (
            session.source_chain_digest if session is not None else material.source_chain_digest
        )
        expected_runtime = session.runtime_executable if session is not None else material.runtime
        _, source, source_chain, source_chain_digest = self._source_executable()
        runtime = self._pin_runtime_executable(Path(expected_runtime.path))
        if len(source_chain) == 1:
            self._same_pin(source, expected_source, "Codex source executable")
        self._same_source_chain(
            source_chain, source_chain_digest,
            expected_source_chain, expected_source_chain_digest,
        )
        if len(source_chain) != 1:
            self._same_pin(source, expected_source, "Codex source executable")
        self._same_pin(runtime, expected_runtime, "private Codex executable")
        if session is not None:
            digest = self._ollama_digest(session.material.selected_context_window)
            if digest != session.ollama_model_digest:
                raise RuntimeSessionError("Ollama model digest changed")
        self._write_turn_file(directory, f"{stem}.prompt.txt", prompt)
        product = (workspace.resolve(strict=True) / "project").resolve(strict=True)
        argv = self._command(
            role, product, runtime, session=session, read_only=read_only
        )
        expected_systemd = session.systemd if session is not None else self._systemd_material
        self._require_systemd(expected_systemd)
        unit = self._scope_unit(role.role_instance_id, stem)
        scoped_argv = self._scope_argv(unit, argv)
        codex_home = str(directory / "codex-home")
        started = time.monotonic()
        process: subprocess.Popen[str] | None = None
        stdout = ""
        stderr = ""
        timed_out = False
        cleanup = "not-started"
        try:
            process = subprocess.Popen(
                scoped_argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, shell=False, cwd=product,
                env=self._clean_environment(codex_home),
            )
            try:
                stdout, stderr = process.communicate(prompt, timeout=self._remaining_timeout())
            except subprocess.TimeoutExpired:
                timed_out = True
                cleanup = self._kill_scope(unit)
                stdout, stderr = process.communicate(timeout=5)
            if not timed_out:
                inactive, state = self._wait_scope_inactive(unit, timeout=0)
                if not inactive:
                    cleanup = "lingering-descendant;" + self._kill_scope(unit)
                    gone, final_state = self._wait_scope_inactive(unit)
                    if gone:
                        self._reset_scope(unit)
                    self._write_turn_diagnostic(
                        directory, stem, unit=unit,
                        cleanup=f"{cleanup};confirmed={gone};{final_state}",
                    )
                    if not gone:
                        raise RuntimeBackendError(
                            "HIGH: Codex user-systemd scope remained active after forced cleanup"
                        )
                    raise RuntimeBackendError(
                        "Codex turn left a detached descendant in its user-systemd scope"
                    )
                cleanup = f"normal-inactive;{state}"
            inactive, state = self._wait_scope_inactive(unit)
            if not inactive:
                cleanup = cleanup + ";" + self._kill_scope(unit)
                inactive, state = self._wait_scope_inactive(unit)
            if not inactive:
                self._write_turn_diagnostic(
                    directory, stem, unit=unit,
                    cleanup=f"{cleanup};confirmed=false;{state}",
                )
                raise RuntimeBackendError(
                    "HIGH: Codex user-systemd scope cleanup could not be confirmed"
                )
            cleanup = f"{cleanup};confirmed=true;{state}"
            self._reset_scope(unit)
        except BaseException as exc:
            if cleanup == "not-started":
                cleanup = self._kill_scope(unit)
            try:
                if process is not None and process.poll() is None:
                    stdout, stderr = process.communicate(timeout=5)
            except subprocess.SubprocessError:
                pass
            wrapper_stopped = process is None or process.poll() is not None
            try:
                inactive, state = self._wait_scope_inactive(unit)
            except RuntimeBackendError as cleanup_exc:
                self._write_turn_diagnostic(
                    directory, stem, unit=unit,
                    cleanup=f"{cleanup};confirmed=false;state-error={cleanup_exc}",
                )
                raise RuntimeBackendError(
                    "HIGH: Codex exception cleanup could not verify the user-systemd scope"
                ) from exc
            if not inactive:
                cleanup = cleanup + ";" + self._kill_scope(unit)
                inactive, state = self._wait_scope_inactive(unit)
            self._write_turn_diagnostic(
                directory, stem, unit=unit,
                cleanup=(
                    f"{cleanup};confirmed={str(inactive).lower()};"
                    f"wrapper_stopped={str(wrapper_stopped).lower()};{state}"
                ),
            )
            if not inactive or not wrapper_stopped:
                raise RuntimeBackendError(
                    "HIGH: Codex exception cleanup did not stop its wrapper and scope"
                ) from exc
            self._reset_scope(unit)
            raise
        self._write_turn_diagnostic(directory, stem, unit=unit, cleanup=cleanup)
        if process is None:
            raise RuntimeBackendError("Codex scope wrapper did not start")
        result = _ProcessResult(
            returncode=124 if timed_out else cast(int, process.returncode), stdout=stdout,
            stderr=stderr, timed_out=timed_out, duration_seconds=time.monotonic() - started,
        )
        self._write_turn_file(directory, f"{stem}.jsonl", result.stdout)
        self._write_turn_file(directory, f"{stem}.stdout.txt", result.stdout)
        self._write_turn_file(directory, f"{stem}.stderr.txt", result.stderr)
        expected_material = session.material if session is not None else self._role_material[role.role_instance_id]
        self._validate_private_home(workspace, role, expected_material)
        if result.timed_out:
            raise RuntimeBackendError(f"Codex turn timed out after {self.timeout_seconds} seconds")
        if result.returncode != 0:
            raise RuntimeBackendError(
                f"Codex process exited {result.returncode}; see private runtime {stem}.stderr.txt"
            )
        return self._parse_events(
            result.stdout, initial=session is None,
            expected_thread=session.thread_id if session is not None else None,
        )

    def _canonical_session(self, session: CodexSessionInfo) -> bytes:
        return json.dumps(
            session.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8") + b"\n"

    def _load_session(self, role: RoleInstance, workspace: Path) -> CodexSessionInfo:
        directory = self._runtime_dir(workspace, role)
        content = self._read_private(directory, "session.json")
        try:
            session = CodexSessionInfo.model_validate_json(content, strict=True)
        except (ValueError, UnicodeError) as exc:
            raise RuntimeSessionError("Codex session file is malformed") from exc
        if content != self._canonical_session(session):
            raise RuntimeSessionError("Codex session file is not canonical JSON")
        return session

    def _store_session(
        self, *, thread_id: str, role: RoleInstance, context_digest: str, workspace: Path,
        phase: Literal["draft", "resume", "feedback", "candidate"], turn: int,
        material: _RuntimeMaterial, model_digest: str,
    ) -> CodexSessionInfo:
        executable = self._role_executables.get(role.role_instance_id)
        if executable is None:
            raise RuntimeSessionError("private Codex executable was not prepared for this role")
        config_args = self._config_args(material.effective_config)
        root = workspace.resolve(strict=True)
        home = self._runtime_dir(workspace, role) / "codex-home"
        session = CodexSessionInfo(
            thread_id=thread_id, source_executable=executable.source,
            source_chain=executable.source_chain,
            source_chain_digest=executable.source_chain_digest,
            runtime_executable=executable.runtime, executable_version=self.expected_version,
            systemd=self._require_systemd(),
            logical_profile=self.profile,
            material=material, model=CATALOG_MODEL, provider="ollama_local",
            ollama_model=self.ollama_model, ollama_model_digest=model_digest,
            backend_id=role.backend.definition_id, role_instance_id=role.role_instance_id,
            role_instance_digest=role.resolved_digest, context_digest=context_digest,
            workspace=str((root / "project").resolve(strict=True)), canary_root=str(root),
            private_codex_home=str(home),
            outer_sandbox=(
                "host-parent-native-read-only" if phase == "candidate"
                else "host-parent-native-workspace-write"
            ),
            command_config=config_args, phase=phase, turn=turn,
        )
        directory = self._runtime_dir(workspace, role)
        self._atomic_write(directory, "session.json", self._canonical_session(session))
        self._sessions[thread_id] = session
        self._roles[thread_id] = role
        return session

    def _validate_session(
        self, session: CodexSessionInfo, session_id: str, role: RoleInstance,
        context_digest: str, workspace: Path,
    ) -> str:
        self._validate_role(role)
        _, source, source_chain, source_chain_digest = self._source_executable()
        runtime = self._pin_runtime_executable(
            self._executable_dir(workspace, role) / "bin/codex"
        )
        executable = _ExecutableMaterial(
            source=source, source_chain=source_chain,
            source_chain_digest=source_chain_digest, runtime=runtime,
        )
        self._role_executables[role.role_instance_id] = executable
        version = self._version(executable.runtime)
        if len(executable.source_chain) == 1:
            self._same_pin(executable.source, session.source_executable, "Codex source executable")
        self._same_source_chain(
            executable.source_chain, executable.source_chain_digest,
            session.source_chain, session.source_chain_digest,
        )
        if len(executable.source_chain) != 1:
            self._same_pin(executable.source, session.source_executable, "Codex source executable")
        self._same_pin(executable.runtime, session.runtime_executable, "private Codex executable")
        root = workspace.resolve(strict=True)
        home = self._runtime_dir(workspace, role) / "codex-home"
        effective = self._effective_config(role, private_codex_home=home)
        expected = {
            "thread_id": session_id, "executable_version": version,
            "logical_profile": self.profile,
            "model": CATALOG_MODEL, "provider": "ollama_local", "ollama_model": self.ollama_model,
            "backend_id": role.backend.definition_id, "role_instance_id": role.role_instance_id,
            "role_instance_digest": role.resolved_digest, "context_digest": context_digest,
            "workspace": str((root / "project").resolve(strict=True)),
            "canary_root": str(root), "private_codex_home": str(home),
            "command_config": self._config_args(effective),
        }
        for field, value in expected.items():
            if getattr(session, field) != value:
                raise RuntimeSessionError(f"Codex session {field} mismatch")
        self._require_systemd(session.systemd)
        self._validate_private_home(workspace, role, session.material)
        model_digest = self._ollama_digest(session.material.selected_context_window)
        if model_digest != session.ollama_model_digest:
            raise RuntimeSessionError("Ollama model digest changed")
        return model_digest

    def draft(self, role_instance: RoleInstance, context: RenderedContext, workspace: Path) -> DraftTurn:
        self._validate_role(role_instance)
        expected_source = self._preflight_sources.get(role_instance.role_instance_id)
        if expected_source is None:
            raise RuntimePreflightError("Codex source material was not pinned at preflight")
        material = self._role_material.get(role_instance.role_instance_id)
        if material is None:
            raise RuntimePreflightError("Codex private home was not generated at preflight")
        _, source_profile, _, source_catalog, _, record_digest = self._source_material()
        source_pin = (source_profile, source_catalog, record_digest)
        if source_pin != expected_source:
            raise RuntimePreflightError(
                "Codex source profile or model catalog identity changed since preflight"
            )
        self._validate_private_home(workspace, role_instance, material)
        model_digest = self._ollama_digest(material.selected_context_window)
        directory = self._runtime_dir(workspace, role_instance)
        prompt = self._context_prompt(role_instance, context, "draft") + self._response_protocol()
        thread_id, value = self._run(
            role_instance, workspace, prompt, directory, "001-draft", session=None, read_only=False
        )
        if thread_id is None:
            raise RuntimeSessionError("initial Codex turn did not emit an exact thread ID")
        self._store_session(
            thread_id=thread_id, role=role_instance, context_digest=context.rendered_digest,
            workspace=workspace, phase="draft", turn=1, material=material, model_digest=model_digest,
        )
        return DraftTurn(
            session_id=thread_id, response=self._semantic_response(value),
            consumed_context_digest=context.rendered_digest,
        )

    def resume(
        self, session_id: str, role_instance: RoleInstance, context: RenderedContext,
        workspace: Path, *, candidate_sequence: int,
    ) -> DraftTurn:
        session = self._load_session(role_instance, workspace)
        model_digest = self._validate_session(
            session, session_id, role_instance, context.rendered_digest, workspace
        )
        prompt = (
            self._context_prompt(role_instance, context, "resume")
            + f"Resume this exact assignment after {candidate_sequence} candidate report(s). Reinspect current files and continue.\n"
            + self._response_protocol()
        )
        directory = self._runtime_dir(workspace, role_instance)
        _, value = self._run(
            role_instance, workspace, prompt, directory, f"{session.turn + 1:03d}-resume",
            session=session, read_only=False,
        )
        self._store_session(
            thread_id=session.thread_id, role=role_instance, context_digest=context.rendered_digest,
            workspace=workspace, phase="resume", turn=session.turn + 1,
            material=session.material, model_digest=model_digest,
        )
        return DraftTurn(
            session_id=session.thread_id, response=self._semantic_response(value),
            consumed_context_digest=context.rendered_digest,
        )

    def _active(self, session_id: str) -> tuple[CodexSessionInfo, RoleInstance, Path, str]:
        role = self._roles.get(session_id)
        cached = self._sessions.get(session_id)
        if role is None or cached is None:
            raise RuntimeSessionError("unknown Codex session")
        workspace = Path(cached.canary_root)
        loaded = self._load_session(role, workspace)
        model_digest = self._validate_session(
            loaded, session_id, role, cached.context_digest, workspace
        )
        return loaded, role, workspace, model_digest

    def feedback(self, session_id: str, defect_packet: DefectPacket) -> SemanticResponse:
        session, role, workspace, model_digest = self._active(session_id)
        prompt = (
            "[CODEXTEAM V2 FEEDBACK]\nApply this defect packet within the original role permissions: "
            + defect_packet.model_dump_json() + "\n" + self._response_protocol()
        )
        directory = self._runtime_dir(workspace, role)
        _, value = self._run(
            role, workspace, prompt, directory, f"{session.turn + 1:03d}-feedback",
            session=session, read_only=False,
        )
        self._store_session(
            thread_id=session.thread_id, role=role, context_digest=session.context_digest,
            workspace=workspace, phase="feedback", turn=session.turn + 1,
            material=session.material, model_digest=model_digest,
        )
        return self._semantic_response(value)

    def candidate(self, session_id: str, *, read_only: bool) -> StageSemantic:
        if not read_only:
            raise RuntimeOutputError("Codex candidate requires an explicit read-only turn")
        session, role, workspace, model_digest = self._active(session_id)
        directory = self._runtime_dir(workspace, role)
        _, value = self._run(
            role, workspace, self._candidate_protocol(role), directory,
            f"{session.turn + 1:03d}-candidate", session=session, read_only=True,
        )
        self._store_session(
            thread_id=session.thread_id, role=role, context_digest=session.context_digest,
            workspace=workspace, phase="candidate", turn=session.turn + 1,
            material=session.material, model_digest=model_digest,
        )
        return self._stage_semantic(value)


__all__ = [
    "CodexRuntimeAdapter", "CodexSessionInfo", "DEFAULT_CODEX_EXECUTABLE",
    "DEFAULT_OLLAMA_ENDPOINT", "DEFAULT_OLLAMA_MODEL",
    "PINNED_CODEX_VERSION",
]
