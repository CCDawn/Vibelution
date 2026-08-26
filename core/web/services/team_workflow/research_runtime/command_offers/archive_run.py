"""archive_run CommandOffer for terminal workflow recovery."""

from __future__ import annotations

from core.research.workflow.contracts import (
    CommandOffer,
    ConfirmationContract,
    WorkflowCommandKind,
)
from core.research.workflow.ledger.records import RunRecord
from core.research.workflow.transitions import RunStatus, can_transition_run


_ARCHIVABLE_STATUSES = frozenset(
    {
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.RECONCILIATION_REQUIRED,
    }
)


def build_archive_run_offer(*, run: RunRecord) -> CommandOffer:
    try:
        current = RunStatus(run.status)
    except ValueError:
        current = None
    available = bool(
        current is not None
        and current in _ARCHIVABLE_STATUSES
        and can_transition_run(current, RunStatus.ARCHIVED)
    )
    return CommandOffer(
        command=WorkflowCommandKind.ARCHIVE_RUN,
        node_id=None,
        available=available,
        label="归档运行",
        reason_code="archive_available" if available else "archive_not_allowed",
        blocker_ids=() if available else ("archive_not_allowed",),
        idempotency_key=f"offer:{run.run_id}:archive_run:v{run.run_version}",
        expected_run_version=run.run_version,
        payload={"reason": "operator archived"},
        destructive=True,
        confirmation=ConfirmationContract(
            title="归档运行",
            body="归档后当前运行不会再次执行；如需重跑，系统会创建新的运行记录。",
            confirm_label="确认归档",
            cancel_label="取消",
        ),
    )
