"""Review-round budget consistency between the V2 projection and the command
envelope.

The projection layer (``hypothesis_first_state_v2``) and the chain execution
layer (``hypothesis_first_chain``) each recompute review-round progress from
durable records.  The audit suspected a double-read window where a round could
be opened beyond ``roundBudget`` or a budget exhaustion could be misjudged.
These tests lock down that the window stays closed:

- the projection offers ``open_next_review`` while ``round_index`` is below
  the single hard limit — alongside an early ``human_adjudication`` offer that
  reuses the exhausted path's exact contract — and drops the budget-bounded
  open at the boundary, leaving only ``human_adjudication``;
- execution re-authorizes against a freshly re-projected snapshot inside the
  per-question scope lock, so a stale ``expectedStateVersion`` is rejected by
  CAS before any mutation runs;
- the authorized action payload is matched exactly, so a caller cannot replace
  the server-owned hard limit with a per-request budget;
- after re-authorization the owning mutation still recomputes the next round
  index from durable links and refuses to exceed the effective budget.

No exploitable double-read window was found.  A separate real read defect
discovered while wiring this harness — ``_scope_records`` shadowing
``round_ids`` and dropping every hypothesis round record on the canonical
full-load path — is locked down at the bottom of this file as a plain
regression case now that it is fixed.
"""

from __future__ import annotations

import pytest

from core.web.routes.team_workflows.hypothesis_first_state_models import (
    HypothesisFirstStateV2,
)
from core.web.services.team_workflow import hypothesis_rounds
from core.web.services.team_workflow import hypothesis_selection as selections
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_state_v2,
)
from core.web.services.team_workflow.research_runtime.hypothesis_first_state_v2 import (
    project_hypothesis_first_state_v2,
    project_state_from_records,
)
from core.web.services.team_workflow.storage_durability import append_jsonl_locked

TEAM_ID = "team-budget-consistency"
QUESTION_ID = "SCI-001"
SELECTION_ID = "selection-1"
SELECTION_VERSION = "sel-ver-1"


def _phase(
    *,
    lifecycle: str = "not_started",
    outcome: str = "none",
    actionability: str = "idle",
) -> dict[str, object]:
    return {
        "lifecycle": lifecycle,
        "outcome": outcome,
        "actionability": actionability,
        "attempt": None,
        "updatedAt": None,
        "problems": [],
    }


def _budget_projection_records(
    *,
    round_index: int,
    round_budget: int = 3,
    meta_review_accepted: bool = False,
):
    latest_meeting_id = f"review-{round_index}"
    return dict(
        chain_records=[
            {
                "recordKind": "hypothesis_candidate",
                "candidateId": "candidate-1",
                "questionId": QUESTION_ID,
            },
            {
                "recordKind": "review_round_link",
                "linkId": f"link-{round_index}",
                "selectionId": SELECTION_ID,
                "selectionVersion": SELECTION_VERSION,
                "candidateId": "candidate-1",
                "candidateOrder": 0,
                "roundIndex": round_index,
                "roundBudget": round_budget,
                "meetingRoundId": latest_meeting_id,
                "questionId": QUESTION_ID,
            },
        ],
        selection_records=[
            {
                "selectionId": SELECTION_ID,
                "questionId": QUESTION_ID,
                "selectedCandidateIds": ["candidate-1"],
            }
        ],
        meeting_records=[
            {
                "meetingRoundId": latest_meeting_id,
                "meetingType": "hypothesis_review",
                "question": QUESTION_ID,
                "status": "closed",
            }
        ],
        digest_records=[],
        decision_records=[],
        hypothesis_round_records=[
            {
                "roundId": f"round-{round_index}",
                "question": QUESTION_ID,
                "roundIndex": round_index,
                "status": "closed",
                "metaReview": {"accepted": meta_review_accepted},
                "createdAt": "2026-08-25T00:00:00Z",
            }
        ],
    )


