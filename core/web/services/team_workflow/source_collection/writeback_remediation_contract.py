"""Deterministic one-shot remediation contracts for writeback rejections.

Canonical pattern: ``extraction_quote_anchor_supply.build_quote_anchor_remediation``
(structured one-shot remediation package: findings + instruction + attempt +
one-shot warning).  That chain stays untouched; this module generalizes the
same shape to the remaining deterministic rejection classes:

- ``relation_refs``: a relations graph writeback referenced evidenceRefs that
  are not canonical ``claimEvidenceId`` values.
- ``relation_missing_fields``: the persisted relations graph lacks a required
  collection (edges / evidenceGaps / counterEvidenceRefs) or has a malformed
  one.
- ``evidence_fields``: an extraction writeback violated the Challenge v2
  evidence-card field contract (path-based errors from
  ``normalize_challenge_evidence_fields``).

At a deterministic rejection the system already holds both the submitted
offending values and the allowed set, so the diff is computable without any
LLM.  The rendered contract lands on the canonical task record as
``task["writebackRemediationContract"]`` and is injected into the next
``source_collection_context_tool`` read as ``context["writebackRemediation"]``
until exhausted.  Nothing here relaxes a validation: when a diff ingredient
cannot be extracted, the contract degrades gracefully (allowed list only).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

# Stable contract surface (a later LLM-planner layer consumes these names).
WRITEBACK_REMEDIATION_SCHEMA_VERSION = 1

WRITEBACK_REMEDIATION_KIND_RELATION_REFS = "relation_refs"
WRITEBACK_REMEDIATION_KIND_RELATION_MISSING_FIELDS = "relation_missing_fields"
WRITEBACK_REMEDIATION_KIND_EVIDENCE_FIELDS = "evidence_fields"

WRITEBACK_REMEDIATION_KINDS = (
    WRITEBACK_REMEDIATION_KIND_RELATION_REFS,
    WRITEBACK_REMEDIATION_KIND_RELATION_MISSING_FIELDS,
    WRITEBACK_REMEDIATION_KIND_EVIDENCE_FIELDS,
)

# At most this many findings render into one contract payload.
_REMEDIATION_FINDING_LIMIT = 8

# At most this many allowed refs are inlined into the rejection hint block.
_ALLOWED_REFS_HINT_LIMIT = 12

# Bound each rendered violation value inside findings and hints.
_VIOLATION_VALUE_MAX_CHARS = 160

# Relation collections that carry ``evidenceRefs``; the key groups mirror the
# agent-graph payload reader (writeback_materialize) and the quality gate's
# edge sweep so a violation can always be traced back to the submitted shape.
_RELATION_COLLECTION_KEY_GROUPS: tuple[tuple[str, ...], ...] = (
    ("candidateRelations", "candidate_relations"),
    ("sourceThemeEdges", "source_theme_edges", "sourceTopicEdges", "source_topic_edges"),
    ("topicRelations", "topic_relations", "themeRelations", "theme_relations"),
)
_COUNTER_REF_KEYS = ("counterEvidenceRefs", "counter_evidence_refs")

# ``evidence_relation_graph missing required fields: edges, evidenceGaps``
_MISSING_FIELDS_PATTERN = re.compile(
    r"missing required fields:\s*(?P<fields>[A-Za-z_,\s]+)"
)

# Shape-guard rejections from the agent-graph payload reader, e.g.
# ``result_json.candidateGraph.edges must be an array of objects`` and
# ``every result_json.counterEvidenceRefs item must be an object``.
_SHAPE_REJECTION_MARKERS = (
    "must be an array of objects",
    "item must be an object",
)
_SHAPE_REJECTION_PATH_PATTERN = re.compile(r"result_json\.(?P<path>[A-Za-z_][\w.]*)")

# Evidence-card contract errors start with the violating path token, e.g.
# ``candidateExtractions[0].claims[1] is missing explicit fact``.
_LEADING_PATH_PATTERN = re.compile(r"^(?P<path>[A-Za-z_][\w.\[\]-]*)")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _clip(value: Any, max_chars: int = _VIOLATION_VALUE_MAX_CHARS) -> str:
    text = _clean(value)
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def classify_relation_graph_rejection_error(error_text: str) -> str:
    """Map one relation-graph rejection message to a contract kind.

    Covers both ``load_evidence_relation_graph_payload`` read-back errors and
    the agent-graph payload reader's shape guard (``must be an array of
    objects`` / ``every ... item must be an object``).  Returns ``""`` when
    the error does not belong to a covered deterministic class — callers then
    skip the contract entirely instead of guessing.
    """
    text = _clean(error_text)
    if not text:
        return ""
    if (
        "missing required fields" in text
        or "edges must be objects" in text
        or any(marker in text for marker in _SHAPE_REJECTION_MARKERS)
    ):
        return WRITEBACK_REMEDIATION_KIND_RELATION_MISSING_FIELDS
    if (
        "must be canonical claimEvidenceId" in text
        or "canonical evidence cards are missing" in text
    ):
        return WRITEBACK_REMEDIATION_KIND_RELATION_REFS
    return ""


def relation_missing_field_findings(error_text: str) -> list[dict[str, Any]]:
    """Render missing/malformed graph collections from the validator's message."""
    text = _clean(error_text)
    match = _MISSING_FIELDS_PATTERN.search(text)
    if match:
        names = [
            _clean(name)
            for name in match.group("fields").split(",")
            if _clean(name)
        ]
        if names:
            return [
                {"finding": "missing_required_field", "path": name}
                for name in names
            ]
    if "edges must be objects" in text:
        return [{"finding": "malformed_collection", "path": "edges"}]
    shape_match = _SHAPE_REJECTION_PATH_PATTERN.search(text)
    if any(marker in text for marker in _SHAPE_REJECTION_MARKERS) and shape_match:
        return [
            {
                "finding": "malformed_collection",
                "path": shape_match.group("path"),
            }
        ]
    return [
        {
            "finding": "graph_shape_invalid",
            "path": "",
            "detail": _clip(text, 400),
        }
    ]


