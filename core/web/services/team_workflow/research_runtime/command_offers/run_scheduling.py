"""Operator scheduling offers; no node or execution identity changes."""

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.transitions import RunStatus, can_pause_run


def build_run_scheduling_offers(*, run, attempts=()) -> list[CommandOffer]:
    pausable = run.status in {"running", "waiting_human"} and bool(attempts) and can_pause_run(RunStatus(run.status))
    offers = []
    for command, label, available in (
        (WorkflowCommandKind.PAUSE_RUN, "暂停调度", pausable),
        (WorkflowCommandKind.RESUME_RUN, "恢复调度", run.status == "paused"),
    ):
        reason = "ready" if available else "run_not_pauseable" if command is WorkflowCommandKind.PAUSE_RUN else "run_not_paused"
        offers.append(CommandOffer(
            command=command, node_id=None, available=available, label=label,
            reason_code=reason, blocker_ids=() if available else (reason,),
            idempotency_key=f"offer:{run.run_id}:{command.value}:v{run.run_version}",
            expected_run_version=run.run_version,
            payload={} if available else {"remediation_label": (
                "当前运行没有可暂停的调度" if command is WorkflowCommandKind.PAUSE_RUN
                else "当前调度未暂停"
            )},
        ))
    return offers
