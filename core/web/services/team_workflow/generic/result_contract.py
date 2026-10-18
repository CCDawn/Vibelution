"""Bounded business-result validation after canonical native Turn completion."""
from __future__ import annotations

import json
import re


_PROBLEM_CODE = re.compile(r"[A-Za-z0-9_.:-]{1,80}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate result field")
        value[key] = item
    return value


def evaluate_result(contract: str, content: str) -> dict:
    """Validate an opt-in outcome without storing or interpreting its contents.

    The caller owns native success, exact assistant Turn selection and text
    availability. Legacy text results therefore retain their existing success.
    """
    if contract == "text":
        return {"succeeded": True, "failureCode": "", "evidenceRefs": []}

    invalid = {"succeeded": False, "failureCode": "business_result_invalid", "evidenceRefs": []}
    if contract != "outcome_v1" or not isinstance(content, str) or len(content) > 12_000:
        return invalid
    try:
        value = json.loads(content, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError):
        return invalid
    if not isinstance(value, dict) or set(value) - {"taskStatus", "problemCode", "evidenceRefs"}:
        return invalid

    task_status = value.get("taskStatus")
    evidence = value.get("evidenceRefs")
    if task_status not in ("succeeded", "failed") or not isinstance(evidence, list) or not 1 <= len(evidence) <= 20:
        return invalid
    if any(not isinstance(ref, str) or not ref.strip() or len(ref) > 500 for ref in evidence):
        return invalid

    problem_code = value.get("problemCode", "")
    if not isinstance(problem_code, str):
        return invalid
    if task_status == "succeeded":
        if problem_code:
            return invalid
    elif _PROBLEM_CODE.fullmatch(problem_code) is None:
        return invalid
    return {"succeeded": task_status == "succeeded", "failureCode": problem_code, "evidenceRefs": evidence}