def collect_relation_ref_violations(
    result: Mapping[str, Any],
    allowed_refs: set[str],
) -> list[dict[str, Any]]:
    """Find every non-canonical evidence reference in the submitted result.

    Scans the relation collections the agent actually writes (root keys plus a
    nested ``candidateGraph.edges`` and the implicit root ``edges`` shape the
    merge path also accepts) and the counter-evidence refs.  Each finding
    carries the exact submitted path and offending value so the agent can fix
    deterministically instead of re-reading context blind.
    """
    findings: list[dict[str, Any]] = []
    if not isinstance(result, Mapping):
        return findings

    def _edge_findings(container: Mapping[str, Any], path_prefix: str) -> None:
        items = container.get("edges") if isinstance(container.get("edges"), list) else []
        for index, edge in enumerate(items):
            if not isinstance(edge, Mapping):
                continue
            refs = edge.get("evidenceRefs")
            if isinstance(edge.get("evidence_refs"), list):
                refs = edge["evidence_refs"]
            base = f"{path_prefix}[{index}].evidenceRefs"
            if not isinstance(refs, list) or not refs:
                findings.append({"finding": "missing_evidence_refs", "path": base})
                continue
            for ref_index, ref in enumerate(refs):
                if not isinstance(ref, str) or ref not in allowed_refs:
                    findings.append(
                        {
                            "finding": "non_canonical_ref",
                            "path": f"{base}[{ref_index}]",
                            "value": _clip(ref),
                        }
                    )

    # Implicit graph write shape: a root ``edges`` array feeds the merged graph
    # exactly like ``candidateGraph.edges`` (writeback_materialize's agent
    # payload reader), so it needs the same violation sweep.
    _edge_findings(result, "edges")
    scanned_keys: set[str] = set()
    for key_group in _RELATION_COLLECTION_KEY_GROUPS:
        for key in key_group:
            if key in scanned_keys or not isinstance(result.get(key), list):
                continue
            scanned_keys.add(key)
            display_key = key_group[0]
            for index, edge in enumerate(result[key]):
                if not isinstance(edge, Mapping):
                    continue
                refs = edge.get("evidenceRefs")
                if isinstance(edge.get("evidence_refs"), list):
                    refs = edge["evidence_refs"]
                base = f"{display_key}[{index}].evidenceRefs"
                if not isinstance(refs, list) or not refs:
                    findings.append({"finding": "missing_evidence_refs", "path": base})
                    continue
                for ref_index, ref in enumerate(refs):
                    if not isinstance(ref, str) or ref not in allowed_refs:
                        findings.append(
                            {
                                "finding": "non_canonical_ref",
                                "path": f"{base}[{ref_index}]",
                                "value": _clip(ref),
                            }
                        )
    graph = result.get("candidateGraph") if isinstance(result.get("candidateGraph"), Mapping) else (
        result.get("candidate_graph") if isinstance(result.get("candidate_graph"), Mapping) else None
    )
    if graph is not None:
        _edge_findings(graph, "candidateGraph.edges")
    for key in _COUNTER_REF_KEYS:
        items = result.get(key) if isinstance(result.get(key), list) else None
        if items is None:
            continue
        for index, item in enumerate(items):
            base = f"counterEvidenceRefs[{index}].evidenceRef"
            if not isinstance(item, Mapping):
                findings.append(
                    {"finding": "non_canonical_counter_ref", "path": base, "value": _clip(item)}
                )
                continue
            evidence_ref = item.get("evidenceRef")
            if not isinstance(evidence_ref, str) or evidence_ref not in allowed_refs:
                findings.append(
                    {
                        "finding": "non_canonical_counter_ref",
                        "path": base,
                        "value": _clip(evidence_ref),
                    }
                )
    return findings


