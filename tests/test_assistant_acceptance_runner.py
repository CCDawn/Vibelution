"""Missing acceptance evidence must not be summarized as full success."""
from types import SimpleNamespace

import pytest

from scripts.acceptance_assistant_scheduling import aggregate_status, completion_status


def test_unexecuted_launcher_cannot_borrow_cross_project_success():
    assert completion_status({"crossProject": {"status": "passed"},
        "launcherLifecycle": {"status": "not_tested"}}) == "partial"


def test_unexecuted_lost_ack_cannot_borrow_restart_success():
    assert completion_status({"longTask": {"status": "passed"},
        "cancellation": {"status": "passed"}, "lostAcknowledgement": {"status": "not_tested"}}) == "partial"


def test_completed_stages_and_failed_stages_have_distinct_outcomes():
    assert completion_status({"first": {"status": "passed"}, "second": {"status": "passed"}}) == "passed"
    assert completion_status({"first": {"status": "passed"}, "second": {"status": "failed"}}) == "failed"


def test_report_preserves_partial_and_failed_cases():
    assert aggregate_status({"a": {"status": "passed"}, "b": {"status": "partial"}}) == "partial"
    assert aggregate_status({"a": {"status": "passed"}, "b": {"status": "failed"}}) == "failed"
    assert aggregate_status({"a": {"status": "passed"}}) == "passed"
    assert aggregate_status({}) == "failed"


@pytest.mark.parametrize("status", ["starting", "running", "unknown", None])
def test_only_completed_stages_can_pass(status):
    assert completion_status({"stage": {"status": status}, "metadata": {"count": 3}}) == "partial"


def test_launcher_readiness_failure_reaps_owned_process_if_formal_exit_fails(monkeypatch, tmp_path):
    from scripts import acceptance_assistant_projects as projects
    from scripts import acceptance_assistant_scheduling as runner
    from scripts import acceptance_local_assistant_development as base

    class Controller:
        process = SimpleNamespace(poll=lambda: None)
        plan = {}
        control_path = tmp_path / "control.json"
        stopped = False
        slots = {"B": SimpleNamespace(root=tmp_path / "other-project")}

        def stop_standalone(self):
            pass

        def start(self, **kwargs):
            raise runner.AcceptanceFailure("readiness_failed")

        def _save(self):
            pass

        def _capture_children(self):
            pass

        def wait_exit(self, **kwargs):
            raise runner.AcceptanceFailure("formal_exit_failed")

        def stop_owned_after_failure(self):
            self.stopped = True

    controller = Controller()
    monkeypatch.setattr(projects, "prepare_launcher_phase", lambda *a, **kw: controller)
    monkeypatch.setattr(base, "git", lambda *a: str(tmp_path / ".git"))
    args = SimpleNamespace(electron=None, desktop_dist=None, pythonw=None, readiness_timeout=1)
    with pytest.raises(runner.AcceptanceFailure, match="formal_exit_failed"):
        runner.run_launcher_phase(None, {}, args)
    assert controller.stopped
    assert controller.plan["nextAction"]["type"] == "exit"
