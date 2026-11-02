#!/usr/bin/env python3
"""Real cross-project dispatch; Launcher lifecycle remains a separate proof.

Only human messages request tasks. The diagnostic adapter performs read-only
discovery before any task exists, using authority created by the real host.
Private clones, their hooks, descriptors and inputs never touch the source repo.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import secrets
import shutil
import time
from urllib.parse import quote

import anyio

from core.infrastructure.no_console_git import run_git
from scripts import acceptance_local_assistant_development as base
from scripts.acceptance_assistant_multitask import actions, native_proof, tagged_value
from scripts.assistant_acceptance_support import AssistantAcceptanceFixture, tool_calls
from scripts.local_quality_gate import git_hook_isolated_environment

require = base.require
AcceptanceFailure = base.AcceptanceFailure
MARKER_PATH = Path("tests/fixtures/assistant_projects/marker.json")
SUCCESS_MARKER = "ASSISTANT_PROJECT_ROOTS_VERIFIED"


@dataclass(frozen=True)
class ProjectSlot:
    name: str
    project_id: str
    root: Path
    label: str
    value: int

    def snapshot(self) -> dict:
        path = (self.root / MARKER_PATH).resolve()
        require(path.is_file() and not path.is_symlink() and path.stat().st_size < 4096,
                "project_marker_invalid")
        raw = path.read_bytes()
        require(json.loads(raw) == {"slot": self.name, "label": self.label, "value": self.value},
                "project_marker_changed")
        return {"path": path, "text": raw.decode("utf-8"), "sha256": hashlib.sha256(raw).hexdigest()}


def fixture_git(root: Path, *args: str, env: dict | None = None) -> str:
    # The hook helper clears repository bindings; also discard inherited Git
    # config/identity overrides before touching a temporary repository.
    isolated = {key: value for key, value in git_hook_isolated_environment().items()
                if not key.upper().startswith("GIT_")}
    if env is not None:
        isolated.update({key: value for key, value in env.items() if not key.upper().startswith("GIT_")})
    result = run_git(list(args), cwd=root, env=isolated, timeout=120)
    require(result.returncode == 0, "project_fixture_git_failed")
    return result.stdout.strip()


def _common_dir(root: Path, env: dict | None = None) -> Path:
    return Path(fixture_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir", env=env)).resolve()


def assert_checkout_layout(home: Path, source: Path, roots: dict[str, Path], env: dict | None = None) -> dict:
    require(set(roots) == {"A", "A1", "B"} and len({path.resolve() for path in roots.values()}) == 3,
            "project_checkout_roots_not_distinct")
    common = {key: _common_dir(root, env) for key, root in roots.items()}
    source_common = _common_dir(source)
    require(all(base.inside(root, home) for root in roots.values())
            and all(base.inside(path, home) and path != source_common for path in common.values()),
            "project_checkout_not_private")
    require(common["A"] == common["A1"] and common["A"] != common["B"],
            "project_git_common_dir_isolation_failed")
    require((roots["A"] / ".git").is_dir() and (roots["B"] / ".git").is_dir()
            and (roots["A1"] / ".git").is_file(), "project_checkout_kind_invalid")
    require(fixture_git(roots["A"], "branch", "--show-current", env=env) == "main"
            and fixture_git(roots["B"], "branch", "--show-current", env=env) == "main"
            and fixture_git(roots["A1"], "branch", "--show-current", env=env).startswith("codex/"),
            "project_fixture_branch_invalid")
    registered = fixture_git(roots["A"], "worktree", "list", "--porcelain", env=env)
    require(any(Path(line[9:]).resolve() == roots["A1"].resolve()
                for line in registered.splitlines() if line.startswith("worktree ")),
            "project_branch_worktree_not_registered")
    return {"independentGitCommonDirs": True, "branchIsRegisteredWorktree": True,
            "roots": {key: str(root) for key, root in roots.items()}}


def prepare_projects(fixture: AssistantAcceptanceFixture) -> list[ProjectSlot]:
    from core.launcher.frontend_build import resolve_active_frontend_dist
    require(not fixture.backends and fixture.host_process is None, "project_fixture_requires_unused_runtime")
    generation = secrets.token_hex(6)
    parent = fixture.home / "checkouts"
    parent.mkdir()
    roots = {"A": parent / "project-a", "A1": parent / "project-a-branch", "B": parent / "project-b"}
    # Read the configured human identity from the real source without writing it.
    identity = {key: fixture_git(fixture.source, "config", "--get", "user." + key) for key in ("name", "email")}
    require(all(identity.values()), "configured_human_git_identity_required")
    hooks = fixture.home / "empty-fixture-hooks"
    hooks.mkdir()
    slots = [ProjectSlot(name, "opaque-" + generation + "-" + name.lower(), roots[name],
                         name + "_VALUE", 100000 + secrets.randbelow(900000)) for name in ("A", "A1", "B")]
    require(len({slot.value for slot in slots}) == 3, "project_marker_values_not_distinct")

    def commit_input(slot: ProjectSlot, *, project_identity: bool) -> None:
        require(base.inside(_common_dir(slot.root, fixture.env), fixture.home), "fixture_hooks_outside_private_repo")
        fixture_git(slot.root, "config", "--local", "core.hooksPath", str(hooks), env=fixture.env)
        for key, value in identity.items():
            fixture_git(slot.root, "config", "--local", "user." + key, value, env=fixture.env)
        base.private_json(slot.root / MARKER_PATH, {"slot": slot.name, "label": slot.label, "value": slot.value})
        files = [MARKER_PATH.as_posix()]
        if project_identity:
            base.private_json(slot.root / ".vibelution" / "project.json",
                              {"schemaVersion": 1, "projectId": "fixture-" + generation + "-" + slot.name.lower()})
            files.append(".vibelution/project.json")
        fixture_git(slot.root, "add", "--", *files, env=fixture.env)
        fixture_git(slot.root, "-c", "commit.gpgsign=false", "commit", "-m", "Add private project acceptance input", env=fixture.env)

    for slot in (slots[0], slots[2]):
        fixture_git(parent, "-c", "core.hooksPath=" + str(hooks), "clone", "--shared", "--no-hardlinks",
                    "--branch", "main", str(fixture.source), str(slot.root), env=fixture.env)
        fixture_git(slot.root, "config", "--local", "core.hooksPath", str(hooks), env=fixture.env)
        fixture_git(slot.root, "switch", "-c", "codex/acceptance-input-" + generation, env=fixture.env)
        commit_input(slot, project_identity=True)
        fixture_git(slot.root, "switch", "main", env=fixture.env)
        fixture_git(slot.root, "merge", "--ff-only", "codex/acceptance-input-" + generation, env=fixture.env)
    fixture_git(roots["A"], "worktree", "add", "-b", "codex/acceptance-branch-" + generation,
                str(roots["A1"]), "main", env=fixture.env)
    commit_input(slots[1], project_identity=False)
    assert_checkout_layout(fixture.home, fixture.source, roots, fixture.env)
    for slot in slots:
        slot.snapshot()
        require(not fixture_git(slot.root, "status", "--porcelain", env=fixture.env), "project_fixture_not_clean")
        # Static assets are a physical copy, never a node_modules/venv link.
        built = resolve_active_frontend_dist(fixture.source)
        if built.is_dir():
            shutil.copytree(built, slot.root / "web" / "dist", dirs_exist_ok=True)
    project_ids = [base.read_json(roots[name] / ".vibelution" / "project.json")["projectId"] for name in ("A", "A1", "B")]
    require(project_ids[0] == project_ids[1] and project_ids[0] != project_ids[2], "fixture_native_project_ids_not_isolated")
    return slots


def _native_task_ids(fixture: AssistantAcceptanceFixture) -> dict[str, set[str]]:
    return {key: {path.stem for path in (backend.runtime_root / "local_assistant_tasks" / "tasks").glob("*.json")}
            for key, backend in fixture.backends.items()}


async def diagnose_projects(fixture: AssistantAcceptanceFixture, slots: list[ProjectSlot], agents: dict[str, str]) -> dict:
    from core.assistant_runtime.dispatch import DispatchError, DispatchService
    from core.assistant_runtime.local_project_client import LocalAssistantBackendClient

    require(all(not value for value in _native_task_ids(fixture).values()) and not fixture.dispatches(),
            "diagnostic_must_precede_native_tasks")
    # Real assistant_host bootstrap owns creation. Never synthesize this token.
    authority = base.read_json(fixture.profile / "launcher-authority.json", limit=4096)
    require(authority.get("schemaVersion") == 1 and authority.get("status") == "enabled"
            and isinstance(authority.get("token"), str), "native_launcher_authority_missing")
    capability = authority["token"]
    service = DispatchService(fixture.home / "project-diagnostics", {slot.project_id: slot.root for slot in slots},
        client_factory=lambda root, state_path: LocalAssistantBackendClient(root, state_path=state_path, capability=capability))
    listed = await service.available_projects()
    require({row.get("projectId") for row in listed.get("projects", [])} == {slot.project_id for slot in slots}
            and listed.get("skippedProjects") == [], "real_project_discovery_incomplete")
    observed = {}
    for slot in slots:
        result = await service.discover(slot.project_id)
        ids = {row.get("agentId") for row in result.get("agents", [])}
        require(agents[slot.project_id] in ids and not (ids & (set(agents.values()) - {agents[slot.project_id]})),
                "project_agent_discovery_wrong_root")
        observed[slot.project_id] = agents[slot.project_id]
    try:
        await service.discover("unknown-project-" + secrets.token_hex(6))
    except DispatchError as exc:
        require(exc.code == "PROJECT_NOT_AUTHORIZED", "unknown_project_wrong_error")
    else:
        raise AcceptanceFailure("unknown_project_was_accepted")
    descriptor_path = fixture.backends[slots[0].project_id].runtime_root / "launcher" / "state.json"
    original_bytes = descriptor_path.read_bytes()
    descriptor = base.read_json(descriptor_path)
    before = _native_task_ids(fixture)
    mismatch = None
    try:
        base.private_json(descriptor_path, {**descriptor, "url": fixture.backends[slots[2].project_id].url})
        try:
            await service.discover(slots[0].project_id)
        except DispatchError as exc:
            mismatch = exc.code
        require(mismatch == "RUNTIME_IDENTITY_MISMATCH", "real_backend_root_mismatch_not_rejected")
    finally:
        descriptor_path.write_bytes(original_bytes)
    restored = await service.discover(slots[0].project_id)
    require(agents[slots[0].project_id] in {row.get("agentId") for row in restored.get("agents", [])},
            "same_adapter_did_not_recover_after_descriptor_restore")
    require(_native_task_ids(fixture) == before and all(not value for value in before.values())
            and not service.list_dispatches() and not fixture.dispatches(), "diagnostics_created_native_tasks")
    return {"status": "passed", "availableProjectCount": 3, "discoveredAgentIds": observed,
            "unknownProjectCode": "PROJECT_NOT_AUTHORIZED", "misroutedBackendCode": mismatch,
            "sameDispatchServiceRecovered": True, "nativeTasksBefore": 0, "nativeTasksAfter": 0,
            "credentialSource": "native_host_bootstrap"}


def task_message(slots: list[ProjectSlot], agents: dict[str, str], goal_id: str, dispatch_ids: list[str]) -> str:
    targets = "；".join(f"{slot.name}: project_id={slot.project_id}, agent_id={agents[slot.project_id]}, "
                         f"dispatch_id={dispatch_ids[index]}, 文件绝对路径={slot.root / MARKER_PATH}, 输出标签={slot.label}"
                         for index, slot in enumerate(slots))
    return ("这是已授权的真实跨项目和分支只读验收。你自己通过真实工具发现、派遣并汇总，不得创建Agent。"
            f"三项目标为：{targets}。goal_id={goal_id}。先用index/describe读取契约，再用projects和agents核对三根。"
            "使用delegation_goal_create绑定上述精确三组project_id/agent_id，permission_profile=read_only，"
            "max_tasks=3，ttl_minutes=30。然后用dispatch_derived自主写三项读取任务，参数只有"
            "goal_id/project_id/agent_id/dispatch_id/task/permission_profile，不要title。"
            "每个目标必须在自己真实root内用read_file_tool读取上面自己的绝对路径，offset=0/max_lines=0，"
            "读取JSON后按分配标签输出<标签>=<文件中的value整数>，并报告slot。不能从其他根读取、"
            "执行终端、写文件、继续派遣、改权限或配置，不得猜marker值。"
            "派完三项后持续用receipt（仅dispatch_id）取原生结果。未知时保留原ID，不新增第四项或重建goal。"
            f"所有原生成功后最终回答带{SUCCESS_MARKER}及三项标签和真实值，说明三根结果分别来自哪个project_id。"
            "任何审批或失败保留未完成，不宣称成功。")


def assert_native_binding(slot: ProjectSlot, agent_id: str, dispatch: dict, task: dict) -> dict:
    require(dispatch.get("projectId") == slot.project_id and dispatch.get("agentId") == agent_id,
            "project_dispatch_target_mismatch")
    require(dispatch.get("nativeTaskId") == task.get("taskId") and task.get("agentId") == agent_id
            and all(isinstance(task.get(key), str) and task[key] for key in ("taskId", "sessionId", "turnId")),
            "project_native_identity_mismatch")
    require(task.get("effectivePermissionProfile") == "read_only"
            and Path(str(task.get("localWorkspacePath") or "")).resolve() == slot.root.resolve(),
            "project_native_workspace_mismatch")
    return {"projectId": slot.project_id, "root": str(slot.root), "agentId": agent_id,
            "nativeTaskId": task["taskId"], "sessionId": task["sessionId"], "turnId": task["turnId"]}


def launcher_handoff(fixture: AssistantAcceptanceFixture, slots: list[ProjectSlot], *, electron: Path,
                     desktop_dist: Path, pythonw: Path) -> dict:
    """Prepare an ordinary Electron launch, without launching or claiming success.

    The caller must stop the standalone host/backends first and own any Popen it
    starts. Its Terra operator uses the real page's native-frame send IPC; only
    journal tool calls plus real main/branch receipts can complete this phase.
    """
    require(electron.is_file() and pythonw.is_file() and (desktop_dist / "main.js").is_file(),
            "launcher_handoff_build_missing")
    a = next(slot for slot in slots if slot.name == "A")
    stage = fixture.home / "launcher-lifecycle"
    local = stage / "localappdata"
    user_data = local / "Vibelution" / "DesktopShell"
    config = stage / "config" / "config.toml"
    base.write_config(config, fixture._snapshot, stage / "data")
    # The normal Electron app lock fixes userData here before single-instance
    # locking; --user-data-dir cannot substitute for this private LOCALAPPDATA.
    base.private_json(user_data / "vibelution-launch-profile.json", {
        "schemaVersion": 1, "workspaceRoot": str(a.root), "operatorConfigPath": str(config), "pythonPath": str(pythonw)})
    for slot in slots:
        target = slot.root / "desktop/electron/dist"
        if desktop_dist.resolve() != target.resolve():
            shutil.copytree(desktop_dist, target, dirs_exist_ok=True)
    target_dist = a.root / "desktop" / "electron" / "dist"
    environment_paths = {"LOCALAPPDATA": local, "APPDATA": stage / "appdata", "USERPROFILE": stage / "user",
                         "HOME": stage / "user", "VIBELUTION_PROJECTS_HOME": stage / "projects",
                         "VIBELUTION_DATA_HOME": stage / "data", "VIBELUTION_CONFIG_HOME": config.parent}
    for path in environment_paths.values():
        path.mkdir(parents=True, exist_ok=True)
    args = [str(electron), str(target_dist / "main.js"), "--workspace", str(a.root), "--config", str(config),
            "--project", str(a.root), "--hidden-presentation", "--local-debugging"]
    plan = {"schemaVersion": 1, "status": "not_tested", "workspaceRoot": str(a.root), "userDataRoot": str(user_data),
            "argvPrefix": args, "operations": ["start", "status", "restart", "stop"],
            "environmentOverrides": {**{key: str(value) for key, value in environment_paths.items()},
                                     "VIBELUTION_CONFIG_PATH": str(config), "VIBELUTION_ELECTRON_REGISTER_DEEP_LINKS": "0"},
            "discoverDebugArgv": [str(pythonw.with_name("python.exe")), str(a.root / "scripts" / "desktop_debug.py"),
                                  "--project", str(a.root)],
            "targets": [{"slot": slot.name, "projectId": slot.project_id, "root": str(slot.root)} for slot in slots],
            "requiredEvidence": ["real native-frame send IPC", "project_lifecycle tool journal",
                                 "electron_main and electron_branch completed receipts", "owned process exit"],
            "standaloneProcessesMustStopBeforeStart": True, "pid": None, "cdp": None}
    path = stage / "control" / "instructions.json"
    base.private_json(path, plan)
    return {"status": "not_tested", "reason": "real_native_frame_lifecycle_receipts_required", "instructionsPath": str(path)}


def run_case(fixture: AssistantAcceptanceFixture, evidence: dict, timeout: float = 1200) -> None:
    evidence.update(crossProject={"status": "starting"}, launcherLifecycle={"status": "not_tested",
                    "reason": "real_native_frame_lifecycle_receipts_required"}, approvalCount=0, reminders=0)
    slots = prepare_projects(fixture)
    roots = {slot.name: slot.root for slot in slots}
    evidence["checkoutLayout"] = assert_checkout_layout(fixture.home, fixture.source, roots, fixture.env)
    agents = {}
    for slot in slots:
        fixture.start_backend(slot.project_id, slot.root)
        agents[slot.project_id] = fixture.create_agent("Project acceptance " + slot.name, slot.project_id)
    require(len(set(agents.values())) == 3, "project_agents_not_distinct")
    fixture.start_host()
    # This sole reader has an independent ledger and no tasks. Finish it before
    # asking the actual host/model to admit any delegated work.
    with base.environment(fixture.env):
        evidence["diagnostics"] = anyio.run(diagnose_projects, fixture, slots, agents)
    generation = secrets.token_hex(6)
    goal_id = "project-goal-" + generation
    dispatch_ids = ["project-" + generation + "-" + slot.name.lower() for slot in slots]
    expected = {slot.label: slot.value for slot in slots}
    snapshots = [slot.snapshot() for slot in slots]
    evidence.update(goalId=goal_id, dispatchIds=dispatch_ids, expectedValues=expected, nativeTasks=[])
    fixture.send(task_message(slots, agents, goal_id, dispatch_ids), request_id=goal_id)
    deadline, last_reminder = time.monotonic() + timeout, time.monotonic()
    tasks, dispatches_by_id = {}, {}
    while time.monotonic() < deadline:
        require(fixture.host_process is not None and fixture.host_process.poll() is None, "assistant_host_exited")
        fixture.assert_no_approvals()
        dispatches = fixture.dispatches()
        require(all(row.get("dispatchId") in dispatch_ids for row in dispatches)
                and len({row.get("dispatchId") for row in dispatches}) == len(dispatches), "unexpected_project_dispatch")
        for dispatch in dispatches:
            dispatch_id = dispatch["dispatchId"]
            slot = slots[dispatch_ids.index(dispatch_id)]
            dispatches_by_id[dispatch_id] = dispatch
            require(dispatch.get("projectId") == slot.project_id and dispatch.get("agentId") == agents[slot.project_id],
                    "project_dispatch_target_mismatch")
            if dispatch.get("nativeTaskId"):
                task = fixture.task(dispatch["nativeTaskId"], slot.project_id)
                tasks[dispatch_id] = task
                if task.get("status") in base.TERMINAL:
                    require(task["status"] == "succeeded", "project_native_task_failed")
        evidence["nativeTasks"] = [{"dispatchId": key, "nativeTaskId": value.get("taskId"), "status": value.get("status")}
                                   for key, value in tasks.items()]
        events = fixture.assistant_events()
        answer = base.final_answer(events)
        if len(tasks) == 3 and all(task.get("status") == "succeeded" for task in tasks.values()) \
                and SUCCESS_MARKER in answer and all(tagged_value(answer, key, value) for key, value in expected.items()):
            break
        starts = {row.get("turnId") for row in events if row.get("eventType") == "turn_started"}
        ends = {row.get("turnId") for row in events if row.get("eventType") in {"turn_completed", "turn_failed", "turn_interrupted"}}
        if evidence["reminders"] < 3 and time.monotonic() - last_reminder > 45 and starts and starts <= ends:
            fixture.send(f"继续原goal_id={goal_id}和原三项dispatch_id={','.join(dispatch_ids)}。"
                         "先核对已保存任务；已派只查receipt，只补未派的原ID，禁止新goal/ID。"
                         "三项真实完成后按原标签报告真实值，不猜值。", request_id=goal_id + "-continue-" + str(evidence["reminders"]))
            evidence["reminders"] += 1
            last_reminder = time.monotonic()
        time.sleep(2)
    else:
        raise AcceptanceFailure("cross_project_model_acceptance_timeout")

    require(all(len({task[key] for task in tasks.values()}) == 3 for key in ("taskId", "sessionId", "turnId")),
            "project_native_records_not_distinct")
    proofs = []
    calls = actions(fixture.assistant_events())
    goals = [row for row in calls if row["action"] == "delegation_goal_create" and row["result"].get("goalId") == goal_id]
    require(goals, "project_real_goal_missing")
    target_pairs = {(slot.project_id, agents[slot.project_id]) for slot in slots}
    for row in goals:
        args = row["parameters"]
        require(args.get("goal_id") == goal_id and args.get("permission_profile") == "read_only"
                and args.get("max_tasks") == 3 and args.get("ttl_minutes") == 30
                and {(item.get("project_id"), item.get("agent_id")) for item in args.get("targets", [])} == target_pairs,
                "project_goal_binding_mismatch")
    for index, slot in enumerate(slots):
        dispatch_id, task = dispatch_ids[index], tasks[dispatch_ids[index]]
        identity = assert_native_binding(slot, agents[slot.project_id], dispatches_by_id[dispatch_id], task)
        detail = fixture.backend(slot.project_id, "/api/sessions/" + quote(task["sessionId"], safe="")
                                 + "?messageLimit=0&transcriptScope=none&includeSecondary=false")
        require(detail.get("agentId") == agents[slot.project_id]
                and detail.get("id", detail.get("sessionId")) == task["sessionId"], "project_session_owner_mismatch")
        # Journals carry session/turn identity. Agent ownership comes from the
        # actual session DTO and native task, not a nonexistent journal field.
        events = fixture.target_events(task)
        require(events and all(row.get("sessionId") == task["sessionId"] and row.get("turnId") == task["turnId"]
                               for row in events),
                "project_journal_identity_mismatch")
        proof = native_proof(task, events, base.journal_events(fixture.home, task["sessionId"]),
                             {slot.label: slot.value}, [snapshots[index]])
        reads = [row for row in tool_calls(events)
                 if row["callName"] == "read_file_tool"]
        require(reads and all(Path(str(row["args"].get("file_path") or "")).resolve() == snapshots[index]["path"] for row in reads),
                "project_read_crossed_root")
        proof.update(identity, dispatchId=dispatch_id)
        proofs.append(proof)
        derived = [row for row in calls if row["action"] == "dispatch_derived"
                   and row["parameters"].get("dispatch_id") == dispatch_id and row["result"].get("nativeTaskId") == task["taskId"]]
        require(derived and all(row["parameters"].get("goal_id") == goal_id
                and row["parameters"].get("permission_profile") == "read_only"
                and row["parameters"].get("project_id") == slot.project_id
                and row["parameters"].get("agent_id") == agents[slot.project_id] for row in derived), "project_real_derived_dispatch_missing")
        require(any(row["action"] == "receipt" and row["parameters"] == {"dispatch_id": dispatch_id}
                    and row["result"].get("nativeTaskId") == task["taskId"]
                    and (row["result"].get("receipt") or {}).get("status") == "succeeded" for row in calls),
                "project_real_success_receipt_missing")
        require(slot.snapshot()["sha256"] == snapshots[index]["sha256"], "project_marker_changed")
        policy = fixture.backend(slot.project_id, "/api/agents/" + agents[slot.project_id]).get("toolPolicy") or {}
        require(all(policy.get(key) == [] for key in ("allowedTools", "preferredTools", "readScopes", "writeScopes")),
                "project_permanent_agent_policy_changed")
    require(_native_task_ids(fixture) == {slot.project_id: {tasks[dispatch_ids[index]]["taskId"]}
                                        for index, slot in enumerate(slots)}, "unexpected_project_native_records")
    fixture.assert_no_approvals()
    evidence.update(nativeTasks=proofs, modelRequests=base.model_requests(fixture.home),
                    crossProject={"status": "passed", "realProjectCount": 2, "registeredBranchCount": 1,
                                  "realDerivedDispatchCount": 3, "assistantReturnedVerifiedValues": True,
                                  "ordinaryAgentPoliciesRemainEmpty": True})
    require(all(value > 0 for value in evidence["modelRequests"].values()), "real_model_requests_not_observed")


# Phase 2 helpers are deliberately separate from the frozen phase-1 entrypoint.
def lifecycle_proof(expected: dict, request_record: dict, native_result: dict, events: list[dict]) -> dict:
    """Join a real journal action, request binding and exact native settlement."""
    import math
    import re
    from scripts.acceptance_assistant_multitask import event_time

    request = {key: expected[key] for key in ("projectId", "operation", "requestId")}
    require(request_record.get("schemaVersion") == 1 and request_record.get("request") == request,
            "launcher_request_binding_mismatch")
    binding, command = request_record.get("binding") or {}, request_record.get("command") or {}
    require(Path(str(binding.get("workspaceRoot") or "")).resolve() == Path(expected["root"]).resolve(),
            "launcher_request_root_mismatch")
    command_id = command.get("commandId")
    branch = expected["slot"] == "A1"
    require(isinstance(command_id, str) and re.fullmatch(r"cmd_[A-Za-z0-9_-]{1,160}", command_id)
            and command.get("operation") == expected["operation"]
            and command.get("type") == {"start": "open", "stop": "close", "restart": "restart"}[expected["operation"]]
            and (command.get("owner") == "branch") == branch, "launcher_native_command_mismatch")
    require(native_result.get("schemaVersion") == 1
            and native_result.get("source") == ("electron_branch" if branch else "electron_main")
            and all(native_result.get(key) == command[key] for key in ("commandId", "operation", "type"))
            and native_result.get("accepted") is True and native_result.get("ok") is True
            and native_result.get("completed") is True and native_result.get("timedOut", False) is False,
            "launcher_real_native_settlement_missing")
    if branch:
        require(native_result.get("owner") == "branch" and command.get("instanceId")
                and native_result.get("instanceId") == command["instanceId"]
                and Path(str(native_result.get("workspaceRoot") or "")).resolve() == Path(expected["root"]).resolve(),
                "launcher_branch_settlement_binding_mismatch")
    started = event_time({"timestamp": native_result.get("startedAt")})
    settled = event_time({"timestamp": native_result.get("settledAt")})
    duration = native_result.get("runMs")
    require(settled >= started and type(duration) in (int, float) and math.isfinite(duration) and duration >= 0,
            "launcher_native_settlement_time_invalid")
    parameters = {"project_id": expected["projectId"], "operation": expected["operation"], "request_id": expected["requestId"]}
    calls = actions(events)
    sent = [row for row in calls if row["action"] == "project_lifecycle" and row["parameters"] == parameters]
    receipts = [row for row in calls if row["action"] == "project_lifecycle_receipt" and row["parameters"] == parameters
                and all(row["result"].get(key) == value for key, value in request.items())
                and row["result"].get("state") == "completed" and row["result"].get("accepted") is True]
    require(sent and receipts, "launcher_real_assistant_lifecycle_journal_missing")
    return {**request, "root": expected["root"], "source": native_result["source"], "commandId": command_id,
            "nativeCompleted": True, "nativeStartedAt": native_result["startedAt"],
            "nativeSettledAt": native_result["settledAt"], "nativeRunMs": duration,
            "journalWriteCallId": sent[0]["callId"], "journalReceiptCallId": receipts[-1]["callId"],
            **({"instanceId": command["instanceId"]} if branch else {})}


def _private_profile_events(profile: Path) -> list[dict]:
    paths = list(profile.rglob("turn_journal.jsonl"))
    require(len(paths) <= 8, "launcher_journal_count_exceeded")
    rows, total = [], 0
    for path in paths:
        require(base.inside(path, profile) and not path.is_symlink(), "launcher_journal_path_invalid")
        total += path.stat().st_size
        require(total <= base.MAX_JOURNAL_BYTES, "launcher_journal_bytes_exceeded")
        with path.open(encoding="utf-8") as stream:
            rows.extend(json.loads(line) for line in stream if line.endswith("\n"))
    return rows


class IsolatedLauncherController:
    """Parent-owned normal Electron process; no test runner or main-control RPC.

    Construct after phase 1, call ``stop_standalone`` then ``start``. Give the
    resulting control JSON to the sole Terra operator. ``prepare_operation``
    returns a message to send via the genuine native-frame invoke bridge;
    ``wait_operation`` observes actual journals/files/processes, never a done
    flag. Terra must call requestDesktopShellExit on an owned native surface;
    ``wait_exit`` confirms this Popen and its captured descendants exited.
    """

    def __init__(self, fixture: AssistantAcceptanceFixture, slots: list[ProjectSlot], *,
                 electron: Path, desktop_dist: Path, pythonw: Path):
        self.fixture, self.slots = fixture, {slot.name: slot for slot in slots}
        build_root = desktop_dist.resolve().parents[2]
        expected_tree = fixture_git(self.slots["A"].root, "rev-parse", "HEAD:desktop/electron", env=fixture.env)
        provenance = base.read_json(desktop_dist / "unpackaged-provenance.json")
        require(provenance.get("electronTreeHash") == expected_tree
                and fixture_git(build_root, "rev-parse", "HEAD:desktop/electron") == expected_tree,
                "launcher_build_git_tree_mismatch")
        handoff = launcher_handoff(fixture, slots, electron=electron, desktop_dist=desktop_dist, pythonw=pythonw)
        self.control_path = Path(handoff["instructionsPath"])
        self.plan = base.read_json(self.control_path)
        self.stage = self.control_path.parents[1]
        self.env = {**fixture.env, **self.plan["environmentOverrides"]}
        for key in ("TEMP", "TMP", "TMPDIR"):
            self.env[key] = str(self.stage / "tmp")
        (self.stage / "tmp").mkdir(exist_ok=True)
        for key in ("ELECTRON_RUN_AS_NODE", "VIBELUTION_WEB_CONTROL_TOKEN", "VIBELUTION_ASSISTANT_TOKEN"):
            self.env.pop(key, None)
        self.python = pythonw.with_name("python.exe")
        self.profile = Path(self.plan["userDataRoot"]) / "assistant" / "profile"
        self.ports = fixture.record.setdefault("launcherPorts", {})
        for name in ("A", "B"):
            if name not in self.ports:
                self.ports[name] = {kind: base.acceptance_runtime._allocate_port(
                    lease_root=fixture.home / "launcher-port-leases", kind=kind, instance_id="launcher-" + name,
                    candidates=range(start, start + 1000))
                    for kind, start in (("backend", 20000 + secrets.randbelow(10000)),
                                        ("frontend", 40000 + secrets.randbelow(10000)))}
        from core.launcher.frontend_build import inspect_frontend_build
        builds = []
        with base.environment(fixture.env):
            for name, slot in self.slots.items():
                build = inspect_frontend_build(slot.root)
                require(build["current"], "launcher_matching_frontend_build_required")
                builds.append({"slot": name, "dist": build["dist"], "buildKey": build["buildKey"],
                               "frontendTree": build["buildInputs"]["frontendTree"]})
        self.process = None
        self.create_time = None
        self._children = {}
        self.plan.update(profileRoot=str(self.profile),
            projectRegistryPath=str(Path(self.plan["userDataRoot"]) / "assistant" / "projects.json"),
            instanceRegistryPath=str(Path(self.env["LOCALAPPDATA"]) / "Vibelution" / "instances.json"),
            electronTreeHash=expected_tree, requests=[], registeredProjects=[],
            nativeSendBridge="window.vibelutionLauncherAssistant.invoke({operation:'send',message,requestId})",
             nativeOpenLauncherBridge="window.vibelutionLauncherAssistant.invoke({operation:'openLauncher'})",
            nativeExitBridge="window.vibelutionLauncher.requestDesktopShellExit()",
             nativeExitInstruction="Open the Launcher from the assistant bridge, rediscover that owned Launcher page, then use its exit bridge.",
             privatePorts=self.ports, frontendBuilds=builds,
            registrationInstruction="Use ordinary CLI status for each private workspace; read actual projects.json registrations. Never write registry IDs.")
        self._save()

    def _save(self):
        base.private_json(self.control_path, self.plan)

    def stop_standalone(self) -> None:
        self.fixture.stop_host()
        for project_id, instance_id in self.fixture._owned_backend_ids.items():
            base.acceptance_runtime.stop_instance(instance_id=instance_id, runtime_home=self.fixture.runtime_home)
            state = base.acceptance_runtime.status_instance(instance_id=instance_id, runtime_home=self.fixture.runtime_home)
            require(not any((state.get("processAlive") or {}).values()), "standalone_backend_not_stopped")
            self.fixture.cleanup["backendStopped:" + project_id] = True
        self.fixture.cleanup["backendsStopped"] = True

    def _argv(self, operation: str, *, root: Path | None = None) -> list[str]:
        require(operation in {"start", "stop", "restart", "status"}, "invalid_launcher_cli_operation")
        args = list(self.plan["argvPrefix"])
        args[1] = str((root or self.slots["A"].root) / "desktop/electron/dist/main.js")
        args[args.index("--workspace") + 1] = str(root or self.slots["A"].root)
        args[args.index("--project") + 1] = str(root or self.slots["A"].root)
        return [*args, operation]

    def _target_environment(self, root: Path) -> dict:
        name = next(name for name, slot in self.slots.items() if slot.root.resolve() == root.resolve())
        ports = self.ports["A" if name == "A1" else name]
        return {**self.env, "VIBELUTION_PORT": str(ports["backend"]),
                "AGENT_WORKBENCH_BACKEND_PORT": str(ports["backend"]),
                "VIBELUTION_FRONTEND_PORT": str(ports["frontend"]), "PYTHONIOENCODING": "utf-8"}

    def start(self, timeout: float = 120, *, root: Path | None = None) -> dict:
        import subprocess
        import tomllib
        from config.toml_writer import dumps_public_config
        from scripts.windowless_subprocess import no_window_subprocess_kwargs

        require(self.process is None and self.fixture.cleanup.get("assistantStopped")
                and self.fixture.cleanup.get("backendsStopped"), "standalone_runtime_must_stop_first")
        target = (root or self.slots["A"].root).resolve()
        require(target in {slot.root.resolve() for slot in self.slots.values()}, "launcher_start_target_outside_fixture")
        child_env = self._target_environment(target)
        config_path = Path(self.env["VIBELUTION_CONFIG_PATH"])
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        config.setdefault("workbench", {}).update(backend_port=int(child_env["VIBELUTION_PORT"]),
                                                 frontend_port=int(child_env["VIBELUTION_FRONTEND_PORT"]))
        config_path.write_text(dumps_public_config(config), encoding="utf-8")
        with (self.stage / "electron.stdout.log").open("ab", buffering=0) as stdout, \
                (self.stage / "electron.stderr.log").open("ab", buffering=0) as stderr:
            self.process = subprocess.Popen(self._argv("start", root=target), cwd=target, env=child_env,
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, **no_window_subprocess_kwargs())
        self.create_time = base.acceptance_runtime._process_create_time(self.process.pid)
        self.fixture.cleanup["launcherElectronStopped"] = False
        self.plan.update(pid=self.process.pid, createTime=self.create_time, status="starting", workspaceRoot=str(target))
        self._save()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            require(self.process.poll() is None, "isolated_electron_exited_before_ready")
            result = subprocess.run([str(self.python), str(target / "scripts" / "desktop_debug.py"),
                "--project", str(target)], cwd=target, env=child_env,
                stdin=subprocess.DEVNULL, capture_output=True, timeout=10, **no_window_subprocess_kwargs())
            if result.returncode == 0:
                debug = json.loads(result.stdout)
                require(debug.get("pid") == self.process.pid, "isolated_electron_debug_pid_mismatch")
                self.plan.update(status="ready_for_native_operator", cdp=debug)
                backend = self.backend_identity(target)
                if backend["port"] != int(child_env["VIBELUTION_PORT"]) or not self._backend_ready(backend, target):
                    self.plan["status"] = "waiting_for_bootstrap_backend"
                    self._save()
                    time.sleep(1)
                    continue
                self.plan["bootstrapBackend"] = backend
                self.refresh_registrations()
                self._capture_children()
                self._save()
                return {"instructionsPath": str(self.control_path), "pid": self.process.pid,
                        "workspaceRoot": str(target), "cdp": debug}
            time.sleep(1)
        raise AcceptanceFailure("isolated_electron_debug_readiness_timeout")

    def cli(self, operation: str, *, root: Path | None = None, timeout: float = 120) -> int:
        """Only ordinary native CLI, useful for private workspace observation."""
        import subprocess
        from scripts.windowless_subprocess import no_window_subprocess_kwargs

        target = (root or self.slots["A"].root).resolve()
        require(target in {slot.root.resolve() for slot in self.slots.values()}, "launcher_cli_target_outside_fixture")
        with (self.stage / "cli.stdout.log").open("ab", buffering=0) as stdout, \
                (self.stage / "cli.stderr.log").open("ab", buffering=0) as stderr:
            result = subprocess.run(self._argv(operation, root=target), cwd=target, env=self._target_environment(target),
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, timeout=timeout, **no_window_subprocess_kwargs())
        return result.returncode

    def refresh_registrations(self) -> list[dict]:
        path = Path(self.plan["projectRegistryPath"])
        if not path.is_file():
            return []
        stored = base.read_json(path)
        require(stored.get("schemaVersion") == 1 and isinstance(stored.get("registrations"), list),
                "launcher_real_project_registry_invalid")
        roots = {slot.root.resolve(): name for name, slot in self.slots.items()}
        rows = []
        for row in stored["registrations"]:
            if row.get("active") is True:
                root = Path(str(row.get("root") or "")).resolve()
                require(root in roots, "launcher_registered_root_outside_fixture")
                rows.append({"slot": roots[root], "projectId": row["baseProjectId"] + ":" + row["registrationUuid"],
                             "root": str(root), "integrationRoot": row["integrationRoot"]})
        require(len({row["slot"] for row in rows}) == len(rows), "launcher_registered_root_duplicate")
        self.plan["registeredProjects"] = rows
        self._save()
        return rows

    def _private_runtime_path(self, path: Path, root: Path) -> bool:
        path, root = path.resolve(), root.resolve()
        if base.inside(path, self.fixture.home):
            return True
        # A reused private checkout can retain its pre-migration runtime.
        # Only its own .runtime subtree is admitted, never a sibling project
        # or a junction resolving outside that verified checkout.
        legacy = root / ".runtime"
        return (root in {slot.root.resolve() for slot in self.slots.values()}
                and base.inside(path, root) and (path == legacy or base.inside(path, legacy)))

    def backend_identity(self, root: Path) -> dict:
        import psutil
        from vibelution_storage import resolve_project_runtime_home

        with base.environment(self.env):
            runtime = resolve_project_runtime_home(root)
        require(self._private_runtime_path(runtime, root), "launcher_runtime_outside_fixture")
        path = runtime / "launcher" / "state.json"
        state = base.read_json(path) if path.is_file() else {}
        pid = state.get("backendPid", 0)
        create_time = state.get("backendCreateTime")
        alive = type(pid) is int and pid > 0 and base.acceptance_runtime._process_matches(pid, create_time)
        if alive:
            require(Path(psutil.Process(pid).cwd()).resolve() == root.resolve(), "launcher_backend_process_root_mismatch")
            create_time = psutil.Process(pid).create_time()
        return {"root": str(root), "runtimeRoot": str(runtime), "pid": pid, "createTime": create_time, "alive": alive,
                "port": state.get("backendPort", state.get("port"))}

    def _backend_ready(self, identity: dict, root: Path) -> bool:
        port = identity.get("port")
        if not identity.get("alive") or type(port) is not int or not 0 < port < 65536:
            return False
        try:
            health = base.request(f"http://127.0.0.1:{port}", "/api/health", token="", timeout=5)
        except AcceptanceFailure:
            return False
        return (isinstance(health, dict) and health.get("status") == "ok" and health.get("routesReady") is True
                and Path(str(health.get("workspaceRoot") or "")).resolve() == root.resolve())

    def prepare_operation(self, slot_name: str, operation: str) -> dict:
        require(operation in {"start", "restart", "stop"}, "invalid_launcher_operation")
        rows = [row for row in self.refresh_registrations() if row["slot"] == slot_name]
        require(len(rows) == 1, "launcher_target_not_registered")
        row = rows[0]
        request_id = "lifecycle-" + secrets.token_hex(8)
        expected = {"slot": slot_name, "projectId": row["projectId"], "root": row["root"],
                    "operation": operation, "requestId": request_id,
                    "before": self.backend_identity(Path(row["root"]))}
        self.plan["requests"].append(expected)
        self._save()
        message = (f"这是已授权的私有fixture生命周期测试。只对project_id={row['projectId']}，"
            f"执行operation={operation}，保持request_id={request_id}。目标根为{row['root']}，"
            "不要操作其他项目。请经personal_assistant_manage_tool的project_lifecycle和真实原生审批执行，"
            "随后用同project_id/operation/request_id调用project_lifecycle_receipt直到completed且accepted=true。"
            "未知则保留原ID如实报告，禁止新ID重试、直接HTTP或终端替代。此消息只授权这个私有目标。")
        return {"request": expected, "nativeSend": {"operation": "send", "message": message,
                                                    "requestId": request_id + "-user"}}

    def wait_operation(self, expected: dict, timeout: float = 300) -> dict:
        deadline, last_failure = time.monotonic() + timeout, "launcher_request_not_observed"
        record_path = Path(self.plan["userDataRoot"]) / "assistant" / "lifecycle-requests" / (
            hashlib.sha256(expected["requestId"].encode()).hexdigest() + ".json")
        while time.monotonic() < deadline:
            require(self.process is not None and self.process.poll() is None, "isolated_electron_exited")
            if record_path.is_file():
                record = base.read_json(record_path, limit=16384)
                command, binding = record.get("command") or {}, record.get("binding") or {}
                if not command or not binding:
                    time.sleep(1)
                    continue
                manager = Path(str(binding.get("runtimeManagerDir") or ""))
                require(self._private_runtime_path(manager, Path(expected["root"])), "launcher_native_manager_outside_fixture")
                command_id = str(command.get("commandId") or "")
                require(command_id and all(char.isalnum() or char in "_-" for char in command_id),
                        "launcher_native_command_id_invalid")
                result_path = manager / ("branch-results" if expected["slot"] == "A1" else "results") / (command_id + ".json")
                if result_path.is_file():
                    try:
                        proof = lifecycle_proof(expected, record, base.read_json(result_path, limit=65536),
                                                _private_profile_events(self.profile))
                        after = self.backend_identity(Path(expected["root"]))
                        before = expected["before"]
                        old_alive = type(before.get("pid")) is int and before["pid"] > 0 and \
                            base.acceptance_runtime._process_matches(before["pid"], before.get("createTime"))
                        operation = expected["operation"]
                        require((after["alive"] if operation in {"start", "restart"} else not after["alive"])
                                and (operation != "start" or not before["alive"])
                                and (operation != "stop" or before["alive"] and not old_alive)
                                and (operation != "restart" or before["alive"] and not old_alive
                                     and (after["pid"], after["createTime"]) != (before["pid"], before["createTime"])),
                                "launcher_process_transition_not_observed")
                        if operation in {"start", "restart"}:
                            require(self._backend_ready(after, Path(expected["root"])), "launcher_backend_health_not_ready")
                    except AcceptanceFailure as exc:
                        last_failure = str(exc)
                    else:
                        proof.update(status="passed", processBefore=before, processAfter=after)
                        self.plan.setdefault("verifiedOperations", []).append(proof)
                        self._capture_children()
                        self._save()
                        return proof
            time.sleep(1)
        raise AcceptanceFailure(last_failure)

    def _capture_children(self) -> None:
        import psutil

        require(self.process is not None and base.acceptance_runtime._process_matches(self.process.pid, self.create_time),
                "isolated_electron_process_ownership_changed")
        for child in psutil.Process(self.process.pid).children(recursive=True):
            try:
                self._children[child.pid] = child.create_time()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def wait_exit(self, timeout: float = 60) -> dict:
        """Call after Terra requested the real owned shell's formal exit IPC."""
        import subprocess

        require(self.process is not None, "isolated_electron_not_started")
        try:
            returncode = self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AcceptanceFailure("isolated_electron_formal_exit_timeout") from None
        require(returncode == 0 and (self.plan.get("nextAction") or {}).get("type") == "exit",
                "isolated_electron_formal_exit_unconfirmed")
        require(not any(base.acceptance_runtime._process_matches(pid, created) for pid, created in self._children.items()),
                "isolated_electron_descendant_cleanup_unconfirmed")
        self.fixture.cleanup["launcherElectronStopped"] = True
        self.plan.update(status="exited", cleanup={"electronStopped": True, "capturedDescendantsStopped": True})
        self._save()
        return self.plan["cleanup"]

    def stop_owned_after_failure(self) -> None:
        """Contain a failed probe without treating forced exit as acceptance."""
        if self.process is None:
            return
        # A missing timestamp must never degrade the guard to PID-only matching.
        if (type(self.create_time) not in {int, float} or not math.isfinite(self.create_time)
                or self.create_time <= 0):
            self.fixture.cleanup["launcherElectronStopped"] = False
            self.plan.update(status="failed", cleanup={"ownedProcessesStopped": False, "ownershipUnconfirmed": True})
            self._save()
            return
        if base.acceptance_runtime._process_matches(self.process.pid, self.create_time):
            import psutil
            try:
                self._capture_children()
            except (psutil.NoSuchProcess, psutil.AccessDenied, AcceptanceFailure):
                pass
            base.acceptance_runtime._terminate_recorded(self.process.pid, self.create_time)
        for pid, created in self._children.items():
            if base.acceptance_runtime._process_matches(pid, created):
                base.acceptance_runtime._terminate_recorded(pid, created)
        stopped = (not base.acceptance_runtime._process_matches(self.process.pid, self.create_time)
                   and not any(base.acceptance_runtime._process_matches(pid, created)
                               for pid, created in self._children.items()))
        self.fixture.cleanup.update(launcherElectronStopped=stopped, launcherForcedStop=True)
        self.plan.update(status="failed", cleanup={"ownedProcessesStopped": stopped, "forced": True})
        self._save()


