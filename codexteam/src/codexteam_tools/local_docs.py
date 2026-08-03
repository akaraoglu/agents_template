from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import re
import sqlite3
import sys
import tempfile
import tokenize
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

from .paths import PathValidationError, contained_path, safe_relative_path

MANIFEST_SCHEMA_VERSION = 1
INDEX_SCHEMA_VERSION = 1
DEFAULT_MAX_FILE_BYTES = 1_000_000
DEFAULT_CHUNK_CHARS = 2_400
MAX_CHUNK_CHARS = 6_000
MAX_SEARCH_RESULTS = 8
MAX_READ_CHARS = 6_000
SOURCE_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,63}")
SUPPORTED_TEXT_SUFFIXES = {".md", ".rst", ".txt"}
HARD_EXCLUDED_PARTS = {
    ".git",
    ".codexteam",
    ".pytest_cache",
    "__pycache__",
    "archive",
    "archives",
    "node_modules",
}
QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "use",
    "using",
    "with",
}


class LocalDocsError(ValueError):
    pass


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    adapter: str
    options: dict[str, Any]


@dataclass(frozen=True)
class LocalDocsConfig:
    manifest_path: Path
    workspace_root: Path
    index_path: Path
    max_file_bytes: int
    chunk_chars: int
    sources: tuple[SourceSpec, ...]


@dataclass(frozen=True)
class Document:
    source_id: str
    locator: str
    title: str
    section: str
    version: str
    text: str
    sha256: str
    source_bytes: int

    @classmethod
    def create(
        cls,
        *,
        source_id: str,
        locator: str,
        title: str,
        section: str,
        version: str,
        text: str,
        source_bytes: int,
    ) -> Document:
        clean_text = text.strip()
        if not clean_text:
            raise LocalDocsError(f"empty document text for {source_id}:{locator}")
        return cls(
            source_id=source_id,
            locator=locator,
            title=title.strip() or locator,
            section=section.strip() or title.strip() or locator,
            version=version.strip(),
            text=clean_text,
            sha256=hashlib.sha256(clean_text.encode("utf-8")).hexdigest(),
            source_bytes=source_bytes,
        )

    def digest_record(self) -> dict[str, Any]:
        return {
            "locator": self.locator,
            "section": self.section,
            "sha256": self.sha256,
            "source_bytes": self.source_bytes,
            "source_id": self.source_id,
            "text": self.text,
            "title": self.title,
            "version": self.version,
        }


@dataclass(frozen=True)
class SourceSummary:
    source_id: str
    adapter: str
    version: str
    root_label: str
    document_count: int
    source_bytes: int
    sha256: str


@dataclass(frozen=True)
class IndexPlan:
    config: LocalDocsConfig
    documents: tuple[Document, ...]
    sources: tuple[SourceSummary, ...]
    sha256: str

    def summary(self, *, action: str) -> dict[str, Any]:
        return {
            "action": action,
            "index_path": str(self.config.index_path),
            "sha256": self.sha256,
            "document_count": len(self.documents),
            "source_count": len(self.sources),
            "sources": [
                {
                    "id": source.source_id,
                    "adapter": source.adapter,
                    "version": source.version,
                    "documents": source.document_count,
                    "source_bytes": source.source_bytes,
                    "sha256": source.sha256,
                }
                for source in self.sources
            ],
        }


Adapter = Callable[[LocalDocsConfig, SourceSpec], tuple[str, str, list[Document]]]


