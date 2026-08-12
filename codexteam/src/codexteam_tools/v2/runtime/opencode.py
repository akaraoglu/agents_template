from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import Field

from ..canonical import canonical_sha256
from ..catalog import Catalog
from ..evidence import workspace_manifest
from ..models import (
    ContextPack,
    PermissionOperation,
    PermissionResource,
    RoleInstance,
    project_path_pattern_matches,
)
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


PINNED_OPENCODE_VERSION = "1.18.16"
DEFAULT_OPENCODE_EXECUTABLE = Path("/home/alik/.opencode/bin/opencode")
DEFAULT_OLLAMA_ENDPOINT = "http://127.0.0.1:11434"
DEFAULT_OPENCODE_MODEL = "ollama/muse-glimmer:30b"
DEFAULT_OLLAMA_MODEL = "muse-glimmer:30b"
SUPPORTED_OPENCODE_MODELS = {
    "ollama/muse-glimmer:30b": "muse-glimmer:30b",
    "ollama/qwen3.6-27b:latest": "qwen3.6-27b:latest",
}
_MODEL_DISPLAYS = {
    "ollama/muse-glimmer:30b": "Muse Glimmer 30B local",
    "ollama/qwen3.6-27b:latest": "Qwen3.6 27B local",
}
MUSE_OLLAMA_DIGEST = "de878ce33ad81d060001db1469a02eebe4d86f0ad58cfe52dc062fdcbe4464c1"
MUSE_CONTEXT_LIMIT = 131072
MUSE_INPUT_LIMIT = 114688
MUSE_OUTPUT_LIMIT = 16384
DEFAULT_SYSTEMD_RUN = Path("/usr/bin/systemd-run")
DEFAULT_SYSTEMCTL = Path("/usr/bin/systemctl")
MUTABLE_AGENT = "mutable"
READONLY_AGENT = "readonly"
QUALIFICATION_TEXT_AGENT = "qualification-text"
QUALIFICATION_READ_AGENT = "qualification-read"
QUALIFICATION_WRITE_AGENT = "qualification-write"
_SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"
_DIGEST = r"^[0-9a-f]{64}$"
_READONLY_STAGES = frozenset({"discovery", "assurance", "review"})


class OpenCodeFilePin(RuntimeModel):
    path: str
    device: int
    inode: int
    mode: int
    owner: int
    group: int
    digest: str = Field(pattern=_DIGEST)


class OpenCodeSessionInfo(RuntimeModel):
    session_id: str = Field(min_length=1)
    source_executable: OpenCodeFilePin
    runtime_executable: OpenCodeFilePin
    executable_version: str
    config_digest: str = Field(pattern=_DIGEST)
    model: str
    ollama_model_digest: str = Field(pattern=_DIGEST)
    backend_id: str
    role_instance_id: str
    role_instance_digest: str = Field(pattern=_DIGEST)
    context_digest: str = Field(pattern=_DIGEST)
    workspace: str
    canary_root: str
    private_home: str
    private_config: str
    mutable_agent: str
    phase: Literal["draft", "resume", "feedback", "candidate", "qualification"]
    turn: int = Field(ge=1)