def prepare_launcher_phase(fixture: AssistantAcceptanceFixture, evidence: dict, *, electron: Path,
                           desktop_dist: Path, pythonw: Path) -> IsolatedLauncherController:
    """Rehydrate phase-1 private targets and return the parent's sole controller."""
    require((evidence.get("crossProject") or {}).get("status") == "passed", "cross_project_phase_not_complete")
    roots = (evidence.get("checkoutLayout") or {}).get("roots") or {}
    slots = []
    for name in ("A", "A1", "B"):
        root = Path(roots[name]).resolve()
        backends = [backend for backend in fixture.backends.values() if backend.root == root]
        require(len(backends) == 1, "launcher_phase_target_backend_not_unique")
        slots.append(ProjectSlot(name, backends[0].project_id, root, name + "_VALUE", evidence["expectedValues"][name + "_VALUE"]))
    controller = IsolatedLauncherController(fixture, slots, electron=electron, desktop_dist=desktop_dist, pythonw=pythonw)
    evidence["launcherLifecycle"] = {"status": "not_tested", "instructionsPath": str(controller.control_path),
                                     "reason": "real_native_frame_lifecycle_receipts_required"}
    return controller


def reuse_cross_project_evidence(fixture: AssistantAcceptanceFixture, evidence: dict, artifact: Path) -> None:
    """Reuse actual phase-1 records; keep retry provenance distinct from new work."""
    import tempfile
    from scripts.assistant_acceptance_support import Backend

    artifact = artifact.resolve()
    require(base.inside(artifact, Path(tempfile.gettempdir()).resolve()) and artifact.name == "projects.json"
            and artifact.parent.name.startswith("Vibelution-scheduling-projects-") and not artifact.is_symlink()
            and artifact.is_file() and artifact.stat().st_size <= base.MAX_JSON_BYTES,
            "project_evidence_not_private_artifact")
    raw = artifact.read_bytes()
    previous = base.read_json(artifact)
    require(previous.get("scenario") == "projects" and previous.get("schemaVersion") == 1
            and (previous.get("crossProject") or {}).get("status") == "passed"
            and len(previous.get("nativeTasks") or []) == 3
            and previous.get("cleanup") and all(previous["cleanup"].values()), "project_evidence_not_complete")
    old_home = artifact.parent / "projects"
    roots = {key: Path(value).resolve() for key, value in previous["checkoutLayout"]["roots"].items()}
    assert_checkout_layout(old_home, fixture.source, roots, fixture.env)
    control = old_home / "launcher-lifecycle/control/instructions.json"
    if control.is_file():
        old = base.read_json(control)
        require(not base.acceptance_runtime._process_matches(old.get("pid"), old.get("createTime")),
                "previous_launcher_still_running")
    for proof in previous["nativeTasks"]:
        matches = [name for name, root in roots.items() if root == Path(proof["root"]).resolve()]
        require(len(matches) == 1, "reused_native_root_not_unique")
        name = matches[0]
        slot = ProjectSlot(name, proof["projectId"], roots[name], name + "_VALUE", previous["expectedValues"][name + "_VALUE"])
        require(proof.get("nativeStatus") == "succeeded" and proof.get("userAdmissions") == 1
                and proof.get("reads") and slot.snapshot()["sha256"] == proof["reads"][0]["inputSha256"],
                "reused_project_input_or_proof_changed")
        # This descriptor is only a root lookup for the Launcher controller.
        # No old runtime or task authority is restarted or synthesized.
        fixture.backends[slot.project_id] = Backend(slot.project_id, slot.root, "not-started", "", fixture.home / "not-started")
    for key in ("crossProject", "diagnostics", "checkoutLayout", "expectedValues", "nativeTasks", "modelRequests",
                "goalId", "dispatchIds", "approvalCount", "reminders"):
        evidence[key] = previous[key]
    evidence["crossProjectEvidenceSource"] = {"artifact": str(artifact), "sha256": hashlib.sha256(raw).hexdigest(),
                                              "reusedWithoutResubmission": True}
