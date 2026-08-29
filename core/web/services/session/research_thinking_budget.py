"""Hard thinking-budget system prompt instruction for research node Agent sessions.

Research workflow node Agent sessions (workflow-run/node scoped experiment
bindings) call GLM-class thinking models through the relay. Direct probes on
the same relay/model showed complex node prompts trigger 8K+ silent reasoning
tokens (~3 minutes per call) while visible output stays under ~600 tokens, and
that a *hard* system-prompt budget line ("思考过程必须控制在500字以内，快速
决策，直接行动。") cuts reasoning to ~765 tokens with normal tool calls. Soft
wording has no effect and relay-side thinking switches are rejected or ignored,
so the prompt line is the only effective lever.

This module owns that lever: budget resolution (env override, bounded default),
the instruction block text, and workflow-scope detection. Ordinary user chat
sessions without a workflow-scoped experiment binding never receive the block.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from typing import Any

RESEARCH_THINKING_BUDGET_ENV = "VIBELUTION_RESEARCH_THINKING_BUDGET_CHARS"
DEFAULT_RESEARCH_THINKING_BUDGET_CHARS = 500

# Hard upper bound keeps an operator typo in the env override from turning the
# budget line into another unbounded-reasoning invitation.
_MAX_RESEARCH_THINKING_BUDGET_CHARS = 4000

THINKING_BUDGET_SEGMENT_KEY = "research_thinking_budget"


def resolve_research_thinking_budget_chars(
    env_value: str | None = None,
) -> int:
    """Resolve the thinking budget in chars; invalid overrides fall back to default."""

    raw = (
        str(
            os.environ.get(RESEARCH_THINKING_BUDGET_ENV)
            if env_value is None
            else env_value
        )
        or ""
    ).strip()
    if not raw:
        return DEFAULT_RESEARCH_THINKING_BUDGET_CHARS
    try:
        budget = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_RESEARCH_THINKING_BUDGET_CHARS
    if budget <= 0:
        return DEFAULT_RESEARCH_THINKING_BUDGET_CHARS
    return min(budget, _MAX_RESEARCH_THINKING_BUDGET_CHARS)


def build_research_node_thinking_budget_block(budget_chars: int | None = None) -> str:
    """Render the hard budget instruction block.

    Wording must stay hard ("必须…以内" + "快速决策，直接行动。"); soft
    equivalents measurably fail to bound reasoning. Keep the quality fallback
    sentence action-oriented without "充分思考/深入分析" style incentives.
    """

    resolved = (
        resolve_research_thinking_budget_chars()
        if budget_chars is None
        else max(1, int(budget_chars))
    )
    return "\n".join(
        [
            "## 思考预算（硬性要求）",
            f"内部思考过程必须控制在 {resolved} 字以内：快速决策，直接行动。",
            "回复直接给出行动与结果，不展开长篇推演。",
        ]
    )


def is_workflow_scoped_experiment_binding(binding: Any) -> bool:
    """True only for experiment bindings bound to one workflow run/node."""

    if not isinstance(binding, dict):
        return False
    workflow_run_id = str(binding.get("workflowRunId") or "").strip()
    workflow_node_id = str(binding.get("workflowNodeId") or "").strip()
    return bool(workflow_run_id) and bool(workflow_node_id)


def build_research_thinking_budget_segment(
    session_id: str,
    *,
    project_root: Any,
    load_chat_state: Callable[[Any, str], dict[str, Any] | None],
) -> dict[str, Any] | None:
    """Return the cache_prefix segment for workflow-scoped node sessions, else None.

    ``load_chat_state`` is late-bound so facade monkeypatches stay effective in
    tests and the service singleton is not imported here.
    """

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    try:
        conversation = load_chat_state(project_root, normalized_session_id)
    except Exception:  # noqa: BLE001 - chat state read failure must never break the turn
        return None
    binding = (
        conversation.get("experimentBinding")
        if isinstance(conversation, dict)
        else None
    )
    if not is_workflow_scoped_experiment_binding(binding):
        return None
    block = build_research_node_thinking_budget_block()
    if not block:
        return None
    return {
        "key": THINKING_BUDGET_SEGMENT_KEY,
        "block": block,
        "placement": "cache_prefix",
        "stability": "session_static",
        "chars": len(block),
        "hash": hashlib.sha256(block.encode("utf-8", errors="ignore")).hexdigest()[:16],
    }
