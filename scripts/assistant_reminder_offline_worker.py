"""One-shot private child of the Launcher reminder migration Job.

All authority and paths arrive through the main-owned loopback capability.
No CLI path, agent, or sender-stopped flag is accepted.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _install_worker_audit(target: Path, port: int, *, route_lock_path: Path | None = None) -> None:
    """Allow only the main-owned loopback capability; isolate all writes."""
    def audit(event, args):
        if event == "socket.getaddrinfo":
            if args[0] != "127.0.0.1" or str(args[1]) != str(port):
                raise PermissionError("reminder_worker_network_denied")
            return
        if event == "socket.connect":
            address = args[1]
            if (type(address) is not tuple or len(address) != 2 or address[0] != "127.0.0.1"
                    or type(address[1]) is not int or address[1] != port):
                raise PermissionError("reminder_worker_network_denied")
            return
        if event in {"socket.bind", "socket.sendto", "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.startfile"}:
            raise PermissionError("reminder_worker_operation_denied")
        if event == "open":
            path, _mode, flags = args
            if isinstance(path, int) or not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                return
            paths = (path,)
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.chown", "os.utime", "os.truncate"}:
            paths = (args[0],)
        elif event in {"os.rename", "os.link", "os.symlink"}:
            paths = args[:2]
        else:
            return
        for path in paths:
            if isinstance(path, int):
                raise PermissionError("reminder_worker_write_denied")
            raw = os.fsdecode(path)
            if event == "open" and os.path.normcase(raw) == os.path.normcase(os.devnull):
                continue
            if os.name == "nt" and raw.startswith("\\\\?\\"):
                local = raw[4:]
                if len(local) < 3 or not local[0].isalpha() or local[1:3] != ":\\":
                    raise PermissionError("reminder_worker_write_denied")
                raw = local
            resolved = Path(raw).resolve()
            # The verifier needs one exact, main-bound source-side lock leaf;
            # the gate independently pins and verifies that file before use.
            if event == "open" and route_lock_path is not None and resolved == route_lock_path:
                continue
            if (event == "os.mkdir" and route_lock_path is not None
                    and resolved == route_lock_path.parent and resolved.is_dir()):
                continue
            if not resolved.is_relative_to(target):
                raise PermissionError("reminder_worker_write_denied")
    sys.addaudithook(audit)


def main() -> int:
    token = os.environ.pop("VIBELUTION_REMINDER_WORKER_TOKEN", "")
    url = os.environ.pop("VIBELUTION_REMINDER_WORKER_URL", "")
    sync_id = None
    channel = None
    try:
        if sys.argv[1:] or not re.fullmatch(r"[a-f0-9]{64}", token):
            raise ValueError("invalid capability")
        match = re.fullmatch(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})", url)
        if match is None:
            raise ValueError("invalid channel")
        from scripts.assistant_migration_activate import _initial_call, _initial_channel, _isolated_environment
        from core.assistant_runtime.migration_io import check_path, validate_path
        channel = _initial_channel(int(match.group(1)), token)
        bound = _initial_call(channel, token, "GET", "/binding")
        keys = {"schemaVersion", "registeredProjectId", "revision", "projectRoot", "sourceConfig",
                "sourceProjectsHome", "sourceUserProfile", "targetProfile", "targetConfig", "syncId", "mode", "recoveryId"}
        valid_id = lambda value: type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", value) is not None
        if (type(bound) is not dict or set(bound) != keys or type(bound["schemaVersion"]) is not int
                or bound["schemaVersion"] != 1 or type(bound["revision"]) is not int or bound["revision"] < 0
                or type(bound["registeredProjectId"]) is not str or not bound["registeredProjectId"]
                or not valid_id(bound["syncId"]) or bound["mode"] not in ("start", "resume")
                or bound["mode"] == "start" and bound["recoveryId"] is not None
                or bound["recoveryId"] is not None and (type(bound["recoveryId"]) is not str
                    or re.fullmatch(r"rprep-[a-f0-9]{40}", bound["recoveryId"]) is None)):
            raise ValueError("invalid binding")
        sync_id = bound["syncId"]
        for key in ("projectRoot", "sourceConfig", "sourceProjectsHome", "sourceUserProfile", "targetProfile"):
            path = check_path(Path(bound[key]))
            if not path.is_absolute() or path.resolve(strict=True) != path:
                raise ValueError("invalid path")
        target, target_config = Path(bound["targetProfile"]), validate_path(Path(bound["targetConfig"]))
        if target_config.parent != target:
            raise ValueError("invalid target")
        permit = _initial_call(channel, token, "POST", "/permit")
        if type(permit) is not dict or permit != {"schemaVersion": 1, "granted": True} or type(permit["schemaVersion"]) is not int:
            raise ValueError("permit unavailable")
        def check_admission():
            status = _initial_call(channel, token, "GET", "/check")
            if (type(status) is not dict or status != {"schemaVersion": 1, "current": True}
                    or type(status.get("schemaVersion")) is not int or type(status.get("current")) is not bool):
                raise ValueError("permit unavailable")
        isolated = _isolated_environment(target, target_config)
        isolated["VIBELUTION_PROJECTS_HOME"] = bound["sourceProjectsHome"]
        # The route resolver needs the main-owned operator profile to resolve
        # the established default data home. All writable runtime homes remain
        # private and the audit hook rejects writes outside the target profile.
        isolated["USERPROFILE"] = bound["sourceUserProfile"]
        os.environ.clear()
        os.environ.update(isolated)
        route_lock = Path(bound["projectRoot"]) / ".vibelution" / "reminder-route-gate.lock"
        _install_worker_audit(target, int(match.group(1)), route_lock_path=route_lock)
        for key in ("HOME", "APPDATA", "LOCALAPPDATA", "TEMP"):
            Path(os.environ[key]).mkdir(parents=True, exist_ok=True)
        from core.assistant_runtime.dispatch import DispatchService
        from core.assistant_runtime.history_preview import HistoryPreview
        from core.assistant_runtime.reminder_source_identity import observe_reminder_source
        from core.assistant_runtime.reminder_offline_worker import run_reminder_offline_worker
        from core.infrastructure.reminder_route_gate import HeldRouteGate
        dispatch = DispatchService(target, {})
        dispatch.replace_projects({"schemaVersion": 1, "revision": bound["revision"],
                                   "projects": {bound["registeredProjectId"]: bound["projectRoot"]}})
        preview = HistoryPreview(dispatch, Path(bound["sourceConfig"]))
        # The project route must remain stable from the first observation
        # through the final transaction and receipt. This gates cooperating
        # writers only and is not a proof about older senders.
        route = HeldRouteGate(Path(bound["projectRoot"]))
        try:
            def check_bound_admission():
                route.check()
                check_admission()
            check_bound_admission()
            with observe_reminder_source(dispatch, preview, bound["registeredProjectId"], bound["revision"]) as source:
                result = run_reminder_offline_worker(source=source, sync_id=sync_id, check_admission=check_bound_admission,
                                                    mode=bound["mode"], recovery_id=bound["recoveryId"], target_config=target_config)
            check_bound_admission()
            print(json.dumps(result, separators=(",", ":")))
            return 0
        finally:
            route.release()
    except Exception:
        print(json.dumps({"schemaVersion": 1, "state": "unknown", "syncId": sync_id,
                          "readyForCutover": False}, separators=(",", ":")))
        return 1
    finally:
        if channel is not None:
            channel.close()


if __name__ == "__main__":
    raise SystemExit(main())
