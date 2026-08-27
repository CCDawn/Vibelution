"""Real-LLM wiring for the human-click review chain.

The default digest drafter and the four hypothesis review runners are
deterministic DEV fixtures.  This module builds the real model-backed
counterparts from the operator-configured LLM and wires them into the
service-layer defaults:

* ``build_meeting_digest_drafter`` drafts the Coordinator meeting digest
  from the bound room messages.
* ``build_hypothesis_review_runners`` returns the reflection / pairwise /
  Pareto / MetaReview runners consumed by ``execute_hypothesis_review``.

Resolution is lazy and fail-open at *availability* level only: when no model
is configured the callers keep the DEV fixture behaviour, so DEV/CI stays
deterministic.  Once a runner runs, it fails closed — any malformed model
output raises ``ContractValidationError`` before anything is persisted,
mirroring the executor contract.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from config import get_config
from core.infrastructure.llm_utils import build_cacheable_system_message
from core.llm import LLMInvocationContext, get_llm_client, invoke_llm
from core.llm.agent_runtime import config_for_agent_llm_model
from core.llm.client import model_invocation_receipt_context_scope
from core.llm.invocation import invoke_llm_outcome
from core.llm.types import LLMError
from core.research.workflow.contracts import ContractValidationError
from core.research.workflow.contracts.hypothesis_quality import (
    AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS,
    HYPOTHESIS_SCORE_DIMENSIONS,
    canonical_hypothesis_score_rubric,
)
from core.web.services.team.team_constants import (
    CHALLENGE_CUP_RESEARCH_TEAM_DIALOGUE_MODEL_REF,
)
from core.web.services.team_workflow.hypothesis_review_executor import (
    ProviderBoundReviewResult,
)

REVIEW_LLM_PROFILE_ID = "primary"
REVIEW_LLM_SURFACE = "team_workflow_review"
REVIEW_LLM_CACHE_SCOPE = "team_workflow_review"

# Ratings accepted by the seven-dimension review authority rows.
DIMENSION_REVIEW_RATINGS = ("insufficient", "weak", "mixed", "adequate", "strong")

_MAX_MESSAGE_CHARS = 1200
_MAX_MESSAGES = 40

# Wall-clock budget for one review-profile LLM call (digest draft and the
# four hypothesis review runners).  Normal digest calls finish well under a
# minute on the team relay; the slowest legitimate calls on the same channel
# are discussion utterances at roughly 2-3.5 minutes, and a digest sees the
# whole bounded transcript (<= _MAX_MESSAGES), so 180s keeps headroom above
# the slowest observed utterance.  Without this budget a wedged provider
# connection pinned the meeting in ``summarizing`` for 33+ minutes while
# holding the per-meeting summary lock with no in-product recovery path
# (SCI-096 P0, validated 2026-08-28).
REVIEW_LLM_CALL_TIMEOUT_SECONDS = 180.0
_REVIEW_LLM_CALL_TIMEOUT_ENV = "VIBELUTION_REVIEW_LLM_CALL_TIMEOUT_SECONDS"


def review_llm_call_timeout_seconds() -> float:
    """Return the review-call timeout, tunable via the environment override."""

    raw = str(os.environ.get(_REVIEW_LLM_CALL_TIMEOUT_ENV) or "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return REVIEW_LLM_CALL_TIMEOUT_SECONDS
        if value > 0:
            return value
    return REVIEW_LLM_CALL_TIMEOUT_SECONDS


class ReviewLLMTimeoutError(LLMError):
    """One review-profile LLM call exceeded the configured wall-clock budget.

    Classified as the canonical ``timeout`` LLM error category (retryable) so
    existing error consumers can handle it like any other provider timeout;
    ``purpose`` and ``timeout_seconds`` keep the structured context for the
    meeting runtime's persisted ``summaryDraftError``.
    """

    def __init__(self, *, purpose: str, timeout_seconds: float) -> None:
        super().__init__(
            "timeout",
            f"review step `{purpose}` did not return within {timeout_seconds:g}s",
            retryable=True,
        )
        self.purpose = str(purpose)
        self.timeout_seconds = float(timeout_seconds)


def _invoke_llm_with_timeout(
    invoke: Callable[[], Any],
    *,
    purpose: str,
    timeout_seconds: float,
) -> Any:
    """Run one review LLM call, failing structured when the budget elapses.

    The provider call keeps running on its daemon worker after a timeout (the
    transport has no cooperative cancel); the caller returns immediately so
    the meeting runtime can persist a recoverable draft error and release the
    summary lock instead of hanging forever.
    """

    outcome: dict[str, Any] = {}
    finished = threading.Event()

    def _run() -> None:
        try:
            outcome["value"] = invoke()
        except BaseException as exc:  # noqa: BLE001 - re-raised on the waiter
            outcome["error"] = exc
        finally:
            finished.set()

    worker = threading.Thread(
        target=_run,
        name=f"review-llm-{purpose}",
        daemon=True,
    )
    worker.start()
    if not finished.wait(timeout_seconds):
        raise ReviewLLMTimeoutError(purpose=purpose, timeout_seconds=timeout_seconds)
    error = outcome.get("error")
    if error is not None:
        raise error
    return outcome.get("value")


def resolve_review_llm() -> dict[str, Any] | None:
    """Resolve the Challenge Cup team LLM for review calls.

    Review and digest generation belong to the Challenge Cup workflow, so
    they must use the same canonical model binding as its managed team
    agents.  The global ``primary`` profile belongs to the operator and may
    point at an unrelated or unavailable provider.  The selected team model
    is projected onto an isolated runtime config; no operator config is
    mutated.

    A provider without usable credentials is treated as unavailable and the
    deterministic DEV fixtures stay in charge.
    """

    try:
        runtime_config = config_for_agent_llm_model(
            get_config(),
            model_id=CHALLENGE_CUP_RESEARCH_TEAM_DIALOGUE_MODEL_REF,
            runtime_profile_id=REVIEW_LLM_PROFILE_ID,
            slot="dialogue",
        )
        client = get_llm_client(
            profile_id=REVIEW_LLM_PROFILE_ID,
            config=runtime_config,
        )
        model_id = str(getattr(getattr(client, "profile", None), "model", "") or "").strip()
        provider = getattr(client, "provider", None)
        api_key = str(getattr(provider, "api_key", "") or "").strip()
        api_key_env = str(getattr(provider, "api_key_env", "") or "").strip()
        requires_api_key = bool(getattr(provider, "requires_api_key", True))
    except Exception:
        return None
    if not model_id:
        return None
    if requires_api_key and not api_key and not (api_key_env and os.environ.get(api_key_env)):
        return None
    return {
        "client": client,
        "profileId": REVIEW_LLM_PROFILE_ID,
        "modelId": model_id,
        "providerId": str(getattr(provider, "provider_id", "") or "").strip(),
        "modelRef": (
            f"{str(getattr(provider, 'provider_id', '') or '').strip()}/{model_id}"
        ),
    }


def _parse_json_object(text: str, *, what: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ContractValidationError(f"{what} did not return valid JSON")
        try:
            payload = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            raise ContractValidationError(f"{what} did not return valid JSON") from None
    if not isinstance(payload, dict):
        raise ContractValidationError(f"{what} must return a JSON object")
    return payload


def _invoke_review_llm(
    llm: Mapping[str, Any],
    *,
    agent_id: str,
    purpose: str,
    system_prompt: str,
    user_payload: Mapping[str, Any],
    session_id: str,
    receipt_context: Mapping[str, Any] | None = None,
    require_provider_receipt: bool = False,
) -> dict[str, Any] | ProviderBoundReviewResult:
    """Run one review model call and parse its JSON object output."""

    messages: list[Any] = [
        build_cacheable_system_message(system_prompt),
        {
            "role": "user",
            "content": json.dumps(dict(user_payload), ensure_ascii=False),
        },
    ]
    receipt_binding = (
        receipt_context.get("questionStageBinding")
        if isinstance(receipt_context, Mapping)
        and isinstance(receipt_context.get("questionStageBinding"), Mapping)
        else {}
    )
    receipt_session_id = str(receipt_binding.get("sessionId") or "").strip()
    turn_id = str(receipt_binding.get("turnId") or "").strip()
    invocation_id = str(
        receipt_context.get("invocationId") if isinstance(receipt_context, Mapping) else ""
    ).strip()
    if require_provider_receipt and (
        not isinstance(receipt_context, Mapping)
        or not receipt_session_id
        or not turn_id
        or not invocation_id
    ):
        raise ContractValidationError(
            f"review step `{purpose}` requires server-owned provider receipt authority"
        )
    invocation_context = LLMInvocationContext(
        surface=REVIEW_LLM_SURFACE,
        run_kind="team_workflow_review",
        run_id=invocation_id if require_provider_receipt else "",
        session_id=receipt_session_id if require_provider_receipt else session_id,
        agent_id=agent_id,
        llm_slot="dialogue",
        cache_scope=REVIEW_LLM_CACHE_SCOPE,
        cache_partition=f"{session_id}:{purpose}",
        prompt_purpose=purpose,
        conversation_bound=False,
        metadata={
            "purpose": purpose,
            "reviewProfileId": llm["profileId"],
            **(
                {"turnId": turn_id, "invocationId": invocation_id}
                if require_provider_receipt
                else {}
            ),
        },
    )
    if not require_provider_receipt:
        response = _invoke_llm_with_timeout(
            lambda: invoke_llm(
                llm["client"],
                messages,
                context=invocation_context,
            ),
            purpose=purpose,
            timeout_seconds=review_llm_call_timeout_seconds(),
        )
        content = str(getattr(response, "content", "") or "")
        return _parse_json_object(content, what=f"review step `{purpose}`")

    def _invoke_bound_outcome() -> Any:
        # The receipt scope is a ContextVar: it must wrap the invocation
        # inside the timeout worker so the nested client call still sees it.
        with model_invocation_receipt_context_scope(receipt_context):
            return invoke_llm_outcome(
                llm["client"],
                messages,
                context=invocation_context,
            )

    outcome = _invoke_llm_with_timeout(
        _invoke_bound_outcome,
        purpose=purpose,
        timeout_seconds=review_llm_call_timeout_seconds(),
    )
    identity = getattr(outcome, "identity", None)
    if (
        str(getattr(outcome, "kind", "") or "") != "final_answer"
        or str(getattr(identity, "session_id", "") or "") != receipt_session_id
        or str(getattr(identity, "turn_id", "") or "") != turn_id
        or str(getattr(identity, "invocation_id", "") or "") != invocation_id
    ):
        raise ContractValidationError(
            f"review step `{purpose}` did not return the bound final provider outcome"
        )
    raw_receipt = getattr(outcome, "model_invocation_receipt", None)
    if not isinstance(raw_receipt, Mapping) or not raw_receipt:
        raise ContractValidationError(
            f"review step `{purpose}` completed without a provider receipt"
        )
    payload = _parse_json_object(
        str(getattr(outcome, "final_text", "") or ""),
        what=f"review step `{purpose}`",
    )
    return ProviderBoundReviewResult(
        payload=payload,
        model_invocation_receipt=dict(raw_receipt),
    )


# ---------------------------------------------------------------------------
# Coordinator digest drafter
# ---------------------------------------------------------------------------


def _meeting_transcript(
    source_messages: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    transcript: list[dict[str, Any]] = []
    for message in source_messages:
        if str(message.get("status") or "").strip().lower() != "completed":
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        speaker = (
            str(message.get("speakerTitle") or "").strip()
            or str(message.get("participantId") or "").strip()
            or "participant"
        )
        transcript.append(
            {
                "speaker": speaker,
                "content": content[:_MAX_MESSAGE_CHARS],
            }
        )
        if len(transcript) >= _MAX_MESSAGES:
            break
    return transcript


_DIGEST_SYSTEM_PROMPT = """你是科研团队的 Coordinator，负责把团队会议发言整理为结构化会议纪要。