def evidence_field_findings(errors: Sequence[str]) -> list[dict[str, Any]]:
    """Render path-based Challenge v2 evidence-card contract errors."""
    findings: list[dict[str, Any]] = []
    for error in errors:
        text = _clean(error)
        if not text:
            continue
        match = _LEADING_PATH_PATTERN.match(text)
        findings.append(
            {
                "finding": "evidence_field_contract_violation",
                "path": match.group("path") if match else "",
                "detail": _clip(text, 400),
            }
        )
    return findings


_RELATION_REFS_INSTRUCTION = (
    "关系图 evidenceRefs/counterEvidenceRefs 引用了不属于 allowedEvidenceRefs "
    "的 canonical claimEvidenceId。请读取最新 source_collection_context_tool："
    "上下文会带本契约（writebackRemediation）与 allowedEvidenceRefs；"
    "把 findings[] 里每个 path 上的违规 value 替换为 allowedEvidenceRefs 中的"
    "某个 claimEvidenceId（逐字复制，禁止改写或拼接）。没有可绑定的 canonical "
    "证据时不得伪造引用：把对应边删掉或写 status=blocked 附真实原因。"
    "这是同类违规唯一一次系统修正机会：再次违规将按契约直接拒绝。"
)

_RELATION_MISSING_FIELDS_INSTRUCTION = (
    "关系图缺少或损坏必需集合（见 findings[].path）。请补全后重新回写 completed："
    "edges 必须是对象数组且每条边绑定 canonical evidenceRefs；"
    "evidenceGaps[] 每项含 id、description、neededEvidence、blocksConclusion；"
    "counterEvidenceRefs[] 每项含 evidenceRef、claim、disposition，"
    "evidenceRef 必须是 allowedEvidenceRefs 中的 canonical claimEvidenceId。"
    "没有真实反证时写 counterEvidenceRefs=[] 并回写 status=blocked 附真实原因，"
    "不得伪造。这是同类违规唯一一次系统修正机会：再次违规将按契约直接拒绝。"
)

