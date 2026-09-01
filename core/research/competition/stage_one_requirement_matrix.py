"""Official direction-1A requirement tracking matrix (challenge contract §2.5).

Every official requirement row carries a ``deliveryClass`` (one of the four
§2.5 delivery boundaries), a ``coverageStatus``, canonical ``evidenceRefs``
and a ``deferredOwner``.  Unmet ``G1_REQUIRED`` rows block stage-one G1; every
other delivery class stays ``not_yet_evidenced`` until real evidence exists
and is never silently promoted to submission ready.  The matrix never scores
or predicts official results.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

STAGE_ONE_REQUIREMENT_MATRIX_KIND = "challenge_cup_stage_one_requirement_matrix"
STAGE_ONE_REQUIREMENT_MATRIX_SCHEMA_VERSION = 1

# §2.5 delivery boundaries.
DELIVERY_CLASS_G1_REQUIRED = "G1_REQUIRED"
DELIVERY_CLASS_STAGE1_SCALE_OUT = "STAGE1_SCALE_OUT"
DELIVERY_CLASS_SUBMISSION_PACKAGE = "SUBMISSION_PACKAGE"
DELIVERY_CLASS_PHASE2_USER = "PHASE2_USER"
DELIVERY_CLASSES = (
    DELIVERY_CLASS_G1_REQUIRED,
    DELIVERY_CLASS_STAGE1_SCALE_OUT,
    DELIVERY_CLASS_SUBMISSION_PACKAGE,
    DELIVERY_CLASS_PHASE2_USER,
)

# Coverage is evidence-backed only; there is no partial or predicted state.
COVERAGE_EVIDENCED = "evidenced"
COVERAGE_NOT_YET_EVIDENCED = "not_yet_evidenced"
COVERAGE_STATUSES = (COVERAGE_EVIDENCED, COVERAGE_NOT_YET_EVIDENCED)

# Deferred owners for rows outside the current single-question G1 scope.
DEFERRED_OWNER_SCALE_OUT = "direction1a_scale_out"
DEFERRED_OWNER_SUBMISSION_PACKAGE = "direction1a_submission_package"
DEFERRED_OWNER_PHASE2_USER = "user_phase_two_nodes_8_17"

# Requirement row identities.
REQUIREMENT_CORE_HYPOTHESIS = "official_core_hypothesis_novelty_coherence"
REQUIREMENT_PLAN_EXECUTABILITY = "official_plan_executability_six_facets"
REQUIREMENT_TWO_ROUND_REVISION = "official_two_round_revision"
REQUIREMENT_SCALE_OUT = "official_scale_out_125_questions"
REQUIREMENT_TECH_DEPTH = "official_technical_depth_multimodal"
REQUIREMENT_APPLICATION = "official_application_evidence"
REQUIREMENT_SUBMISSION_MATERIALS = "official_submission_materials"
REQUIREMENT_PHASE2_EXPERIMENTS = "official_phase2_experiments"

_ITEM_FIELDS = (
    "requirementId",
    "requirement",
    "officialDimension",
    "officialScoringPoints",
    "deliveryClass",
    "coverageStatus",
    "evidenceRefs",
    "deferredOwner",
)
_TOP_LEVEL_FIELDS = (
    "schemaVersion",
    "matrixKind",
    "scopeId",
    "items",
    "direction1ASubmissionReady",
)


class StageOneRequirementMatrixError(ValueError):
    """The official requirement matrix payload is invalid or drifted."""


@dataclass(frozen=True, slots=True)
class StageOneRequirementItem:
    requirementId: str
    requirement: str
    officialDimension: str
    officialScoringPoints: tuple[str, ...]
    deliveryClass: str
    coverageStatus: str
    evidenceRefs: tuple[str, ...]
    deferredOwner: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirementId": self.requirementId,
            "requirement": self.requirement,
            "officialDimension": self.officialDimension,
            "officialScoringPoints": list(self.officialScoringPoints),
            "deliveryClass": self.deliveryClass,
            "coverageStatus": self.coverageStatus,
            "evidenceRefs": list(self.evidenceRefs),
            "deferredOwner": self.deferredOwner,
        }

    @classmethod
    def _template(
        cls,
        *,
        requirement_id: str,
        requirement: str,
        official_dimension: str,
        official_scoring_points: tuple[str, ...],
        delivery_class: str,
        deferred_owner: str,
    ) -> StageOneRequirementItem:
        return cls(
            requirementId=requirement_id,
            requirement=requirement,
            officialDimension=official_dimension,
            officialScoringPoints=official_scoring_points,
            deliveryClass=delivery_class,
            coverageStatus=COVERAGE_NOT_YET_EVIDENCED,
            evidenceRefs=(),
            deferredOwner=deferred_owner,
        )


# §2.5 table, row by row.  ``officialDimension`` is empty for submission
# requirements that are not tied to one of the three official dimensions;
# ``officialScoringPoints`` partitions the seven official scoring points.
_STAGE_ONE_REQUIREMENT_TEMPLATES: tuple[StageOneRequirementItem, ...] = (
    StageOneRequirementItem._template(
        requirement_id=REQUIREMENT_CORE_HYPOTHESIS,
        requirement="核心假设创新性与自洽性",
        official_dimension="科学价值",
        official_scoring_points=("核心假设创新性与自洽性",),
        delivery_class=DELIVERY_CLASS_G1_REQUIRED,
        deferred_owner="",
    ),
    StageOneRequirementItem._template(
        requirement_id=REQUIREMENT_PLAN_EXECUTABILITY,
        requirement="方案可落地验证性、六个参考评价面与研究计划可执行性",
        official_dimension="科学价值",
        official_scoring_points=("方案可落地验证性",),
        delivery_class=DELIVERY_CLASS_G1_REQUIRED,
        deferred_owner="",
    ),
    StageOneRequirementItem._template(
        requirement_id=REQUIREMENT_TWO_ROUND_REVISION,
        requirement="两轮生成—评价—修订过程",
        official_dimension="",
        official_scoring_points=(),
        delivery_class=DELIVERY_CLASS_G1_REQUIRED,
        deferred_owner="",
    ),
    StageOneRequirementItem._template(
        requirement_id=REQUIREMENT_SCALE_OUT,
        requirement="125 题结果文档与规模化稳定性",
        official_dimension="",
        official_scoring_points=(),
        delivery_class=DELIVERY_CLASS_STAGE1_SCALE_OUT,
        deferred_owner=DEFERRED_OWNER_SCALE_OUT,
    ),
    StageOneRequirementItem._template(
        requirement_id=REQUIREMENT_TECH_DEPTH,
        requirement="超级智能体/多智能体、上下文工程、Qwen 调用与多模态处理成效",
        official_dimension="技术深度",
        official_scoring_points=(
            "超级智能体或多智能体协作设计",
            "多模态大模型处理科学模态数据的成效",
        ),
        delivery_class=DELIVERY_CLASS_SUBMISSION_PACKAGE,
        deferred_owner=DEFERRED_OWNER_SUBMISSION_PACKAGE,
    ),
    StageOneRequirementItem._template(
        requirement_id=REQUIREMENT_APPLICATION,
        requirement="实际场景支撑、论文/专利转化潜力",
        official_dimension="应用潜力",
        official_scoring_points=(
            "实际场景问题支撑能力",
            "论文/专利成果转化潜力",
        ),
        delivery_class=DELIVERY_CLASS_SUBMISSION_PACKAGE,
        deferred_owner=DEFERRED_OWNER_SUBMISSION_PACKAGE,
    ),
    StageOneRequirementItem._template(
        requirement_id=REQUIREMENT_SUBMISSION_MATERIALS,
        requirement="≤20 页 PDF、核心源码、可调用测试 API、交互前端和复现材料",
        official_dimension="应用潜力",
        official_scoring_points=("代码与结果可复现性",),
        delivery_class=DELIVERY_CLASS_SUBMISSION_PACKAGE,
        deferred_owner=DEFERRED_OWNER_SUBMISSION_PACKAGE,
    ),
    StageOneRequirementItem._template(
        requirement_id=REQUIREMENT_PHASE2_EXPERIMENTS,
        requirement="对照/消融、科学实验、数据采集、结果评价与失败边界实证",
        official_dimension="",
        official_scoring_points=(),
        delivery_class=DELIVERY_CLASS_PHASE2_USER,
        deferred_owner=DEFERRED_OWNER_PHASE2_USER,
    ),
)

# Canonical artifact kinds that may evidence each G1_REQUIRED row inside the
# current single-question stage-one scope.  Anything outside this mapping has
# no stage-one evidence authority.
G1_REQUIRED_EVIDENCE_KINDS: Mapping[str, tuple[str, ...]] = {
    REQUIREMENT_CORE_HYPOTHESIS: (
        "hypothesis_set",
        "core_hypothesis_coherence",
        "dimension_reviews",
    ),
    REQUIREMENT_PLAN_EXECUTABILITY: ("stage1_research_plan",),
    REQUIREMENT_TWO_ROUND_REVISION: (
        "feedback_iterations",
        "review_independence",
        "review_disagreement",
    ),
}


def stage_one_requirement_rows() -> tuple[StageOneRequirementItem, ...]:
    """Return the static §2.5 rows without any coverage evaluation."""

    return tuple(
        StageOneRequirementItem(
            requirementId=row.requirementId,
            requirement=row.requirement,
            officialDimension=row.officialDimension,
            officialScoringPoints=row.officialScoringPoints,
            deliveryClass=row.deliveryClass,
            coverageStatus=row.coverageStatus,
            evidenceRefs=row.evidenceRefs,
            deferredOwner=row.deferredOwner,
        )
        for row in _STAGE_ONE_REQUIREMENT_TEMPLATES
    )


def _template_by_id(requirement_id: str) -> StageOneRequirementItem:
    for row in _STAGE_ONE_REQUIREMENT_TEMPLATES:
        if row.requirementId == requirement_id:
            return row
    raise StageOneRequirementMatrixError(
        f"unknown stage-one requirement id: {requirement_id}"
    )


def evaluate_stage_one_requirement_matrix(
    evidence: Mapping[str, Sequence[str]] | None = None,
) -> tuple[StageOneRequirementItem, ...]:
    """Resolve §2.5 rows against the provided stage-one evidence refs.

    ``evidence`` maps a ``G1_REQUIRED`` requirement id to canonical artifact
    refs produced inside this stage.  Rows outside ``G1_REQUIRED`` have no
    stage-one evidence authority: fabricating refs for them raises instead of
    silently promoting scale-out, submission-package or phase-two work.
    """

    supplied = dict(evidence or {})
    unknown_keys = sorted(set(supplied) - set(G1_REQUIRED_EVIDENCE_KINDS))
    if unknown_keys:
        raise StageOneRequirementMatrixError(
            "unknown stage-one evidence keys: " + ", ".join(unknown_keys)
        )
    resolved: list[StageOneRequirementItem] = []
    for row in _STAGE_ONE_REQUIREMENT_TEMPLATES:
        refs: tuple[str, ...] = ()
        if row.requirementId in supplied:
            if row.deliveryClass != DELIVERY_CLASS_G1_REQUIRED:
                raise StageOneRequirementMatrixError(
                    "stage-one has no authority to evidence requirement: "
                    + row.requirementId
                )
            raw_refs = supplied[row.requirementId]
            if not isinstance(raw_refs, Sequence) or isinstance(raw_refs, str):
                raise StageOneRequirementMatrixError(
                    f"evidence refs must be a sequence for {row.requirementId}"
                )
            cleaned = tuple(str(ref or "").strip() for ref in raw_refs)
            if not cleaned or any(not ref for ref in cleaned):
                raise StageOneRequirementMatrixError(
                    f"evidence refs must be non-empty for {row.requirementId}"
                )
            refs = cleaned
        resolved.append(
            StageOneRequirementItem(
                requirementId=row.requirementId,
                requirement=row.requirement,
                officialDimension=row.officialDimension,
                officialScoringPoints=row.officialScoringPoints,
                deliveryClass=row.deliveryClass,
                coverageStatus=(
                    COVERAGE_EVIDENCED if refs else COVERAGE_NOT_YET_EVIDENCED
                ),
                evidenceRefs=refs,
                deferredOwner=row.deferredOwner,
            )
        )
    return tuple(resolved)


def direction_1a_submission_ready(
    items: Sequence[StageOneRequirementItem],
) -> bool:
    """True only when every §2.5 row across all delivery classes is evidenced."""

    if not items:
        return False
    return all(
        item.coverageStatus == COVERAGE_EVIDENCED and item.evidenceRefs
        for item in items
    )


def unmet_g1_required(items: Sequence[StageOneRequirementItem]) -> tuple[str, ...]:
    """Requirement ids of ``G1_REQUIRED`` rows that still block stage-one G1."""

    return tuple(
        item.requirementId
        for item in items
        if item.deliveryClass == DELIVERY_CLASS_G1_REQUIRED
        and (
            item.coverageStatus != COVERAGE_EVIDENCED or not item.evidenceRefs
        )
    )


def not_yet_evidenced_ids(items: Sequence[StageOneRequirementItem]) -> tuple[str, ...]:
    return tuple(
        item.requirementId
        for item in items
        if item.coverageStatus != COVERAGE_EVIDENCED or not item.evidenceRefs
    )


def matrix_to_dict(
    items: Sequence[StageOneRequirementItem],
    *,
    scope_id: str,
) -> dict[str, Any]:
    scope = str(scope_id or "").strip()
    if not scope:
        raise StageOneRequirementMatrixError("scopeId must be non-empty text")
    materialized = tuple(items)
    if tuple(item.requirementId for item in materialized) != tuple(
        row.requirementId for row in _STAGE_ONE_REQUIREMENT_TEMPLATES
    ):
        raise StageOneRequirementMatrixError(
            "requirement matrix must contain every §2.5 row exactly once, in order"
        )
    return {
        "schemaVersion": STAGE_ONE_REQUIREMENT_MATRIX_SCHEMA_VERSION,
        "matrixKind": STAGE_ONE_REQUIREMENT_MATRIX_KIND,
        "scopeId": scope,
        "items": [item.to_dict() for item in materialized],
        "direction1ASubmissionReady": direction_1a_submission_ready(materialized),
    }


def requirement_matrix_from_dict(
    payload: Mapping[str, Any],
) -> tuple[StageOneRequirementItem, ...]:
    """Parse and fully validate a materialized matrix payload."""

    if not isinstance(payload, Mapping):
        raise StageOneRequirementMatrixError("requirement matrix must be an object")
    unknown = sorted(set(payload) - set(_TOP_LEVEL_FIELDS))
    missing = sorted(set(_TOP_LEVEL_FIELDS) - set(payload))
    if unknown:
        raise StageOneRequirementMatrixError(
            "requirement matrix contains unsupported fields: " + ", ".join(unknown)
        )
    if missing:
        raise StageOneRequirementMatrixError(
            "requirement matrix is missing fields: " + ", ".join(missing)
        )
    if payload.get("schemaVersion") != STAGE_ONE_REQUIREMENT_MATRIX_SCHEMA_VERSION:
        raise StageOneRequirementMatrixError("requirement matrix schema is unsupported")
    if payload.get("matrixKind") != STAGE_ONE_REQUIREMENT_MATRIX_KIND:
        raise StageOneRequirementMatrixError("requirement matrix kind is invalid")
    if not str(payload.get("scopeId") or "").strip():
        raise StageOneRequirementMatrixError("requirement matrix scopeId is required")

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise StageOneRequirementMatrixError("requirement matrix items must be a list")
    if len(raw_items) != len(_STAGE_ONE_REQUIREMENT_TEMPLATES):
        raise StageOneRequirementMatrixError(
            "requirement matrix must contain every §2.5 row exactly once"
        )
    items: list[StageOneRequirementItem] = []
    for raw_item, template in zip(raw_items, _STAGE_ONE_REQUIREMENT_TEMPLATES):
        if not isinstance(raw_item, Mapping):
            raise StageOneRequirementMatrixError("matrix item must be an object")
        unknown_item = sorted(set(raw_item) - set(_ITEM_FIELDS))
        missing_item = sorted(set(_ITEM_FIELDS) - set(raw_item))
        if unknown_item or missing_item:
            raise StageOneRequirementMatrixError(
                f"matrix item {template.requirementId} has unsupported or missing fields"
            )
        if str(raw_item.get("requirementId") or "") != template.requirementId:
            raise StageOneRequirementMatrixError("matrix row order drifted from §2.5")
        # Contract-fixed fields must match the §2.5 row exactly; only the
        # coverage status and its evidence refs are materialized state.
        for fixed_field in (
            "requirement",
            "officialDimension",
            "deliveryClass",
            "deferredOwner",
        ):
            if raw_item.get(fixed_field) != getattr(template, fixed_field):
                raise StageOneRequirementMatrixError(
                    f"matrix item {template.requirementId} drifted on {fixed_field}"
                )
        if tuple(raw_item.get("officialScoringPoints") or ()) != (
            template.officialScoringPoints
        ):
            raise StageOneRequirementMatrixError(
                f"matrix item {template.requirementId} drifted on officialScoringPoints"
            )
        status = str(raw_item.get("coverageStatus") or "")
        if status not in COVERAGE_STATUSES:
            raise StageOneRequirementMatrixError(
                f"matrix item {template.requirementId} has an unknown coverageStatus"
            )
        raw_refs = raw_item.get("evidenceRefs")
        if not isinstance(raw_refs, list) or any(
            not str(ref or "").strip() for ref in raw_refs
        ):
            raise StageOneRequirementMatrixError(
                f"matrix item {template.requirementId} evidenceRefs must be non-empty strings"
            )
        refs = tuple(str(ref) for ref in raw_refs)
        if (status == COVERAGE_EVIDENCED) != bool(refs):
            raise StageOneRequirementMatrixError(
                f"matrix item {template.requirementId} coverageStatus and evidenceRefs disagree"
            )
        items.append(
            StageOneRequirementItem(
                requirementId=template.requirementId,
                requirement=template.requirement,
                officialDimension=template.officialDimension,
                officialScoringPoints=template.officialScoringPoints,
                deliveryClass=template.deliveryClass,
                coverageStatus=status,
                evidenceRefs=refs,
                deferredOwner=template.deferredOwner,
            )
        )
    parsed = tuple(items)
    if bool(payload.get("direction1ASubmissionReady")) != direction_1a_submission_ready(
        parsed
    ):
        raise StageOneRequirementMatrixError(
            "requirement matrix aggregate disagrees with its items"
        )
    return parsed


__all__ = [
    "COVERAGE_EVIDENCED",
    "COVERAGE_NOT_YET_EVIDENCED",
    "COVERAGE_STATUSES",
    "DEFERRED_OWNER_PHASE2_USER",
    "DEFERRED_OWNER_SCALE_OUT",
    "DEFERRED_OWNER_SUBMISSION_PACKAGE",
    "DELIVERY_CLASSES",
    "DELIVERY_CLASS_G1_REQUIRED",
    "DELIVERY_CLASS_PHASE2_USER",
    "DELIVERY_CLASS_STAGE1_SCALE_OUT",
    "DELIVERY_CLASS_SUBMISSION_PACKAGE",
    "G1_REQUIRED_EVIDENCE_KINDS",
    "REQUIREMENT_APPLICATION",
    "REQUIREMENT_CORE_HYPOTHESIS",
    "REQUIREMENT_PHASE2_EXPERIMENTS",
    "REQUIREMENT_PLAN_EXECUTABILITY",
    "REQUIREMENT_SCALE_OUT",
    "REQUIREMENT_SUBMISSION_MATERIALS",
    "REQUIREMENT_TECH_DEPTH",
    "REQUIREMENT_TWO_ROUND_REVISION",
    "STAGE_ONE_REQUIREMENT_MATRIX_KIND",
    "STAGE_ONE_REQUIREMENT_MATRIX_SCHEMA_VERSION",
    "StageOneRequirementItem",
    "StageOneRequirementMatrixError",
    "direction_1a_submission_ready",
    "evaluate_stage_one_requirement_matrix",
    "matrix_to_dict",
    "not_yet_evidenced_ids",
    "requirement_matrix_from_dict",
    "stage_one_requirement_rows",
    "unmet_g1_required",
]
