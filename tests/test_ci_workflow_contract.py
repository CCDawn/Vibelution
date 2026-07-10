from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


def workflow_text() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


def test_ci_remains_manual_only() -> None:
    text = workflow_text()
    trigger_block = text.split("concurrency:", 1)[0]
    assert "workflow_dispatch:" in trigger_block
    assert "pull_request:" not in trigger_block
    assert "push:" not in trigger_block


def test_manual_ci_runs_reachable_fatal_ruff() -> None:
    text = workflow_text()
    assert "tj-actions/changed-files" not in text
    assert "github.event_name == 'pull_request'" not in text
    assert (
        "python -m ruff check --select E9,F63,F7,F82 agent.py config core scripts tools"
        in text
    )