要求：
- 只依据给出的会议发言，不得编造发言人或结论。
- summary 用一两句中文概括会议结论。
- agreements / risks / knowledgeCandidates 是字符串数组；disagreements 的每项是 {"issue","positions","unresolvedReason"}；actionItems 的每项是 {"ownerRoleId","action","dueGate"}。
- 候选生成会议必须输出 proposedCandidates：每项 {"candidateId","statement","rationale","proposedBy"}，candidateId 沿用发言中出现的标识，没有标识就用 cand-1、cand-2 顺序编号。
- 假说评审会议可以输出 evidenceRequests：每项 {"evidenceGap","searchEnvelope",...}，仅在发言明确要求补充证据时输出，否则给空数组。
- 严格输出单个 JSON 对象，不要输出 markdown 代码块或任何解释文字。

输出 JSON 结构：
{"summary": str, "agendaSummary": str, "discussionTopics": [str], "agreements": [str], "disagreements": [{"issue": str, "positions": [str], "unresolvedReason": str}], "actionItems": [{"ownerRoleId": str, "action": str, "dueGate": str}], "risks": [str], "knowledgeCandidates": [str], "proposedCandidates": [{"candidateId": str, "statement": str, "rationale": str, "proposedBy": str}], "evidenceRequests": [dict]}
"""


def build_meeting_digest_drafter(llm: Mapping[str, Any] | None = None):
    """Return the real-LLM Coordinator digest drafter, or ``None`` if unavailable."""

    resolved = dict(llm) if isinstance(llm, Mapping) and llm else resolve_review_llm()
    if not resolved:
        return None

    def drafter(
        meeting_round: dict[str, Any], source_messages: list[dict[str, Any]]
    ) -> Mapping[str, Any]:
        from core.web.services.team_workflow import meeting_rounds

        meeting_type = str(meeting_round.get("meetingType") or "").strip()
        transcript = _meeting_transcript(source_messages)
        if not transcript:
            raise ContractValidationError(
                "digest drafter requires completed source messages"
            )
        produced = _invoke_review_llm(
            resolved,
            agent_id="coordinator",
            purpose="meeting_digest",
            system_prompt=_DIGEST_SYSTEM_PROMPT,
            user_payload={
                "meetingType": meeting_type,
                "meetingRoundId": str(meeting_round.get("meetingRoundId") or ""),
                "agenda": list(meeting_round.get("agenda") or []),
                "participants": list(meeting_round.get("participants") or []),
                "messages": transcript,
            },
            session_id=str(meeting_round.get("teamId") or "") or "team",
        )
        # Server-owned fields: source refs are computed from the bound
        # messages, never delegated to the model.
        source_refs = [
            meeting_rounds.message_source_ref(message)
            for message in source_messages
            if str(message.get("status") or "").strip().lower() == "completed"
            and not meeting_rounds.is_pass_message(message)
        ]
        digest = dict(produced)
        digest["sourceMessageRefs"] = source_refs
        digest.setdefault("summary", "")
        digest.setdefault("agendaSummary", "")
        digest.setdefault("discussionTopics", list(meeting_round.get("agenda") or []))
        digest.setdefault("agreements", [])
        digest.setdefault("disagreements", [])
        digest.setdefault("actionItems", [])
        digest.setdefault("risks", [])
        digest.setdefault("blockers", [])
        digest.setdefault("knowledgeCandidates", [])
        digest.setdefault("proposedCandidates", [])
        digest.setdefault("evidenceRequests", [])
        return digest

    return drafter


# ---------------------------------------------------------------------------
# Hypothesis review runners
# ---------------------------------------------------------------------------


def _rubric_block() -> str:
    return json.dumps(canonical_hypothesis_score_rubric(), ensure_ascii=False)


_REFLECTION_SYSTEM_PROMPT = f"""你是科研假说评审员（独立评分步骤）。按官方五维 rubric 对单个假说候选独立评分。

