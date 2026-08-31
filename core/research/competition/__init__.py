"""Tracked, fail-closed Challenge Cup competition contracts."""

from .calibration_records import (
    AUTO_DECISIONS,
    BUNDLE_STATUSES,
    BUNDLE_STATUS_COMPLETE,
    BUNDLE_STATUS_PENDING,
    CalibrationRecordError,
    G12CalibrationBundle,
    G12JudgementRecord,
    HUMAN_DECISIONS,
    g12_calibration_bundle_hash,
)
from .resources import (
    CATALOG_ID,
    CATALOG_SHA256,
    CORE_BEHAVIOR_HASH,
    CORE_POLICY_HASH,
    CompetitionResourceError,
    load_competition_program_core,
    load_full_catalog_execution_core,
    load_legacy_representative_cases,
    load_science_question_catalog,
)
from .stage_one_completion_policy import (
    StageOneCompletionPolicy,
    StageOneCompletionPolicyError,
    load_stage_one_completion_policy,
    require_current_stage_one_policy_snapshot,
    stage_one_policy_snapshot_for,
)

__all__ = [
    "AUTO_DECISIONS",
    "BUNDLE_STATUSES",
    "BUNDLE_STATUS_COMPLETE",
    "BUNDLE_STATUS_PENDING",
    "CATALOG_ID",
    "CATALOG_SHA256",
    "CORE_BEHAVIOR_HASH",
    "CORE_POLICY_HASH",
    "CalibrationRecordError",
    "CompetitionResourceError",
    "G12CalibrationBundle",
    "G12JudgementRecord",
    "HUMAN_DECISIONS",
    "StageOneCompletionPolicy",
    "StageOneCompletionPolicyError",
    "g12_calibration_bundle_hash",
    "load_competition_program_core",
    "load_full_catalog_execution_core",
    "load_legacy_representative_cases",
    "load_science_question_catalog",
    "load_stage_one_completion_policy",
    "require_current_stage_one_policy_snapshot",
    "stage_one_policy_snapshot_for",
]
