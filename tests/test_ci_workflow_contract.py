from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"

MANUAL_DISPATCH_GATE = "if: github.event_name == 'workflow_dispatch'"
FAST_GATE_JOBS = ("python-lint", "linux-sandbox", "web")
MANUAL_ONLY_JOBS = ("python-tests", "electron-tests")


def workflow_text() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


def job_blocks() -> dict:
    lines = workflow_text().splitlines()
    blocks = {}
    current = None
    for line in lines[lines.index("jobs:") + 1 :]:
        if (
            line.startswith("  ")
            and not line.startswith("   ")
            and line.rstrip().endswith(":")
        ):
            current = line.strip()[:-1]
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    return {name: "\n".join(body) for name, body in blocks.items()}


def test_ci_uses_layered_triggers() -> None:
    text = workflow_text()
    trigger_block = text.split("concurrency:", 1)[0]
    assert "workflow_dispatch:" in trigger_block
    assert "push:" in trigger_block
    assert "pull_request:" in trigger_block
    assert trigger_block.count("branches: [main]") == 2


def test_expensive_jobs_only_run_on_manual_dispatch() -> None:
    blocks = job_blocks()
    for job_id in MANUAL_ONLY_JOBS:
        assert MANUAL_DISPATCH_GATE in blocks[job_id]


def test_fast_gate_jobs_run_on_every_trigger() -> None:
    blocks = job_blocks()
    for job_id in FAST_GATE_JOBS:
        assert MANUAL_DISPATCH_GATE not in blocks[job_id]


def test_fast_gate_runs_reachable_fatal_ruff() -> None:
    text = workflow_text()
    assert "tj-actions/changed-files" not in text
    assert "github.event_name == 'pull_request'" not in text
    assert (
        "python -m ruff check --select E9,F63,F7,F82 agent.py config core scripts tools"
        in text
    )


def test_manual_python_tests_collect_all_pytest_failures() -> None:
    assert ".\\.venv\\Scripts\\python.exe -m coverage run -m pytest tests -q --maxfail=0" in workflow_text()