Rubric（分数 0.0-1.0，两位小数，按分档描述对号入座）：
{_rubric_block()}

要求：
- scores 必须恰好包含五个维度：{list(HYPOTHESIS_SCORE_DIMENSIONS)}。
- claim 沿用候选自己的 claim 原文；rationale 用中文说明打分依据；differenceFromAlternatives 说明相对其他候选的差异。
- lineageRefs 沿用候选携带的来源引用，没有就给空数组，不得编造。
- dimensionReviews 是七维独立评审行（维度为 {list(HYPOTHESIS_SCORE_DIMENSIONS) + list(AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS)}），每行 {{"hypothesis_id","dimension","rating","rationale","reviewer","evidence_refs"}}；rating 只能取 {list(DIMENSION_REVIEW_RATINGS)}；evidence_refs 只能从输入 refsWhitelist 中选择，白名单为空则 dimensionReviews 给空数组。
- reviewedBy 固定为 "llm"，status 固定为 "reviewed"。
- 严格输出单个 JSON 对象。

输出 JSON 结构：
{{"claim": str, "rationale": str, "differenceFromAlternatives": str, "lineageRefs": [str], "scores": {{{", ".join(f'"{d}": float' for d in HYPOTHESIS_SCORE_DIMENSIONS)}}}, "reviewedBy": "llm", "status": "reviewed", "dimensionReviews": [dict]}}
"""

_PAIRWISE_SYSTEM_PROMPT = """你是科研假说评审员（两两比较步骤）。对给出的左右两个候选做一次比较。