def load_config(manifest_path: str | Path) -> LocalDocsConfig:
    manifest_input = Path(manifest_path).expanduser()
    if manifest_input.is_symlink():
        raise LocalDocsError(f"manifest cannot be a symlink: {manifest_input}")
    manifest = manifest_input.resolve(strict=True)
    if not manifest.is_file():
        raise LocalDocsError(f"manifest must be a regular file: {manifest}")
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    if set(data) != {"schema_version", "index", "sources"}:
        raise LocalDocsError(
            "manifest must contain only schema_version, index, and sources"
        )
    if data["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise LocalDocsError(
            f"unsupported manifest schema_version: {data['schema_version']!r}"
        )
    index = data["index"]
    if not isinstance(index, dict):
        raise LocalDocsError("index must be a table")
    allowed_index_fields = {"path", "max_file_bytes", "chunk_chars"}
    unknown_index_fields = sorted(set(index) - allowed_index_fields)
    if unknown_index_fields:
        raise LocalDocsError(
            "unknown index fields: " + ", ".join(unknown_index_fields)
        )
    index_relative = _required_string(index, "path", label="index.path")
    workspace_root = manifest.parent.resolve(strict=True)
    safe_index = safe_relative_path(index_relative, label="index path")
    index_input = workspace_root / Path(*safe_index.parts)
    if index_input.is_symlink():
        raise LocalDocsError(f"index path cannot be a symlink: {index_input}")
    index_path = contained_path(workspace_root, index_relative, label="index path")
    max_file_bytes = _bounded_integer(
        index.get("max_file_bytes", DEFAULT_MAX_FILE_BYTES),
        label="index.max_file_bytes",
        minimum=1_024,
        maximum=10_000_000,
    )
    chunk_chars = _bounded_integer(
        index.get("chunk_chars", DEFAULT_CHUNK_CHARS),
        label="index.chunk_chars",
        minimum=400,
        maximum=MAX_CHUNK_CHARS,
    )
    raw_sources = data["sources"]
    if not isinstance(raw_sources, list) or not raw_sources:
        raise LocalDocsError("sources must be a non-empty array of tables")
    sources: list[SourceSpec] = []
    seen: set[str] = set()
    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            raise LocalDocsError("each source must be a table")
        source_id = _required_string(raw_source, "id", label="source.id")
        if SOURCE_ID_PATTERN.fullmatch(source_id) is None:
            raise LocalDocsError(f"invalid source id: {source_id!r}")
        if source_id in seen:
            raise LocalDocsError(f"duplicate source id: {source_id}")
        adapter = _required_string(raw_source, "adapter", label="source.adapter")
        if adapter not in ADAPTERS:
            raise LocalDocsError(f"unsupported adapter for {source_id}: {adapter}")
        options = {
            key: value
            for key, value in raw_source.items()
            if key not in {"id", "adapter"}
        }
        _validate_source_options(source_id, adapter, options)
        sources.append(SourceSpec(source_id, adapter, options))
        seen.add(source_id)
    return LocalDocsConfig(
        manifest_path=manifest,
        workspace_root=workspace_root,
        index_path=index_path,
        max_file_bytes=max_file_bytes,
        chunk_chars=chunk_chars,
        sources=tuple(sources),
    )


def collect_index(config: LocalDocsConfig) -> IndexPlan:
    all_documents: list[Document] = []
    summaries: list[SourceSummary] = []
    seen_locators: set[tuple[str, str]] = set()
    for spec in config.sources:
        version, root_label, documents = ADAPTERS[spec.adapter](config, spec)
        ordered = sorted(documents, key=lambda item: item.locator)
        if not ordered:
            raise LocalDocsError(f"source produced no documents: {spec.source_id}")
        for document in ordered:
            identity = (document.source_id, document.locator)
            if identity in seen_locators:
                raise LocalDocsError(
                    f"duplicate document locator: {document.source_id}:{document.locator}"
                )
            seen_locators.add(identity)
        source_digest = _records_digest(
            [document.digest_record() for document in ordered]
        )
        summaries.append(
            SourceSummary(
                source_id=spec.source_id,
                adapter=spec.adapter,
                version=version,
                root_label=root_label,
                document_count=len(ordered),
                source_bytes=sum(document.source_bytes for document in ordered),
                sha256=source_digest,
            )
        )
        all_documents.extend(ordered)
    all_documents.sort(key=lambda item: (item.source_id, item.locator))
    summaries.sort(key=lambda item: item.source_id)
    digest = _records_digest(
        [document.digest_record() for document in all_documents]
    )
    return IndexPlan(
        config=config,
        documents=tuple(all_documents),
        sources=tuple(summaries),
        sha256=digest,
    )


