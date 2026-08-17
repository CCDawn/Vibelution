"""Shared DEV-fixture helpers for Challenge Cup experiment adapters.

These helpers never start a process, GPU kernel, network fetch or training run.
Real-device and full-run contracts return ``unavailable`` instead of inventing
performance numbers or scientific conclusions.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .protocol import AdapterContractError, ExperimentContract, phase_result
from ..workflow.contracts import ResearchScopeEnvelope

AUTHORIZED_DEV_MODES = frozenset({"dev_fixture", "smoke", "offline"})
UNAUTHORIZED_RUN_MODES = frozenset({"full", "benchmark", "live", "real"})


def contract_mapping(contract: ExperimentContract) -> dict[str, Any]:
    payload = contract.to_dict()
    return payload if isinstance(payload, dict) else {}


def method_config(contract: ExperimentContract) -> dict[str, Any]:
    raw = contract_mapping(contract).get("methodConfig")
    return dict(raw) if isinstance(raw, Mapping) else {}


def run_mode(contract: ExperimentContract) -> str:
    config = method_config(contract)
    raw = str(config.get("runMode") or "dev_fixture").strip().lower()
    if not raw:
        raise AdapterContractError("runMode must be a non-empty string.")
    return raw


def scope_mismatch(scope: ResearchScopeEnvelope, *, question: str, theme: str, campaign: str) -> dict[str, Any] | None:
    mismatches = []
    if scope.question != question:
        mismatches.append(f"question:{scope.question}")
    if scope.theme != theme:
        mismatches.append(f"theme:{scope.theme}")
    if scope.campaign != campaign:
        mismatches.append(f"campaign:{scope.campaign}")
    if not mismatches:
        return None
    return phase_result(
        "failed",
        reason="scope_mismatch",
        mismatches=mismatches,
        expected={"question": question, "theme": theme, "campaign": campaign},
    )


def unauthorized_real_run(contract: ExperimentContract, *, extra_flags: tuple[str, ...] = ()) -> dict[str, Any] | None:
    config = method_config(contract)
    mode = run_mode(contract)
    if mode in UNAUTHORIZED_RUN_MODES:
        return phase_result(
            "unavailable",
            reason="research_authorization_required",
            runMode=mode,
        )
    for flag in extra_flags:
        if bool(config.get(flag)):
            return phase_result(
                "unavailable",
                reason="research_authorization_required",
                flag=flag,
            )
    if mode not in AUTHORIZED_DEV_MODES:
        return phase_result("failed", reason="unsupported_run_mode", runMode=mode)
    return None
