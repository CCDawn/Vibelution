#!/usr/bin/env python3
"""Isolated native project gateway for Launcher assistant model acceptance.

Run with --runtime-dir <TEMP>/<acceptance>/target-runtime --instance-id <nonce>.
VIBELUTION_CONFIG_PATH is a read-only source configuration. DATA_HOME and
PROJECTS_HOME must be absolute children of that same acceptance directory.
Startup provisions one ordinary, tool-free target Agent and never submits a
model request. The acceptance driver owns task submission and explicit cleanup.
"""

import argparse
import asyncio
from contextlib import asynccontextmanager, suppress
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import tempfile
import time
import tomllib
from typing import Any


SOURCE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE_ROOT))
sys.dont_write_bytecode = True


class IsolationViolation(RuntimeError):
    """Safe diagnostic: paths and config values never enter error messages."""


def _inside(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    return resolved != root and resolved.is_relative_to(root)


def _required_env_path(name: str) -> Path:
    value = os.environ.get(name, "")
    if not value or not Path(value).is_absolute():
        raise IsolationViolation(f"missing_absolute_{name.lower()}")
    return Path(value).resolve()


def _provider_snapshot(source: dict[str, Any]) -> dict[str, Any]:
    """Copy model routing, excluding unrelated product settings and secrets."""
    llm = source.get("llm") or {}

    def check(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {"api_key", "apikey", "token", "access_token", "refresh_token", "secret", "password",
                                      "authorization", "x-api-key", "api-key", "x-auth-token", "cookie"} and child:
                    raise IsolationViolation("inline_credentials_must_be_environment_references")
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(llm)
    return {"llm": llm, "runtime": {"profile": (source.get("runtime") or {}).get("profile", "")}}


def _install_file_audit(home: Path) -> None:
    """Deny writes outside the fixture and reads of known live project data."""
    user = Path(os.environ.get("USERPROFILE") or Path.home()).resolve()
    local = Path(os.environ.get("LOCALAPPDATA") or user / "AppData" / "Local").resolve()
    protected = [SOURCE_ROOT / part for part in (
        ".runtime", "workspace", "logs", "log_info", "backups", ".docs/project-memory",
    )]
    protected += [local / "Vibelution" / "projects", local / "Vibelution" / "mcp",
                  user / "Documents" / "Vibelution" / "data"]
    protected = [path.resolve() for path in protected if not path.resolve().is_relative_to(home)]

    def audit_path(value: Any, *, writing: bool) -> None:
        if isinstance(value, int) or value is None:
            return
        if os.fsdecode(value).casefold() == os.devnull.casefold():
            return
        path = Path(os.fsdecode(value)).resolve()
        if writing and not (path == home or _inside(path, home)):
            raise IsolationViolation("write_outside_acceptance_home")
        if not writing and any(path == root or path.is_relative_to(root) for root in protected):
            raise IsolationViolation("read_from_live_project_data")

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "open":
            _path, mode, flags = args
            writing = bool((flags or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            writing = writing or (isinstance(mode, str) and any(char in mode for char in "wax+"))
            audit_path(_path, writing=writing)
        elif event == "sqlite3.connect" and args[0] != ":memory:":
            audit_path(args[0], writing=True)
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.truncate", "os.utime", "os.chown"}:
            audit_path(args[0], writing=True)
        elif event in {"os.rename", "os.link"}:
            audit_path(args[0], writing=True)
            audit_path(args[1], writing=True)
        elif event == "os.symlink":
            audit_path(args[1], writing=True)
        elif event.startswith(("winreg.Set", "winreg.Delete", "winreg.Create")):
            raise IsolationViolation("registry_write_forbidden")
        elif event == "subprocess.Popen":
            raise IsolationViolation("subprocess_not_allowed_in_target_fixture")

    sys.addaudithook(audit)


def _prepare(args: argparse.Namespace) -> dict[str, Any]:
    if not args.runtime_dir.is_absolute() or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", args.instance_id):
        raise IsolationViolation("invalid_runtime_directory_or_generation")
    runtime_dir = args.runtime_dir.resolve()
    home = runtime_dir.parent
    system_temp = Path(tempfile.gettempdir()).resolve()
    if not _inside(home, system_temp) or home.is_relative_to(SOURCE_ROOT):
        raise IsolationViolation("acceptance_home_must_be_a_private_temp_directory")
    projects = _required_env_path("VIBELUTION_PROJECTS_HOME")
    data = _required_env_path("VIBELUTION_DATA_HOME")
    source_config = _required_env_path("VIBELUTION_CONFIG_PATH")
    if not all(_inside(path, home) for path in (projects, data, runtime_dir)):
        raise IsolationViolation("data_and_projects_must_share_acceptance_home")
    if os.environ.get("VIBELUTION_PROCESS_ROLE") == "launcher_assistant":
        raise IsolationViolation("target_must_not_use_launcher_assistant_role")
    source_bytes = source_config.read_bytes()
    raw_config = tomllib.loads(source_bytes.decode("utf-8"))
    if not isinstance(raw_config, dict):
        raise IsolationViolation("invalid_source_config")
    raw_config = _provider_snapshot(raw_config)

    _install_file_audit(home)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    private_config = runtime_dir / "private-config" / "config.toml"
    if private_config.exists() or (runtime_dir / "ready.json").exists():
        raise IsolationViolation("fixture_generation_requires_unused_runtime_directory")
    private_config.parent.mkdir(parents=True, exist_ok=True)
    # Native config APIs may initialize metadata or upgrade schema. Only the
    # isolated snapshot is exposed to those APIs; the source stays read-only.
    os.environ["VIBELUTION_CONFIG_PATH"] = str(private_config)
    os.environ["VIBELUTION_CONFIG_HOME"] = str(private_config.parent)
    os.environ["VIBELUTION_PROCESS_ROLE"] = "acceptance_target"
    os.environ.pop("VIBELUTION_ASSISTANT_NATIVE_ROOT", None)
    os.environ["VIBELUTION_WEB_CONTROL_TOKEN"] = secrets.token_urlsafe(32)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    for variable, suffix in (("TMP", "tmp"), ("TEMP", "tmp"), ("TMPDIR", "tmp"),
                             ("HF_HOME", "cache/huggingface"), ("TIKTOKEN_CACHE_DIR", "cache/tiktoken"),
                             ("XDG_CACHE_HOME", "cache")):
        cache = home / suffix
        cache.mkdir(parents=True, exist_ok=True)
        os.environ[variable] = str(cache)
    tempfile.tempdir = str(home / "tmp")
    raw_config.setdefault("storage", {})["data_home"] = str(data)
    raw_config.setdefault("launcher", {})["developer_mode"] = {"enabled": False}
    from config.toml_writer import dumps_public_config
    private_config.write_text(dumps_public_config(raw_config), encoding="utf-8")
    try:
        private_config.chmod(0o600)
    except OSError:
        pass

    from vibelution_storage import (
        resolve_active_project_storage_paths, resolve_project_data_home,
        resolve_project_runtime_home, resolve_project_workspace_home,
    )
    storage = resolve_active_project_storage_paths(SOURCE_ROOT)
    for path in (storage.data, storage.runtime, storage.logs, storage.memory, storage.cache,
                 resolve_project_data_home(SOURCE_ROOT), resolve_project_workspace_home(SOURCE_ROOT)):
        if not _inside(path, home):
            raise IsolationViolation("resolved_native_storage_outside_acceptance_home")
    descriptor = resolve_project_runtime_home(SOURCE_ROOT) / "launcher" / "state.json"
    if not _inside(descriptor, projects) or descriptor.exists():
        raise IsolationViolation("launcher_descriptor_not_private_or_already_owned")
    return {"home": home, "runtime_dir": runtime_dir, "source_config": source_config,
            "source_hash": hashlib.sha256(source_bytes).hexdigest(), "descriptor": descriptor,
            "generation": args.instance_id, "session_config_history": args.session_config_history}


def _serve(binding: dict[str, Any]) -> int:
    # platform.uname() may fall back to `cmd /c ver` on Windows. Cache the
    # real process OS identity without invoking a shell before Uvicorn (or a
    # provider library) asks platform.system(). The subprocess audit remains
    # active so a future dependency cannot silently reintroduce that path.
    if os.name == "nt":
        import platform
        version = sys.getwindowsversion()
        platform._uname_cache = platform.uname_result(
            "Windows", socket.gethostname(), str(version.major),
            f"{version.major}.{version.minor}.{version.build}",
            os.environ.get("PROCESSOR_ARCHITECTURE", ""),
        )
        # OpenAI's client also asks platform.platform(), whose Windows branch
        # independently invokes win32_ver(). Cache its four presentation forms
        # from the same OS identity, before a driver constructs any SDK client.
        label = f"Windows-{version.major}-{version.major}.{version.minor}.{version.build}"
        platform._platform_cache.update({(aliased, terse): label for aliased in (False, True) for terse in (False, True)})
    import uvicorn
    from fastapi import FastAPI, HTTPException, Request
    from pydantic import BaseModel

    from core.external_agent.backend_client import _checkout_revision
    from core.infrastructure import developer_sandbox
    from core.infrastructure.atomic_io import atomic_write_json
    from core.infrastructure.native_runtime import is_launcher_assistant_process
    from core.web.control import (
        WebControlGuardMiddleware, control_token_payload,
        ensure_control_source, validate_control_request,
    )
    from core.web.routes import external_agent, launcher_assistant_management
    from core.web.services.external_management.service import build_default_service
    from core.web.services import agent_directory_service as directory, session_service as sessions
    from core.web.services.external_agent.service import ExternalAgentTaskService
    from core.web.services.external_agent.store import ExternalAgentTaskStore
    from core.web.services.session import directory_runtime
    from core.web.services.team_workflow.generic import runtime as team_runtime

    home, runtime_dir = binding["home"], binding["runtime_dir"]
    if is_launcher_assistant_process() or directory.PROJECT_ROOT != SOURCE_ROOT or sessions.PROJECT_ROOT != SOURCE_ROOT:
        raise IsolationViolation("target_facade_must_keep_ordinary_checkout_root")
    for path in (directory_runtime.conversation_store_path(SOURCE_ROOT),
                 developer_sandbox.formal_workspace_path(SOURCE_ROOT)):
        if not _inside(path, home):
            raise IsolationViolation("resolved_directory_path_outside_acceptance_home")
    revision = _checkout_revision(SOURCE_ROOT)
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", revision):
        raise IsolationViolation("cannot_resolve_real_checkout_revision")
    ready_path = runtime_dir / "ready.json"
    service = ExternalAgentTaskService(
        ExternalAgentTaskStore(binding["descriptor"].parents[1] / "external_agents"),
        enabled=True, operator_permission_ceiling="read_only", runtime_permission_ceiling="read_only",
        lease_seconds=30, max_task_seconds=1800,
    )
    external_agent._SERVICE = service
    launcher_assistant_management._SERVICE = build_default_service(SOURCE_ROOT)
    stopped = asyncio.Event()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    os.environ["VIBELUTION_PORT"] = str(port)
    state: dict[str, Any] = {
        "protocolVersion": 1, "role": "launcher_assistant_target_fixture",
        "generation": binding["generation"], "instanceId": binding["generation"],
        "pid": os.getpid(), "port": port, "projectRoot": str(SOURCE_ROOT),
        "runtimeSourceCommit": revision,
    }
    if os.name == "nt":
        import ctypes
        state["consoleWindowPresent"] = bool(ctypes.windll.kernel32.GetConsoleWindow())
        if state["consoleWindowPresent"]:
            raise IsolationViolation("fixture_requires_a_no_console_subprocess")

    def initialize() -> None:
        opened = sessions.begin_session_service_lifecycle()
        if not opened.get("opened"):
            raise IsolationViolation("native_executors_not_open")
        status = directory_runtime.initialize_session_directory_runtime(project_root=SOURCE_ROOT, migrate_legacy_chat_state=False)
        if status.status != "ready":
            raise IsolationViolation("native_directory_not_ready")
        existing = directory.list_agents(include_archived=True, detail="full")
        pa_count = sum(bool((row.get("metadata") or {}).get("personalAssistantProfile")) for row in existing)
        if pa_count:
            raise IsolationViolation("personal_assistant_must_not_exist_in_target")
        targets = [row for row in existing if row.get("createdBy") == "launcher_assistant_target_fixture"]
        if len(targets) > 1:
            raise IsolationViolation("multiple_fixture_target_agents")
        target = targets[0] if targets else directory.create_agent_instance(
            display_name="Launcher acceptance target", primary_mode="general",
            created_by="launcher_assistant_target_fixture",
            llm_bindings=sessions.default_session_llm_bindings(),
            initial_tool_policy={"allowedTools": [], "preferredTools": [], "readScopes": [],
                                 "writeScopes": [], "networkAccess": "none", "mutationAccess": "restricted"},
            metadata={"fixtureGeneration": binding["generation"]},
        )
        target = directory.get_agent(target["agentId"], include_archived=True)
        policy = target.get("toolPolicy") or {}
        if target.get("status") != "active" or policy.get("allowedTools") or policy.get("networkAccess") != "none":
            raise IsolationViolation("target_policy_is_not_tool_free")
        if binding["session_config_history"]:
            from core.agent_plugins.virtual_human_life.storage import VirtualHumanLifeStore
            from core.llm.agent_runtime import agent_dialogue_model_id
            from core.web.services.agent_config_authority import canonical_agent_config_payload
            from core.web.services.team import team_store

            def history_stage(phase):
                atomic_write_json(runtime_dir / "session-config-stage.json", {"phase": phase}, strict_replace=True)

            history_stage("agent_A")
            model_id = agent_dialogue_model_id(target)
            if not model_id:
                raise IsolationViolation("history_fixture_requires_native_model_binding")
            target = directory.update_agent_instance(target["agentId"], role_key="assistant_worker", metadata={
                "llmModelParameters": {model_id: {"contextWindow": 32768, "reasoningEffort": "low"}},
                "llmReasoningEffort": {"dialogue": "low"}})
            store = directory_runtime.get_open_directory_store()
            if store is None:
                raise IsolationViolation("history_fixture_requires_open_native_directory")
            imported = store.repository.import_agent_config_snapshots([{
                "agent_id": target["agentId"], "display_name": target["displayName"], "kind": target["kind"],
                "status": target["status"], "config": canonical_agent_config_payload(target),
                "source": "launcher_assistant_history_fixture_A"}]).result(timeout=5)
            revision_a = imported[0]["configRevisionId"]
            history_stage("native_direct_session")
            direct = sessions.ensure_agent_direct_session(agent_id=target["agentId"],
                title="Historical model config acceptance", created_by="launcher_assistant_target_fixture")
            session_id = direct["id"]
            row = store.repository.get_session(session_id)
            if not row or row["agentConfigRevisionId"] != revision_a:
                raise IsolationViolation("history_fixture_native_session_pin_mismatch")
            # The normal read gate requires an authoritative empty roster and
            # a disabled Companion binding. Use their native storage owners.
            history_stage("visibility_authorities")
            team_store._save_index({"schemaVersion": 1, "teams": []})
            plugin = VirtualHumanLifeStore(SOURCE_ROOT, plugin_root_resolver=lambda owner:
                developer_sandbox.route_workspace_path(SOURCE_ROOT, "agent_directory", "agents", owner,
                    "plugins", "virtual-human-life", intent="state", seed=False))
            plugin.write_json(target["agentId"], "binding.json", {"agentId": target["agentId"], "enabled": False})
            history_stage("agent_B")
            target = directory.update_agent_instance(target["agentId"], metadata={
                "llmModelParameters": {model_id: {"contextWindow": 65536, "reasoningEffort": "high"}},
                "llmReasoningEffort": {"dialogue": "high"}})
            advanced = store.repository.compare_and_swap_agent_config(agent_id=target["agentId"],
                expected_config_revision_id=revision_a, display_name=target["displayName"], kind=target["kind"],
                status=target["status"], config=canonical_agent_config_payload(target),
                source="launcher_assistant_history_fixture_B").result(timeout=5)
            if advanced["configRevisionId"] == revision_a or store.repository.get_session(session_id)["agentConfigRevisionId"] != revision_a:
                raise IsolationViolation("history_fixture_current_must_differ_from_session_pin")
            expected = {"source": "session_agent_config_revision", "untrustedContent": True, "config": {
                "sessionId": session_id, "agentId": target["agentId"], "agentConfigRevisionId": revision_a,
                "modelId": model_id, "contextWindow": 32768, "reasoningEffort": "low"}}
            state["sessionConfigFixture"] = {"expected": expected, "currentRevisionId": advanced["configRevisionId"],
                "currentContextWindow": 65536, "currentReasoningEffort": "high",
                "activeSessionId": store.repository.get_active_session_id()}
            atomic_write_json(runtime_dir / "session-config-fixture.json", state["sessionConfigFixture"], strict_replace=True)
            history_stage("complete")
        service.allowed_agent_ids = frozenset({target["agentId"]})
        discovered = service.list_agents()["agents"]
        if len(discovered) != 1 or discovered[0]["agentId"] != target["agentId"]:
            raise IsolationViolation("native_discovery_does_not_match_target")
        final_agents = directory.list_agents(include_archived=True, detail="full")
        if any((row.get("metadata") or {}).get("personalAssistantProfile") for row in final_agents):
            raise IsolationViolation("personal_assistant_created_during_target_bootstrap")
        state.update({"targetAgentId": target["agentId"], "noPaCount": 0, "sourceConfigUnchanged": True})
        # Exercise the same native Team scheduler as a project lifespan. The
        # assistant and test driver never own a replacement execution loop.
        if not team_runtime.begin_generic_workflow_lifecycle().get("opened"):
            raise IsolationViolation("native_team_executor_not_open")
        atomic_write_json(binding["descriptor"], {
            "url": f"http://127.0.0.1:{port}", "runtimeProjectRoot": str(SOURCE_ROOT),
            "runtimeSourceCommit": revision, "generation": binding["generation"], "pid": os.getpid(),
        }, strict_replace=True)

    async def reconcile_forever() -> None:
        while not stopped.is_set():
            try:
                await asyncio.to_thread(service.reconcile)
            except Exception as exc:
                atomic_write_json(runtime_dir / "reconcile-error.json", {"errorType": type(exc).__name__}, strict_replace=True)
            try:
                await asyncio.wait_for(stopped.wait(), timeout=1)
            except TimeoutError:
                pass

    def drain(*, close_directory: bool = True) -> None:
        # A Team acceptance opens four native Agent runtimes in addition to
        # the gateway target. Give their existing owners one shared bounded
        # drain deadline instead of treating the single-Agent budget as proof
        # that all Team model resources have retired.
        deadline = time.monotonic() + 30
        team_result = team_runtime.shutdown_generic_workflow_executor(deadline=deadline)
        for task in service.store.list_nonterminal():
            if task.get("sessionId"):
                sessions.request_stop_session_turn(task["sessionId"], expected_turn_id=str(task.get("turnId") or ""), fast_ack=True)
        result = sessions.shutdown_session_service(deadline=deadline)
        if result.get("closed") and close_directory:
            directory_runtime.shutdown_session_directory_runtime(timeout=max(0, deadline - time.monotonic()))
        unchanged = hashlib.sha256(binding["source_config"].read_bytes()).hexdigest() == binding["source_hash"]
        atomic_write_json(runtime_dir / "drain.json", {
            "generation": binding["generation"], "closed": bool(result.get("closed")) and close_directory,
            "directoryClosed": not directory_runtime.is_directory_store_open(), "sourceConfigUnchanged": unchanged,
            "teamExecutorClosed": bool(team_result.get("closed")),
            "nativeDrain": result,
        }, strict_replace=True)

    @asynccontextmanager
    async def lifespan(_app):
        reconcile_task = None
        ready_task = None

        async def publish_listening_ready():
            while not server.started:
                if server.should_exit:
                    return
                await asyncio.sleep(0.01)
            atomic_write_json(ready_path, state, strict_replace=True)

        try:
            try:
                await asyncio.to_thread(initialize)
            except Exception as exc:
                raise RuntimeError(f"Isolated target bootstrap failed ({type(exc).__name__}).") from None
            reconcile_task = asyncio.create_task(reconcile_forever())
            ready_task = asyncio.create_task(publish_listening_ready())
            yield
        finally:
            stopped.set()
            if ready_task is not None:
                ready_task.cancel()
                with suppress(asyncio.CancelledError):
                    await ready_task
            reconciliation_stopped = True
            if reconcile_task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(reconcile_task), timeout=15)
                except (asyncio.CancelledError, TimeoutError):
                    reconciliation_stopped = False
            await asyncio.to_thread(drain, close_directory=reconciliation_stopped)
            for owned_path in (ready_path, binding["descriptor"]):
                if owned_path.is_file():
                    payload = json.loads(owned_path.read_text(encoding="utf-8"))
                    if payload.get("generation") == binding["generation"]:
                        owned_path.unlink()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(WebControlGuardMiddleware)
    app.include_router(external_agent.router, prefix="/api")
    app.include_router(launcher_assistant_management.router, prefix="/api")

    @app.get("/api/control-token")
    def token(request: Request):
        ensure_control_source(request)
        return control_token_payload()

    @app.get("/api/health")
    def health(request: Request):
        ensure_control_source(request)
        return {"status": "ok", **state}

    @app.get("/api/fixture/identity")
    def identity(request: Request):
        error = validate_control_request(request)
        if error is not None:
            raise HTTPException(error.status_code, detail=error.detail)
        # Re-read native authority after task execution; the bootstrap snapshot
        # alone cannot prove dispatch did not provision a project assistant.
        agents = directory.list_agents(include_archived=True, detail="full")
        result = {**state, "noPaCount": sum(
            bool((row.get("metadata") or {}).get("personalAssistantProfile"))
            for row in agents
        )}
        if binding["session_config_history"]:
            repository = directory_runtime.get_open_directory_store().repository
            expected = state["sessionConfigFixture"]["expected"]["config"]
            result["sessionConfigReadback"] = {
                "agentConfigRevisionId": repository.get_session(expected["sessionId"])["agentConfigRevisionId"],
                "currentRevisionId": repository.get_current_agent_config(expected["agentId"])["configRevisionId"],
                "activeSessionId": repository.get_active_session_id(),
            }
        return result

    class ShutdownRequest(BaseModel):
        generation: str

    @app.post("/api/fixture/shutdown")
    def shutdown(request: Request, payload: ShutdownRequest):
        error = validate_control_request(request)
        if error is not None:
            raise HTTPException(error.status_code, detail=error.detail)
        if not secrets.compare_digest(payload.generation, binding["generation"]):
            raise HTTPException(409, detail="Fixture generation mismatch")
        server.should_exit = True
        return {"status": "stopping", "generation": binding["generation"]}

    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=15))
    try:
        server.run(sockets=[sock])
        return 0 if server.started else 2
    finally:
        sock.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--session-config-history", action="store_true",
                        help="Prepare an isolated ordinary direct Session pinned to historical model config A while current is B")
    args = parser.parse_args()
    try:
        return _serve(_prepare(args))
    except Exception as exc:
        # Config validation errors can contain input values. Never emit their
        # message/traceback, provider settings, environment, or control token.
        error = str(exc) if isinstance(exc, IsolationViolation) else "fixture_start_failed"
        print(json.dumps({"status": "blocked", "errorType": type(exc).__name__, "boundary": error}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