class OpenCodeRuntimeAdapter:
    """Pinned OpenCode adapter with product-only tools and authoritative audit."""

    def __init__(
        self,
        *,
        catalog: Catalog,
        executable: str | Path = DEFAULT_OPENCODE_EXECUTABLE,
        model: str = DEFAULT_OPENCODE_MODEL,
        timeout_seconds: int = 600,
        overall_timeout_seconds: int | None = 3600,
        ollama_endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
        expected_version: str = PINNED_OPENCODE_VERSION,
        test_executable_root: str | Path | None = None,
        _test_only_allow_executable_root: bool = False,
        _test_only_systemd_root: str | Path | None = None,
    ) -> None:
        if timeout_seconds < 1 or (overall_timeout_seconds is not None and overall_timeout_seconds < 1):
            raise ValueError("timeouts must be positive")
        source = Path(executable).expanduser()
        if not source.is_absolute():
            raise ValueError("OpenCode executable must be absolute")
        if (test_executable_root is not None or _test_only_systemd_root is not None) and not _test_only_allow_executable_root:
            raise ValueError("test roots are available only to the internal fake harness")
        if test_executable_root is None and source != DEFAULT_OPENCODE_EXECUTABLE:
            raise ValueError(
                f"OpenCode executable must be pinned to {DEFAULT_OPENCODE_EXECUTABLE}"
            )
        if model not in SUPPORTED_OPENCODE_MODELS:
            raise ValueError(f"unsupported OpenCode model {model!r}")
        self.catalog = catalog
        self.executable = source
        self.model = model
        self.ollama_model = SUPPORTED_OPENCODE_MODELS[model]
        self.timeout_seconds = timeout_seconds
        self.overall_timeout_seconds = overall_timeout_seconds
        self.ollama_endpoint = ollama_endpoint.rstrip("/")
        self.expected_version = expected_version
        self.test_executable_root = Path(test_executable_root) if test_executable_root else None
        systemd_root = Path(_test_only_systemd_root) if _test_only_systemd_root else DEFAULT_SYSTEMD_RUN.parent
        if not systemd_root.is_absolute():
            raise ValueError("systemd tool root must be absolute")
        self._systemd_run = systemd_root / DEFAULT_SYSTEMD_RUN.name
        self._systemctl_path = systemd_root / DEFAULT_SYSTEMCTL.name
        self._test_systemd = _test_only_systemd_root is not None
        self._started = time.monotonic()
        self._sessions: dict[str, OpenCodeSessionInfo] = {}
        self._roles: dict[str, RoleInstance] = {}
        self._pins: dict[str, tuple[OpenCodeFilePin, OpenCodeFilePin]] = {}
        self._configs: dict[str, tuple[dict[str, Any], str]] = {}
        self._contexts: dict[str, RenderedContext] = {}
        self._systemd_pins: tuple[OpenCodeFilePin, OpenCodeFilePin] | None = None

    @property
    def sessions(self) -> dict[str, str]:
        return {
            role.stage_id: session.session_id
            for session_id, session in self._sessions.items()
            if (role := self._roles.get(session_id)) is not None
        }

    def _remaining_timeout(self) -> int:
        if self.overall_timeout_seconds is None:
            return self.timeout_seconds
        remaining = self.overall_timeout_seconds - (time.monotonic() - self._started)
        if remaining <= 0:
            raise RuntimeBackendError("OpenCode canary overall timeout expired")
        return max(1, min(self.timeout_seconds, int(remaining)))

    @staticmethod
    def _read_pin(
        path: Path, label: str, *, owners: set[int], allow_current_group_write: bool = False
    ) -> tuple[bytes, OpenCodeFilePin]:
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        except OSError as exc:
            raise RuntimePreflightError(f"{label} is unavailable or is a symlink") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid not in owners:
                raise RuntimePreflightError(f"{label} must be a trusted regular file")
            if metadata.st_mode & stat.S_IWOTH:
                raise RuntimePreflightError(f"{label} must not be world writable")
            if metadata.st_mode & stat.S_IWGRP:
                groups = {os.getgid(), os.getegid(), *os.getgroups()}
                if not (
                    allow_current_group_write
                    and metadata.st_uid == os.getuid()
                    and metadata.st_gid in groups
                ):
                    raise RuntimePreflightError(f"{label} must not be group writable")
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            content = b"".join(chunks)
        finally:
            os.close(descriptor)
        return content, OpenCodeFilePin(
            path=str(path), device=metadata.st_dev, inode=metadata.st_ino,
            mode=stat.S_IMODE(metadata.st_mode), owner=metadata.st_uid,
            group=metadata.st_gid, digest=hashlib.sha256(content).hexdigest(),
        )

    def _source(self) -> tuple[bytes, OpenCodeFilePin]:
        try:
            source = self.executable.resolve(strict=True)
        except OSError as exc:
            raise RuntimePreflightError("OpenCode executable is unavailable") from exc
        content, pin = self._read_pin(
            source, "OpenCode source executable", owners={0, os.getuid()},
            allow_current_group_write=True,
        )
        if self.test_executable_root is None and (
            len(content) < 20 or content[:6] != b"\x7fELF\x02\x01"
            or int.from_bytes(content[18:20], "little") != 62
        ):
            raise RuntimePreflightError("OpenCode executable is not an x86-64 Linux ELF")
        return content, pin

    @staticmethod
    def _safe_directory(path: Path, *, mode: int = 0o700) -> Path:
        path.mkdir(parents=True, exist_ok=True, mode=mode)
        metadata = path.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise RuntimeSessionError(f"unsafe private directory: {path}")
        path.chmod(mode)
        return path

    @staticmethod
    def _atomic_write(path: Path, content: bytes, *, mode: int = 0o600) -> None:
        directory = path.parent
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        temporary = f".{path.name}.{secrets.token_hex(8)}.tmp"
        descriptor = -1
        try:
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                mode, dir_fd=directory_fd,
            )
            os.fchmod(descriptor, mode)
            view = memoryview(content)
            while view:
                count = os.write(descriptor, view)
                if count == 0:
                    raise OSError("short write")
                view = view[count:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary, path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
        except OSError as exc:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except OSError:
                pass
            raise RuntimeSessionError(f"could not atomically write {path.name}") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(directory_fd)

    def _runtime(self, workspace: Path, role: RoleInstance) -> Path:
        root = workspace.resolve(strict=True)
        if not root.is_dir():
            raise RuntimeSessionError("workspace must be a directory")
        return self._safe_directory(root / ".codexteam" / "v2" / "runtime" / role.role_instance_id / "opencode")

    def _stage_executable(self, workspace: Path, role: RoleInstance) -> tuple[OpenCodeFilePin, OpenCodeFilePin]:
        content, source = self._source()
        binary_dir = self._safe_directory(self._runtime(workspace, role) / "bin")
        target = binary_dir / "opencode"
        if not target.exists():
            self._atomic_write(target, content, mode=0o500)
        _, runtime = self._read_pin(target, "private OpenCode executable", owners={os.getuid()})
        if runtime.mode != 0o500 or runtime.digest != source.digest:
            raise RuntimeSessionError("private OpenCode executable identity differs from source")
        self._pins[role.role_instance_id] = (source, runtime)
        return source, runtime

    @staticmethod
    def _is_writable(role: RoleInstance, catalog: Catalog) -> bool:
        resolved = catalog.resolve_agent_spec(
            role.agent_spec.definition_id, role.agent_spec.definition_version
        )
        return role.stage_id not in _READONLY_STAGES and any(
            rule.effect == "allow"
            and rule.operation == PermissionOperation.WRITE
            and rule.resource == PermissionResource.PROJECT_PATH
            for rule in resolved.permission_policy.rules
        )

    def _write_scope(self, role: RoleInstance) -> tuple[str, ...]:
        if not self._is_writable(role, self.catalog):
            return ()
        resolved = self.catalog.resolve_agent_spec(
            role.agent_spec.definition_id, role.agent_spec.definition_version
        )
        policy_scope = tuple(
            rule.resource_pattern
            for rule in resolved.permission_policy.rules
            if rule.effect == "allow"
            and rule.operation == PermissionOperation.WRITE
            and rule.resource == PermissionResource.PROJECT_PATH
        )
        effective: set[str] = set()
        for assignment_pattern in role.assignment_scope:
            for policy_pattern in policy_scope:
                if project_path_pattern_matches(
                    policy_pattern, assignment_pattern, candidate_is_pattern=True
                ):
                    effective.add(assignment_pattern)
                elif project_path_pattern_matches(
                    assignment_pattern, policy_pattern, candidate_is_pattern=True
                ):
                    effective.add(policy_pattern)
        return tuple(sorted(effective))

    @staticmethod
    def _product_pattern(pattern: str) -> str:
        if pattern == "project":
            return "*"
        if not pattern.startswith("project/"):
            raise RuntimePreflightError(
                f"OpenCode assignment scope is outside the product root: {pattern!r}"
            )
        return pattern.removeprefix("project/")

    def _permissions(
        self, role: RoleInstance, product: Path, *, readonly: bool = False
    ) -> dict[str, Any]:
        del product
        # OpenCode's path-pattern permission matching is not reliable for
        # creating previously absent nested files. Writer agents therefore get
        # normal edit/write freedom inside the exact product cwd. The compiled
        # assignment scope is supplied in the prompt and StageRunner performs
        # an immediate authoritative audit after every mutable turn.
        edit_permission = (
            "allow"
            if not readonly and self._write_scope(role)
            else "deny"
        )
        return {
            "*": "deny",
            "read": {"*": "deny", "**": "allow"},
            "glob": "allow",
            "grep": "allow",
            "list": "allow",
            "edit": edit_permission,
            # OpenCode authorizes new-file creation through `write`
            # separately from `edit`. Both use the same compiled scope.
            "write": edit_permission,
            "bash": "deny",
            "task": "deny",
            "skill": "deny",
            "webfetch": "deny",
            "websearch": "deny",
            "lsp": "deny",
            "question": "deny",
            "external_directory": {"*": "deny"},
            "todowrite": "deny",
        }

    def _config(self, role: RoleInstance, product: Path) -> dict[str, Any]:
        resolved = self.catalog.resolve_agent_spec(
            role.agent_spec.definition_id, role.agent_spec.definition_version
        )
        if resolved.backend.provider != "opencode" or resolved.model_profile.model != self.model:
            raise RuntimePreflightError("RoleInstance is not pinned to the active OpenCode model")
        responsibility = resolved.responsibility.description.strip()
        model_config: dict[str, Any] = {
            "id": self.ollama_model,
            "name": _MODEL_DISPLAYS[self.model],
        }
        if self.model == DEFAULT_OPENCODE_MODEL:
            model_config.update({
                "family": "muse-glimmer",
                "attachment": True,
                "reasoning": True,
                "tool_call": True,
                "interleaved": "reasoning",
                "temperature": True,
                "limit": {
                    "context": MUSE_CONTEXT_LIMIT,
                    "input": MUSE_INPUT_LIMIT,
                    "output": MUSE_OUTPUT_LIMIT,
                },
                "modalities": {"input": ["text", "image"], "output": ["text"]},
            })
        text_permissions = self._permissions(role, product, readonly=True)
        text_permissions.update({
            "read": "deny", "glob": "deny", "grep": "deny", "list": "deny",
        })
        return {
            "$schema": "https://opencode.ai/config.json",
            "model": self.model,
            "small_model": self.model,
            "enabled_providers": ["ollama"],
            "provider": {
                "ollama": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Ollama localhost only",
                    "options": {"baseURL": "http://127.0.0.1:11434/v1"},
                    "models": {self.ollama_model: model_config},
                }
            },
            "plugin": [],
            "mcp": {},
            "lsp": False,
            "formatter": False,
            "instructions": [],
            "skills": {"paths": [], "urls": []},
            "subagent_depth": 0,
            "share": "disabled",
            "snapshot": False,
            "autoupdate": False,
            "default_agent": MUTABLE_AGENT,
            "agent": {
                MUTABLE_AGENT: {
                    "description": f"CodexTeam {role.stage_id} worker",
                    "mode": "primary",
                    "model": self.model,
                    "prompt": responsibility,
                    "permission": self._permissions(role, product),
                },
                READONLY_AGENT: {
                    "description": f"CodexTeam {role.stage_id} read-only reporter",
                    "mode": "primary",
                    "model": self.model,
                    "prompt": responsibility,
                    "permission": self._permissions(role, product, readonly=True),
                },
                QUALIFICATION_TEXT_AGENT: {
                    "description": "Muse qualification without tools",
                    "mode": "primary",
                    "model": self.model,
                    "prompt": "Return only the requested strict JSON object.",
                    "permission": text_permissions,
                },
                QUALIFICATION_READ_AGENT: {
                    "description": "Muse qualification with read-only tools",
                    "mode": "primary",
                    "model": self.model,
                    "prompt": "Use only read-only product tools and return strict JSON.",
                    "permission": self._permissions(role, product, readonly=True),
                },
                QUALIFICATION_WRITE_AGENT: {
                    "description": "Muse qualification with bounded product writes",
                    "mode": "primary",
                    "model": self.model,
                    "prompt": "Make only the requested bounded product change and return strict JSON.",
                    "permission": self._permissions(role, product),
                },
            },
        }

    @staticmethod
    def _canonical(value: Any) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"

    def _prepare_home(self, workspace: Path, role: RoleInstance) -> tuple[dict[str, Any], str]:
        runtime = self._runtime(workspace, role)
        for relative in (
            "home", "config", "data", "state", "cache", "runtime", "config/opencode"
        ):
            self._safe_directory(runtime / relative)
        config = self._config(role, self._product(workspace))
        content = self._canonical(config)
        digest = hashlib.sha256(content).hexdigest()
        path = runtime / "config" / "opencode" / "opencode.json"
        if not path.exists():
            self._atomic_write(path, content, mode=0o400)
        observed = self._read_private(path, mode=0o400)
        if observed != content:
            raise RuntimeSessionError("private OpenCode config differs from the generated config")
        self._configs[role.role_instance_id] = (config, digest)
        return config, digest

    @staticmethod
    def _read_private(path: Path, *, mode: int = 0o600) -> bytes:
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError as exc:
            raise RuntimeSessionError(f"private file is unavailable: {path.name}") from exc
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != mode
                or metadata.st_uid != os.getuid()
            ):
                raise RuntimeSessionError(f"private file has unsafe identity: {path.name}")
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    def _environment(self, runtime: Path) -> dict[str, str]:
        environment = {
            "PATH": f"{runtime / 'bin'}:{_SAFE_PATH}",
            "HOME": str(runtime / "home"),
            "XDG_CONFIG_HOME": str(runtime / "config"),
            "XDG_DATA_HOME": str(runtime / "data"),
            "XDG_STATE_HOME": str(runtime / "state"),
            "XDG_CACHE_HOME": str(runtime / "cache"),
            "XDG_RUNTIME_DIR": str(runtime / "runtime"),
            "OPENCODE_CONFIG": str(runtime / "config/opencode/opencode.json"),
            "OPENCODE_CONFIG_DIR": str(runtime / "config/opencode"),
            "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
            "OPENCODE_DISABLE_CLAUDE_CODE": "1",
            "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT": "1",
            "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
            "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        host_runtime = f"/run/user/{os.getuid()}"
        environment["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={host_runtime}/bus"
        return environment

    def _version(self, executable: OpenCodeFilePin, runtime: Path) -> str:
        try:
            result = subprocess.run(
                (executable.path, "--version"), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                shell=False, env=self._environment(runtime), timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimePreflightError("OpenCode version probe failed") from exc
        observed = result.stdout.strip()
        if result.returncode != 0 or observed != self.expected_version:
            raise RuntimePreflightError(
                f"OpenCode version mismatch: expected {self.expected_version!r}, observed {observed!r}"
            )
        return observed

    def _validate_installed_config(
        self, executable: OpenCodeFilePin, runtime: Path, product: Path,
        expected: dict[str, Any],
    ) -> None:
        try:
            result = subprocess.run(
                (executable.path, "debug", "config", "--pure"),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, shell=False, cwd=product, env=self._environment(runtime),
                timeout=15, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimePreflightError("OpenCode config validation failed") from exc
        if result.returncode != 0:
            raise RuntimePreflightError("OpenCode rejected the generated config: " + result.stderr.strip())
        try:
            observed = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimePreflightError("OpenCode config validation returned malformed JSON") from exc
        for key in (
            "model", "small_model", "enabled_providers", "plugin", "mcp", "lsp",
            "formatter", "instructions", "skills", "subagent_depth", "share",
            "snapshot", "autoupdate", "default_agent",
        ):
            if observed.get(key) != expected[key]:
                raise RuntimePreflightError(f"OpenCode effective config changed {key!r}")
        for name in (MUTABLE_AGENT, READONLY_AGENT):
            agent = observed.get("agent", {}).get(name, {})
            if agent.get("permission") != expected["agent"][name]["permission"]:
                raise RuntimePreflightError(f"OpenCode effective {name} permissions changed")
        models = observed.get("provider", {}).get("ollama", {}).get("models", {})
        if models.get(self.ollama_model) != expected["provider"]["ollama"]["models"][self.ollama_model]:
            raise RuntimePreflightError("OpenCode effective model metadata changed")
        for name in (
            QUALIFICATION_TEXT_AGENT, QUALIFICATION_READ_AGENT, QUALIFICATION_WRITE_AGENT,
        ):
            agent = observed.get("agent", {}).get(name, {})
            if agent.get("model") != self.model or agent.get("permission") != expected["agent"][name]["permission"]:
                raise RuntimePreflightError(f"OpenCode effective {name} config changed")
        for tool in ("edit", "write"):
            mutable_permission = observed["agent"][MUTABLE_AGENT]["permission"].get(tool)
            expected_permission = expected["agent"][MUTABLE_AGENT]["permission"][tool]
            if mutable_permission != expected_permission:
                raise RuntimePreflightError(
                    f"OpenCode effective mutable {tool} permission changed"
                )
            if observed["agent"][READONLY_AGENT]["permission"].get(tool) != "deny":
                raise RuntimePreflightError(
                    f"OpenCode effective readonly agent does not deny {tool}"
                )

    def _ollama_digest(self) -> str:
        if self.ollama_endpoint != DEFAULT_OLLAMA_ENDPOINT:
            raise RuntimePreflightError("Ollama must use the pinned localhost endpoint")
        request = urllib.request.Request(f"{self.ollama_endpoint}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=min(10, self._remaining_timeout())) as response:
                payload = json.load(response)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            raise RuntimePreflightError("Ollama availability probe failed") from exc
        matches = [
            item for item in (payload.get("models", ()) if isinstance(payload, dict) else ())
            if isinstance(item, dict) and item.get("name") == self.ollama_model
        ]
        if len(matches) != 1 or not isinstance(matches[0].get("digest"), str):
            raise RuntimePreflightError("Ollama did not expose one exact model digest")
        digest = matches[0]["digest"]
        if re.fullmatch(_DIGEST, digest) is None:
            raise RuntimePreflightError("Ollama returned an invalid model digest")
        if self.model == DEFAULT_OPENCODE_MODEL:
            if digest != MUSE_OLLAMA_DIGEST:
                raise RuntimePreflightError("Ollama Muse Glimmer digest differs from the pinned digest")
            show = urllib.request.Request(
                f"{self.ollama_endpoint}/api/show", method="POST",
                data=json.dumps({"model": self.ollama_model}, separators=(",", ":")).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(
                    show, timeout=min(10, self._remaining_timeout())
                ) as response:
                    metadata = json.load(response)
            except (OSError, ValueError, urllib.error.URLError) as exc:
                raise RuntimePreflightError("Ollama model metadata probe failed") from exc
            details = metadata.get("details") if isinstance(metadata, dict) else None
            model_info = metadata.get("model_info") if isinstance(metadata, dict) else None
            capabilities = metadata.get("capabilities") if isinstance(metadata, dict) else None
            contexts = [
                value for key, value in (model_info.items() if isinstance(model_info, dict) else ())
                if (key == "context_length" or key.endswith(".context_length"))
                and type(value) is int and value > 0
            ]
            if (
                not isinstance(details, dict)
                or details.get("family") != "muse-glimmer"
                or details.get("parameter_size") != "27.9B"
                or details.get("quantization_level") != "Q4_K_M"
                or contexts != [MUSE_CONTEXT_LIMIT]
                or not isinstance(capabilities, list)
                or not all(isinstance(item, str) for item in capabilities)
                or set(capabilities) != {"completion", "tools", "thinking", "vision"}
            ):
                raise RuntimePreflightError("Ollama Muse Glimmer metadata differs from the pinned profile")
        return digest

    def _pin_systemd(self) -> tuple[OpenCodeFilePin, OpenCodeFilePin]:
        owners = {os.getuid()} if self._test_systemd else {0}
        _, run = self._read_pin(self._systemd_run, "systemd-run executable", owners=owners)
        _, control = self._read_pin(self._systemctl_path, "systemctl executable", owners=owners)
        for pin, label in ((run, "systemd-run"), (control, "systemctl")):
            result = subprocess.run(
                (pin.path, "--version"), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                shell=False, env=self._systemd_environment(), timeout=10, check=False,
            )
            if result.returncode != 0 or not result.stdout.startswith("systemd "):
                raise RuntimePreflightError(f"{label} version probe failed")
        pins = (run, control)
        if self._systemd_pins is not None and pins != self._systemd_pins:
            raise RuntimeSessionError("pinned systemd executable identity changed")
        self._systemd_pins = pins
        return pins

    @staticmethod
    def _systemd_environment() -> dict[str, str]:
        runtime = f"/run/user/{os.getuid()}"
        return {
            "PATH": _SAFE_PATH, "HOME": "/nonexistent-codexteam-home",
            "XDG_RUNTIME_DIR": runtime,
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus",
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        }

    @staticmethod
    def _unit(role_id: str, phase: str) -> str:
        role = re.sub(r"[^a-z0-9]", "-", role_id.lower()).strip("-")[:22] or "role"
        turn = re.sub(r"[^a-z0-9]", "-", phase.lower()).strip("-")[:16] or "turn"
        return f"ctv2-oc-{role}-{turn}-{secrets.token_hex(5)}"[:63].rstrip("-")

    def _scope_argv(self, unit: str, command: list[str]) -> list[str]:
        run, _ = self._systemd_pins or self._pin_systemd()
        return [
            run.path, "--user", "--scope", "--quiet", f"--unit={unit}",
            "--property=KillMode=control-group",
            "--property=CollectMode=inactive-or-failed", "--", *command,
        ]

    def _systemctl_run(self, *args: str) -> subprocess.CompletedProcess[str]:
        _, control = self._systemd_pins or self._pin_systemd()
        try:
            return subprocess.run(
                (control.path, "--user", *args), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                shell=False, env=self._systemd_environment(), timeout=5, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeBackendError("HIGH: user-systemd control failed") from exc

    def _scope_inactive(self, unit: str, *, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            result = self._systemctl_run(
                "show", f"{unit}.scope", "--property=LoadState",
                "--property=ActiveState", "--property=SubState",
            )
            if result.returncode != 0:
                raise RuntimeBackendError("HIGH: could not inspect user-systemd scope")
            values = dict(
                line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
            )
            if values.get("LoadState") == "not-found" or values.get("ActiveState") == "inactive":
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def _kill_scope(self, unit: str) -> None:
        result = self._systemctl_run(
            "kill", "--kill-whom=all", "--signal=SIGKILL", f"{unit}.scope"
        )
        if result.returncode != 0 and "not loaded" not in result.stderr.lower():
            raise RuntimeBackendError("HIGH: user-systemd scope kill failed")

    def _scope_probe(self) -> ProbeResult:
        self._pin_systemd()
        unit = self._unit("probe", "normal")
        try:
            result = subprocess.run(
                self._scope_argv(unit, ["/usr/bin/true"]), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                shell=False, env=self._systemd_environment(), timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._kill_scope(unit)
            raise RuntimePreflightError("user-systemd scope probe failed") from exc
        if result.returncode != 0 or not self._scope_inactive(unit):
            self._kill_scope(unit)
            if not self._scope_inactive(unit):
                raise RuntimePreflightError("user-systemd scope probe cleanup failed")
            raise RuntimePreflightError("user-systemd scope probe failed")
        self._systemctl_run("reset-failed", f"{unit}.scope")
        return ProbeResult(
            operation=PermissionOperation.EXECUTE,
            resource=PermissionResource.PROCESS,
            status="passed",
            evidence_summary="Pinned user-systemd completed a transient scope and became inactive.",
        )

    def _product(self, workspace: Path) -> Path:
        root = workspace.resolve(strict=True)
        product = (root / "project").resolve(strict=True)
        if product.parent != root or not product.is_dir():
            raise RuntimePreflightError("product workspace must be the contained project directory")
        return product

    def preflight(
        self, role_instance: RoleInstance, context_pack: ContextPack, workspace: Path
    ) -> PreflightReceipt:
        resolved = self.catalog.resolve_agent_spec(
            role_instance.agent_spec.definition_id, role_instance.agent_spec.definition_version
        )
        if resolved.backend.provider != "opencode":
            raise RuntimePreflightError("RoleInstance is not pinned to OpenCode")
        if resolved.model_profile.model != self.model:
            raise RuntimePreflightError("RoleInstance is not pinned to the adapter OpenCode model")
        product = self._product(workspace)
        before = workspace_manifest(product).root_digest
        source, executable = self._stage_executable(workspace, role_instance)
        runtime = self._runtime(workspace, role_instance)
        self._version(executable, runtime)
        config, config_digest = self._prepare_home(workspace, role_instance)
        self._validate_installed_config(executable, runtime, product, config)
        model_digest = self._ollama_digest()
        probes = [self._scope_probe()]
        descriptor = os.open(product, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.close(descriptor)
        probes.append(ProbeResult(
            operation=PermissionOperation.READ, resource=PermissionResource.PROJECT_PATH,
            status="passed", evidence_summary="Opened the exact product directory without symlink traversal.",
        ))
        edit_scope = self._write_scope(role_instance)
        if edit_scope:
            probes.append(ProbeResult(
                operation=PermissionOperation.WRITE,
                resource=PermissionResource.PROJECT_PATH,
                status="passed",
                evidence_summary=(
                    "OpenCode writer has product-cwd edit/write capability. "
                    "Compiled assignment scope is " + ", ".join(edit_scope)
                    + "; StageRunner performs immediate authoritative auditing."
                ),
            ))
        if any(
            config["agent"][READONLY_AGENT]["permission"][tool] != "deny"
            for tool in ("edit", "write")
        ):
            raise RuntimePreflightError("OpenCode readonly agent does not deny edits and writes")
        operations = {
            operation for capability in resolved.capabilities for operation in capability.required_operations
        }
        resources = {
            resource for capability in resolved.capabilities for resource in capability.required_resources
        }
        if PermissionOperation.SEND in operations:
            probes.append(ProbeResult(
                operation=PermissionOperation.SEND, resource=PermissionResource.MAILBOX,
                status="passed", evidence_summary="Adapter returns typed semantic values to StageRunner.",
            ))
        if PermissionResource.EVIDENCE in resources:
            probes.append(ProbeResult(
                operation=PermissionOperation.WRITE, resource=PermissionResource.EVIDENCE,
                status="passed", evidence_summary="Evidence writes remain kernel-owned outside OpenCode cwd.",
            ))
        if PermissionOperation.EXECUTE in operations and not any(
            probe.operation == PermissionOperation.EXECUTE for probe in probes
        ):
            probes.append(ProbeResult(
                operation=PermissionOperation.EXECUTE, resource=PermissionResource.PROCESS,
                status="passed", evidence_summary="Pinned OpenCode executable ran under user-systemd.",
            ))
        if workspace_manifest(product).root_digest != before:
            raise RuntimePreflightError("OpenCode preflight changed the product manifest")
        limitations = [
            f"OpenCode source executable: {source.path} (sha256={source.digest}).",
            f"OpenCode private executable: {executable.path} (sha256={executable.digest}, mode=0500, version={self.expected_version}).",
            f"Generated OpenCode config sha256={config_digest}; Ollama model sha256={model_digest}.",
            "OpenCode permissions are not an OS sandbox; assignment-scoped writes are governed by role config and authoritative post-turn StageRunner audit.",
            "The parent OpenCode process can reach localhost Ollama; model web, shell, task, skill, and external-directory tools are denied for this canary.",
        ]
        if source.mode & stat.S_IWGRP:
            limitations.append("Current-user group-writable source bytes were copied to a private 0500 executable.")
        self._configs[role_instance.role_instance_id] = (config, config_digest)
        return PreflightReceipt(
            role_instance_digest=role_instance.resolved_digest,
            context_pack_digest=context_pack.digest,
            catalog_digest=self.catalog.catalog_lock()["catalog_digest"],
            workspace=str(workspace.resolve(strict=True)), backend_id="opencode",
            observed_capabilities=tuple(item.capability_id for item in resolved.capabilities),
            probes=tuple(probes), enforcement_limitations=tuple(limitations),
        )

    def dry_run_plan(self, workspace: Path) -> dict[str, Any]:
        content, source = self._source()
        del content
        systemd = self._pin_systemd()
        self._scope_probe()
        digest = self._ollama_digest()
        effective_permissions = {}
        for config, _ in self._configs.values():
            mutable = config["agent"][MUTABLE_AGENT]
            stage = mutable["description"].removeprefix("CodexTeam ").removesuffix(" worker")
            effective_permissions[stage] = {
                "read": mutable["permission"]["read"],
                "edit": mutable["permission"]["edit"],
                "readonly_edit": config["agent"][READONLY_AGENT]["permission"]["edit"],
            }
        return {
            "backend": "opencode", "version": self.expected_version,
            "source_executable_digest": source.digest,
            "runtime_executable": "<private-runtime>/bin/opencode",
            "runtime_executable_digest": source.digest,
            "systemd_run_digest": systemd[0].digest,
            "systemctl_digest": systemd[1].digest,
            "model": self.model, "ollama_model_digest": digest,
            "workspace": "<temporary>/project",
            "private_home": "<temporary>/.codexteam/v2/runtime/<role>/opencode",
            "model_calls": False,
            "effective_permissions": dict(sorted(effective_permissions.items())),
            "command_previews": (
                f"systemd-run --user --scope ... -- <private-opencode> run --pure --format json --model {self.model} --agent mutable --dir <product> --title <title>",
                f"systemd-run --user --scope ... -- <private-opencode> run --pure --format json --model {self.model} --agent readonly --dir <product> --session <exact-session-id>",
            ),
        }

    def _guidance(self, role: RoleInstance) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        total = 0
        for module in self.catalog.resolve_agent_spec(
            role.agent_spec.definition_id, role.agent_spec.definition_version
        ).guidance_modules:
            content = (self.catalog.root / module.path).read_bytes()
            if hashlib.sha256(content).hexdigest() != module.digest:
                raise RuntimePreflightError(f"guidance content mismatch: {module.path}")
            total += len(content)
            if total > 16 * 1024:
                raise RuntimePreflightError("selected guidance exceeds prompt budget")
            result.append({
                "path": module.path, "sha256": module.digest,
                "content": content.decode("utf-8"),
            })
        return result

    @staticmethod
    def _objective(stage: str) -> str:
        return {
            "discovery": "Inspect README.md and request exactly both optional stages, architecture and ux. Do not change files.",
            "architecture": "Create docs/architecture/CLI.md. Specify one Python stdlib CLI module, iterative Fibonacci, integer argv input, exact stdout, and separate unit/integration tests. Change no other file. The product uses Python stdlib and needs no package manifest.",
            "ux": "Create docs/design/CLI.md. Specify the exact command `python3 src/fib.py 7`, exact stdout `13\\n`, integer input behavior, and concise invalid-input behavior. Change no other file. The product uses Python stdlib and needs no package manifest.",
            "implementation": "Create src/fib.py and tests/test_fib_unit.py only. Implement an importable iterative fibonacci(n: int) and a Python stdlib CLI reading argv[1]; input 7 must print exactly `13\\n`. The unit file must assert fibonacci(7) == 13 without third-party dependencies. Do not create a package manifest.",
            "verification": "Create tests/integration/test_cli.py only. Use Python stdlib subprocess, derive src/fib.py from __file__, assert return code 0, stderr empty, and stdout exactly `13\\n` for argument 7, then print `13\\n` so the verification contract can compare exact stdout. Do not create a package manifest.",
            "assurance": "Audit the implementation and verification evidence for security and privacy risk without changing files.",
            "review": "Independently decide whether the acceptance criterion and evidence justify ACCEPT without changing files.",
        }[stage]

    def _scope_prompt(self, role: RoleInstance, *, read_only: bool) -> str:
        scope = () if read_only else tuple(
            self._product_pattern(pattern) for pattern in self._write_scope(role)
        )
        allowed = ", ".join(scope) if scope else "(none; this turn is read-only)"
        return (
            f"Allowed write paths: {allowed}\n"
            "Any other file is forbidden, including product-root manifests, package files, and configuration. "
            "Within the allowed paths, use normal engineering judgment to complete the objective.\n"
        )

    @staticmethod
    def _candidate_model(stage: str):
        from .base import SemanticAssurance, SemanticCandidate, SemanticDiscovery, SemanticReview
        return {
            "discovery": SemanticDiscovery,
            "assurance": SemanticAssurance,
            "review": SemanticReview,
        }.get(stage, SemanticCandidate)

    @staticmethod
    def _candidate_schema(stage: str) -> dict[str, Any]:
        schema = OpenCodeRuntimeAdapter._candidate_model(stage).model_json_schema(mode="validation")
        schema["$defs"]["EvidenceType"]["enum"] = {
            "discovery": ["analysis"],
            "architecture": ["artifact"],
            "ux": ["artifact"],
            "implementation": ["artifact", "analysis"],
            "verification": ["test_output"],
            "assurance": ["review"],
            "review": ["review"],
        }[stage]
        return schema

    def _turn_prompt(
        self, role: RoleInstance, context: RenderedContext, phase: str, *, candidate: bool = False
    ) -> str:
        items = [
            {
                "category": item.category, "summary": item.summary,
                "locator": item.locator, "content": item.content,
                "sha256": item.content_digest, "intended_use": item.intended_use,
            }
            for item in context.items
        ]
        schema = self._candidate_schema(role.stage_id) if candidate else SemanticResponse.model_json_schema(mode="validation")
        return (
            "[CODEXTEAM V2 OPENCODE TURN]\n"
            f"Stage: {role.stage_id}\nPhase: {phase}\n"
            f"Objective: {self._objective(role.stage_id)}\n"
            "All file paths are relative to this product root. Do not access its parent.\n"
            + self._scope_prompt(role, read_only=candidate)
            + f"Rendered context digest: {context.rendered_digest}\n"
            f"RenderedContext: {json.dumps(items, sort_keys=True)}\n"
            f"Guidance: {json.dumps(self._guidance(role), sort_keys=True)}\n"
            + (
                "Assurance and review decisions must use the supplied implementation candidate, accepted "
                "verification receipt criterion evidence, and assurance report when present.\n"
                if role.stage_id in {"assurance", "review"}
                else ""
            )
            + (
                "Use stage-appropriate evidence: discovery=analysis, architecture/ux=artifact, implementation=artifact or analysis, "
                "verification=test_output, assurance/review=review.\n"
                if candidate
                else ""
            )
            + ("This reporting turn is read-only.\n" if candidate else "")
            + "Return only one raw JSON object, or one exact ```json fence, matching this schema:\n"
            + json.dumps(schema, sort_keys=True)
            + "\n"
        )

    @staticmethod
    def _parse_message(message: str) -> dict[str, Any]:
        value = message.strip()
        if value.startswith("```"):
            match = re.fullmatch(r"```json\r?\n(.*)\r?\n```", value, flags=re.DOTALL)
            if match is None:
                raise RuntimeOutputError("final OpenCode text is not raw JSON or one JSON fence")
            value = match.group(1)
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuntimeOutputError("final OpenCode text is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise RuntimeOutputError("final OpenCode text is not a JSON object")
        return parsed

    @staticmethod
    def _error_text(event: dict[str, Any]) -> str:
        value = event.get("error") or event.get("message") or "OpenCode reported an error"
        if isinstance(value, dict):
            data = value.get("data")
            if isinstance(data, dict) and isinstance(data.get("message"), str):
                value = data["message"]
            else:
                value = value.get("message") or value.get("name") or json.dumps(value, sort_keys=True)
        return str(value)[:500]

    @classmethod
    def _parse_events(cls, stdout: str, *, expected_session: str | None = None) -> tuple[str, dict[str, Any]]:
        session_ids: list[str] = []
        messages: list[str] = []
        failures: list[str] = []
        terminal = 0
        for line_number, raw in enumerate(stdout.splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeOutputError(f"invalid OpenCode JSONL at line {line_number}") from exc
            if not isinstance(event, dict):
                raise RuntimeOutputError(f"invalid OpenCode JSONL object at line {line_number}")
            session_id = event.get("sessionID")
            if not isinstance(session_id, str) or not session_id.strip():
                raise RuntimeSessionError(f"OpenCode event at line {line_number} omitted sessionID")
            session_ids.append(session_id.strip())
            event_type = event.get("type")
            part = event.get("part")
            if event_type == "text" and isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    messages.append(text)
            elif event_type == "step_finish" and isinstance(part, dict) and part.get("reason") == "stop":
                terminal += 1
            elif event_type == "error":
                failures.append(cls._error_text(event))
            elif event_type not in {"step_start", "text", "tool_use", "step_finish", "reasoning"}:
                raise RuntimeOutputError(f"unsupported OpenCode event type at line {line_number}: {event_type!r}")
        unique = tuple(dict.fromkeys(session_ids))
        if len(unique) != 1:
            raise RuntimeSessionError("OpenCode stream did not report one consistent sessionID")
        if expected_session is not None and unique[0] != expected_session:
            raise RuntimeSessionError("OpenCode continuation sessionID mismatch")
        if failures:
            raise RuntimeBackendError("OpenCode reported failure: " + "; ".join(failures))
        if terminal != 1:
            raise RuntimeBackendError("OpenCode JSONL did not report one terminal stop step")
        if not messages:
            raise RuntimeOutputError("OpenCode returned no text part")
        return unique[0], cls._parse_message(messages[-1])

    def _command(
        self, role: RoleInstance, executable: OpenCodeFilePin, product: Path, *,
        session: OpenCodeSessionInfo | None, read_only: bool, agent: str | None = None,
    ) -> list[str]:
        command = [
            executable.path, "run", "--pure", "--format", "json", "--model",
            self.model, "--agent", agent or (READONLY_AGENT if read_only else MUTABLE_AGENT),
            "--dir", str(product),
        ]
        if session is None:
            command.extend(("--title", f"CodexTeam v2 {role.stage_id}"))
        else:
            command.extend(("--session", session.session_id))
        return command

    def _validate_material(
        self, role: RoleInstance, workspace: Path, session: OpenCodeSessionInfo | None = None
    ) -> tuple[OpenCodeFilePin, str, str]:
        source_content, source = self._source()
        del source_content
        pins = self._pins.get(role.role_instance_id)
        if pins is None:
            raise RuntimeSessionError("OpenCode executable was not prepared for this role")
        _, runtime = self._read_pin(Path(pins[1].path), "private OpenCode executable", owners={os.getuid()})
        if (source, runtime) != pins or runtime.mode != 0o500:
            raise RuntimeSessionError("OpenCode executable identity changed")
        config, digest = self._configs.get(role.role_instance_id, (None, None))
        if config is None or digest is None:
            raise RuntimeSessionError("OpenCode config was not prepared for this role")
        path = self._runtime(workspace, role) / "config/opencode/opencode.json"
        if hashlib.sha256(self._read_private(path, mode=0o400)).hexdigest() != digest:
            raise RuntimeSessionError("OpenCode config digest changed")
        model_digest = self._ollama_digest()
        if session is not None and model_digest != session.ollama_model_digest:
            raise RuntimeSessionError("Ollama model digest changed")
        return runtime, digest, model_digest

    def _write_diagnostic(self, directory: Path, name: str, content: str) -> None:
        self._atomic_write(directory / name, content.encode("utf-8"), mode=0o600)

    def _run(
        self, role: RoleInstance, workspace: Path, prompt: str, stem: str, *,
        session: OpenCodeSessionInfo | None, read_only: bool, agent: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        executable, _, _ = self._validate_material(role, workspace, session)
        product = self._product(workspace)
        runtime = self._runtime(workspace, role)
        command = self._command(
            role, executable, product, session=session, read_only=read_only, agent=agent
        )
        if any(flag in command for flag in ("--continue", "--fork", "--auto")):
            raise RuntimeSessionError("unsafe OpenCode continuation flag")
        self._pin_systemd()
        unit = self._unit(role.role_instance_id, stem)
        process: subprocess.Popen[str] | None = None
        stdout = ""
        stderr = ""
        timed_out = False
        self._write_diagnostic(runtime, f"{stem}.prompt.txt", prompt)
        try:
            process = subprocess.Popen(
                self._scope_argv(unit, command), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                shell=False, cwd=product, env=self._environment(runtime),
            )
            try:
                stdout, stderr = process.communicate(prompt, timeout=self._remaining_timeout())
            except subprocess.TimeoutExpired:
                timed_out = True
                self._kill_scope(unit)
                stdout, stderr = process.communicate(timeout=5)
            if not self._scope_inactive(unit, timeout=0):
                self._kill_scope(unit)
                if not self._scope_inactive(unit):
                    raise RuntimeBackendError("HIGH: OpenCode scope cleanup could not be confirmed")
                if not timed_out:
                    raise RuntimeBackendError("OpenCode turn left a lingering descendant")
        except BaseException as exc:
            try:
                self._kill_scope(unit)
                inactive = self._scope_inactive(unit)
            except RuntimeBackendError as cleanup_exc:
                raise RuntimeBackendError("HIGH: OpenCode exception cleanup failed") from cleanup_exc
            if process is not None and process.poll() is None:
                try:
                    process.communicate(timeout=5)
                except subprocess.SubprocessError:
                    pass
            if not inactive or (process is not None and process.poll() is None):
                raise RuntimeBackendError("HIGH: OpenCode exception cleanup was incomplete") from exc
            raise
        finally:
            try:
                self._systemctl_run("reset-failed", f"{unit}.scope")
            except RuntimeBackendError:
                pass
        self._write_diagnostic(runtime, f"{stem}.jsonl", stdout)
        self._write_diagnostic(runtime, f"{stem}.stderr.txt", stderr)
        self._write_diagnostic(
            runtime, f"{stem}.scope.json",
            json.dumps({"scope_unit": f"{unit}.scope", "inactive": True}, sort_keys=True) + "\n",
        )
        self._validate_material(role, workspace, session)
        if timed_out:
            raise RuntimeBackendError(f"OpenCode turn timed out after {self.timeout_seconds} seconds")
        if process is None or process.returncode != 0:
            code = None if process is None else process.returncode
            raise RuntimeBackendError(f"OpenCode process exited {code}; see private {stem}.stderr.txt")
        return self._parse_events(
            stdout, expected_session=session.session_id if session is not None else None
        )

    @staticmethod
    def _qualification_tool_events(stdout: str) -> tuple[dict[str, Any], ...]:
        tools: list[dict[str, Any]] = []
        for raw in stdout.splitlines():
            if not raw.strip():
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("type") != "tool_use":
                continue
            part = event.get("part")
            state = part.get("state") if isinstance(part, dict) else None
            if not isinstance(part, dict) or not isinstance(state, dict):
                continue
            tool = part.get("tool")
            inputs = state.get("input")
            status_value = state.get("status")
            if isinstance(tool, str) and isinstance(inputs, dict) and isinstance(status_value, str):
                tools.append({"tool": tool, "input": inputs, "status": status_value})
        return tuple(tools)

    def qualification_turn(
        self,
        role: RoleInstance,
        workspace: Path,
        prompt: str,
        stem: str,
        *,
        agent: Literal["qualification-text", "qualification-read", "qualification-write"],
        context_digest: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Run one pinned qualification turn without the stage-specific prompt schemas."""
        session = None
        if session_id is not None:
            session = self._load_session(role, workspace)
            self._validate_session(session, session_id, role, context_digest, workspace)
        _, _, model_digest = self._validate_material(role, workspace, session)
        observed_session, value = self._run(
            role,
            workspace,
            prompt,
            stem,
            session=session,
            read_only=agent != QUALIFICATION_WRITE_AGENT,
            agent=agent,
        )
        turn = 1 if session is None else session.turn + 1
        self._store_session(
            session_id=observed_session,
            role=role,
            context_digest=context_digest,
            workspace=workspace,
            phase="qualification",
            turn=turn,
            model_digest=model_digest,
        )
        runtime = self._runtime(workspace, role)
        stdout = self._read_private(runtime / f"{stem}.jsonl").decode("utf-8")
        return {
            "session_id": observed_session,
            "value": value,
            "tools": self._qualification_tool_events(stdout),
            "evidence": {
                "jsonl": str(runtime / f"{stem}.jsonl"),
                "stderr": str(runtime / f"{stem}.stderr.txt"),
                "prompt": str(runtime / f"{stem}.prompt.txt"),
            },
        }

    def _session_bytes(self, session: OpenCodeSessionInfo) -> bytes:
        return self._canonical(session.model_dump(mode="json"))

    def _store_session(
        self, *, session_id: str, role: RoleInstance, context_digest: str,
        workspace: Path,
        phase: Literal["draft", "resume", "feedback", "candidate", "qualification"],
        turn: int, model_digest: str,
    ) -> OpenCodeSessionInfo:
        pins = self._pins[role.role_instance_id]
        _, config_digest = self._configs[role.role_instance_id]
        root = workspace.resolve(strict=True)
        runtime = self._runtime(workspace, role)
        session = OpenCodeSessionInfo(
            session_id=session_id, source_executable=pins[0], runtime_executable=pins[1],
            executable_version=self.expected_version, config_digest=config_digest,
            model=self.model, ollama_model_digest=model_digest,
            backend_id=role.backend.definition_id, role_instance_id=role.role_instance_id,
            role_instance_digest=role.resolved_digest, context_digest=context_digest,
            workspace=str(self._product(workspace)), canary_root=str(root),
            private_home=str(runtime),
            private_config=str(runtime / "config/opencode/opencode.json"),
            mutable_agent=MUTABLE_AGENT, phase=phase, turn=turn,
        )
        self._atomic_write(runtime / "session.json", self._session_bytes(session), mode=0o600)
        self._sessions[session_id] = session
        self._roles[session_id] = role
        return session

    def _load_session(self, role: RoleInstance, workspace: Path) -> OpenCodeSessionInfo:
        content = self._read_private(self._runtime(workspace, role) / "session.json")
        try:
            session = OpenCodeSessionInfo.model_validate_json(content, strict=True)
        except (ValueError, UnicodeError) as exc:
            raise RuntimeSessionError("OpenCode session file is malformed") from exc
        if content != self._session_bytes(session):
            raise RuntimeSessionError("OpenCode session file is not canonical JSON")
        return session

    def _validate_session(
        self, session: OpenCodeSessionInfo, session_id: str, role: RoleInstance,
        context_digest: str, workspace: Path,
    ) -> str:
        executable, config_digest, model_digest = self._validate_material(role, workspace, session)
        expected = {
            "session_id": session_id,
            "source_executable": self._pins[role.role_instance_id][0],
            "runtime_executable": executable,
            "executable_version": self._version(executable, self._runtime(workspace, role)),
            "config_digest": config_digest, "model": self.model,
            "backend_id": role.backend.definition_id,
            "role_instance_id": role.role_instance_id,
            "role_instance_digest": role.resolved_digest,
            "context_digest": context_digest,
            "workspace": str(self._product(workspace)),
            "canary_root": str(workspace.resolve(strict=True)),
            "private_home": str(self._runtime(workspace, role)),
            "private_config": str(self._runtime(workspace, role) / "config/opencode/opencode.json"),
            "mutable_agent": MUTABLE_AGENT,
        }
        for field, value in expected.items():
            if getattr(session, field) != value:
                raise RuntimeSessionError(f"OpenCode session {field} mismatch")
        return model_digest

    @staticmethod
    def _response(value: dict[str, Any]) -> SemanticResponse:
        try:
            return SemanticResponse.model_validate_json(json.dumps(value), strict=True)
        except ValueError as exc:
            raise RuntimeOutputError(f"malformed runtime SemanticResponse: {exc}") from exc

    @staticmethod
    def _semantic(value: dict[str, Any]) -> StageSemantic:
        try:
            return STAGE_SEMANTIC_ADAPTER.validate_json(json.dumps(value), strict=True)
        except ValueError as exc:
            raise RuntimeOutputError(f"malformed runtime stage semantic: {exc}") from exc

    def draft(self, role_instance: RoleInstance, context: RenderedContext, workspace: Path) -> DraftTurn:
        _, _, model_digest = self._validate_material(role_instance, workspace)
        prompt = self._turn_prompt(role_instance, context, "draft")
        session_id, value = self._run(
            role_instance, workspace, prompt, "001-draft", session=None, read_only=False
        )
        self._store_session(
            session_id=session_id, role=role_instance, context_digest=context.rendered_digest,
            workspace=workspace, phase="draft", turn=1, model_digest=model_digest,
        )
        self._contexts[session_id] = context
        return DraftTurn(
            session_id=session_id, response=self._response(value),
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
        prompt = self._turn_prompt(role_instance, context, "resume") + (
            f"Resume after {candidate_sequence} candidate report(s). Reinspect current product files.\n"
        )
        _, value = self._run(
            role_instance, workspace, prompt, f"{session.turn + 1:03d}-resume",
            session=session, read_only=False,
        )
        self._store_session(
            session_id=session_id, role=role_instance, context_digest=context.rendered_digest,
            workspace=workspace, phase="resume", turn=session.turn + 1,
            model_digest=model_digest,
        )
        self._contexts[session_id] = context
        return DraftTurn(
            session_id=session_id, response=self._response(value),
            consumed_context_digest=context.rendered_digest,
        )

    def _active(self, session_id: str) -> tuple[OpenCodeSessionInfo, RoleInstance, Path, str]:
        role = self._roles.get(session_id)
        cached = self._sessions.get(session_id)
        if role is None or cached is None:
            raise RuntimeSessionError("unknown OpenCode session")
        workspace = Path(cached.canary_root)
        session = self._load_session(role, workspace)
        digest = self._validate_session(
            session, session_id, role, cached.context_digest, workspace
        )
        return session, role, workspace, digest

    def feedback(self, session_id: str, defect_packet: DefectPacket) -> SemanticResponse:
        session, role, workspace, digest = self._active(session_id)
        prompt = (
            "[CODEXTEAM V2 FEEDBACK]\nApply this defect packet within the original role: "
            + defect_packet.model_dump_json() + "\n"
            + self._scope_prompt(role, read_only=False)
            + "Return raw JSON matching: "
            + json.dumps(SemanticResponse.model_json_schema(mode="validation"), sort_keys=True)
        )
        _, value = self._run(
            role, workspace, prompt, f"{session.turn + 1:03d}-feedback",
            session=session, read_only=False,
        )
        self._store_session(
            session_id=session_id, role=role, context_digest=session.context_digest,
            workspace=workspace, phase="feedback", turn=session.turn + 1,
            model_digest=digest,
        )
        return self._response(value)

    def candidate(self, session_id: str, *, read_only: bool) -> StageSemantic:
        if not read_only:
            raise RuntimeOutputError("OpenCode candidate requires an explicit read-only turn")
        session, role, workspace, digest = self._active(session_id)
        context = self._contexts.get(session_id)
        if context is None or context.rendered_digest != session.context_digest:
            raise RuntimeSessionError("OpenCode candidate context is unavailable or drifted")
        prompt = self._turn_prompt(role, context, "candidate", candidate=True)
        _, value = self._run(
            role, workspace, prompt, f"{session.turn + 1:03d}-candidate",
            session=session, read_only=True,
        )
        self._store_session(
            session_id=session_id, role=role, context_digest=session.context_digest,
            workspace=workspace, phase="candidate", turn=session.turn + 1,
            model_digest=digest,
        )
        return self._semantic(value)


__all__ = [
    "DEFAULT_OPENCODE_EXECUTABLE", "DEFAULT_OPENCODE_MODEL", "MUTABLE_AGENT",
    "MUSE_CONTEXT_LIMIT", "MUSE_INPUT_LIMIT", "MUSE_OLLAMA_DIGEST", "MUSE_OUTPUT_LIMIT",
    "OpenCodeFilePin", "OpenCodeRuntimeAdapter", "OpenCodeSessionInfo",
    "PINNED_OPENCODE_VERSION", "QUALIFICATION_READ_AGENT", "QUALIFICATION_TEXT_AGENT",
    "QUALIFICATION_WRITE_AGENT", "READONLY_AGENT", "SUPPORTED_OPENCODE_MODELS",
]
