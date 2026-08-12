from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence, TypeVar, cast, get_args

from pydantic import BaseModel

from .canonical import canonical_json_bytes, canonical_sha256
from .models import ContractModel, RecordRef, TOP_LEVEL_MODELS, VersionedRecord, validate_wire


class StorageError(RuntimeError):
    pass


class StorageConflict(StorageError):
    pass


class RevisionConflict(StorageConflict):
    pass


class CorruptStore(StorageError):
    pass


@dataclass(frozen=True)
class StoredEvent:
    aggregate_id: str
    sequence: int
    aggregate_version: int
    previous_event_digest: str | None
    payload: Mapping[str, Any]
    digest: str

    def wire(self) -> dict[str, Any]:
        return {
            "aggregate_id": self.aggregate_id,
            "aggregate_version": self.aggregate_version,
            "digest": self.digest,
            "payload": dict(self.payload),
            "previous_event_digest": self.previous_event_digest,
            "sequence": self.sequence,
        }


@dataclass(frozen=True)
class StateProjection:
    revision: int
    digest: str
    value: Any


TRecord = TypeVar("TRecord", bound=ContractModel)


_MODEL_KINDS = {model: cast(str, get_args(model.model_fields["kind"].annotation)[0]) for model in TOP_LEVEL_MODELS}
_IDENTITY_FIELDS = {
    _MODEL_KINDS[model]: next(
        name for name in model.model_fields if name.endswith("_id") and name not in {"correlation_id", "attempt_id"}
    )
    for model in TOP_LEVEL_MODELS
}
_MODEL_REGISTRY: dict[str, type[ContractModel]] = {
    _MODEL_KINDS[model]: model for model in TOP_LEVEL_MODELS
}


