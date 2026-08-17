"""Tracked, fail-closed Challenge Cup competition contracts."""

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

__all__ = [
    "CATALOG_ID",
    "CATALOG_SHA256",
    "CORE_BEHAVIOR_HASH",
    "CORE_POLICY_HASH",
    "CompetitionResourceError",
    "load_competition_program_core",
    "load_full_catalog_execution_core",
    "load_legacy_representative_cases",
    "load_science_question_catalog",
]