_EVIDENCE_FIELDS_INSTRUCTION = (
    "Challenge v2 证据卡字段校验失败（findings[] 带具体 path 与 detail）。"
    "请按每条 finding 的 path 补全或修正对应条目字段后重新回写 completed："
    "title、source_type、source_url、retrieved_at、fact、relation、"
    "verification_status 必须显式给出；source_type/relation/verification_status "
    "只能取契约枚举值；source_url 必须是 https URL，retrieved_at 必须是带时区的"
    " RFC3339 时间；每条嵌套 claims[]/keyFindings[] 项必须自带 fact。"
    "这是同类违规唯一一次系统修正机会：再次违规将按契约直接拒绝。"
)

_KIND_INSTRUCTIONS = {
    WRITEBACK_REMEDIATION_KIND_RELATION_REFS: _RELATION_REFS_INSTRUCTION,
    WRITEBACK_REMEDIATION_KIND_RELATION_MISSING_FIELDS: _RELATION_MISSING_FIELDS_INSTRUCTION,
    WRITEBACK_REMEDIATION_KIND_EVIDENCE_FIELDS: _EVIDENCE_FIELDS_INSTRUCTION,
}


def build_writeback_remediation_contract(
    kind: str,
    findings: Sequence[Mapping[str, Any]],
    *,
    recorded_at: str,
    attempt: int = 1,
) -> dict[str, Any]:
    """Render the structured one-shot remediation payload.

    Mirrors ``build_quote_anchor_remediation``: bounded findings, an explicit
    instruction, the attempt counter and the one-shot exhaustion flag.  A
    second rejection of the same kind flips ``exhausted`` to true and the
    context stops injecting the contract — the loop is bounded by construction.
    """
    normalized_kind = _clean(kind)
    rendered: list[dict[str, Any]] = []
    for finding in list(findings)[:_REMEDIATION_FINDING_LIMIT]:
        item = {
            "finding": _clean(finding.get("finding")),
            "path": _clean(finding.get("path")),
        }
        if finding.get("value") not in (None, ""):
            item["value"] = _clip(finding.get("value"))
        if finding.get("detail") not in (None, ""):
            item["detail"] = _clip(finding.get("detail"), 400)
        rendered.append({key: value for key, value in item.items() if value != ""})
    return {
        "schemaVersion": WRITEBACK_REMEDIATION_SCHEMA_VERSION,
        "kind": normalized_kind,
        "findings": rendered,
        "instruction": _KIND_INSTRUCTIONS.get(normalized_kind, ""),
        "attempt": max(1, int(attempt or 1)),
        "recordedAt": _clean(recorded_at),
        "exhausted": False,
    }


def next_writeback_remediation_attempt(
    prior_contract: Mapping[str, Any] | None,
    kind: str,
) -> tuple[int, bool]:
    """Return ``(attempt, exhausted)`` for a new rejection of ``kind``.

    First rejection: attempt 1, not exhausted.  A rejection of the same kind
    while an unexhausted contract exists is the second one-shot attempt —
    the contract flips to exhausted.  Once exhausted it stays exhausted; a
    different kind replaces the contract with a fresh attempt 1.
    """
    if not isinstance(prior_contract, Mapping) or not prior_contract:
        return 1, False
    if _clean(prior_contract.get("kind")) != _clean(kind):
        return 1, False
    prior_attempt = int(prior_contract.get("attempt") or 1)
    return prior_attempt + 1, True


def active_writeback_remediation(task: Mapping[str, Any]) -> dict[str, Any]:
    """Return the task's unexhausted remediation contract, or ``{}``."""
    contract = task.get("writebackRemediationContract") if isinstance(task, Mapping) else None
    if not isinstance(contract, dict) or not contract or bool(contract.get("exhausted")):
        return {}
    return contract