要求：
- outcome 只能是 "left_wins"、"right_wins" 或 "tie"；只依据候选内容与评审上下文判断。
- justification 用中文说明胜负依据，必须非空。
- 严格输出单个 JSON 对象。

输出 JSON 结构：
{"outcome": "left_wins" | "right_wins" | "tie", "justification": str}
"""

_PARETO_SYSTEM_PROMPT = """你是科研假说评审员（Pareto 分类步骤）。基于五维评分把所有候选划分为 Pareto 前沿与被支配两类。

要求：
- paretoFrontCandidateIds 与 dominatedCandidateIds 的并集必须恰好覆盖全部候选 id，且两集合不相交。
- 前沿集合不能为空；notes 用中文说明划分依据。
- 严格输出单个 JSON 对象。

输出 JSON 结构：
{"paretoFrontCandidateIds": [str], "dominatedCandidateIds": [str], "notes": str}
"""

_METAREVIEW_SYSTEM_PROMPT = """你是科研团队 Coordinator（MetaReview 步骤）。综合独立评分、两两比较与 Pareto 分类，给出最终推荐。

要求：
- recommendationCandidateId 必须从给出的候选 id 中选择。
- rationale 用中文说明推荐依据；riskNotes 汇总未解决风险。
- accepted 表示本轮评审结论是否可接受（推荐候选质量足以进入实验设计）。
- 严格输出单个 JSON 对象。