def test_projection_offers_open_next_review_within_budget() -> None:
    """A closed unaccepted round below budget must offer the follow-up
    review-open command with server-published budget payload, plus the early
    adjudication offer (same contract as the exhausted path)."""
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id=TEAM_ID,
            question_id=QUESTION_ID,
            reset_boundary=None,
            **_budget_projection_records(round_index=1),
        )
    )

    commands = {
        action.command: action for action in state.allowedActions if action.kind == "command"
    }
    assert state.currentPhase == "convergence"
    assert state.convergence.roundIndex == 1
    assert state.convergence.roundBudget == 5
    assert commands["open_next_review"].enabled is True
    assert commands["open_next_review"].actionId == "open-next-review:round-1"
    assert commands["open_next_review"].payload.previousMeetingRoundId == "review-1"
    assert commands["open_next_review"].payload.roundBudget == 5
    # Early adjudication stays available inside the budget: same action id
    # scheme, payload shape and schema ref as the exhausted-path offer.
    assert commands["human_adjudication"].actionId == "human-adjudication:round-1"
    assert commands["human_adjudication"].payload.hypothesisRoundId == "round-1"
    assert commands["human_adjudication"].inputSchemaRef == (
        "hypothesis-first/human-adjudication/v1"
    )
    assert state.convergence.lifecycle == "waiting_human"
    assert state.convergence.outcome == "none"


def test_legacy_round_three_continues_under_single_hard_limit() -> None:
    """A link persisted with the retired budget of 3 must not block an
    unconverged chain before the agent can decide whether round 4 is needed."""
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id=TEAM_ID,
            question_id=QUESTION_ID,
            reset_boundary=None,
            **_budget_projection_records(round_index=3, round_budget=3),
        )
    )

    commands = {
        action.command: action for action in state.allowedActions if action.kind == "command"
    }
    assert state.convergence.roundIndex == 3
    assert state.convergence.roundBudget == 5
    assert commands["open_next_review"].payload.roundBudget == 5
    assert commands["human_adjudication"].actionId == "human-adjudication:round-3"
    assert state.convergence.lifecycle == "waiting_human"


def test_projection_switches_to_human_adjudication_when_budget_exhausted() -> None:
    """At ``round_index == round_budget`` the same closed unaccepted round must
    flip to exhausted and never keep offering the budget-bounded open."""
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id=TEAM_ID,
            question_id=QUESTION_ID,
            reset_boundary=None,
            **_budget_projection_records(round_index=5),
        )
    )

    commands = {
        action.command: action for action in state.allowedActions if action.kind == "command"
    }
    assert state.currentPhase == "convergence"
    assert state.convergence.roundIndex == 5
    assert state.convergence.roundBudget == 5
    assert "open_next_review" not in commands
    assert commands["human_adjudication"].payload.hypothesisRoundId == "round-5"
    assert state.convergence.lifecycle == "completed"
    assert state.convergence.outcome == "exhausted"


