from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"

MANUAL_DISPATCH_GATE = "if: github.event_name == 'workflow_dispatch'"
FAST_GATE_JOBS = ("python-lint", "linux-sandbox")
MANUAL_ONLY_JOBS = ("python-tests", "electron-tests")
WEB_DISPATCH_STEPS = ("Run Vitest", "Verify bundle budgets")
WEB_PUSH_STEPS = ("Install dependencies", "Verify package lock is in sync", "Build frontend")


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


def step_blocks(job_body: str) -> dict:
    """Split a job body into {step name: step text} blocks."""
    steps = {}
    current = None
    for line in job_body.splitlines():
        stripped = line.strip()
        if stripped.startswith("- name:"):
            current = stripped[len("- name:") :].strip()
            steps[current] = [line]
        elif current is not None:
            steps[current].append(line)
    return {name: "\n".join(body) for name, body in steps.items()}


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


def test_web_job_splits_push_integrity_from_full_suites() -> None:
    """The web job has no job-level gate: install, lockfile sync, and the
    production build run on every push; the Vitest suite and the bundle
    ratchet are manual-dispatch only until the in-flight baselines are green.
    """
    blocks = job_blocks()
    web_body = blocks["web"]
    header = web_body.split("steps:", 1)[0]
    assert MANUAL_DISPATCH_GATE not in header
    steps = step_blocks(web_body)
    for step_name in WEB_DISPATCH_STEPS:
        assert MANUAL_DISPATCH_GATE in steps[step_name], step_name
    for step_name in WEB_PUSH_STEPS:
        assert MANUAL_DISPATCH_GATE not in steps[step_name], step_name


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
