#!/usr/bin/env python3
"""Run isolated, opt-in native assistant scheduling acceptance cases."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import sys
import tempfile
import time
import traceback

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))
sys.dont_write_bytecode = True

from scripts.acceptance_local_assistant_development import AcceptanceFailure, inside, private_json, require


def completion_status(evidence: dict) -> str:
    """Unexecuted required stages remain visible even when executed work passed."""
    stages = [item["status"] for item in evidence.values() if isinstance(item, dict) and "status" in item]
    if "failed" in stages:
        return "failed"
    if any(status != "passed" for status in stages):
        return "partial"
    return "passed"


def aggregate_status(cases: dict) -> str:
    states = [case.get("status") for case in cases.values()]
    if not states or "failed" in states:
        return "failed"
    return "passed" if all(state == "passed" for state in states) else "partial"


def finish_launcher(controller) -> dict:
    try:
        require(controller.process.poll() is None, "isolated_electron_exited_before_formal_exit")
        controller._capture_children()
        controller.plan["nextAction"] = {"type": "exit", "operation": "requestDesktopShellExit"}
        controller._save()
        print(json.dumps({"launcherControl": str(controller.control_path), "state": "awaiting_formal_exit"}), flush=True)
        return controller.wait_exit(timeout=180)
    except Exception:
        controller.stop_owned_after_failure()
        raise


def run_launcher_phase(fixture, evidence: dict, args: argparse.Namespace) -> None:
    """Keep a real isolated shell alive while its owned UI submits requests."""
    from scripts.acceptance_assistant_projects import prepare_launcher_phase
    from scripts.acceptance_local_assistant_development import git

    main = Path(git(SOURCE_ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()).parent
    def prepare():
        return prepare_launcher_phase(fixture, evidence,
            electron=args.electron or main / "desktop/electron/node_modules/electron/dist/electron.exe",
            desktop_dist=args.desktop_dist or main / "desktop/electron/dist",
            pythonw=args.pythonw or main / ".venv/Scripts/pythonw.exe")

    controller = prepare()
    controller.stop_standalone()
    proofs = []
    try:
        # Each integration is registered by its genuine native inventory. A
        # second-instance CLI cannot replace an existing integration bootstrap.
        controller.start(timeout=max(180, args.readiness_timeout), root=controller.slots["B"].root)
        print(json.dumps({"launcherControl": str(controller.control_path), "state": "ready_for_native_operator"}), flush=True)
        deadline = time.monotonic() + max(180, args.readiness_timeout)
        while time.monotonic() < deadline:
            registered = [row for row in controller.refresh_registrations() if row["slot"] == "B"]
            if len(registered) == 1:
                break
            time.sleep(2)
        else:
            raise AcceptanceFailure("launcher_other_project_not_registered")
        exit_proof = finish_launcher(controller)
        evidence["launcherBootstrapB"] = {"status": "passed", "registration": registered[0], "formalExit": exit_proof}
        controller = prepare()
        controller.start(timeout=max(180, args.readiness_timeout))
        print(json.dumps({"launcherControl": str(controller.control_path), "state": "ready_for_native_operator"}), flush=True)
        deadline = time.monotonic() + max(180, args.readiness_timeout)
        while time.monotonic() < deadline:
            registered = {row["slot"] for row in controller.refresh_registrations()}
            if {"A", "A1", "B"} <= registered:
                break
            time.sleep(2)
        else:
            raise AcceptanceFailure("launcher_registered_targets_not_ready")
        if not controller.backend_identity(controller.slots["A"].root)["alive"]:
            require(controller.cli("start") == 0, "launcher_primary_start_cli_failed")
            deadline = time.monotonic() + max(180, args.readiness_timeout)
            while time.monotonic() < deadline:
                if controller.backend_identity(controller.slots["A"].root)["alive"]:
                    break
                time.sleep(2)
            else:
                raise AcceptanceFailure("launcher_primary_backend_not_ready")
        for slot, operation in (("A", "restart"), ("A1", "start"), ("A1", "restart"), ("A1", "stop"), ("B", "start"), ("B", "restart")):
            prepared = controller.prepare_operation(slot, operation)
            controller.plan["nextAction"] = {"type": "send", **prepared}
            controller._save()
            print(json.dumps({"launcherOperation": operation, "slot": slot, "state": "awaiting_native_ui"}), flush=True)
            proofs.append(controller.wait_operation(prepared["request"], timeout=300))
        evidence["launcherLifecycle"] = {"status": "passed", "operations": proofs,
                                          "instructionsPath": str(controller.control_path)}
    except AcceptanceFailure as exc:
        evidence["launcherLifecycle"].update(status="failed", failureCode=str(exc))
        raise
    finally:
        if controller.process is not None and controller.plan.get("status") not in {"exited", "failed"}:
            finish_launcher(controller)


def run(args: argparse.Namespace) -> dict:
    home = args.runtime_home.resolve()
    require(inside(home, Path(tempfile.gettempdir()).resolve()), "private_system_temp_required")
    require(not home.exists() or not any(home.iterdir()), "unused_runtime_home_required")
    home.mkdir(parents=True, exist_ok=True)
    names = ("multitask", "recovery", "projects") if args.scenario == "all" else (args.scenario,)
    report = {"schemaVersion": 1, "status": "running", "modelId": args.model_id,
              "startedAt": datetime.now(timezone.utc).isoformat(), "cases": {}}
    private_json(home / "report.json", report)
    from scripts.assistant_acceptance_support import AssistantAcceptanceFixture

    for name in names:
        evidence = {"schemaVersion": 1, "scenario": name, "status": "running"}
        report["cases"][name] = evidence
        fixture = None
        print(json.dumps({"scenario": name, "state": "starting"}), flush=True)
        try:
            module = importlib.import_module("scripts.acceptance_assistant_" + name)
            fixture = AssistantAcceptanceFixture(home / name, args.source_config, args.model_id,
                source=SOURCE_ROOT, readiness_timeout=args.readiness_timeout)
            with fixture:
                if args.projects_evidence:
                    require(name == "projects" and args.launcher_phase, "project_evidence_requires_launcher_only")
                    module.reuse_cross_project_evidence(fixture, evidence, args.projects_evidence)
                else:
                    module.run_case(fixture, evidence, timeout=args.timeout)
                if name == "projects" and args.launcher_phase:
                    run_launcher_phase(fixture, evidence, args)
            evidence["status"] = completion_status(evidence)
        except AcceptanceFailure as exc:
            evidence.update(status="failed", failureCode=str(exc))
        except Exception as exc:
            # Exception text may contain HTTP bodies or credential-bearing data.
            evidence.update(status="failed", failureCode="unexpected_" + type(exc).__name__)
            evidence["failureFrames"] = [
                {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(exc.__traceback__)[-6:]]
        finally:
            if fixture is not None:
                evidence["cleanup"] = fixture.cleanup
                evidence["configuration"] = fixture.configuration_evidence()
                if evidence["status"] in {"passed", "partial"} and not all(fixture.cleanup.values()):
                    evidence.update(status="failed", failureCode="runtime_cleanup_unconfirmed")
            private_json(home / (name + ".json"), evidence)
            private_json(home / "report.json", report)
        print(json.dumps({"scenario": name, "state": evidence["status"],
                          "failureCode": evidence.get("failureCode")}), flush=True)
    report["status"] = aggregate_status(report["cases"])
    report["completedAt"] = datetime.now(timezone.utc).isoformat()
    private_json(home / "report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("multitask", "recovery", "projects", "all"), default="all")
    parser.add_argument("--runtime-home", type=Path, required=True)
    parser.add_argument("--source-config", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--readiness-timeout", type=float, default=120)
    parser.add_argument("--launcher-phase", action="store_true",
        help="Also await real native-frame UI lifecycle requests in an isolated Electron instance.")
    parser.add_argument("--electron", type=Path)
    parser.add_argument("--desktop-dist", type=Path)
    parser.add_argument("--pythonw", type=Path)
    parser.add_argument("--projects-evidence", type=Path,
        help="Reuse completed private cross-project proof while retrying only the Launcher stage.")
    args = parser.parse_args()
    try:
        report = run(args)
    except AcceptanceFailure as exc:
        report = {"status": "failed", "failureCode": str(exc)}
    except Exception as exc:
        report = {"status": "failed", "failureCode": "unexpected_" + type(exc).__name__}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if report["status"] == "passed" else 2 if report["status"] == "partial" else 1


if __name__ == "__main__":
    raise SystemExit(main())