def _append_record(path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl_locked(path, record)


def _seed_completed_round(
    *,
    round_index: int,
    round_budget: int = 3,
) -> None:
    """Persist one durable completed review round through raw appends.

    Shape mirrors what the owning services write, read back by the real
    projector via ``project_hypothesis_first_state_v2``.
    """
    selection_record = {
        "schemaVersion": 1,
        "selectionId": SELECTION_ID,
        "program": "XH-202619",
        "theme": "theme-1",
        "campaign": "campaign-1",
        "question": QUESTION_ID,
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agentId": "agent-a",
        "mode": "formal",
        "scopeHash": "scope-hash",
        "questionId": QUESTION_ID,
        "selectedCandidateIds": ["candidate-1"],
        "previousSelectionId": "",
        "decidedBy": "agent-a",
        "selectionHash": f"hash-{SELECTION_ID}",
        "createdAt": "2026-08-26T00:00:00Z",
    }
    _append_record(
        selections._storage_path(TEAM_ID),
        selection_record,
    )
    _append_record(
        chain._storage_path(TEAM_ID),
        {
            "recordKind": "hypothesis_candidate",
            "candidateId": "candidate-1",
            "questionId": QUESTION_ID,
        },
    )
    _append_record(
        chain._storage_path(TEAM_ID),
        {
            "recordKind": "review_round_link",
            "linkId": f"link-{round_index}",
            "selectionId": SELECTION_ID,
            "selectionVersion": SELECTION_VERSION,
            "candidateId": "candidate-1",
            "candidateOrder": 0,
            "roundIndex": round_index,
            "roundBudget": round_budget,
            "meetingRoundId": f"review-{round_index}",
            "questionId": QUESTION_ID,
        },
    )
    _append_record(
        meetings._rounds_path(TEAM_ID),
        {
            "meetingRoundId": f"review-{round_index}",
            "meetingType": "hypothesis_review",
            "question": QUESTION_ID,
            "status": "closed",
            "inputArtifactRefs": [f"hypothesis_selection:{SELECTION_ID}"],
        },
    )
    _append_record(
        hypothesis_rounds._storage_path(TEAM_ID),
        {
            "roundId": f"round-{round_index}",
            "question": QUESTION_ID,
            "roundIndex": round_index,
            "status": "closed",
            "metaReview": {"accepted": False},
            "createdAt": "2026-08-25T00:00:00Z",
        },
    )


def _raise_program_output_missing(*_args, **_kwargs):
    raise ValueError("challenge_question_run_not_found")


class _EmptyQueryService:
    def list_runs(self, **_kwargs):
        return {"runs": []}


def _envelope_env(
    tmp_path,
    monkeypatch,
) -> list[dict]:
    """Isolate storage and stub only the room-opening leaf of the fan-out.

    Everything between ``execute_v2_command`` and the budget gate stays real:
    fresh reprojection, CAS, allowed-action matching, durable link recompute.
    Only ``meeting_runtime.open_hypothesis_review_meeting`` (room backend) is
    replaced, mirroring the harness of ``test_challenge_chain_observability``.
    Returns the list of captured opening payloads.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_runtime
    from core.web.services.team_workflow.research_runtime import (
        meeting_receipt_authority,
    )
    from tests._support.team_workflow.helpers import _use_tmp_project_root

    _use_tmp_project_root(tmp_path, monkeypatch)
    hypothesis_first_state_v2.clear_hypothesis_first_state_v2_cache()
    # 本文件不涉及 formal 流程权威：读侧给空实现，程序输出保持不存在。
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.formal_read_runtime.get_query_service",
        lambda: _EmptyQueryService(),
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.challenge_question_runs.get_challenge_question_run_detail",
        _raise_program_output_missing,
    )
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(selections, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(hypothesis_rounds, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    # 真实投影要求官方目录题号；本文件只关心轮次预算一致性语义。
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "is_official_question_id",
        lambda value: True,
    )

    opened: list[dict] = []

    def fake_open(_team_id, payload, **_kwargs):
        opened.append(dict(payload))
        return {
            "status": "created",
            "meetingRound": {"meetingRoundId": payload["meetingRoundId"]},
            "roomId": f"room-{payload['candidateId']}",
            "roundId": f"round-{payload['candidateId']}",
            "chatRoomRoundIds": [f"chat-{payload['candidateId']}"],
        }

    monkeypatch.setattr(meeting_runtime, "open_hypothesis_review_meeting", fake_open)
    monkeypatch.setattr(
        meeting_runtime,
        "_ensure_linked_room",
        lambda value: ({"teamId": value}, "team-room"),
    )
    monkeypatch.setattr(
        meeting_receipt_authority,
        "resolve_active_question_authority",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        chain,
        "_resolve_hypothesis_participants",
        lambda *_args: {"participants": ["agent-evaluator"]},
    )
    monkeypatch.setattr(chain, "_build_round_candidates", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        chain,
        "list_hypothesis_candidates",
        lambda *_args, **_kwargs: {
            "candidates": [{"candidateId": "candidate-1"}]
        },
    )
    return opened


def _published_command(snapshot: dict, command: str) -> dict:
    matched = [
        action
        for action in snapshot.get("allowedActions") or []
        if isinstance(action, dict)
        and action.get("kind") == "command"
        and action.get("command") == command
    ]
    assert len(matched) == 1, f"expected exactly one {command} action: {matched}"
    return matched[0]


def _chain_ledger() -> list[dict]:
    from core.web.services.team_workflow.storage_durability import read_jsonl_tolerant

    return read_jsonl_tolerant(chain._storage_path(TEAM_ID))


def test_open_next_review_executes_under_current_snapshot_and_increments_round(
    tmp_path,
    monkeypatch,
) -> None:
    """With a current snapshot the envelope executes the published open and
    the durable review-round binding advances to round 2 within budget."""
    opened = _envelope_env(tmp_path, monkeypatch)
    _seed_completed_round(round_index=1)

    snapshot = project_hypothesis_first_state_v2(TEAM_ID, QUESTION_ID)
    action = _published_command(snapshot, "open_next_review")
    assert action["enabled"] is True
    seeded_links = [
        record
        for record in _chain_ledger()
        if record.get("recordKind") == "review_round_link"
    ]
    assert [int(link["roundIndex"]) for link in seeded_links] == [1]

    result = chain.execute_v2_command(
        TEAM_ID,
        {
            "actionId": action["actionId"],
            "idempotencyKey": action["idempotencyKey"],
            "expectedStateVersion": action["expectedStateVersion"],
            "command": "open_next_review",
            "payload": dict(action["payload"]),
            "input": {},
        },
        question_id=QUESTION_ID,
    )

    assert result["acceptedStateVersion"] == action["expectedStateVersion"]
    # fan-out 信封的顶层状态随候选会议结果可能是 opened 或 created；二者都代表
    # 第 2 轮已真实开轮，轮次递增由下方耐久 link 断言兜底。
    assert result["result"]["status"] in {"opened", "created"}
    # 执行层真实执行了开轮：叶 room stub 收到 candidate-1 的第 2 轮会议。
    assert len(opened) == 1
    assert opened[0]["candidateId"] == "candidate-1"
    assert "-r2" in str(opened[0]["meetingRoundId"])
    advanced_links = [
        record
        for record in _chain_ledger()
        if record.get("recordKind") == "review_round_link"
    ]
    assert sorted(int(link["roundIndex"]) for link in advanced_links) == [1, 2]
    newest = max(advanced_links, key=lambda link: int(link["roundIndex"]))
    assert newest["selectionId"] == SELECTION_ID
    assert int(newest["roundBudget"]) == 5


def test_stale_expected_state_version_is_rejected_before_any_mutation(
    tmp_path,
    monkeypatch,
) -> None:
    """A concurrent writer advancing rounds between snapshot and submit makes
    the stale CAS fail before any round mutation can run."""
    opened = _envelope_env(tmp_path, monkeypatch)
    _seed_completed_round(round_index=1)

    snapshot = project_hypothesis_first_state_v2(TEAM_ID, QUESTION_ID)
    action = _published_command(snapshot, "open_next_review")
    baseline = len(_chain_ledger())

    # 并发写者（工作流收尾路径）抢先推进轮次：第 2 轮假设轮开始创建。
    _append_record(
        hypothesis_rounds._storage_path(TEAM_ID),
        {
            "roundId": "round-2",
            "question": QUESTION_ID,
            "roundIndex": 2,
            "status": "created",
            "createdAt": "2026-08-26T12:00:00Z",
        },
    )

    with pytest.raises(chain.StateVersionConflictError) as raised:
        chain.execute_v2_command(
            TEAM_ID,
            {
                "actionId": action["actionId"],
                "idempotencyKey": action["idempotencyKey"],
                "expectedStateVersion": action["expectedStateVersion"],
                "command": "open_next_review",
                "payload": dict(action["payload"]),
                "input": {},
            },
            question_id=QUESTION_ID,
        )

    assert raised.value.code == "state_version_conflict"
    assert raised.value.expected == action["expectedStateVersion"]
    assert raised.value.actual != action["expectedStateVersion"]
    # 被拒的提交没有触达任何轮次变更：链账本保持基线，room stub 未被调用。
    assert opened == []
    assert len(_chain_ledger()) == baseline


def test_exhausted_budget_blocks_open_next_review_at_reauthorization(
    tmp_path,
    monkeypatch,
) -> None:
    """At the budget boundary a fully current version still cannot reopen a
    review round: fresh allowedActions no longer publish the command."""
    opened = _envelope_env(tmp_path, monkeypatch)
    _seed_completed_round(round_index=5)

    snapshot = project_hypothesis_first_state_v2(TEAM_ID, QUESTION_ID)
    commands = {
        action["command"]
        for action in snapshot.get("allowedActions") or []
        if isinstance(action, dict) and action.get("kind") == "command"
    }
    assert "human_adjudication" in commands
    assert "open_next_review" not in commands

    with pytest.raises(chain.HypothesisFirstChainError, match="no longer allowed"):
        chain.execute_v2_command(
            TEAM_ID,
            {
                "actionId": "open-next-review:review-3",
                "idempotencyKey": "hf2:budget-forge:1",
                "expectedStateVersion": snapshot["stateVersion"],
                "command": "open_next_review",
                "payload": {
                    "previousMeetingRoundId": "review-3",
                    "roundBudget": 99,
                },
                "input": {},
            },
            question_id=QUESTION_ID,
        )

    assert opened == []
    links = [
        record
        for record in _chain_ledger()
        if record.get("recordKind") == "review_round_link"
    ]
    assert [int(link["roundIndex"]) for link in links] == [5]


def test_published_hard_limit_cannot_be_replaced_by_caller(
    tmp_path,
    monkeypatch,
) -> None:
    """The envelope matches the whole published payload; replacing the hard
    limit with the retired default budget fails authorization."""
    opened = _envelope_env(tmp_path, monkeypatch)
    _seed_completed_round(round_index=1)

    snapshot = project_hypothesis_first_state_v2(TEAM_ID, QUESTION_ID)
    action = _published_command(snapshot, "open_next_review")
    forged_payload = {**action["payload"], "roundBudget": 3}
    assert forged_payload != action["payload"]

    with pytest.raises(chain.HypothesisFirstChainError, match="no longer allowed"):
        chain.execute_v2_command(
            TEAM_ID,
            {
                "actionId": action["actionId"],
                "idempotencyKey": "hf2:budget-forge:2",
                "expectedStateVersion": action["expectedStateVersion"],
                "command": "open_next_review",
                "payload": forged_payload,
                "input": {},
            },
            question_id=QUESTION_ID,
        )

    assert opened == []
    links = [
        record
        for record in _chain_ledger()
        if record.get("recordKind") == "review_round_link"
    ]
    assert sorted(int(link["roundIndex"]) for link in links) == [1]


# 纯投影层之外的存量防线说明：open_next_review_meeting 在写入前会用耐久
# review_round_link 重算 round_index，并在超过 effective_budget 时返回
# budget_exhausted（见 test_research_workflow_hypothesis_first_chain.py 的
# test_round_budget_exhaustion_requires_manual_decision）。V2 信封层与本文件
# 锁定的是新鲜重投影 + CAS + 精确 payload 匹配把双读窗口闭合在鉴权阶段。


def test_full_loader_projection_keeps_hypothesis_rounds_for_budget_gate(
    tmp_path,
    monkeypatch,
) -> None:
    """Canonical full loader must keep hypothesis rounds so the budget gate
    can flip convergence into its terminal/open states.

    Regression anchor for the fixed read defect: ``_scope_records`` used to
    rebind the outer ``round_ids = set(snapshot["targetRoundIds"])`` while
    iterating meeting ``chatRoomRoundIds``, so ``hypothesis_round_records``
    was always filtered against the wrong collection and came back empty —
    starving convergence of ``open_next_review`` / ``human_adjudication`` on
    the real read path (introduced by c70f3efe9, fixed by renaming the loop
    local)."""
    _envelope_env(tmp_path, monkeypatch)
    _seed_completed_round(round_index=1)

    snapshot = project_hypothesis_first_state_v2(TEAM_ID, QUESTION_ID)
    commands = {
        action["command"]
        for action in snapshot.get("allowedActions") or []
        if isinstance(action, dict) and action.get("kind") == "command"
    }
    assert snapshot["convergence"]["roundIndex"] == 1
    assert snapshot["convergence"]["lifecycle"] == "waiting_human"
    assert "open_next_review" in commands
