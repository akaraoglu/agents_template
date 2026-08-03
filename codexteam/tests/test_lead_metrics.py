"""Focused tests for codexteam_tools.lead_metrics.record_lead_usage().

Covers validation, write/update, dry-run, preserved records, malformed data,
and CLI success/failure — per T009 S0 scope.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from codexteam_tools.lead_metrics import record_lead_usage


# ------------------------------------------------------------------ helpers --

def _valid_kwargs(**overrides) -> dict:
    """Return default valid kwargs, optionally overriding fields."""
    base = {
        "task_id": "T001",
        "profile": "gpt-4.1-mini",
        "provider": "openai_cloud",
        "duration_seconds": 234,
        "input_tokens": 50_000,
        "cached_input_tokens": 40_000,
        "output_tokens": 8_000,
    }
    base.update(overrides)
    return base


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """Create a minimal project with the expected runtime directory."""
    runtime = tmp_path / ".codexteam" / "runtime"
    runtime.mkdir(parents=True)
    return tmp_path


# ---- validation --------------------------------------------------

class TestValidation:
    """All five validation rules are enforced before any I/O."""

    def test_valid_returns_none(self, project):
        result = record_lead_usage(project, **_valid_kwargs(), dry_run=True)
        assert result is None

    def test_invalid_task_id_rejected(self, project):
        err = record_lead_usage(
            project, **_valid_kwargs(task_id="INVALID"), dry_run=True
        )
        assert "invalid task ID" in (err or "")

    def test_profile_empty_string_rejected(self, project):
        err = record_lead_usage(
            project, **_valid_kwargs(profile="   "), dry_run=True
        )
        assert "profile must be a non-empty string" in (err or "")

    def test_provider_empty_string_rejected(self, project):
        err = record_lead_usage(
            project, **_valid_kwargs(provider=""), dry_run=True
        )
        assert "provider must be a non-empty string" in (err or "")

    def test_negative_duration_rejected(self, project):
        err = record_lead_usage(
            project, **_valid_kwargs(duration_seconds=-1), dry_run=True
        )
        assert "duration_seconds must be a non-negative number" in (err or "")

    def test_negative_input_tokens_rejected(self, project):
        err = record_lead_usage(
            project, **_valid_kwargs(input_tokens=-1), dry_run=True
        )
        assert "input_tokens must be a non-negative number" in (err or "")

    def test_cached_exceeds_input_rejected(self, project):
        err = record_lead_usage(
            project,
            **_valid_kwargs(cached_input_tokens=999, input_tokens=100),
            dry_run=True,
        )
        assert "cached_input_tokens must not exceed input_tokens" in (err or "")

    def test_zero_values_accepted(self, project):
        """Boundary: all-zero numeric fields are valid."""
        result = record_lead_usage(
            project,
            **_valid_kwargs(duration_seconds=0, input_tokens=0, cached_input_tokens=0, output_tokens=0),
            dry_run=True,
        )
        assert result is None

    def test_float_duration_accepted(self, project):
        """duration_seconds accepts floats."""
        result = record_lead_usage(
            project, **_valid_kwargs(duration_seconds=12.3456), dry_run=True
        )
        assert result is None

    def test_non_string_profile_rejected(self, project):
        err = record_lead_usage(
            project, **_valid_kwargs(profile=42), dry_run=True
        )
        assert "profile must be a non-empty string" in (err or "")

    def test_non_string_task_id_rejected(self, project):
        err = record_lead_usage(project, **_valid_kwargs(task_id=123), dry_run=True)
        assert "task_id must be a string" in (err or "")

    def test_bool_duration_rejected(self, project):
        err = record_lead_usage(
            project, **_valid_kwargs(duration_seconds=True), dry_run=True
        )
        assert "duration_seconds must be a non-negative number" in (err or "")

    def test_bool_input_tokens_rejected(self, project):
        err = record_lead_usage(
            project, **_valid_kwargs(input_tokens=False), dry_run=True
        )
        assert "input_tokens must be a non-negative number" in (err or "")

    @pytest.mark.parametrize(
        ("field", "value"),
        (
            ("duration_seconds", float("nan")),
            ("output_tokens", float("inf")),
            ("cached_input_tokens", float("-inf")),
        ),
    )
    def test_non_finite_number_rejected(self, project, field, value):
        err = record_lead_usage(
            project, **_valid_kwargs(**{field: value}), dry_run=True
        )
        assert f"{field} must be a non-negative number" in (err or "")


# ---- write behaviour ----------------------------------------------

class TestWrite:
    """Valid writes create/update the metrics file correctly."""

    def test_creates_file_when_absent(self, project):
        result = record_lead_usage(project, **_valid_kwargs())
        assert result is None
        data = json.loads(
            (project / ".codexteam" / "runtime" / "lead-metrics.json").read_text()
        )
        assert data["schema_version"] == "1.0"
        assert data["metric_scope"] == "lead_orchestration"
        assert "generated_at" in data
        record = data["tasks"]["T001"]
        assert record["metric_scope"] == "lead_orchestration"
        assert record["profile"] == "gpt-4.1-mini"
        assert record["provider"] == "openai_cloud"
        assert record["duration_seconds"] == 234
        assert record["input_tokens"] == 50_000
        assert record["cached_input_tokens"] == 40_000
        assert record["uncached_input_tokens"] == 10_000
        assert record["output_tokens"] == 8_000

    def test_updates_existing_task(self, project):
        """Second call to the same task replaces its record."""
        record_lead_usage(project, **_valid_kwargs())
        record_lead_usage(
            project,
            **_valid_kwargs(task_id="T001", profile="gpt54-mini", duration_seconds=99),
        )
        data = json.loads(
            (project / ".codexteam" / "runtime" / "lead-metrics.json").read_text()
        )
        assert data["tasks"]["T001"]["profile"] == "gpt54-mini"
        assert data["tasks"]["T001"]["duration_seconds"] == 99

    def test_preserves_other_task_records(self, project):
        """Writing T002 does not clobber T001."""
        record_lead_usage(project, **_valid_kwargs(task_id="T001"))
        record_lead_usage(
            project,
            **_valid_kwargs(task_id="T002", profile="gpt54-mini"),
        )
        data = json.loads(
            (project / ".codexteam" / "runtime" / "lead-metrics.json").read_text()
        )
        assert data["tasks"]["T001"]["profile"] == "gpt-4.1-mini"
        assert data["tasks"]["T002"]["profile"] == "gpt54-mini"

    def test_task_id_normalized(self, project):
        """Lowercase task IDs are upper-cased before storage."""
        record_lead_usage(project, **_valid_kwargs(task_id="t001"))
        data = json.loads(
            (project / ".codexteam" / "runtime" / "lead-metrics.json").read_text()
        )
        assert "T001" in data["tasks"]

    def test_schema_version_updated_on_each_write(self, project):
        record_lead_usage(project, **_valid_kwargs())
        before = (
            project / ".codexteam" / "runtime" / "lead-metrics.json"
        ).read_text()
        # Write a second time — generated_at will differ, schema_version stays "1.0"
        record_lead_usage(
            project,
            **_valid_kwargs(task_id="T002"),
        )
        after = (
            project / ".codexteam" / "runtime" / "lead-metrics.json"
        ).read_text()
        assert before != after
        data = json.loads(after)
        assert data["schema_version"] == "1.0"

    def test_missing_project_dir_rejected(self, tmp_path):
        nonexistent = tmp_path / "does-not-exist"
        err = record_lead_usage(nonexistent, **_valid_kwargs())
        assert "does not exist or is not a directory" in (err or "")

    def test_dry_run_does_not_require_project_path(self, tmp_path):
        nonexistent = tmp_path / "does-not-exist"
        assert record_lead_usage(
            nonexistent, **_valid_kwargs(), dry_run=True
        ) is None


# ---- dry-run ------------------------------------------------------

class TestDryRun:
    """dry_run=True validates but never touches the filesystem."""

    def test_no_file_created(self, project):
        metrics = project / ".codexteam" / "runtime" / "lead-metrics.json"
        assert not metrics.exists()
        result = record_lead_usage(project, **_valid_kwargs(), dry_run=True)
        assert result is None
        assert not metrics.exists()

    def test_existing_file_unchanged(self, project):
        metrics = project / ".codexteam" / "runtime" / "lead-metrics.json"
        metrics.write_text('{"schema_version": "1.0", "tasks": {}}')
        before = metrics.read_text()
        record_lead_usage(project, **_valid_kwargs(), dry_run=True)
        assert metrics.read_text() == before


# ---- malformed existing data --------------------------------------

class TestMalformedExistingData:
    """Malformed existing data is refused without data loss."""

    def test_invalid_json_refused_and_file_unchanged(self, project):
        metrics = project / ".codexteam" / "runtime" / "lead-metrics.json"
        original = "not-json\n"
        metrics.write_text(original)
        error = record_lead_usage(project, **_valid_kwargs())
        assert "invalid JSON" in (error or "")
        assert metrics.read_text() == original

    def test_non_dict_root_refused_and_file_unchanged(self, project):
        metrics = project / ".codexteam" / "runtime" / "lead-metrics.json"
        original = "[1, 2, 3]\n"
        metrics.write_text(original)
        error = record_lead_usage(project, **_valid_kwargs())
        assert "not an object" in (error or "")
        assert metrics.read_text() == original

    def test_wrong_schema_version_refused_and_file_unchanged(self, project):
        metrics = project / ".codexteam" / "runtime" / "lead-metrics.json"
        original = json.dumps({"schema_version": "2.0", "tasks": {}})
        metrics.write_text(original)
        error = record_lead_usage(project, **_valid_kwargs())
        assert "schema_version" in (error or "")
        assert metrics.read_text() == original

    def test_tasks_not_dict_refused_and_file_unchanged(self, project):
        metrics = project / ".codexteam" / "runtime" / "lead-metrics.json"
        original = json.dumps({"schema_version": "1.0", "tasks": ["T001"]})
        metrics.write_text(original)
        error = record_lead_usage(project, **_valid_kwargs())
        assert "'tasks' key is not an object" in (error or "")
        assert metrics.read_text() == original

    def test_missing_file_starts_fresh(self, project):
        metrics = project / ".codexteam" / "runtime" / "lead-metrics.json"
        assert not metrics.exists()
        result = record_lead_usage(project, **_valid_kwargs())
        assert result is None
        data = json.loads(metrics.read_text())
        assert data["tasks"]["T001"]["profile"] == "gpt-4.1-mini"


# ---- CLI -----------------------------------------------------------

class TestCLI:
    """record-lead-metrics.py script success and failure paths."""

    SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record-lead-metrics.py"

    def test_cli_success(self, project):
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             "--project", str(project),
             "--task", "T003",
             "--profile", "gpt-4.1-mini",
             "--provider", "openai_cloud",
             "--duration-seconds", "50",
             "--input-tokens", "10000",
             "--cached-input-tokens", "8000",
             "--output-tokens", "2000"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_cli_dry_run(self, project):
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             "--project", str(project),
             "--task", "T004",
             "--profile", "gpt-4.1-mini",
             "--provider", "openai_cloud",
             "--duration-seconds", "50",
             "--input-tokens", "10000",
             "--cached-input-tokens", "8000",
             "--output-tokens", "2000",
             "--dry-run"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert not (project / ".codexteam" / "runtime" / "lead-metrics.json").exists()

    def test_cli_invariant_violation_fails(self, project):
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             "--project", str(project),
             "--task", "T005",
             "--profile", "gpt-4.1-mini",
             "--provider", "openai_cloud",
             "--duration-seconds", "50",
             "--input-tokens", "100",
             "--cached-input-tokens", "999",
             "--output-tokens", "2000"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "ERROR" in result.stderr

    def test_cli_invalid_task_id_fails(self, project):
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             "--project", str(project),
             "--task", "BAD",
             "--profile", "gpt-4.1-mini",
             "--provider", "openai_cloud",
             "--duration-seconds", "50",
             "--input-tokens", "100",
             "--cached-input-tokens", "99",
             "--output-tokens", "2000"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_cli_nan_duration_fails(self, project):
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             "--project", str(project),
             "--task", "T006",
             "--profile", "gpt-4.1-mini",
             "--provider", "openai_cloud",
             "--duration-seconds", "nan",
             "--input-tokens", "100",
             "--cached-input-tokens", "99",
             "--output-tokens", "200"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "ERROR" in result.stderr

    def test_cli_nonexistent_project_fails(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             "--project", str(tmp_path / "missing"),
             "--task", "T007",
             "--profile", "gpt-4.1-mini",
             "--provider", "openai_cloud",
             "--duration-seconds", "50",
             "--input-tokens", "100",
             "--cached-input-tokens", "99",
             "--output-tokens", "200"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "ERROR" in result.stderr

    def test_cli_dry_run_nonexistent_project_succeeds(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             "--project", str(tmp_path / "missing"),
             "--task", "T008",
             "--profile", "gpt-4.1-mini",
             "--provider", "openai_cloud",
             "--duration-seconds", "50",
             "--input-tokens", "100",
             "--cached-input-tokens", "99",
             "--output-tokens", "200",
             "--dry-run"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "OK" in result.stdout