def write_index(plan: IndexPlan) -> None:
    destination = plan.config.index_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        connection = sqlite3.connect(temporary)
        try:
            connection.executescript(
                """
                PRAGMA journal_mode = OFF;
                PRAGMA synchronous = OFF;
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE sources (
                    source_id TEXT PRIMARY KEY,
                    adapter TEXT NOT NULL,
                    version TEXT NOT NULL,
                    root_label TEXT NOT NULL,
                    document_count INTEGER NOT NULL,
                    source_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL
                );
                CREATE TABLE documents (
                    id INTEGER PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES sources(source_id),
                    locator TEXT NOT NULL,
                    title TEXT NOT NULL,
                    section TEXT NOT NULL,
                    version TEXT NOT NULL,
                    text TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    source_bytes INTEGER NOT NULL,
                    UNIQUE(source_id, locator)
                );
                CREATE VIRTUAL TABLE documents_fts USING fts5(
                    title,
                    section,
                    text,
                    content='documents',
                    content_rowid='id',
                    tokenize='unicode61'
                );
                """
            )
            metadata = {
                "schema_version": str(INDEX_SCHEMA_VERSION),
                "sha256": plan.sha256,
                "document_count": str(len(plan.documents)),
                "source_count": str(len(plan.sources)),
            }
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                sorted(metadata.items()),
            )
            connection.executemany(
                """
                INSERT INTO sources(
                    source_id, adapter, version, root_label,
                    document_count, source_bytes, sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        source.source_id,
                        source.adapter,
                        source.version,
                        source.root_label,
                        source.document_count,
                        source.source_bytes,
                        source.sha256,
                    )
                    for source in plan.sources
                ],
            )
            connection.executemany(
                """
                INSERT INTO documents(
                    source_id, locator, title, section, version,
                    text, sha256, source_bytes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        document.source_id,
                        document.locator,
                        document.title,
                        document.section,
                        document.version,
                        document.text,
                        document.sha256,
                        document.source_bytes,
                    )
                    for document in plan.documents
                ],
            )
            connection.execute(
                "INSERT INTO documents_fts(documents_fts) VALUES ('rebuild')"
            )
            connection.commit()
        finally:
            connection.close()
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def verify_index(plan: IndexPlan) -> dict[str, Any]:
    actual = _read_metadata(plan.config.index_path)
    expected = {
        "schema_version": str(INDEX_SCHEMA_VERSION),
        "sha256": plan.sha256,
        "document_count": str(len(plan.documents)),
        "source_count": str(len(plan.sources)),
    }
    return {
        **plan.summary(action="verify"),
        "verified": actual == expected,
        "expected": expected,
        "actual": actual,
    }