def _allowed_refs_hint(
    allowed_refs: Sequence[str],
    evidence_context: Mapping[str, str] | None = None,
) -> str:
    refs = [_clean(ref) for ref in allowed_refs if _clean(ref)]
    if not refs:
        return (
            "allowedEvidenceRefs 为空：本轮没有 canonical 证据卡，任何 evidenceRef 都不合法；"
            "不要伪造引用，写 status=blocked 附真实原因。"
        )
    context = evidence_context if isinstance(evidence_context, Mapping) else {}

    def _render(ref: str) -> str:
        # Optional candidate pairing (same authority as
        # ``load_relation_evidence_context``): ``ce-*(cand-*)`` lets the agent
        # bind a ref to the candidate it came from without a re-read.
        candidate = _clean(context.get(ref))
        return f"{ref}({candidate})" if candidate else ref

    shown = sorted(refs[:_ALLOWED_REFS_HINT_LIMIT])
    clipped = len(refs) > len(shown)
    clip_note = f"（共 {len(refs)} 个，仅展示前 {len(shown)} 个）" if clipped else ""
    full_note = (
        "；全量清单见 source_collection_context_tool 的 allowedEvidenceRefs / relationEvidence"
        if clipped
        else ""
    )
    return f"allowedEvidenceRefs 允许的 canonical 引用={[_render(ref) for ref in shown]}{clip_note}{full_note}"


def _violations_hint(findings: Sequence[Mapping[str, Any]]) -> str:
    rendered: list[str] = []
    for finding in list(findings)[:_ALLOWED_REFS_HINT_LIMIT]:
        path = _clean(finding.get("path"))
        value = _clean(finding.get("value"))
        kind = _clean(finding.get("finding"))
        if path and value:
            rendered.append(f"{path}={value}")
        elif path:
            rendered.append(f"{path}（{kind}）")
        else:
            rendered.append(kind)
    if not rendered:
        return "本次提交里未反查出违规值，请对照允许清单逐条核对你的 evidenceRefs"
    return "本次违规值=" + "; ".join(rendered)


def writeback_remediation_hint_block(
    kind: str,
    findings: Sequence[Mapping[str, Any]],
    allowed_refs: Sequence[str],
    evidence_context: Mapping[str, str] | None = None,
) -> str:
    """Render the appended in-line remediation block for a rejection message.

    Graceful degradation: with no extractable findings the block still shows
    the allowed list; with neither, it says so instead of guessing.
    """
    if _clean(kind) == WRITEBACK_REMEDIATION_KIND_RELATION_MISSING_FIELDS:
        missing = [_clean(item.get("path")) for item in findings if _clean(item.get("path"))]
        missing_note = (
            "缺失/损坏的必需集合=" + ", ".join(missing)
            if missing
            else "存在缺失或损坏的必需集合（见异常信息）"
        )
        refs = [_clean(ref) for ref in allowed_refs if _clean(ref)]
        # Inline the allowed list only when it actually loaded: an empty list
        # may mean "load failed" and the misleading "refs 为空" wording must
        # not leak into a missing-fields hint (shape/missing classes share it).
        refs_note = f"；{_allowed_refs_hint(refs, evidence_context)}" if refs else ""
        return (
            f" 补救提示: {missing_note}{refs_note}；"
            "下一次读取 source_collection_context_tool 会带 writebackRemediation "
            "精确补救指令，按其 findings 修正后重新回写；同类违规只有一次系统修正机会。"
        )
    return (
        f" 补救提示: {_allowed_refs_hint(allowed_refs, evidence_context)}；{_violations_hint(findings)}；"
        "下一次读取 source_collection_context_tool 会带 writebackRemediation "
        "精确补救指令，按其 findings 修正后重新回写；同类违规只有一次系统修正机会。"
    )
