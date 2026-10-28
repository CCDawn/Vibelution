"""Private no-console verifier Job, held until main explicitly releases it."""
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    token = os.environ.pop("VIBELUTION_PREHOST_RECOVERY_TOKEN", "")
    url = os.environ.pop("VIBELUTION_PREHOST_RECOVERY_URL", "")
    channel = None
    try:
        if sys.argv[1:] or re.fullmatch(r"[a-f0-9]{64}", token) is None:
            raise ValueError("invalid channel")
        match = re.fullmatch(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})", url)
        if match is None:
            raise ValueError("invalid channel")
        from scripts.assistant_migration_activate import _initial_call, _initial_channel, _isolated_environment
        from scripts.assistant_reminder_offline_worker import _install_worker_audit
        from core.assistant_runtime.migration_io import check_path
        port = int(match.group(1))
        channel = _initial_channel(port, token)
        bound = _initial_call(channel, token, "GET", "/binding")
        keys = {"schemaVersion", "projectId", "operationId", "revision", "projectRoot", "sourceConfig",
                "sourceProjectsHome", "sourceUserProfile", "targetProfile"}
        if (type(bound) is not dict or set(bound) != keys or type(bound["schemaVersion"]) is not int
                or bound["schemaVersion"] != 1 or type(bound["revision"]) is not int or bound["revision"] < 0
                or type(bound["projectId"]) is not str or not bound["projectId"]
                or type(bound["operationId"]) is not str
                or re.fullmatch(r"(?:initial|ksync|krec|affairs)-[a-f0-9]{40}", bound["operationId"]) is None):
            raise ValueError("invalid binding")
        for key in ("projectRoot", "sourceConfig", "sourceProjectsHome", "sourceUserProfile", "targetProfile"):
            path = check_path(Path(bound[key]))
            if not path.is_absolute() or path.resolve(strict=True) != path:
                raise ValueError("invalid path")
        target = Path(bound["targetProfile"])
        # A placeholder is never consumed by bootstrap; the verifier selects
        # and pins the original config under the target owner lock first.
        isolated = _isolated_environment(target, target / ".unselected-recovery-config")
        isolated["VIBELUTION_PROJECTS_HOME"] = bound["sourceProjectsHome"]
        isolated["USERPROFILE"] = bound["sourceUserProfile"]
        os.environ.clear()
        os.environ.update(isolated)
        route_lock = Path(bound["projectRoot"]) / ".vibelution" / "reminder-route-gate.lock"
        _install_worker_audit(target, port, route_lock_path=route_lock)
        # This preliminary read only chooses the config for source preview;
        # the locked verifier reads and pins the same original again before
        # native bootstrap, and rejects any identity or digest change.
        from core.assistant_runtime.reminder_handoff_intent import read_handoff_intent
        from core.assistant_runtime.initial_migration_binding import read_initial_intent
        original = (read_handoff_intent(target, bound["projectId"]) if bound["operationId"].startswith("affairs-")
                    else read_initial_intent(target, bound["operationId"]))
        if (original is None or original["registeredProjectId"] != bound["projectId"]
                or (original.get("syncId") if bound["operationId"].startswith("affairs-") else original["operationId"]) != bound["operationId"]):
            raise ValueError("original intent unavailable")
        config = target / (".initial-migration-models-v1-" + original["operationId"] + "-" + original["registryDigest"] + ".toml")
        os.environ["VIBELUTION_CONFIG_PATH"] = str(config)
        os.environ["VIBELUTION_CONFIG_HOME"] = str(target)
        for key in ("HOME", "APPDATA", "LOCALAPPDATA", "TEMP"):
            Path(os.environ[key]).mkdir(parents=True, exist_ok=True)
        from core.assistant_runtime.dispatch import DispatchService
        from core.assistant_runtime.history_preview import HistoryPreview
        from core.assistant_runtime.prehost_recovery_verifier import held_prehost_recovery_verifier, delete_exact_recovery_marker
        from core.infrastructure.reminder_source_mutex import _try_digest
        dispatch = DispatchService(target, {})
        dispatch.replace_projects({"schemaVersion": 1, "revision": bound["revision"],
                                   "projects": {bound["projectId"]: bound["projectRoot"]}})
        preview = HistoryPreview(dispatch, Path(bound["sourceConfig"]))
        with held_prehost_recovery_verifier(dispatch=dispatch, preview=preview, project_id=bound["projectId"],
                                           revision=bound["revision"], operation_id=bound["operationId"],
                                           select_original_config=True) as check:
            if _initial_call(channel, token, "GET", "/ready") != {"schemaVersion": 1, "accepted": True}:
                raise ValueError("owner unavailable")
            while True:
                command = _initial_call(channel, token, "GET", "/poll")
                if type(command) is not dict or type(command.get("schemaVersion")) is not int or command.get("schemaVersion") != 1:
                    raise ValueError("invalid command")
                if command == {"schemaVersion": 1, "action": "release"}:
                    break
                if command == {"schemaVersion": 1, "action": "wait"}:
                    time.sleep(.05)
                    continue
                request_id = command.get("requestId")
                if (type(request_id) is not str or re.fullmatch(r"[a-f0-9]{32}", request_id) is None
                        or command.get("action") not in ("check", "commit")):
                    raise ValueError("invalid command")
                try:
                    if command["action"] == "check" and set(command) != {"schemaVersion", "action", "requestId"}:
                        raise ValueError("invalid command")
                    if command["action"] == "commit":
                        if set(command) != {"schemaVersion", "action", "requestId", "markerPath", "markerSha256", "markerIdentity", "commitKey"}:
                            raise ValueError("invalid command")
                        mutex = _try_digest(command["commitKey"])
                        if mutex is None:
                            raise ValueError("commit busy")
                        try:
                            def before_delete():
                                response = _initial_call(channel, token, "GET", "/commit-check/" + request_id)
                                if response != {"schemaVersion": 1, "accepted": True} or type(response.get("schemaVersion")) is not int:
                                    raise ValueError("commit revoked")
                            delete_exact_recovery_marker(path=Path(command["markerPath"]), expected_sha256=command["markerSha256"],
                                expected_identity=command["markerIdentity"], operation_id=bound["operationId"],
                                commit_key=command["commitKey"], commit_mutex=mutex, verifier=check, before_delete=before_delete)
                        finally:
                            mutex.release()
                    proof = check()
                    if (proof["state"] != "verified" or proof["operationId"] != bound["operationId"]
                            or proof["readyForCutover"] is not False):
                        raise ValueError("proof unavailable")
                    result = "ok"
                except Exception:
                    result = "failed"
                if _initial_call(channel, token, "GET", "/" + result + "/" + request_id) != {"schemaVersion": 1, "accepted": True}:
                    raise ValueError("owner unavailable")
                if result != "ok":
                    break
        return 0
    except Exception:
        return 1
    finally:
        if channel is not None:
            channel.close()


if __name__ == "__main__":
    raise SystemExit(main())