class LocalDocsReader:
    def __init__(self, index_path: str | Path) -> None:
        index_input = Path(index_path).expanduser()
        if index_input.is_symlink():
            raise LocalDocsError(f"index cannot be a symlink: {index_input}")
        path = index_input.resolve(strict=True)
        if not path.is_file():
            raise LocalDocsError(f"index must be a regular file: {path}")
        metadata = _read_metadata(path)
        if metadata.get("schema_version") != str(INDEX_SCHEMA_VERSION):
            raise LocalDocsError(
                f"unsupported local docs index schema: {metadata.get('schema_version')!r}"
            )
        self.index_path = path
        self.sha256 = metadata["sha256"]

    @classmethod
    def from_manifest(cls, manifest_path: str | Path) -> LocalDocsReader:
        return cls(load_config(manifest_path).index_path)

    def list_doc_sources(self) -> dict[str, Any]:
        with self._connect() as connection:
            index_sha256 = self._index_sha256(connection)
            rows = connection.execute(
                """
                SELECT source_id, adapter, version, root_label,
                       document_count, source_bytes, sha256
                FROM sources
                ORDER BY source_id
                """
            ).fetchall()
        return {
            "index_sha256": index_sha256,
            "sources": [
                {
                    "id": row["source_id"],
                    "adapter": row["adapter"],
                    "version": row["version"],
                    "root": row["root_label"],
                    "documents": row["document_count"],
                    "source_bytes": row["source_bytes"],
                    "sha256": row["sha256"],
                }
                for row in rows
            ],
            "source_bytes": sum(row["source_bytes"] for row in rows),
        }

    def search_docs(
        self,
        query: str,
        *,
        source_ids: Iterable[str] | None = None,
        version: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        clean_query = query.strip()
        if not clean_query or len(clean_query) > 200:
            raise LocalDocsError("query must contain 1-200 characters")
        if isinstance(limit, bool) or not 1 <= limit <= MAX_SEARCH_RESULTS:
            raise LocalDocsError(
                f"limit must be between 1 and {MAX_SEARCH_RESULTS}"
            )
        terms = _query_terms(clean_query)
        if not terms:
            raise LocalDocsError("query must contain a searchable term")
        selected_sources = tuple(dict.fromkeys(source_ids or ()))
        if len(selected_sources) > 8:
            raise LocalDocsError("source_ids cannot contain more than 8 entries")
        for source_id in selected_sources:
            if SOURCE_ID_PATTERN.fullmatch(source_id) is None:
                raise LocalDocsError(f"invalid source id: {source_id!r}")
        if version is not None and (not version.strip() or len(version) > 80):
            raise LocalDocsError("version must contain 1-80 characters")

        match_expression = " OR ".join(f'"{term}"' for term in terms)
        clauses = ["documents_fts MATCH ?"]
        parameters: list[Any] = [match_expression]
        if selected_sources:
            placeholders = ",".join("?" for _ in selected_sources)
            clauses.append(f"d.source_id IN ({placeholders})")
            parameters.extend(selected_sources)
        if version is not None:
            clauses.append("d.version = ?")
            parameters.append(version.strip())
        candidate_limit = min(72, (limit + 1) * 8)
        parameters.append(candidate_limit)
        sql = f"""
            SELECT d.source_id, d.locator, d.title, d.section, d.version,
                   d.text, d.sha256, d.source_bytes,
                   bm25(documents_fts, 2.0, 1.5, 1.0) AS rank
            FROM documents_fts
            JOIN documents d ON d.id = documents_fts.rowid
            WHERE {' AND '.join(clauses)}
            ORDER BY rank, d.source_id, d.locator
            LIMIT ?
        """
        with self._connect() as connection:
            index_sha256 = self._index_sha256(connection)
            if selected_sources:
                known = {
                    row[0]
                    for row in connection.execute(
                        "SELECT source_id FROM sources"
                    ).fetchall()
                }
                unknown = sorted(set(selected_sources) - known)
                if unknown:
                    raise LocalDocsError(
                        "unknown source ids: " + ", ".join(unknown)
                    )
            rows = connection.execute(sql, parameters).fetchall()
        minimum_match_terms = (
            len(terms)
            if len(terms) <= 2
            else max(2, (len(terms) + 1) // 2)
        )
        qualifying_rows = [
            row
            for row in rows
            if _term_coverage(row, terms) >= minimum_match_terms
        ]
        ranked_rows = sorted(
            qualifying_rows,
            key=lambda row: (
                -_term_coverage(row, terms),
                float(row["rank"]),
                row["source_id"],
                row["locator"],
            ),
        )
        truncated = len(ranked_rows) > limit
        rows = ranked_rows[:limit]
        matches = [
            {
                "source_id": row["source_id"],
                "version": row["version"],
                "title": row["title"],
                "section": row["section"],
                "locator": row["locator"],
                "excerpt": _excerpt(row["text"], terms),
                "sha256": row["sha256"],
                "source_bytes": row["source_bytes"],
                "matched_terms": _term_coverage(row, terms),
                "relevance": round(-float(row["rank"]), 6),
            }
            for row in rows
        ]
        return {
            "query": clean_query,
            "index_sha256": index_sha256,
            "matches": matches,
            "truncated": truncated,
            "minimum_match_terms": minimum_match_terms,
            "source_bytes": sum(match["source_bytes"] for match in matches),
        }

    def read_doc(
        self,
        source_id: str,
        locator: str,
        *,
        max_chars: int = DEFAULT_CHUNK_CHARS,
    ) -> dict[str, Any]:
        if SOURCE_ID_PATTERN.fullmatch(source_id) is None:
            raise LocalDocsError(f"invalid source id: {source_id!r}")
        if not locator.strip() or len(locator) > 400:
            raise LocalDocsError("locator must contain 1-400 characters")
        if isinstance(max_chars, bool) or not 200 <= max_chars <= MAX_READ_CHARS:
            raise LocalDocsError(
                f"max_chars must be between 200 and {MAX_READ_CHARS}"
            )
        with self._connect() as connection:
            index_sha256 = self._index_sha256(connection)
            row = connection.execute(
                """
                SELECT source_id, locator, title, section, version,
                       text, sha256, source_bytes
                FROM documents
                WHERE source_id = ? AND locator = ?
                """,
                (source_id, locator),
            ).fetchone()
        if row is None:
            raise LocalDocsError(
                f"unknown document locator: {source_id}:{locator}"
            )
        content = row["text"]
        return {
            "source_id": row["source_id"],
            "version": row["version"],
            "title": row["title"],
            "section": row["section"],
            "locator": row["locator"],
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
            "total_chars": len(content),
            "sha256": row["sha256"],
            "source_bytes": row["source_bytes"],
            "index_sha256": index_sha256,
        }

    def _connect(self) -> sqlite3.Connection:
        if self.index_path.is_symlink() or not self.index_path.is_file():
            raise LocalDocsError(
                f"index must remain a regular non-symlink file: {self.index_path}"
            )
        connection = sqlite3.connect(
            f"file:{self.index_path.as_posix()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _index_sha256(self, connection: sqlite3.Connection) -> str:
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        if metadata.get("schema_version") != str(INDEX_SCHEMA_VERSION):
            raise LocalDocsError(
                f"unsupported local docs index schema: {metadata.get('schema_version')!r}"
            )
        digest = metadata.get("sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise LocalDocsError("local docs index has an invalid sha256")
        return digest


def _text_documents(
    config: LocalDocsConfig,
    spec: SourceSpec,
) -> tuple[str, str, list[Document]]:
    root_relative = _required_string(spec.options, "root", label=f"{spec.source_id}.root")
    safe_relative_path(root_relative, label=f"{spec.source_id}.root", allow_dot=True)
    root_input = (
        config.workspace_root
        if root_relative == "."
        else config.workspace_root / Path(*PurePosixPath(root_relative).parts)
    )
    if root_relative != "." and _path_uses_symlink(
        config.workspace_root,
        root_relative,
    ):
        raise LocalDocsError(f"text source root cannot be a symlink: {root_input}")
    root = (
        config.workspace_root
        if root_relative == "."
        else contained_path(
            config.workspace_root,
            root_relative,
            label=f"{spec.source_id}.root",
        )
    )
    root = root.resolve(strict=True)
    if root.is_symlink() or not root.is_dir():
        raise LocalDocsError(f"text source root must be a directory: {root}")
    version = _required_string(
        spec.options,
        "version",
        label=f"{spec.source_id}.version",
    )
    includes = _string_list(
        spec.options.get("include"),
        label=f"{spec.source_id}.include",
        required=True,
    )
    excludes = _string_list(
        spec.options.get("exclude", []),
        label=f"{spec.source_id}.exclude",
        required=False,
    )
    for pattern in (*includes, *excludes):
        _validate_glob(pattern, source_id=spec.source_id)

    matched: dict[str, Path] = {}
    for pattern in includes:
        for candidate in root.glob(pattern):
            if not candidate.is_file():
                continue
            try:
                relative = candidate.relative_to(root).as_posix()
            except ValueError as exc:
                raise LocalDocsError(
                    f"source path escapes root: {candidate}"
                ) from exc
            if _hard_excluded(relative) or any(
                PurePosixPath(relative).match(pattern) for pattern in excludes
            ):
                continue
            if _path_uses_symlink(root, relative):
                raise LocalDocsError(f"symlinked documentation is not allowed: {candidate}")
            canonical = candidate.resolve(strict=True)
            try:
                canonical.relative_to(root)
            except ValueError as exc:
                raise LocalDocsError(
                    f"documentation escapes source root: {candidate}"
                ) from exc
            if canonical.suffix.lower() not in SUPPORTED_TEXT_SUFFIXES:
                continue
            matched[relative] = canonical

    documents: list[Document] = []
    for relative, path in sorted(matched.items()):
        size = path.stat().st_size
        if size > config.max_file_bytes:
            raise LocalDocsError(
                f"documentation exceeds max_file_bytes: {path} ({size})"
            )
        text = path.read_text(encoding="utf-8")
        sections = (
            _markdown_sections(text, fallback_title=path.stem)
            if path.suffix.lower() == ".md"
            else [(path.stem, path.stem, 1, text)]
        )
        for title, section, start_line, body in sections:
            for chunk_number, chunk in enumerate(
                _chunks(body, config.chunk_chars),
                start=1,
            ):
                suffix = "" if chunk_number == 1 else f":C{chunk_number}"
                documents.append(
                    Document.create(
                        source_id=spec.source_id,
                        locator=f"{relative}#L{start_line}{suffix}",
                        title=title,
                        section=section,
                        version=version,
                        text=chunk,
                        source_bytes=len(chunk.encode("utf-8")),
                    )
                )
    return version, root_relative, documents


def _python_package_documents(
    config: LocalDocsConfig,
    spec: SourceSpec,
) -> tuple[str, str, list[Document]]:
    distribution_name = _required_string(
        spec.options,
        "distribution",
        label=f"{spec.source_id}.distribution",
    )
    try:
        distribution = importlib.metadata.distribution(distribution_name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise LocalDocsError(
            f"Python distribution is not installed: {distribution_name}"
        ) from exc
    files = distribution.files
    if files is None:
        raise LocalDocsError(
            f"Python distribution has no file manifest: {distribution_name}"
        )
    package_root = Path(distribution.locate_file("")).resolve(strict=True)
    version = distribution.version
    documents: list[Document] = []
    for package_path in sorted(files, key=lambda item: str(item)):
        relative = PurePosixPath(str(package_path))
        if (
            relative.suffix != ".py"
            or _hard_excluded(relative.as_posix())
            or any(part.endswith(".dist-info") for part in relative.parts)
        ):
            continue
        candidate = Path(distribution.locate_file(package_path))
        if candidate.is_symlink() or not candidate.is_file():
            continue
        candidate = candidate.resolve(strict=True)
        try:
            candidate.relative_to(package_root)
        except ValueError:
            continue
        size = candidate.stat().st_size
        if size > config.max_file_bytes:
            continue
        with tokenize.open(candidate) as source_file:
            source = source_file.read()
        try:
            tree = ast.parse(source, filename=str(candidate))
        except SyntaxError as exc:
            raise LocalDocsError(
                f"cannot parse installed Python source: {candidate}"
            ) from exc
        entries = _python_docstrings(tree)
        for qualified_name, line, docstring in entries:
            for chunk_number, chunk in enumerate(
                _chunks(docstring, config.chunk_chars),
                start=1,
            ):
                suffix = "" if chunk_number == 1 else f":C{chunk_number}"
                locator = (
                    f"{distribution_name}/{relative.as_posix()}"
                    f"#{qualified_name}:L{line}{suffix}"
                )
                documents.append(
                    Document.create(
                        source_id=spec.source_id,
                        locator=locator,
                        title=f"{distribution.metadata['Name']} {qualified_name}",
                        section=qualified_name,
                        version=version,
                        text=chunk,
                        source_bytes=len(chunk.encode("utf-8")),
                    )
                )
    return version, f"python:{distribution.metadata['Name']}", documents


def _python_docstrings(tree: ast.Module) -> list[tuple[str, int, str]]:
    entries: list[tuple[str, int, str]] = []
    module_doc = ast.get_docstring(tree, clean=False)
    if module_doc:
        entries.append(("<module>", 1, module_doc))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            docstring = ast.get_docstring(node, clean=False)
            if docstring:
                entries.append((node.name, node.lineno, docstring))
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            class_doc = ast.get_docstring(node, clean=False)
            if class_doc:
                entries.append((node.name, node.lineno, class_doc))
            for child in node.body:
                if not isinstance(
                    child,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ) or child.name.startswith("_"):
                    continue
                method_doc = ast.get_docstring(child, clean=False)
                if method_doc:
                    entries.append(
                        (f"{node.name}.{child.name}", child.lineno, method_doc)
                    )
    return entries


ADAPTERS: dict[str, Adapter] = {
    "text": _text_documents,
    "python-package": _python_package_documents,
}


def _validate_source_options(
    source_id: str,
    adapter: str,
    options: dict[str, Any],
) -> None:
    allowed = (
        {"root", "version", "include", "exclude"}
        if adapter == "text"
        else {"distribution"}
    )
    unknown = sorted(set(options) - allowed)
    if unknown:
        raise LocalDocsError(
            f"unknown fields for {source_id}: " + ", ".join(unknown)
        )


def _markdown_sections(
    text: str,
    *,
    fallback_title: str,
) -> list[tuple[str, str, int, str]]:
    lines = text.splitlines()
    title = fallback_title
    section = fallback_title
    start_line = 1
    buffer: list[str] = []
    sections: list[tuple[str, str, int, str]] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append((title, section, start_line, body))

    for line_number, line in enumerate(lines, start=1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if not match:
            buffer.append(line)
            continue
        flush()
        heading = match.group(2).strip()
        if len(match.group(1)) == 1:
            title = heading
        section = heading
        start_line = line_number
        buffer = []
    flush()
    return sections


def _chunks(text: str, limit: int) -> list[str]:
    clean = text.strip()
    if not clean:
        return []
    paragraphs = re.split(r"\n\s*\n", clean)
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_chunks(paragraph, limit))
            continue
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= limit:
            current = candidate
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


def _hard_chunks(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind(" ", 0, limit + 1)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _query_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", query):
        normalized = term.lower()
        if normalized in QUERY_STOPWORDS:
            continue
        if normalized not in terms:
            terms.append(normalized)
        if len(terms) == 12:
            break
    return tuple(terms)


def _excerpt(text: str, terms: tuple[str, ...], *, limit: int = 480) -> str:
    flattened = re.sub(r"\s+", " ", text).strip()
    lower = flattened.lower()
    positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
    start = max(0, min(positions) - 100) if positions else 0
    end = min(len(flattened), start + limit)
    excerpt = flattened[start:end]
    if start:
        excerpt = "..." + excerpt
    if end < len(flattened):
        excerpt += "..."
    return excerpt


def _term_coverage(row: sqlite3.Row, terms: tuple[str, ...]) -> int:
    haystack = " ".join(
        (row["title"], row["section"], row["text"])
    ).lower()
    return sum(term in haystack for term in terms)


def _path_uses_symlink(root: Path, relative: str) -> bool:
    candidate = root
    for part in PurePosixPath(relative).parts:
        candidate /= part
        if candidate.is_symlink():
            return True
    return False


def _hard_excluded(relative: str) -> bool:
    return any(part in HARD_EXCLUDED_PARTS for part in PurePosixPath(relative).parts)


def _validate_glob(pattern: str, *, source_id: str) -> None:
    if (
        not pattern
        or pattern.startswith("/")
        or "\\" in pattern
        or any(part == ".." for part in PurePosixPath(pattern).parts)
    ):
        raise LocalDocsError(f"unsafe glob for {source_id}: {pattern!r}")


def _required_string(
    values: dict[str, Any],
    name: str,
    *,
    label: str,
) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value.strip():
        raise LocalDocsError(f"{label} must be a non-empty string")
    return value.strip()


def _string_list(
    value: Any,
    *,
    label: str,
    required: bool,
) -> tuple[str, ...]:
    if not isinstance(value, list) or (required and not value):
        suffix = "non-empty " if required else ""
        raise LocalDocsError(f"{label} must be a {suffix}array of strings")
    if any(not isinstance(item, str) or not item for item in value):
        raise LocalDocsError(f"{label} must contain only non-empty strings")
    return tuple(value)


def _bounded_integer(
    value: Any,
    *,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LocalDocsError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise LocalDocsError(
            f"{label} must be between {minimum} and {maximum}"
        )
    return value


def _records_digest(records: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(
            records,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _read_metadata(index_path: Path) -> dict[str, str]:
    path = Path(index_path).expanduser().resolve(strict=True)
    if path.is_symlink() or not path.is_file():
        raise LocalDocsError(f"index must be a regular file: {path}")
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            return dict(connection.execute("SELECT key, value FROM metadata"))
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise LocalDocsError(f"invalid local docs index: {path}: {exc}") from exc


def build_index_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview, build, or verify the deterministic local documentation index."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Local documentation source manifest",
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--update",
        action="store_true",
        help="Atomically replace the configured index",
    )
    actions.add_argument(
        "--verify",
        action="store_true",
        help="Recompute sources and verify the existing index digest",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON")
    return parser


def index_main(argv: list[str] | None = None) -> int:
    args = build_index_parser().parse_args(argv)
    try:
        config = load_config(args.manifest)
        plan = collect_index(config)
        if args.verify:
            result = verify_index(plan)
            exit_code = 0 if result["verified"] else 1
        elif args.update:
            write_index(plan)
            result = plan.summary(action="updated")
            exit_code = 0
        else:
            result = plan.summary(action="preview")
            exit_code = 0
    except (
        LocalDocsError,
        OSError,
        PathValidationError,
        sqlite3.Error,
        tomllib.TOMLDecodeError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"{result['action']}: {result['source_count']} sources, "
            f"{result['document_count']} documents, sha256={result['sha256']}"
        )
        print(f"Index: {result['index_path']}")
        if args.verify:
            print(f"Verified: {'yes' if result['verified'] else 'no'}")
    return exit_code
