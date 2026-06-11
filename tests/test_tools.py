import pytest
import datetime
from pathlib import Path
from AgenticTeam.scripts.contracts import WorkResult, OracleResult
from AgenticTeam.scripts.tools import TeamTools, TeamToolError, augment_test_feedback
from AgenticTeam.scripts.leases import acquire_lease, release_lease
from AgenticTeam.scripts.events import clear_events

@pytest.fixture(autouse=True)
def clean_logs():
    clear_events()
    yield
    clear_events()

@pytest.fixture
def workspace_with_lease(tmp_path):
    # Setup files in workspace
    project_root = tmp_path
    (project_root / "src").mkdir()
    (project_root / "src" / "main.py").write_text("print('hello')", encoding="utf-8")
    (project_root / "tests").mkdir()
    (project_root / "tests" / "test_main.py").write_text("def test_dummy(): assert True", encoding="utf-8")
    
    # Acquire a lease
    metadata = {"project_id": "p1", "attempt_id": "att-1"}
    lease = acquire_lease(
        workspace_root=str(project_root),
        resource_id="T001",
        owner="worker-1",
        duration_seconds=30,
        metadata=metadata
    )
    
    yield project_root, lease

def test_read_and_discovery(workspace_with_lease):
    project_root, lease = workspace_with_lease
    tools = TeamTools(str(project_root))
    
    # workspace_inspect
    inspect = tools.workspace_inspect()
    assert inspect["exists"] is True
    assert inspect["is_dir"] is True
    
    # repo_map
    files = tools.repo_map()
    assert "src/main.py" in files
    assert "tests/test_main.py" in files
    
    # repo_search
    matches = tools.repo_search("dummy")
    assert "tests/test_main.py" in matches
    
    # fs_list
    contents = tools.fs_list("src")
    assert "src/main.py" in contents
    
    # fs_read
    content = tools.fs_read("src/main.py")
    assert content == "print('hello')"
    
    # outside workspace read should fail
    with pytest.raises(TeamToolError, match="path_outside_workspace"):
        tools.fs_read("../invalid.py")

def test_safe_mutation_under_lease(workspace_with_lease):
    project_root, lease = workspace_with_lease
    tools = TeamTools(str(project_root))
    
    # fs_mkdir
    res1 = tools.fs_mkdir("src/utils", lease.lease_id, "T001", "worker-1", "att-1")
    assert "Success" in res1
    assert (project_root / "src" / "utils").is_dir()
    
    # fs_write
    res2 = tools.fs_write("src/utils/helper.py", "def help(): pass", lease.lease_id, "T001", "worker-1", "att-1")
    assert "Success" in res2
    assert (project_root / "src" / "utils" / "helper.py").read_text() == "def help(): pass"
    
    # fs_patch
    patch = "SEARCH:def help(): pass\nREPLACE:def help(): return True"
    res3 = tools.fs_patch("src/utils/helper.py", patch, lease.lease_id, "T001", "worker-1", "att-1")
    assert "Success" in res3
    assert "return True" in (project_root / "src" / "utils" / "helper.py").read_text()

def test_mutation_failures(workspace_with_lease):
    project_root, lease = workspace_with_lease
    tools = TeamTools(str(project_root))
    
    # 1. Invalid lease / stale lease
    with pytest.raises(TeamToolError, match="stale_lease"):
        tools.fs_write("src/new.py", "content", "invalid-lease-id", "T001", "worker-1", "att-1")
        
    # 2. Outside workspace write
    with pytest.raises(TeamToolError, match="path_outside_workspace"):
        tools.fs_write("../outside.py", "content", lease.lease_id, "T001", "worker-1", "att-1")
        
    # 3. Content too large
    huge_content = "x" * (1024 * 1024 + 10)
    with pytest.raises(TeamToolError, match="content_too_large"):
        tools.fs_write("src/large.py", huge_content, lease.lease_id, "T001", "worker-1", "att-1")

def test_testing_and_execution(workspace_with_lease):
    project_root, lease = workspace_with_lease
    tools = TeamTools(str(project_root))
    
    # tests_discover
    tests = tools.tests_discover()
    assert "tests/test_main.py" in tests
    
    # cmd_preflight check
    assert tools.cmd_preflight("PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest tests") is True
    assert tools.cmd_preflight("rm -rf /") is False
    
    # cmd_run allowed cmd
    # Note: running actual pytest in tests might be slow/complex, but we can verify it doesn't crash
    # and returns test output
    res = tools.tests_run("tests/test_main.py", lease.lease_id, "T001", "worker-1", "att-1")
    assert "passed" in res or "dummy" in res or "test_main.py" in res


def test_import_time_cli_parse_failure_gets_actionable_feedback():
    raw_output = """
INTERNALERROR>   File "/workspace/src/main.py", line 20, in <module>
INTERNALERROR>     args = parser.parse_args()
INTERNALERROR>   File "/usr/lib/python3.12/argparse.py", line 1908, in parse_args
INTERNALERROR>     args, argv = self.parse_known_args(args, namespace)
INTERNALERROR> SystemExit: 2
"""

    feedback = augment_test_feedback(raw_output)

    assert "ACTIONABLE_TEST_FAILURE[import_time_cli_parse]" in feedback
    assert "Fix the source module, not the tests" in feedback
    assert "main(argv=None)" in feedback
    assert raw_output.strip() in feedback

def test_work_and_oracle_submission(workspace_with_lease):
    project_root, lease = workspace_with_lease
    tools = TeamTools(str(project_root))
    
    # 1. work_submit success
    wr = WorkResult(
        task_id="T001",
        attempt_id="att-1",
        status="DONE",
        summary="Done task",
        output={"key": "val"},
        evidence={"test_passed": True}
    )
    res = tools.work_submit(wr, lease.lease_id, "worker-1")
    assert res == "Success"
    
    # 2. work_submit invalid (missing output/evidence)
    wr_invalid = WorkResult(
        task_id="T001",
        attempt_id="att-1",
        status="DONE",
        summary="Empty",
        output={},
        evidence={}
    )
    with pytest.raises(TeamToolError, match="invalid_payload"):
        tools.work_submit(wr_invalid, lease.lease_id, "worker-1")
        
    # 3. work_block success
    res_block = tools.work_block("T001", "att-1", "API down", lease.lease_id, "worker-1")
    assert res_block == "Success"
    
    # Release worker lease so Oracle can lock it
    release_lease(str(project_root), lease.lease_id)
    
    # Acquire Oracle lease
    oracle_lease = acquire_lease(
        workspace_root=str(project_root),
        resource_id="T001",
        owner="oracle-1",
        duration_seconds=30,
        metadata={"project_id": "p1", "attempt_id": "oracle-attempt"}
    )
    assert oracle_lease is not None
    
    # 4. oracle_report success
    or_res = OracleResult(
        project_id="p1",
        task_id="T001",
        status="PASS",
        evidence_paths=["src/main.py"],
        summary="Looks good"
    )
    res_or = tools.oracle_report(or_res, oracle_lease.lease_id, "oracle-1")
    assert res_or == "Success"
