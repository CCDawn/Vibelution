"""Check (or deploy) the approved auto-advance policy template.

The tracked template ``docs/ops/config/auto-advance-policy.active.json`` is the
governance authority, but the runtime never reads it: both readers resolve the
operator's deployed copy under ``<config-home>/auto-advance-policy.active.json``
(the executor config-first, the shadow evaluator through the environment).
Nothing links the two, and both readers fail *silent* — a stale deployed copy
simply disables automation, because the shadow evaluator records nothing and
the executor stops at the policy-load rung without an error a human would see.

That is not hypothetical: commit 3859bbc79 added the sixth capability switch to
the template (v2.0.0-approved.1 -> v2.1.0-approved.1) while the deployed copy
stayed behind, which silently disabled the whole automation chain until an
operator noticed days later.

Default mode is therefore a read-only check, so drift is visible before it
costs anything::

    python scripts/deploy_auto_advance_policy.py             # report drift
    python scripts/deploy_auto_advance_policy.py --json
    python scripts/deploy_auto_advance_policy.py --write     # deploy + backup

Exit codes: ``0`` in sync (or deployed), ``1`` drift or missing deployment,
``2`` the tracked template itself is missing or fails the activation contract.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

TEMPLATE_RELATIVE = Path("docs") / "ops" / "config" / "auto-advance-policy.active.json"

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_TEMPLATE_PROBLEM = 2


def template_path(project_root: Path | None = None) -> Path:
    """Path of the tracked governance template."""

    return (project_root or _PROJECT_ROOT) / TEMPLATE_RELATIVE


def deployed_path() -> Path:
    """Path of the operator's deployed copy (the runtime source)."""

    from config.paths import AUTO_ADVANCE_POLICY_FILENAME, resolve_config_home

    return resolve_config_home() / AUTO_ADVANCE_POLICY_FILENAME


def _read_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _identity(payload: dict[str, Any]) -> dict[str, Any]:
    approval = payload.get("approval")
    return {
        "policyId": payload.get("policyId"),
        "version": payload.get("version"),
        "status": payload.get("status"),
        "executionMode": payload.get("executionMode"),
        "contentHash": str(
            approval.get("contentHash") if isinstance(approval, dict) else ""
        ),
    }


def _activation_errors(payload: dict[str, Any]) -> list[str]:
    from core.research.workflow.contracts.automation_policy import (
        AutoAdvancePolicyV2,
        AutomationPolicyValidationError,
    )

    try:
        AutoAdvancePolicyV2.from_dict(payload, stage="activation")
    except AutomationPolicyValidationError as exc:
        return [
            f"[{item.get('code')}] {item.get('field')}: {item.get('message')}"
            for item in exc.errors
        ]
    except Exception as exc:  # noqa: BLE001 - an unreadable document is a problem too
        return [str(exc)]
    return []


def inspect(*, template: Path, deployed: Path) -> dict[str, Any]:
    """Read-only comparison of the authority and the deployed copy."""

    report: dict[str, Any] = {
        "templatePath": str(template),
        "deployedPath": str(deployed),
        "templateExists": template.is_file(),
        "deployedExists": deployed.is_file(),
        "templateErrors": [],
        "deployedErrors": [],
        "inSync": False,
        "state": "",
    }
    if not template.is_file():
        report["state"] = "template_missing"
        return report
    template_payload = _read_payload(template)
    report["template"] = _identity(template_payload)
    report["templateErrors"] = _activation_errors(template_payload)
    if report["templateErrors"]:
        report["state"] = "template_invalid"
        return report
    if not deployed.is_file():
        report["state"] = "deployed_missing"
        return report
    deployed_payload = _read_payload(deployed)
    report["deployed"] = _identity(deployed_payload)
    report["deployedErrors"] = _activation_errors(deployed_payload)
    report["inSync"] = template.read_bytes() == deployed.read_bytes()
    report["state"] = "in_sync" if report["inSync"] else "drift"
    return report


def deploy(*, template: Path, deployed: Path) -> dict[str, Any]:
    """Copy the template over the deployed copy, backing up the previous one."""

    report = inspect(template=template, deployed=deployed)
    if report["state"] == "template_missing":
        return {**report, "written": False}
    if report["templateErrors"]:
        return {**report, "written": False}
    if report["inSync"]:
        return {**report, "written": False}
    if deployed.is_file():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = deployed.with_suffix(deployed.suffix + f".predeploy-{stamp}")
        shutil.copy2(deployed, backup)
        report["backupPath"] = str(backup)
    else:
        deployed.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, deployed)
    return {**report, "written": True, "state": "deployed"}


def _exit_code(report: dict[str, Any]) -> int:
    state = str(report.get("state") or "")
    if state in {"template_missing", "template_invalid"}:
        return EXIT_TEMPLATE_PROBLEM
    if state in {"in_sync", "deployed"}:
        return EXIT_OK
    return EXIT_DRIFT


def _human_summary(report: dict[str, Any]) -> str:
    lines = [f"template: {report['templatePath']}", f"deployed: {report['deployedPath']}"]
    template = report.get("template")
    if template:
        lines.append(
            f"  template identity: {template['policyId']} v{template['version']} "
            f"{template['status']}/{template['executionMode']}"
        )
    deployed = report.get("deployed")
    if deployed:
        lines.append(
            f"  deployed identity: {deployed['policyId']} v{deployed['version']} "
            f"{deployed['status']}/{deployed['executionMode']}"
        )
    for item in report.get("templateErrors") or []:
        lines.append(f"  template error: {item}")
    for item in report.get("deployedErrors") or []:
        lines.append(f"  deployed error: {item}")
    state = report.get("state")
    if state == "in_sync":
        lines.append("RESULT: in sync - the runtime reads the approved template.")
    elif state == "drift":
        lines.append(
            "RESULT: DRIFT - the deployed copy is not the approved template; the "
            "runtime keeps reading the deployed copy.  Run with --write to deploy."
        )
    elif state == "deployed_missing":
        lines.append(
            "RESULT: MISSING - no deployed copy; both readers fall back to other "
            "sources (env or nothing).  Run with --write to deploy."
        )
    elif state == "deployed":
        lines.append("RESULT: deployed - the runtime source now matches the approved template.")
    elif state == "template_missing":
        lines.append("RESULT: the tracked template is missing; this is a repo problem.")
    elif state == "template_invalid":
        lines.append(
            "RESULT: the tracked template fails the activation contract; fix the "
            "template before deploying."
        )
    if report.get("backupPath"):
        lines.append(f"backup: {report['backupPath']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check or deploy the approved auto-advance policy template. "
            "Read-only unless --write is given."
        )
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="deploy the template over the operator's copy (backs up the previous one)",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="override the repo root that holds the template (tests)",
    )
    parser.add_argument(
        "--deployed",
        type=Path,
        default=None,
        help="override the deployed copy path (tests)",
    )
    args = parser.parse_args(argv)

    template = template_path(args.project_root)
    deployed = args.deployed if args.deployed is not None else deployed_path()

    report = (
        deploy(template=template, deployed=deployed)
        if args.write
        else inspect(template=template, deployed=deployed)
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) if args.json else _human_summary(report))
    return _exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
