import json
import subprocess
from pathlib import Path

from codexteam_tools.separation_audit import audit_separation


def _control(root: Path, name: str, work: Path) -> Path:
    control = root / name
    control.mkdir(parents=True)
    (control / "REPOSITORIES.json").write_text(json.dumps({
        "schema_version": "1.0",
        "repositories": [{
            "id": name,
            "work_root": str(work),
            "git_root": str(work),
            "git_prefix": ".",
            "remote_url": None,
            "write_policy": "task-owned",
        }],
    }))
    return control


def test_separation_audit_accepts_clean_control_and_source(tmp_path: Path):
    projects = tmp_path / "projects"
    work = tmp_path / "repos/product"
    work.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    _control(projects, "product", work)
    assert audit_separation(projects)["status"] == "passed"


def test_separation_audit_rejects_product_scaffold_and_source_control(tmp_path: Path):
    projects = tmp_path / "projects"
    work = tmp_path / "repos/product"
    work.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    control = _control(projects, "product", work)
    (control / "src").mkdir()
    (work / "TASKS.md").write_text("# Tasks\n")
    result = audit_separation(projects)
    assert result["status"] == "failed"
    assert any("control contains product scaffold" in error for error in result["errors"])
    assert any("source contains control artifact" in error for error in result["errors"])


def test_separation_audit_rejects_source_results_and_registry(tmp_path: Path):
    projects = tmp_path / "projects"
    work = tmp_path / "repos/product"
    work.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    _control(projects, "product", work)
    (work / "results").mkdir()
    (work / "results/evidence.txt").write_text("evidence\n")
    (work / "REPOSITORIES.json").write_text("{}\n")

    result = audit_separation(projects)

    assert result["status"] == "failed"
    assert any("source contains control artifact: results" in error for error in result["errors"])
    assert any("source contains control artifact: REPOSITORIES.json" in error for error in result["errors"])


def test_separation_audit_rejects_tracked_but_deleted_control_artifact(tmp_path: Path):
    projects = tmp_path / "projects"
    work = tmp_path / "repos/product"
    work.mkdir(parents=True)
    _control(projects, "product", work)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    artifact = work / "TASKS.md"
    artifact.write_text("# Tasks\n")
    subprocess.run(["git", "add", "TASKS.md"], cwd=work, check=True)
    artifact.unlink()

    result = audit_separation(projects)

    assert result["status"] == "failed"
    assert any(
        "source Git index contains control artifact: TASKS.md" in error
        for error in result["errors"]
    )


def test_separation_audit_rejects_non_git_source(tmp_path: Path):
    projects = tmp_path / "projects"
    work = tmp_path / "repos/product"
    work.mkdir(parents=True)
    _control(projects, "product", work)

    result = audit_separation(projects)

    assert result["status"] == "failed"
    assert result["projects"][0]["repositories"][0]["git_index_checked"] is False
    assert any("invalid repository binding" in error for error in result["errors"])