def _identifier(value: str, label: str) -> str:
    if not value or len(value) > 240 or not all(char.isalnum() or char in "._:-" for char in value):
        raise ValueError(f"{label} is not a safe identifier")
    return value


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class V2ProjectStore:
    """Contained, lock-coordinated filesystem persistence for a single project."""

    def __init__(self, project: str | Path, *, lock_timeout: float = 5.0) -> None:
        requested = Path(project).absolute()
        self._reject_symlink_ancestors(requested)
        if requested.exists() and not requested.is_dir():
            raise ValueError("project root must be a real directory")
        requested.mkdir(parents=True, exist_ok=True)
        self.project = requested.resolve(strict=True)
        self._reject_symlink_ancestors(self.project)
        identity = os.stat(self.project, follow_symlinks=False)
        self._project_identity = (identity.st_dev, identity.st_ino)
        self.root = self.project / ".codexteam" / "v2"
        self.lock_timeout = lock_timeout
        self._ensure_layout()

    @staticmethod
    def _reject_symlink_ancestors(path: Path) -> None:
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current /= part
            try:
                metadata = os.lstat(current)
            except FileNotFoundError:
                continue
            if os.path.islink(current):
                raise ValueError(f"project path must not have symlink ancestors: {current}")
            if current != path and not os.path.isdir(current):
                raise ValueError(f"project ancestor is not a directory: {current}")

    def _verify_project_root(self) -> None:
        try:
            metadata = os.stat(self.project, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise CorruptStore("project root was removed") from exc
        if os.path.islink(self.project) or (metadata.st_dev, metadata.st_ino) != self._project_identity:
            raise CorruptStore("project root identity changed")

    @contextmanager
    def _project_fd(self) -> Iterator[int]:
        try:
            descriptor = os.open(self.project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise CorruptStore("project root cannot be opened safely") from exc
        try:
            metadata = os.fstat(descriptor)
            if (metadata.st_dev, metadata.st_ino) != self._project_identity:
                raise CorruptStore("project root identity changed")
            yield descriptor
        finally:
            os.close(descriptor)

    def _relative_parts(self, path: Path) -> tuple[str, ...]:
        try:
            parts = path.absolute().relative_to(self.project).parts
        except ValueError as exc:
            raise ValueError("store operation escaped the project root") from exc
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("invalid contained store path")
        return parts

    @contextmanager
    def _directory_fd(self, path: Path, *, create: bool = False) -> Iterator[int]:
        parts = self._relative_parts(path)
        with self._project_fd() as project_fd:
            descriptor = os.dup(project_fd)
            try:
                for part in parts:
                    if create:
                        try:
                            os.mkdir(part, mode=0o700, dir_fd=descriptor)
                        except FileExistsError:
                            pass
                    try:
                        child = os.open(
                            part,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=descriptor,
                        )
                    except FileNotFoundError:
                        raise
                    except OSError as exc:
                        raise CorruptStore(f"store directory cannot be opened safely: {path}") from exc
                    os.close(descriptor)
                    descriptor = child
                yield descriptor
            finally:
                os.close(descriptor)

    @contextmanager
    def _parent_fd(self, path: Path, *, create: bool = False) -> Iterator[tuple[int, str]]:
        with self._directory_fd(path.parent, create=create) as descriptor:
            yield descriptor, path.name

    def _path_exists(self, path: Path) -> bool:
        try:
            with self._parent_fd(path) as (parent, name):
                os.stat(name, dir_fd=parent, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False

    def _read_bytes(self, path: Path) -> bytes:
        with self._parent_fd(path) as (parent, name):
            try:
                descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            except OSError as exc:
                if isinstance(exc, FileNotFoundError):
                    raise
                raise CorruptStore(f"store file cannot be opened safely: {path}") from exc
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise CorruptStore(f"store path is not a regular file: {path}")
                chunks = []
                while chunk := os.read(descriptor, 1024 * 1024):
                    chunks.append(chunk)
                return b"".join(chunks)
            finally:
                os.close(descriptor)

    def _write_projection(self, area: str, name: str, content: bytes, *, create_only: bool = False) -> bool:
        path = self._contained(area, name)
        if create_only:
            return self._create_only(path, content)
        self._atomic_replace(path, content)
        return True

    def _read_projection(self, area: str, *parts: str) -> bytes:
        return self._read_bytes(self._contained(area, *parts))

    def _ensure_layout(self) -> None:
        with self._project_fd() as descriptor:
            del descriptor
        current = self.project
        for part in (".codexteam", "v2"):
            current /= part
            with self._directory_fd(current, create=True):
                pass
        for relative in ("records", "mailbox", "events", "state", "evidence", "seals", "views", "runtime"):
            path = self.root / relative
            with self._directory_fd(path, create=True):
                pass
        with self._directory_fd(self.root / "records" / "_idempotency", create=True):
            pass

    def register_record_type(self, kind: str, model_type: type[ContractModel], identity_field: str) -> None:
        _identifier(kind, "record kind")
        if kind in _MODEL_REGISTRY and _MODEL_REGISTRY[kind] is not model_type:
            raise ValueError(f"record kind {kind!r} is already registered")
        _MODEL_REGISTRY[kind] = model_type
        _IDENTITY_FIELDS[kind] = identity_field

    def _contained(self, relative: str, *parts: str) -> Path:
        self._verify_project_root()
        if relative not in {"records", "mailbox", "events", "state", "evidence", "seals", "views", "runtime"}:
            raise ValueError("unknown store area")
        path = self.root / relative
        for part in parts:
            _identifier(part, "path component")
            path = path / part
        cursor = self.root
        for part in path.relative_to(self.root).parts:
            cursor = cursor / part
            try:
                metadata = os.lstat(cursor)
            except FileNotFoundError:
                continue
            if os.path.islink(cursor):
                raise ValueError(f"store path must not be a symlink: {cursor}")
            if cursor != path and not os.path.isdir(cursor):
                raise CorruptStore(f"store ancestor is not a directory: {cursor}")
        return path

    @contextmanager
    def run_lock(self, run_id: str = "project", *, timeout: float | None = None) -> Iterator[None]:
        self._verify_project_root()
        lock_path = self._contained("runtime", f"{_identifier(run_id, 'run ID')}.lock")
        with self._parent_fd(lock_path, create=True) as (parent, name):
            descriptor = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        deadline = time.monotonic() + (self.lock_timeout if timeout is None else timeout)
        try:
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"timed out acquiring run lock {run_id!r}")
                    time.sleep(0.01)
            self._verify_project_root()
            self._contained("runtime", lock_path.name)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _atomic_replace(self, path: Path, content: bytes) -> None:
        with self._parent_fd(path, create=True) as (parent, name):
            temporary = f".{name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            try:
                with os.fdopen(descriptor, "wb", closefd=True) as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass

    def _create_only(self, path: Path, content: bytes) -> bool:
        with self._parent_fd(path, create=True) as (parent, name):
            temporary = f".{name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            try:
                with os.fdopen(descriptor, "wb", closefd=True) as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                except FileExistsError:
                    return False
                os.fsync(parent)
                return True
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass

    def _append_bytes(self, path: Path, content: bytes) -> None:
        with self._parent_fd(path, create=True) as (parent, name):
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise CorruptStore(f"store path is not a regular file: {path}")
                with os.fdopen(descriptor, "ab", closefd=True) as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise

    def write_immutable(self, record: TRecord, idempotency_key: str, *, _locked: bool = False) -> RecordRef:
        kind = getattr(record, "kind", None)
        if kind not in _MODEL_REGISTRY:
            raise ValueError(f"unknown record kind: {kind!r}")
        checked = cast(TRecord, validate_wire(_MODEL_REGISTRY[kind], record.model_dump(mode="json")))
        identity_field = _IDENTITY_FIELDS[kind]
        record_id = _identifier(cast(str, getattr(checked, identity_field)), "record ID")
        key = _identifier(idempotency_key, "idempotency key")
        content = canonical_json_bytes(checked)
        digest = _sha256(content)
        record_path = self._contained("records", kind, f"{record_id}.json")
        key_path = self._contained("records", "_idempotency", kind, f"{key}.json")
        key_content = canonical_json_bytes({"digest": digest, "record_id": record_id})
        context = nullcontext() if _locked else self.run_lock("records")
        with context:
            if self._path_exists(key_path):
                try:
                    prior = json.loads(self._read_bytes(key_path))
                except (OSError, json.JSONDecodeError) as exc:
                    raise CorruptStore(f"invalid idempotency record for {kind}/{key}") from exc
                if prior != {"digest": digest, "record_id": record_id}:
                    raise StorageConflict(f"idempotency key conflict for {kind}/{key}")
            if self._path_exists(record_path):
                prior_content = self._read_bytes(record_path)
                if prior_content != content:
                    raise StorageConflict(f"immutable record conflict for {kind}/{record_id}")
            else:
                self._create_only(record_path, content)
            if not self._path_exists(key_path):
                self._create_only(key_path, key_content)
        return RecordRef(record_id=record_id, kind=kind, digest=digest)

    def commit_records_event(
        self,
        operation_id: str,
        records: Sequence[tuple[ContractModel, str]],
        aggregate_id: str,
        payload: Mapping[str, Any],
        *,
        expected_version: int,
        allow_interleaving: bool = False,
        _locked: bool = False,
    ) -> StoredEvent:
        """Journal immutable records before atomically recoverable event publication."""
        operation = _identifier(operation_id, "operation ID")
        aggregate = _identifier(aggregate_id, "aggregate ID")
        allow_interleaving = allow_interleaving or aggregate == "mailbox"
        intent_records = []
        for record, key in records:
            kind = cast(str, getattr(record, "kind"))
            identity = cast(str, getattr(record, _IDENTITY_FIELDS[kind]))
            intent_records.append(
                {
                    "digest": canonical_sha256(record),
                    "idempotency_key": _identifier(key, "idempotency key"),
                    "kind": kind,
                    "record_id": identity,
                    "wire": record.model_dump(mode="json"),
                }
            )
        payload_value = dict(payload)
        payload_digest = canonical_sha256(payload_value)
        intent = {
            "aggregate_id": aggregate,
            "allow_interleaving": allow_interleaving,
            "expected_version": expected_version,
            "operation_id": operation,
            "payload": payload_value,
            "payload_digest": payload_digest,
            "records": intent_records,
            "status": "intent",
        }
        journal_path = self._contained("runtime", f"journal-{operation}.json")
        content = canonical_json_bytes(intent)
        context = nullcontext() if _locked else self.run_lock(aggregate)
        with context:
            if self._path_exists(journal_path):
                try:
                    journal_content = self._read_bytes(journal_path)
                    journal = json.loads(journal_content)
                except (OSError, json.JSONDecodeError) as exc:
                    raise CorruptStore(f"invalid operation journal for {operation}") from exc
                if not isinstance(journal, dict) or canonical_json_bytes(journal) != journal_content:
                    raise CorruptStore(f"operation journal is not canonical for {operation}")
            elif not self._create_only(journal_path, content):
                raise CorruptStore(f"unable to create operation journal for {operation}")
            else:
                journal = intent
            status = journal.get("status")
            if status not in {"intent", "records_written", "event_committed"}:
                raise CorruptStore(f"invalid operation journal status for {operation}")
            stable_prior = {
                "aggregate_id": journal.get("aggregate_id"),
                "allow_interleaving": journal.get("allow_interleaving"),
                "operation_id": journal.get("operation_id"),
                "payload": journal.get("payload"),
                "payload_digest": journal.get("payload_digest"),
                "records": [
                    (item.get("kind"), item.get("record_id"), item.get("idempotency_key"))
                    for item in journal.get("records", [])
                    if isinstance(item, dict)
                ],
            }
            stable_current = {
                "aggregate_id": aggregate,
                "allow_interleaving": allow_interleaving,
                "operation_id": operation,
                "payload": payload_value,
                "payload_digest": payload_digest,
                "records": [
                    (item["kind"], item["record_id"], item["idempotency_key"])
                    for item in intent_records
                ],
            }
            if stable_prior != stable_current or (
                status != "event_committed"
                and not allow_interleaving
                and journal.get("expected_version") != expected_version
            ):
                raise CorruptStore(f"operation journal conflict for {operation}")
            if not isinstance(journal.get("records"), list):
                raise CorruptStore(f"invalid operation journal records for {operation}")

            for item in journal["records"]:
                if not isinstance(item, dict):
                    raise CorruptStore(f"invalid journaled record for {operation}")
                try:
                    kind = cast(str, item["kind"])
                    model_type = _MODEL_REGISTRY[kind]
                    record = validate_wire(model_type, item["wire"])
                    identity = cast(str, getattr(record, _IDENTITY_FIELDS[kind]))
                    key = _identifier(item["idempotency_key"], "idempotency key")
                except (KeyError, TypeError, ValueError) as exc:
                    raise CorruptStore(f"invalid journaled record for {operation}") from exc
                if identity != item.get("record_id") or canonical_sha256(record) != item.get("digest"):
                    raise CorruptStore(f"journaled record digest mismatch for {kind}/{identity}")
                reference = self.write_immutable(record, key, _locked=aggregate == "records")
                if reference.digest != item["digest"] or self.resolve(reference) != record:
                    raise CorruptStore(f"journaled record mismatch for {kind}/{identity}")

            if status == "intent":
                journal = {**journal, "status": "records_written"}
                self._atomic_replace(journal_path, canonical_json_bytes(journal))
                status = "records_written"

            events = self.replay_events(aggregate, recover_truncated=True, _locked=True)
            matches = [
                event
                for event in events
                if event.payload.get("operation_id") == operation
                and event.payload.get("operation_payload_digest") == payload_digest
            ]
            if len(matches) > 1:
                raise CorruptStore(f"operation {operation} was published more than once")
            if matches:
                event = matches[0]
                if status == "event_committed":
                    try:
                        recorded_event = StoredEvent(**journal["event"])
                    except (KeyError, TypeError, ValueError) as exc:
                        raise CorruptStore(f"invalid committed operation journal for {operation}") from exc
                    if recorded_event != event:
                        raise CorruptStore(f"committed operation journal has no matching event for {operation}")
                committed = {**journal, "status": "event_committed", "event": event.wire()}
                self._atomic_replace(journal_path, canonical_json_bytes(committed))
                return event
            if any(event.payload.get("operation_id") == operation for event in events):
                raise CorruptStore(f"operation event digest conflict for {operation}")
            if status == "event_committed":
                raise CorruptStore(f"committed operation journal has no matching event for {operation}")
            if not allow_interleaving and len(events) != expected_version:
                raise RevisionConflict(f"event version is {len(events)}, expected {expected_version}")
            event_payload = {
                **payload_value,
                "operation_id": operation,
                "operation_payload_digest": payload_digest,
            }
            event = self.append_event(
                aggregate,
                event_payload,
                expected_version=len(events),
                _locked=True,
            )
            committed = {**journal, "status": "event_committed", "event": event.wire()}
            self._atomic_replace(journal_path, canonical_json_bytes(committed))
            return event

    def journaled_record(self, operation_id: str, kind: str, record_id: str) -> ContractModel | None:
        operation = _identifier(operation_id, "operation ID")
        model_type = _MODEL_REGISTRY.get(kind)
        if model_type is None:
            raise ValueError(f"unknown record kind: {kind!r}")
        identity = _identifier(record_id, "record ID")
        path = self._contained("runtime", f"journal-{operation}.json")
        if not self._path_exists(path):
            return None
        try:
            content = self._read_bytes(path)
            intent = json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            raise CorruptStore(f"invalid operation journal for {operation}") from exc
        if canonical_json_bytes(intent) != content or not isinstance(intent, dict) or not isinstance(intent.get("records"), list):
            raise CorruptStore(f"invalid operation journal for {operation}")
        matches = [
            item
            for item in intent["records"]
            if isinstance(item, dict) and item.get("kind") == kind and item.get("record_id") == identity
        ]
        if len(matches) != 1:
            raise CorruptStore(f"journal does not uniquely bind {kind}/{identity}")
        item = matches[0]
        try:
            record = validate_wire(model_type, item["wire"])
        except (KeyError, ValueError) as exc:
            raise CorruptStore(f"invalid journaled record {kind}/{identity}") from exc
        if canonical_sha256(record) != item.get("digest"):
            raise CorruptStore(f"journaled record digest mismatch for {kind}/{identity}")
        return record

    def read_record(self, kind: str, record_id: str, *, expected_digest: str | None = None) -> ContractModel:
        model_type = _MODEL_REGISTRY.get(kind)
        if model_type is None:
            raise ValueError(f"unknown record kind: {kind!r}")
        path = self._contained("records", kind, f"{_identifier(record_id, 'record ID')}.json")
        try:
            content = self._read_bytes(path)
            data = json.loads(content)
        except FileNotFoundError:
            raise
        except (OSError, json.JSONDecodeError) as exc:
            raise CorruptStore(f"invalid record {kind}/{record_id}") from exc
        record = validate_wire(model_type, data)
        canonical = canonical_json_bytes(record)
        if content != canonical:
            raise CorruptStore(f"record {kind}/{record_id} is not canonical")
        if expected_digest is not None and _sha256(canonical) != expected_digest:
            raise CorruptStore(f"record digest mismatch for {kind}/{record_id}")
        return record

    def resolve(self, reference: RecordRef) -> ContractModel:
        return self.read_record(reference.kind, reference.record_id, expected_digest=reference.digest)

    def records(self, kind: str) -> tuple[ContractModel, ...]:
        if kind not in _MODEL_REGISTRY:
            raise ValueError(f"unknown record kind: {kind!r}")
        directory = self._contained("records", kind)
        try:
            with self._directory_fd(directory) as descriptor:
                names = os.listdir(descriptor)
        except FileNotFoundError:
            return ()
        record_ids = sorted(name[:-5] for name in names if name.endswith(".json"))
        return tuple(self.read_record(kind, record_id) for record_id in record_ids)

    def reference(self, record: ContractModel) -> RecordRef:
        kind = cast(str, getattr(record, "kind"))
        return RecordRef(
            record_id=cast(str, getattr(record, _IDENTITY_FIELDS[kind])),
            kind=kind,
            digest=canonical_sha256(record),
        )

    def append_event(
        self,
        aggregate_id: str,
        payload: Mapping[str, Any] | BaseModel,
        *,
        expected_version: int | None = None,
        _locked: bool = False,
    ) -> StoredEvent:
        payload_value = (
            cast(BaseModel, payload).model_dump(mode="json")
            if isinstance(payload, BaseModel)
            else dict(payload)
        )
        if payload_value.get("type") == "candidate_processed":
            raise PermissionError(
                "candidate_processed is a kernel-reserved event type"
            )
        return self._append_event_internal(
            aggregate_id,
            payload_value,
            expected_version=expected_version,
            _locked=_locked,
        )

    def _append_event_internal(
        self,
        aggregate_id: str,
        payload: Mapping[str, Any],
        *,
        expected_version: int | None = None,
        _locked: bool = False,
    ) -> StoredEvent:
        aggregate = _identifier(aggregate_id, "aggregate ID")
        context = nullcontext() if _locked else self.run_lock(aggregate)
        with context:
            events = self.replay_events(aggregate, recover_truncated=True, _locked=True)
            version = len(events)
            payload_value = dict(payload)
            if expected_version is not None and expected_version != version:
                if 0 <= expected_version < version and events[expected_version].payload == payload_value:
                    return events[expected_version]
                raise RevisionConflict(f"event version is {version}, expected {expected_version}")
            body = {
                "aggregate_id": aggregate,
                "aggregate_version": version + 1,
                "payload": payload_value,
                "previous_event_digest": events[-1].digest if events else None,
                "sequence": version + 1,
            }
            event = StoredEvent(**body, digest=canonical_sha256(body))
            path = self._contained("events", f"{aggregate}.jsonl")
            self._append_bytes(path, canonical_json_bytes(event.wire()) + b"\n")
            return event

    def replay_events(
        self, aggregate_id: str, *, recover_truncated: bool = True, _locked: bool = False
    ) -> tuple[StoredEvent, ...]:
        aggregate = _identifier(aggregate_id, "aggregate ID")
        path = self._contained("events", f"{aggregate}.jsonl")
        if not self._path_exists(path):
            return ()
        content = self._read_bytes(path)
        lines = content.splitlines(keepends=True)
        events: list[StoredEvent] = []
        valid_length = 0
        for index, raw in enumerate(lines):
            complete = raw.endswith(b"\n")
            line = raw[:-1] if complete else raw
            try:
                data = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                if index == len(lines) - 1 and not complete and recover_truncated:
                    if not _locked:
                        with self.run_lock(aggregate):
                            return self.replay_events(aggregate, recover_truncated=True, _locked=True)
                    self._atomic_replace(path, content[:valid_length])
                    break
                raise CorruptStore(f"invalid event JSON at sequence {index + 1}") from exc
            expected_fields = {
                "aggregate_id", "aggregate_version", "digest", "payload", "previous_event_digest", "sequence"
            }
            if not isinstance(data, dict) or set(data) != expected_fields or not isinstance(data["payload"], dict):
                raise CorruptStore(f"invalid event envelope at sequence {index + 1}")
            body = {name: data[name] for name in expected_fields - {"digest"}}
            expected_previous = events[-1].digest if events else None
            if (
                data["aggregate_id"] != aggregate
                or type(data["sequence"]) is not int
                or type(data["aggregate_version"]) is not int
                or data["sequence"] != index + 1
                or data["aggregate_version"] != index + 1
                or data["previous_event_digest"] != expected_previous
                or data["digest"] != canonical_sha256(body)
            ):
                raise CorruptStore(f"broken event chain at sequence {index + 1}")
            events.append(
                StoredEvent(
                    aggregate_id=aggregate,
                    sequence=data["sequence"],
                    aggregate_version=data["aggregate_version"],
                    previous_event_digest=data["previous_event_digest"],
                    payload=data["payload"],
                    digest=data["digest"],
                )
            )
            valid_length += len(raw)
            if index == len(lines) - 1 and not complete and recover_truncated:
                if not _locked:
                    with self.run_lock(aggregate):
                        return self.replay_events(aggregate, recover_truncated=True, _locked=True)
                self._atomic_replace(path, content + b"\n")
        return tuple(events)

    def read_state(self, name: str) -> StateProjection | None:
        path = self._contained("state", f"{_identifier(name, 'state name')}.json")
        if not self._path_exists(path):
            return None
        try:
            data = json.loads(self._read_bytes(path))
        except (OSError, json.JSONDecodeError) as exc:
            raise CorruptStore(f"invalid state projection {name!r}") from exc
        if not isinstance(data, dict) or set(data) != {"digest", "revision", "value"}:
            raise CorruptStore(f"invalid state projection {name!r}")
        if type(data["revision"]) is not int or data["revision"] < 1 or data["digest"] != canonical_sha256(data["value"]):
            raise CorruptStore(f"invalid state digest for {name!r}")
        return StateProjection(data["revision"], data["digest"], data["value"])

    def replace_state(
        self,
        name: str,
        value: Any,
        *,
        expected_revision: int,
        expected_digest: str | None = None,
    ) -> StateProjection:
        state_name = _identifier(name, "state name")
        with self.run_lock(f"state-{state_name}"):
            prior = self.read_state(state_name)
            revision = prior.revision if prior else 0
            if revision != expected_revision or (expected_digest is not None and (prior is None or prior.digest != expected_digest)):
                if prior is not None and revision == expected_revision + 1 and prior.digest == canonical_sha256(value):
                    return prior
                raise RevisionConflict(f"state revision is {revision}, expected {expected_revision}")
            projected = StateProjection(revision + 1, canonical_sha256(value), value)
            self._atomic_replace(
                self._contained("state", f"{state_name}.json"),
                canonical_json_bytes({"digest": projected.digest, "revision": projected.revision, "value": value}),
            )
            return projected


__all__ = [
    "CorruptStore",
    "RevisionConflict",
    "StateProjection",
    "StorageConflict",
    "StorageError",
    "StoredEvent",
    "V2ProjectStore",
]
