"""Canonical tracked resources for the Challenge Cup AI Scientist program.

These resources intentionally live below ``core/research``.  Product runtime
must not depend on the ignored, operator-private ``/挑战杯`` junction.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any


CATALOG_ID = "science-125-questions-2021"
CATALOG_QUESTION_COUNT = 125
CATALOG_SHA256 = "D5035032F80574B9521CC9CC8D73F127721CCADF54451411004323727D2FAAB9"
CORE_BEHAVIOR_HASH = "C3965023488C76DF032130341347915E5EAD5451EE53C2501E75914205EB423A"
CORE_POLICY_HASH = "D3A8FB5B97D1A4ECAF08798D4CFB283AC56A2563EA434C28EC988D15827EB83E"
QUESTION_MIGRATION_MODE = "dual_version_reader_append_only_no_auto_promotion"

_RESOURCE_ROOT = Path(__file__).resolve().parent / "data"
PROGRAM_RESOURCE_PATH = _RESOURCE_ROOT / "competition_program_core.v2.json"
FULL_CATALOG_POLICY_PATH = _RESOURCE_ROOT / "full_catalog_execution_core.v1.json"
QUESTION_CATALOG_PATH = _RESOURCE_ROOT / "science_125_questions.json"
LEGACY_CASE_REGISTRY_PATH = _RESOURCE_ROOT / "legacy_representative_deep_cases.v1.json"

_RESOURCE_SHA256 = {
    PROGRAM_RESOURCE_PATH.name: "06EFC4B363BC597D5FB75CE7C59D9AD3F61214AA044AA2456589C101D061CB36",
    FULL_CATALOG_POLICY_PATH.name: "DEE03F4E40AD361A6727692F0EC44B79C2635EC0A55C941AE7C47B83D97FA28E",
    QUESTION_CATALOG_PATH.name: CATALOG_SHA256,
    LEGACY_CASE_REGISTRY_PATH.name: "9C852B3D6C990A471E7B0F0083508CD43379CC27E9A5DCB5B261138F138CDE28",
}


class CompetitionResourceError(ValueError):
    """A tracked competition resource is missing, malformed, or has drifted."""


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CompetitionResourceError(f"{field} must be an object.")
    return value


def _read_resource(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CompetitionResourceError(f"Required competition resource is unavailable: {path.name}.") from exc
    expected = _RESOURCE_SHA256[path.name]
    actual = hashlib.sha256(raw).hexdigest().upper()
    if actual != expected:
        raise CompetitionResourceError(
            f"Competition resource hash drift for {path.name}: expected {expected}, got {actual}."
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompetitionResourceError(f"Competition resource is not valid UTF-8 JSON: {path.name}.") from exc
    return _mapping(value, field=path.name)


def validate_question_catalog(value: dict[str, Any]) -> dict[str, Any]:
    catalog = _mapping(value, field="catalog")
    if catalog.get("catalog_id") != CATALOG_ID:
        raise CompetitionResourceError("Question catalog id does not match the frozen contract.")
    questions = catalog.get("questions")
    if not isinstance(questions, list):
        raise CompetitionResourceError("Question catalog questions must be an array.")
    if catalog.get("question_count") != CATALOG_QUESTION_COUNT or len(questions) != CATALOG_QUESTION_COUNT:
        raise CompetitionResourceError("Question catalog must contain exactly 125 questions.")
    expected_ids = [f"SCI-{index:03d}" for index in range(1, CATALOG_QUESTION_COUNT + 1)]
    ids = [str(item.get("id") or "") for item in questions if isinstance(item, dict)]
    if ids != expected_ids or len(set(ids)) != CATALOG_QUESTION_COUNT:
        raise CompetitionResourceError("Question catalog ids must be unique and ordered from SCI-001 through SCI-125.")
    domains = [str(item.get("domain") or "") for item in questions if isinstance(item, dict)]
    if any(not str(item.get("question_en") or "").strip() for item in questions if isinstance(item, dict)):
        raise CompetitionResourceError("Every catalog question requires source-of-truth English text.")
    declared_counts = catalog.get("domain_counts")
    if not isinstance(declared_counts, dict) or sum(int(count) for count in declared_counts.values()) != CATALOG_QUESTION_COUNT:
        raise CompetitionResourceError("Question catalog domain counts must sum to 125.")
    actual_counts = {domain: domains.count(domain) for domain in set(domains)}
    if actual_counts != {str(domain): int(count) for domain, count in declared_counts.items()}:
        raise CompetitionResourceError("Question catalog domain counts do not match question records.")
    return deepcopy(catalog)


def validate_competition_program_core(value: dict[str, Any]) -> dict[str, Any]:
    program = _mapping(value, field="competition_program_core")
    if program.get("schemaVersion") != "2.2.0" or program.get("contractVersion") != "2.2.0":
        raise CompetitionResourceError("Competition Program contract version must be 2.2.0.")
    if program.get("status") != "core_frozen":
        raise CompetitionResourceError("Competition Program core must be frozen before runtime use.")
    freeze = _mapping(_mapping(program.get("freezeLayers"), field="freezeLayers").get("programCore"), field="programCore")
    if freeze.get("status") != "frozen" or freeze.get("coreBehaviorHash") != CORE_BEHAVIOR_HASH:
        raise CompetitionResourceError("Competition Program core behavior hash does not match the frozen contract.")
    catalog = _mapping(program.get("catalogExecutionPolicy"), field="catalogExecutionPolicy")
    if catalog.get("catalogQuestionCount") != CATALOG_QUESTION_COUNT or catalog.get("fullCatalogResultSubmissionRequired") is not True:
        raise CompetitionResourceError("Competition Program must require all 125 standard results.")
    result_set = _mapping(program.get("fullCatalogResultSetContract"), field="fullCatalogResultSetContract")
    if result_set.get("questionCount") != CATALOG_QUESTION_COUNT or result_set.get("requiredApprovedQuestionCount") != CATALOG_QUESTION_COUNT:
        raise CompetitionResourceError("FullCatalogResultSet must require 125 approved results.")
    experiments = program.get("requiredDeepExperiments")
    if not isinstance(experiments, list) or [item.get("questionId") for item in experiments if isinstance(item, dict)] != ["SCI-091", "SCI-096"]:
        raise CompetitionResourceError("SCI-091 and SCI-096 must be the two required independent experiments.")
    if any(item.get("required") is not True for item in experiments if isinstance(item, dict)):
        raise CompetitionResourceError("Every declared deep experiment must be required.")
    if len({str(item.get("themeId")) for item in experiments}) != 2 or len({str(item.get("campaignId")) for item in experiments}) != 2:
        raise CompetitionResourceError("Required deep experiments must use independent themes and campaigns.")
    completion = _mapping(program.get("completionContract"), field="completionContract")
    if completion.get("programRule") != "full_catalog_result_set_approved AND all_required_deep_experiments_approved":
        raise CompetitionResourceError("Competition Program completion rule has drifted.")
    if completion.get("legacyQuestionCountsAffectCompletion") is not False or completion.get("legacyRepresentativeCaseCountsAffectCompletion") is not False:
        raise CompetitionResourceError("Legacy counts must never affect active completion.")
    return deepcopy(program)


def validate_full_catalog_execution_core(value: dict[str, Any]) -> dict[str, Any]:
    policy = _mapping(value, field="full_catalog_execution_core")
    if policy.get("version") != "1.2.0" or policy.get("status") != "core_frozen_submission_projection_pending":
        raise CompetitionResourceError("Full Catalog policy version/status does not match the frozen core.")
    freeze = _mapping(_mapping(policy.get("freezeLayers"), field="freezeLayers").get("programAndQuestionCore"), field="programAndQuestionCore")
    if freeze.get("status") != "frozen" or freeze.get("corePolicyHash") != CORE_POLICY_HASH:
        raise CompetitionResourceError("Full Catalog core policy hash does not match the frozen contract.")
    catalog = _mapping(policy.get("catalog"), field="catalog")
    if catalog.get("catalogId") != CATALOG_ID or catalog.get("questionCount") != CATALOG_QUESTION_COUNT or catalog.get("sha256") != CATALOG_SHA256:
        raise CompetitionResourceError("Full Catalog source identity does not match the tracked 125-question catalog.")
    schema = _mapping(policy.get("currentQuestionSchema"), field="currentQuestionSchema")
    if schema.get("version") != 1 or schema.get("targetVersion") != 2 or schema.get("migrationMode") != QUESTION_MIGRATION_MODE:
        raise CompetitionResourceError("Question v1-to-v2 migration policy has drifted.")
    groups = policy.get("questionSchemaV2RequiredGroups")
    if not isinstance(groups, list) or len(groups) != 17 or len(set(str(item) for item in groups)) != 17:
        raise CompetitionResourceError("Question v2 must retain all 17 frozen field groups.")
    return deepcopy(policy)


def load_competition_program_core() -> dict[str, Any]:
    return validate_competition_program_core(_read_resource(PROGRAM_RESOURCE_PATH))


def load_full_catalog_execution_core() -> dict[str, Any]:
    return validate_full_catalog_execution_core(_read_resource(FULL_CATALOG_POLICY_PATH))


def load_science_question_catalog() -> dict[str, Any]:
    return validate_question_catalog(_read_resource(QUESTION_CATALOG_PATH))


def load_legacy_representative_cases() -> dict[str, Any]:
    registry = _read_resource(LEGACY_CASE_REGISTRY_PATH)
    if registry.get("schemaVersion") != 1 or registry.get("registryKind") != "challenge_program_representative_cases":
        raise CompetitionResourceError("Legacy representative case registry is malformed.")
    if not isinstance(registry.get("cases"), list):
        raise CompetitionResourceError("Legacy representative case registry requires a cases array.")
    return deepcopy(registry)