输出 JSON 结构：
{"recommendationCandidateId": str, "rationale": str, "riskNotes": str, "accepted": bool}
"""


def _candidate_refs(candidate: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("lineageRefs", "evidenceRefs", "refs"):
        value = candidate.get(key)
        if isinstance(value, (list, tuple)):
            refs.extend(str(item) for item in value if str(item or "").strip())
    return refs


def _context_digest_refs(context: Mapping[str, Any]) -> list[str]:
    digest = context.get("digest") if isinstance(context.get("digest"), Mapping) else {}
    refs: list[str] = []
    for key in ("sourceMessageRefs", "discussionItemRefs"):
        value = digest.get(key) or context.get(key)
        if isinstance(value, (list, tuple)):
            refs.extend(str(item) for item in value if str(item or "").strip())
    return refs


def build_hypothesis_review_runners(
    llm: Mapping[str, Any] | None = None,
    *,
    require_provider_receipts: bool = False,
) -> dict[str, Any] | None:
    """Return the four real-LLM review runners, or ``None`` if unavailable."""

    resolved = dict(llm) if isinstance(llm, Mapping) and llm else resolve_review_llm()
    if not resolved:
        return None
    session_id = "team"

    def _context_session(context: Mapping[str, Any]) -> str:
        return str(context.get("teamId") or "") or session_id

    def _receipt_context(
        context: Mapping[str, Any],
        *,
        review_step: str,
        identity_parts: Sequence[Any],
    ) -> Mapping[str, Any] | None:
        if not require_provider_receipts:
            return None
        from core.web.services.team_workflow.research_runtime.meeting_receipt_authority import (
            MeetingReceiptAuthorityError,
            build_review_step_receipt_context,
        )

        try:
            receipt_context = build_review_step_receipt_context(
                context,
                review_step=review_step,
                identity_parts=identity_parts,
                session_id=_context_session(context),
                expected_model_route={
                    "modelRef": resolved.get("modelRef"),
                    "providerId": resolved.get("providerId"),
                    "modelId": resolved.get("modelId"),
                },
            )
        except MeetingReceiptAuthorityError as exc:
            raise ContractValidationError(str(exc)) from exc
        if receipt_context is None:
            raise ContractValidationError(
                f"formal {review_step} runner requires server-owned receipt authority"
            )
        return receipt_context

    def reflection_runner(candidate: dict[str, Any], context: dict[str, Any]):
        refs_whitelist = [
            * _candidate_refs(candidate),
            * _context_digest_refs(context),
        ]
        produced = _invoke_review_llm(
            resolved,
            agent_id="research_evidence_reviewer",
            purpose="hypothesis_reflection",
            system_prompt=_REFLECTION_SYSTEM_PROMPT,
            user_payload={
                "candidate": dict(candidate),
                "context": {
                    "contextId": str(context.get("contextId") or ""),
                    "question": str(context.get("question") or ""),
                },
                "refsWhitelist": refs_whitelist,
                "allowedDimensions": list(HYPOTHESIS_SCORE_DIMENSIONS),
                "allowedRatings": list(DIMENSION_REVIEW_RATINGS),
            },
            session_id=_context_session(context),
            receipt_context=_receipt_context(
                context,
                review_step="reflection",
                identity_parts=(str(candidate.get("candidateId") or ""),),
            ),
            require_provider_receipt=require_provider_receipts,
        )
        provider_receipt = None
        if isinstance(produced, ProviderBoundReviewResult):
            provider_receipt = produced.model_invocation_receipt
            result = dict(produced.payload)
        else:
            result = dict(produced)
        result["reviewedBy"] = f"llm:{resolved['modelId']}"
        rows = result.get("dimensionReviews")
        if isinstance(rows, list) and rows:
            for row in rows:
                if isinstance(row, dict):
                    row.setdefault("hypothesis_id", str(candidate.get("candidateId") or ""))
                    row.setdefault("reviewer", result["reviewedBy"])
        if provider_receipt is not None:
            return ProviderBoundReviewResult(result, provider_receipt)
        return result

    def pairwise_runner(
        left: dict[str, Any], right: dict[str, Any], context: dict[str, Any]
    ):
        return _invoke_review_llm(
            resolved,
            agent_id="research_theme_synthesizer",
            purpose="hypothesis_pairwise",
            system_prompt=_PAIRWISE_SYSTEM_PROMPT,
            user_payload={
                "left": dict(left),
                "right": dict(right),
                "context": {
                    "contextId": str(context.get("contextId") or ""),
                    "question": str(context.get("question") or ""),
                },
            },
            session_id=_context_session(context),
            receipt_context=_receipt_context(
                context,
                review_step="pairwise",
                identity_parts=(
                    str(left.get("candidateId") or ""),
                    str(right.get("candidateId") or ""),
                ),
            ),
            require_provider_receipt=require_provider_receipts,
        )

    def pareto_runner(scores_by_candidate: dict[str, dict[str, float]], context: dict[str, Any]):
        return _invoke_review_llm(
            resolved,
            agent_id="research_theme_synthesizer",
            purpose="hypothesis_pareto",
            system_prompt=_PARETO_SYSTEM_PROMPT,
            user_payload={
                "scoresByCandidate": dict(scores_by_candidate),
                "context": {
                    "contextId": str(context.get("contextId") or ""),
                    "question": str(context.get("question") or ""),
                },
            },
            session_id=_context_session(context),
            receipt_context=_receipt_context(
                context,
                review_step="pareto",
                identity_parts=tuple(sorted(scores_by_candidate)),
            ),
            require_provider_receipt=require_provider_receipts,
        )

    def metareview_runner(
        context: dict[str, Any],
        candidates: list[dict[str, Any]],
        pairwise: list[dict[str, Any]],
        pareto: dict[str, Any],
    ):
        produced = _invoke_review_llm(
            resolved,
            agent_id="coordinator",
            purpose="hypothesis_metareview",
            system_prompt=_METAREVIEW_SYSTEM_PROMPT,
            user_payload={
                "context": {
                    "contextId": str(context.get("contextId") or ""),
                    "question": str(context.get("question") or ""),
                },
                "candidates": [dict(item) for item in candidates],
                "pairwiseComparisons": [dict(item) for item in pairwise],
                "pareto": dict(pareto),
            },
            session_id=_context_session(context),
            receipt_context=_receipt_context(
                context,
                review_step="metareview",
                identity_parts=tuple(
                    sorted(str(item.get("candidateId") or "") for item in candidates)
                ),
            ),
            require_provider_receipt=require_provider_receipts,
        )
        provider_receipt = None
        if isinstance(produced, ProviderBoundReviewResult):
            provider_receipt = produced.model_invocation_receipt
            result = dict(produced.payload)
        else:
            result = dict(produced)
        result["reviewerAgentId"] = f"llm:{resolved['modelId']}"
        if provider_receipt is not None:
            return ProviderBoundReviewResult(result, provider_receipt)
        return result

    return {
        "reflection_runner": reflection_runner,
        "pairwise_runner": pairwise_runner,
        "pareto_runner": pareto_runner,
        "metareview_runner": metareview_runner,
    }
