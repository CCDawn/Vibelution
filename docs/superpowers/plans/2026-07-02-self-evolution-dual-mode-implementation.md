# Self-Evolution Dual Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two explicit self-evolution modes: isolated development with worktree review approval, and pure no-tool autonomous observation.

**Architecture:** Keep the existing self-evolution worktree path as the isolated development path, and add a separate observation-run path that does not create worktrees or hold write leases. The frontend selects the mode before launch and renders either the existing worktree approval surface or a compact observation surface backed by conversation-style output.

**Tech Stack:** FastAPI/Pydantic routes in `core/web/routes/evolution.py`, Python service logic in `core/web/services/self_evolution_control_service.py`, React/TypeScript self-evolution UI in `web/src/routes/SelfEvolutionTrack.tsx`, API DTOs in `web/src/api/types.ts`, Vitest and pytest for regression tests.

## Global Constraints

- Autonomous observation mode starts with 0 tools and this phase does not support tool requests, dynamic tool addition, or temporary authorization.
- Autonomous observation mode must not create a worktree, read or write files, run commands, search, modify code, generate a patch, or enter merge approval.
- Isolated development mode must create or reuse the reviewed self-evolution worktree path and must stop at user approval before merge.
- Both modes must reuse the existing conversation display style for live output where practical.
- Historical runs must not replace the current run state on the main self-evolution surface.
- Do not modify `VERSION`, `CHANGELOG.md`, root `config.toml`, `config.example.toml`, or operator config in this implementation branch.
- Launcher refresh is required before real UI runtime verification, but not before unit/build validation.

---

## File Structure

- Modify `core/web/routes/evolution.py`: add observation request/action payloads and new self observation routes.
- Modify `core/web/services/self_evolution_control_service.py`: add observation run lifecycle, prompt contract, boundary checks, SSE stream, and action handling.
- Modify `core/web/services/supervised_worktree_evolution_service.py`: preserve isolated development metadata in self-evolution worktree snapshots if currently missing.
- Modify `web/src/api/types.ts`: add observation run/request/action DTOs and self-mode projection fields.
- Modify `web/src/api/queryKeys.ts`: add self observation query keys if the UI polls observation runs separately.
- Modify `web/src/routes/EvolutionRoute.tsx`: fetch and pass observation active run/history into `SelfEvolutionTrack`.
- Modify `web/src/routes/SelfEvolutionTrack.tsx`: add mode selector, isolated development launch copy, observation launch form, observation status, termination, and report rendering.
- Modify `web/src/routes/SelfEvolutionTrack.static.test.ts`: protect mode selector and no-tool observation UI contracts.
- Modify or add `tests/test_self_evolution_control_service.py`: backend observation lifecycle and prompt contract tests.
- Modify `tests/test_web_evolution_routes.py`: route DTO/API tests for observation start/read/action.

---

### Task 1: Backend Observation Prompt And Run Model

**Files:**
- Modify: `core/web/services/self_evolution_control_service.py`
- Test: `tests/test_self_evolution_control_service.py`

**Interfaces:**
- Produces: `build_self_observation_prompt(goal: str, duration_seconds: int) -> str`
- Produces: `detect_self_observation_boundary_violation(text: str) -> str`
- Produces: `start_self_observation_run(payload: dict[str, Any]) -> dict[str, Any]`
- Produces: `get_active_self_observation_run() -> dict[str, Any] | None`
- Produces: `get_self_observation_run_snapshot(run_id: str) -> dict[str, Any] | None`
- Produces: observation run snapshots with `runKind="self_observation_run"`, `selfMode="observation"`, `allowedTools=[]`, `writeLeases=[]`, `worktreeCreated=False`

- [ ] **Step 1: Write prompt contract tests**

Add these tests to `tests/test_self_evolution_control_service.py`:

```python
def test_self_observation_prompt_is_no_tool_contract():
    from core.web.services import self_evolution_control_service as service

    prompt = service.build_self_observation_prompt("观察自进化能力", duration_seconds=120)

    assert "无工具观察沙盒" in prompt
    assert "你没有任何工具" in prompt
    assert "不能声称已经读取" in prompt
    assert "不能请求工具授权" in prompt
    assert "无法验证" in prompt
    assert "未来需要的证据" in prompt


def test_self_observation_boundary_violation_detects_fake_execution_claims():
    from core.web.services import self_evolution_control_service as service

    assert service.detect_self_observation_boundary_violation("我已经读取了项目文件") == "claimed_file_read"
    assert service.detect_self_observation_boundary_violation("I ran pytest and verified it") == "claimed_command_execution"
    assert service.detect_self_observation_boundary_violation("当前理解：这是一个只能推理的问题") == ""
```

- [ ] **Step 2: Run prompt tests and verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation_prompt or self_observation_boundary" -q`

Expected: FAIL because `build_self_observation_prompt` and `detect_self_observation_boundary_violation` do not exist.

- [ ] **Step 3: Add prompt helpers**

In `core/web/services/self_evolution_control_service.py`, add near existing self-evolution prompt helpers:

```python
SELF_OBSERVATION_MIN_DURATION_SECONDS = 30
SELF_OBSERVATION_MAX_DURATION_SECONDS = 3600


def _normalize_observation_duration(value: Any) -> int:
    try:
        duration = int(value)
    except (TypeError, ValueError):
        duration = 300
    return max(SELF_OBSERVATION_MIN_DURATION_SECONDS, min(SELF_OBSERVATION_MAX_DURATION_SECONDS, duration))


def build_self_observation_prompt(goal: str, duration_seconds: int) -> str:
    normalized_goal = str(goal or "").strip() or DEFAULT_SELF_EVOLUTION_GOAL
    normalized_duration = _normalize_observation_duration(duration_seconds)
    return (
        "你是 Vibelution 的自进化观察 Agent，处在无工具观察沙盒中。\n"
        f"观察目标：{normalized_goal}\n"
        f"运行时长上限：{normalized_duration} 秒。\n\n"
        "硬性规则：\n"
        "1. 你没有任何工具。\n"
        "2. 你不能声称已经读取、搜索、运行、验证、修改、提交、合并或调用外部能力。\n"
        "3. 你不能请求工具授权，因为本模式本阶段不支持工具申请。\n"
        "4. 你只能理解目标、提出假设、分解可能路径、识别风险、描述未来需要的证据。\n"
        "5. 需要证据时必须写入“无法验证”，不能编造结果。\n\n"
        "每段输出使用以下结构：\n"
        "当前理解：\n"
        "可观察推理：\n"
        "关键假设：\n"
        "无法验证：\n"
        "如果未来允许工具，需要的证据：\n"
        "下一段观察重点：\n"
    )


def detect_self_observation_boundary_violation(text: str) -> str:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return ""
    file_read_markers = ("已经读取", "读取了项目", "read the file", "read files", "opened the file")
    command_markers = ("运行了", "执行了命令", "ran pytest", "ran npm", "executed the command", "i ran")
    mutation_markers = ("修改了", "写入了", "提交了", "合并了", "modified the file", "committed", "merged")
    search_markers = ("搜索了", "查到了网页", "searched the web", "web search")
    if any(marker in normalized for marker in file_read_markers):
        return "claimed_file_read"
    if any(marker in normalized for marker in command_markers):
        return "claimed_command_execution"
    if any(marker in normalized for marker in mutation_markers):
        return "claimed_mutation"
    if any(marker in normalized for marker in search_markers):
        return "claimed_search"
    return ""
```

- [ ] **Step 4: Run prompt tests and verify pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation_prompt or self_observation_boundary" -q`

Expected: PASS.

- [ ] **Step 5: Write observation start model tests**

Add:

```python
def test_start_self_observation_run_has_no_tools_no_worktree(monkeypatch):
    from core.web.services import self_evolution_control_service as service

    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service, "_run_self_observation_turn", lambda context: None)
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")

    snapshot = service.start_self_observation_run({"goal": "观察规划能力", "durationSeconds": 90})

    assert snapshot["runKind"] == "self_observation_run"
    assert snapshot["selfMode"] == "observation"
    assert snapshot["allowedTools"] == []
    assert snapshot["writeLeases"] == []
    assert snapshot["worktreeCreated"] is False
    assert snapshot["durationSeconds"] == 90
    assert service.get_active_self_observation_run()["runId"] == snapshot["runId"]
```

- [ ] **Step 6: Run observation start test and verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py::test_start_self_observation_run_has_no_tools_no_worktree -q`

Expected: FAIL because observation lifecycle functions do not exist.

- [ ] **Step 7: Implement minimal observation lifecycle**

In `core/web/services/self_evolution_control_service.py`, add module-level state near existing run state:

```python
_OBSERVATION_RUN_STATE_LOCK = threading.RLock()
_OBSERVATION_RUNS: dict[str, dict[str, Any]] = {}
_ACTIVE_OBSERVATION_RUN_ID: str = ""
```

Add these functions:

```python
def _build_self_observation_snapshot(
    *,
    run_id: str,
    goal: str,
    duration_seconds: int,
    status: str,
    latest_message: str,
    started_at: str,
) -> dict[str, Any]:
    return {
        "runId": run_id,
        "runKind": "self_observation_run",
        "selfMode": "observation",
        "status": status,
        "phase": status,
        "runtimeStatus": status,
        "goal": goal,
        "durationSeconds": duration_seconds,
        "allowedTools": [],
        "toolPolicy": {
            "policyId": "self-observation-no-tools",
            "allowedTools": [],
            "preferredTools": [],
            "blockedTools": [],
            "readScopes": [],
            "writeScopes": [],
            "mutationAccess": "none",
        },
        "writeLeases": [],
        "worktreeCreated": False,
        "conversationSessionId": "",
        "startedAt": started_at,
        "updatedAt": started_at,
        "finishedAt": "",
        "latestMessage": latest_message,
        "messages": [],
        "report": "",
        "boundaryViolation": "",
        "actionStates": {
            "terminate": {"enabled": status in {"queued", "running"}, "label": "终止观察", "reason": ""},
        },
    }


def get_active_self_observation_run() -> dict[str, Any] | None:
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(_ACTIVE_OBSERVATION_RUN_ID)
        if not snapshot:
            return None
        if str(snapshot.get("status") or "").lower() in {"queued", "running"}:
            return dict(snapshot)
        return None


def get_self_observation_run_snapshot(run_id: str) -> dict[str, Any] | None:
    normalized = str(run_id or "").strip()
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(normalized)
        return dict(snapshot) if snapshot else None


def force_cancel_active_self_observation_runs_for_shutdown(reason: str = "") -> list[dict[str, Any]]:
    global _ACTIVE_OBSERVATION_RUN_ID
    closed: list[dict[str, Any]] = []
    now = _now_timestamp()
    with _OBSERVATION_RUN_STATE_LOCK:
        for snapshot in _OBSERVATION_RUNS.values():
            if str(snapshot.get("status") or "").lower() in {"queued", "running"}:
                snapshot["status"] = "terminated"
                snapshot["phase"] = "terminated"
                snapshot["runtimeStatus"] = "terminated"
                snapshot["finishedAt"] = now
                snapshot["updatedAt"] = now
                snapshot["latestMessage"] = reason or "Observation run terminated."
                closed.append(dict(snapshot))
        _ACTIVE_OBSERVATION_RUN_ID = ""
    return closed


def start_self_observation_run(payload: dict[str, Any]) -> dict[str, Any]:
    global _ACTIVE_OBSERVATION_RUN_ID
    lang = get_web_language()
    contract = get_workbench_contract()
    if not bool(contract.get("modeAvailability", {}).get("self_evolution")):
        raise SelfEvolutionRunValidationError(
            text_for(lang, zh="配置里没有启用 self_evolution，当前不能启动自主观察。", en="self_evolution is disabled.")
        )
    data = payload if isinstance(payload, dict) else {}
    goal = str(data.get("goal") or DEFAULT_SELF_EVOLUTION_GOAL).strip() or DEFAULT_SELF_EVOLUTION_GOAL
    duration_seconds = _normalize_observation_duration(data.get("durationSeconds"))
    now = _now_timestamp()
    with _OBSERVATION_RUN_STATE_LOCK:
        active = get_active_self_observation_run()
        if active is not None:
            raise SelfEvolutionRunBusyError(
                text_for(lang, zh="当前已有自主观察正在运行，请先终止或等待结束。", en="An observation run is already active.")
            )
        run_id = f"self-observe-{uuid4().hex[:12]}"
        snapshot = _build_self_observation_snapshot(
            run_id=run_id,
            goal=goal,
            duration_seconds=duration_seconds,
            status="queued",
            latest_message=text_for(lang, zh="自主观察已排队，等待无工具会话启动。", en="Observation run queued."),
            started_at=now,
        )
        _OBSERVATION_RUNS[run_id] = snapshot
        _ACTIVE_OBSERVATION_RUN_ID = run_id
    _RUN_EXECUTOR.submit(_run_self_observation_turn, {"runId": run_id, "goal": goal, "durationSeconds": duration_seconds})
    return get_self_observation_run_snapshot(run_id) or snapshot
```

- [ ] **Step 8: Run observation lifecycle tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation" -q`

Expected: PASS for the newly added tests.

- [ ] **Step 9: Commit Task 1**

```powershell
git add core/web/services/self_evolution_control_service.py tests/test_self_evolution_control_service.py
git commit -m "feat: add self-observation run model"
```

---

### Task 2: Observation Runtime, Termination, And Route API

**Files:**
- Modify: `core/web/services/self_evolution_control_service.py`
- Modify: `core/web/routes/evolution.py`
- Test: `tests/test_self_evolution_control_service.py`
- Test: `tests/test_web_evolution_routes.py`

**Interfaces:**
- Consumes: Task 1 observation snapshot functions.
- Produces: `stream_self_observation_run_events(run_id: str, initial_snapshot: dict[str, Any] | None = None)`
- Produces: `execute_self_observation_action(run_id: str, action: str) -> dict[str, Any]`
- Produces routes:
  - `POST /api/evolution/self/observation-runs`
  - `GET /api/evolution/self/observation-runs/{run_id}`
  - `GET /api/evolution/self/observation-runs/{run_id}/events`
  - `POST /api/evolution/self/observation-runs/{run_id}/actions`

- [ ] **Step 1: Add route tests**

In `tests/test_web_evolution_routes.py`, add:

```python
def test_self_observation_start_route_returns_no_tool_snapshot(client, monkeypatch):
    from core.web.services import self_evolution_control_service as service

    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service, "_run_self_observation_turn", lambda context: None)
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")

    response = client.post("/api/evolution/self/observation-runs", json={"goal": "观察思考", "durationSeconds": 60})

    assert response.status_code == 202
    payload = response.json()
    assert payload["runKind"] == "self_observation_run"
    assert payload["allowedTools"] == []
    assert payload["worktreeCreated"] is False


def test_self_observation_terminate_route(client, monkeypatch):
    from core.web.services import self_evolution_control_service as service

    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service, "_run_self_observation_turn", lambda context: None)
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")
    started = service.start_self_observation_run({"goal": "观察终止", "durationSeconds": 60})

    response = client.post(
        f"/api/evolution/self/observation-runs/{started['runId']}/actions",
        json={"action": "terminate"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "terminated"
```

- [ ] **Step 2: Run route tests and verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_web_evolution_routes.py -k "self_observation" -q`

Expected: FAIL because routes are missing.

- [ ] **Step 3: Add route payload models and endpoints**

In `core/web/routes/evolution.py`, extend imports from `self_evolution_control_service`:

```python
    execute_self_observation_action,
    get_self_observation_run_snapshot,
    start_self_observation_run,
    stream_self_observation_run_events,
```

Add payload classes near `SelfEvolutionWorktreeRunStartPayload`:

```python
class SelfObservationRunStartPayload(BaseModel):
    goal: str = ""
    durationSeconds: int = 300
    uiRoute: str = "/evolution?track=self"


class SelfObservationRunActionPayload(BaseModel):
    action: str = ""
```

Add endpoints after `self_evolution_start_worktree_run`:

```python
@router.post("/evolution/self/observation-runs", status_code=status.HTTP_202_ACCEPTED)
def self_observation_start_run(payload: SelfObservationRunStartPayload) -> dict:
    try:
        return start_self_observation_run(payload.model_dump())
    except SelfEvolutionRunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SelfEvolutionRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/evolution/self/observation-runs/{run_id}")
def self_observation_run(run_id: str) -> dict:
    snapshot = get_self_observation_run_snapshot(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Self observation run not found")
    return snapshot


@router.get("/evolution/self/observation-runs/{run_id}/events")
def self_observation_run_events(run_id: str) -> StreamingResponse:
    snapshot = get_self_observation_run_snapshot(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Self observation run not found")
    return StreamingResponse(
        stream_self_observation_run_events(run_id, initial_snapshot=snapshot),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/evolution/self/observation-runs/{run_id}/actions")
def self_observation_run_action(run_id: str, payload: SelfObservationRunActionPayload) -> dict:
    try:
        return execute_self_observation_action(run_id, payload.action)
    except SelfEvolutionRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SelfEvolutionRunValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

- [ ] **Step 4: Implement termination and SSE helpers**

In `core/web/services/self_evolution_control_service.py`, add:

```python
def execute_self_observation_action(run_id: str, action: str) -> dict[str, Any]:
    normalized = str(run_id or "").strip()
    normalized_action = str(action or "").strip().lower()
    if not normalized:
        raise SelfEvolutionRunValidationError("Missing self observation run id.")
    if normalized_action not in {"terminate", "stop", "cancel"}:
        raise SelfEvolutionRunValidationError("Unsupported self observation action.")
    now = _now_timestamp()
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(normalized)
        if snapshot is None:
            raise SelfEvolutionRunNotFoundError("Self observation run not found.")
        snapshot["status"] = "terminated"
        snapshot["phase"] = "terminated"
        snapshot["runtimeStatus"] = "terminated"
        snapshot["updatedAt"] = now
        snapshot["finishedAt"] = now
        snapshot["latestMessage"] = "自主观察已由用户终止。"
        snapshot["report"] = snapshot.get("report") or "观察被用户终止，未生成完整结束报告。"
        snapshot["actionStates"] = {"terminate": {"enabled": False, "label": "已终止", "reason": "operator_terminated"}}
        if _ACTIVE_OBSERVATION_RUN_ID == normalized:
            globals()["_ACTIVE_OBSERVATION_RUN_ID"] = ""
        return dict(snapshot)


def stream_self_observation_run_events(run_id: str, initial_snapshot: dict[str, Any] | None = None):
    normalized = str(run_id or "").strip()
    if initial_snapshot:
        yield _encode_sse_event("self_observation_run", initial_snapshot)
    while normalized:
        snapshot = get_self_observation_run_snapshot(normalized)
        if snapshot is None:
            return
        yield _encode_sse_event("self_observation_run", snapshot)
        if str(snapshot.get("status") or "").lower() not in {"queued", "running"}:
            return
        time.sleep(1.0)
```

- [ ] **Step 5: Run backend route tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py tests\test_web_evolution_routes.py -k "self_observation" -q`

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```powershell
git add core/web/routes/evolution.py core/web/services/self_evolution_control_service.py tests/test_self_evolution_control_service.py tests/test_web_evolution_routes.py
git commit -m "feat: expose self-observation run api"
```

---

### Task 3: Workspace Snapshot And Frontend Types

**Files:**
- Modify: `core/web/routes/evolution.py`
- Modify: `web/src/api/types.ts`
- Modify: `web/src/api/queryKeys.ts`
- Test: `tests/test_web_evolution_routes.py`

**Interfaces:**
- Consumes: Task 2 observation snapshot route/service functions.
- Produces: `EvolutionWorkspaceSnapshot.selfObservationActiveRun?: SelfObservationRun | null`
- Produces: `SelfObservationRun` TypeScript type.
- Produces: `queryKeys.evolutionSelfObservationRun(runId: string)` and `queryKeys.evolutionSelfObservationActiveRun()`.

- [ ] **Step 1: Add workspace snapshot route test**

In `tests/test_web_evolution_routes.py`, add:

```python
def test_workspace_snapshot_include_self_projects_observation_active_run(client, monkeypatch):
    from core.web.services import self_evolution_control_service as service

    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    monkeypatch.setattr(service, "_run_self_observation_turn", lambda context: None)
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")
    started = service.start_self_observation_run({"goal": "观察投影", "durationSeconds": 60})

    response = client.get("/api/evolution/workspace-snapshot?includeSelf=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selfObservationActiveRun"]["runId"] == started["runId"]
    assert payload["selfObservationActiveRun"]["allowedTools"] == []
```

- [ ] **Step 2: Run snapshot test and verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_web_evolution_routes.py::test_workspace_snapshot_include_self_projects_observation_active_run -q`

Expected: FAIL because workspace snapshot does not include `selfObservationActiveRun`.

- [ ] **Step 3: Project observation active run in workspace snapshot**

In `core/web/routes/evolution.py`, import `get_active_self_observation_run`. In `evolution_workspace_snapshot`, where self projections are added when `includeSelf` is true, add:

```python
self_observation_active_run = get_active_self_observation_run() if includeSelf else None
```

Add to the returned payload:

```python
"selfObservationActiveRun": self_observation_active_run,
```

Keep `selfWorktreeActiveRun` unchanged so isolated development still uses worktree data.

- [ ] **Step 4: Update TypeScript DTOs**

In `web/src/api/types.ts`, add near `SelfEvolutionTransaction`:

```ts
export type SelfObservationRun = {
  runId: string;
  runKind: "self_observation_run" | string;
  selfMode: "observation" | string;
  status: string;
  phase: string;
  runtimeStatus: string;
  goal: string;
  durationSeconds: number;
  allowedTools: string[];
  writeLeases: string[];
  worktreeCreated: boolean;
  conversationSessionId: string;
  startedAt: string;
  updatedAt: string;
  finishedAt: string;
  latestMessage: string;
  report: string;
  boundaryViolation: string;
  actionStates: Record<string, EvolutionActionState>;
};

export type SelfObservationRunStartRequest = {
  goal: string;
  durationSeconds: number;
  uiRoute?: string;
};

export type SelfObservationRunActionRequest = {
  action: "terminate" | "stop" | "cancel" | string;
};
```

Extend `EvolutionWorkspaceSnapshot`:

```ts
selfObservationActiveRun?: SelfObservationRun | null;
```

- [ ] **Step 5: Add query keys**

In `web/src/api/queryKeys.ts`, add near existing self-evolution keys:

```ts
evolutionSelfObservationActiveRun: () => ["evolution", "self", "observation-runs", "active"] as const,
evolutionSelfObservationRun: (runId: string) => ["evolution", "self", "observation-runs", runId] as const,
```

- [ ] **Step 6: Run backend snapshot test and frontend build**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_evolution_routes.py -k "self_observation" -q
npm --prefix web run build
```

Expected: pytest PASS and TypeScript build PASS.

- [ ] **Step 7: Commit Task 3**

```powershell
git add core/web/routes/evolution.py web/src/api/types.ts web/src/api/queryKeys.ts tests/test_web_evolution_routes.py
git commit -m "feat: project self-observation state"
```

---

### Task 4: Frontend Mode Selection And Launch Wiring

**Files:**
- Modify: `web/src/routes/EvolutionRoute.tsx`
- Modify: `web/src/routes/SelfEvolutionTrack.tsx`
- Modify: `web/src/routes/SelfEvolutionTrack.static.test.ts`
- Modify: `web/src/routes/evolutionWorkspaceCache.ts`

**Interfaces:**
- Consumes: `SelfObservationRun` and workspace snapshot `selfObservationActiveRun`.
- Produces: `SelfEvolutionTrack` props:
  - `observationRun?: SelfObservationRun | null`
  - `onStartObservation: (payload: SelfObservationRunStartRequest) => void`
  - `onTerminateObservation: (runId: string) => void`
  - `observationStartPending: boolean`
  - `observationActionPending: boolean`
  - `observationStartError: string`
  - `observationActionError: string`

- [ ] **Step 1: Add static UI contract tests**

In `web/src/routes/SelfEvolutionTrack.static.test.ts`, add:

```ts
it("offers isolated development and pure observation modes", () => {
  expect(routeSource).toContain('type SelfEvolutionMode = "isolated_development" | "observation"');
  expect(routeSource).toContain('value="isolated_development"');
  expect(routeSource).toContain('value="observation"');
  expect(routeSource).toContain("自主观察");
  expect(routeSource).toContain("隔离开发");
});

it("keeps observation mode free of tool and merge actions", () => {
  expect(routeSource).toContain("observationRun");
  expect(routeSource).toContain("allowedTools.length === 0");
  expect(routeSource).toContain("onStartObservation");
  expect(routeSource).toContain("onTerminateObservation");
  expect(routeSource).not.toContain("onRequestObservationTool");
  expect(routeSource).not.toContain("observationToolRequest");
});
```

- [ ] **Step 2: Run static tests and verify failure**

Run: `npm --prefix web run test -- SelfEvolutionTrack.static.test.ts`

Expected: FAIL because UI mode selector and observation props do not exist.

- [ ] **Step 3: Extend `SelfEvolutionTrack` props and local state**

In `web/src/routes/SelfEvolutionTrack.tsx`, import `SelfObservationRun` and `SelfObservationRunStartRequest`.

Add:

```ts
type SelfEvolutionMode = "isolated_development" | "observation";
```

Extend `SelfEvolutionTrackProps`:

```ts
observationRun?: SelfObservationRun | null;
onStartObservation: (payload: SelfObservationRunStartRequest) => void;
onTerminateObservation: (runId: string) => void;
observationStartPending: boolean;
observationActionPending: boolean;
observationStartError: string;
observationActionError: string;
```

Inside the component add:

```ts
const [selfEvolutionMode, setSelfEvolutionMode] = useState<SelfEvolutionMode>("isolated_development");
const [observationGoalInput, setObservationGoalInput] = useState("");
const [observationDurationSeconds, setObservationDurationSeconds] = useState(300);
```

- [ ] **Step 4: Add compact mode selector**

In the launch/control section of `SelfEvolutionTrack.tsx`, add a segmented control before the start buttons:

```tsx
<div className={styles.modeSwitch} role="tablist" aria-label={lang === "zh" ? "自进化模式" : "Self-evolution mode"}>
  <button
    type="button"
    role="tab"
    aria-selected={selfEvolutionMode === "isolated_development"}
    value="isolated_development"
    className={selfEvolutionMode === "isolated_development" ? styles.modeTabActive : styles.modeTab}
    onClick={() => setSelfEvolutionMode("isolated_development")}
  >
    {lang === "zh" ? "隔离开发" : "Isolated development"}
  </button>
  <button
    type="button"
    role="tab"
    aria-selected={selfEvolutionMode === "observation"}
    value="observation"
    className={selfEvolutionMode === "observation" ? styles.modeTabActive : styles.modeTab}
    onClick={() => setSelfEvolutionMode("observation")}
  >
    {lang === "zh" ? "自主观察" : "Observation"}
  </button>
</div>
```

Add styles in `SelfEvolutionTrack.styles.ts` or existing style map:

```ts
modeSwitch: "inline-flex items-center gap-1 rounded-md border border-vui-border bg-vui-surface-subtle p-1",
modeTab: "rounded px-2.5 py-1 text-sm text-vui-fg-secondary hover:bg-vui-surface",
modeTabActive: "rounded bg-vui-surface px-2.5 py-1 text-sm font-semibold text-vui-fg",
```

- [ ] **Step 5: Add observation launch form**

Render only when `selfEvolutionMode === "observation"`:

```tsx
<div className={styles.observationPanel}>
  <label className={styles.formField}>
    <span>{lang === "zh" ? "观察目标" : "Observation goal"}</span>
    <textarea
      className={styles.textArea}
      rows={3}
      value={observationGoalInput}
      onChange={(event) => setObservationGoalInput(event.target.value)}
      placeholder={lang === "zh" ? "描述要观察 Agent 如何思考的问题" : "Describe what you want to observe"}
    />
  </label>
  <label className={styles.formField}>
    <span>{lang === "zh" ? "运行时长（秒）" : "Duration seconds"}</span>
    <input
      className={styles.textInput}
      type="number"
      min={30}
      max={3600}
      value={observationDurationSeconds}
      onChange={(event) => setObservationDurationSeconds(Number(event.target.value || 300))}
    />
  </label>
  <p className={styles.noticeText}>
    {lang === "zh" ? "自主观察模式固定 0 工具，不会申请工具、创建 worktree 或修改代码。" : "Observation mode has 0 tools and cannot modify code."}
  </p>
  <button
    type="button"
    className={styles.primaryAction}
    disabled={observationStartPending || Boolean(observationRun && ["queued", "running"].includes(observationRun.status))}
    onClick={() => onStartObservation({ goal: observationGoalInput, durationSeconds: observationDurationSeconds })}
  >
    {observationStartPending ? (lang === "zh" ? "启动中" : "Starting") : (lang === "zh" ? "开始自主观察" : "Start observation")}
  </button>
  {observationStartError ? <p className={styles.errorText}>{observationStartError}</p> : null}
</div>
```

- [ ] **Step 6: Add observation runtime panel**

Render near the main output area when `selfEvolutionMode === "observation"`:

```tsx
<section className={styles.observationPanel}>
  <header className={styles.sectionHeader}>
    <div>
      <span className={styles.eyebrow}>{lang === "zh" ? "纯观察沙盒" : "No-tool sandbox"}</span>
      <h3>{lang === "zh" ? "自主观察" : "Observation"}</h3>
    </div>
    {observationRun?.status ? <span className={styles.statusPill}>{observationRun.status}</span> : null}
  </header>
  <div className={styles.metricGrid}>
    <div><span>{lang === "zh" ? "工具" : "Tools"}</span><strong>{observationRun?.allowedTools.length === 0 ? "0" : "--"}</strong></div>
    <div><span>{lang === "zh" ? "时长" : "Duration"}</span><strong>{observationRun?.durationSeconds ?? "--"}</strong></div>
    <div><span>{lang === "zh" ? "worktree" : "Worktree"}</span><strong>{observationRun?.worktreeCreated ? "yes" : "no"}</strong></div>
  </div>
  <p className={styles.previewText}>{observationRun?.latestMessage || (lang === "zh" ? "还没有观察输出。" : "No observation output yet.")}</p>
  {observationRun?.report ? <pre className={styles.rawBlock}>{observationRun.report}</pre> : null}
  {observationRun?.boundaryViolation ? <p className={styles.errorText}>{observationRun.boundaryViolation}</p> : null}
  {observationRun && ["queued", "running"].includes(observationRun.status) ? (
    <button
      type="button"
      className={styles.inlineAction}
      disabled={observationActionPending}
      onClick={() => onTerminateObservation(observationRun.runId)}
    >
      {lang === "zh" ? "终止观察" : "Terminate"}
    </button>
  ) : null}
  {observationActionError ? <p className={styles.errorText}>{observationActionError}</p> : null}
</section>
```

- [ ] **Step 7: Wire mutations in `EvolutionRoute.tsx`**

In `EvolutionRoute.tsx`, add mutations:

```ts
const startSelfObservationMutation = useMutation({
  mutationFn: (payload: SelfObservationRunStartRequest) =>
    fetchJson<SelfObservationRun>("/api/evolution/self/observation-runs", {
      method: "POST",
      body: JSON.stringify({ ...payload, uiRoute: "/evolution?track=self" }),
    }),
  onSuccess: () => evolutionWorkspaceCache.afterSelfEvolutionChanged(),
});

const selfObservationActionMutation = useMutation({
  mutationFn: ({ runId, action }: { runId: string; action: string }) =>
    fetchJson<SelfObservationRun>(`/api/evolution/self/observation-runs/${runId}/actions`, {
      method: "POST",
      body: JSON.stringify({ action }),
    }),
  onSuccess: () => evolutionWorkspaceCache.afterSelfEvolutionChanged(),
});
```

Pass props:

```tsx
observationRun={workspaceSnapshot?.selfObservationActiveRun ?? null}
onStartObservation={(payload) => startSelfObservationMutation.mutate(payload)}
onTerminateObservation={(runId) => selfObservationActionMutation.mutate({ runId, action: "terminate" })}
observationStartPending={startSelfObservationMutation.isPending}
observationActionPending={selfObservationActionMutation.isPending}
observationStartError={startSelfObservationMutation.error?.message || ""}
observationActionError={selfObservationActionMutation.error?.message || ""}
```

- [ ] **Step 8: Run frontend tests**

Run: `npm --prefix web run test -- SelfEvolutionTrack.static.test.ts EvolutionRoute.layout.test.ts evolutionWorkspaceCache.test.ts`

Expected: PASS.

- [ ] **Step 9: Commit Task 4**

```powershell
git add web/src/routes/EvolutionRoute.tsx web/src/routes/SelfEvolutionTrack.tsx web/src/routes/SelfEvolutionTrack.styles.ts web/src/routes/SelfEvolutionTrack.static.test.ts web/src/routes/evolutionWorkspaceCache.ts
git commit -m "feat(web): add self-evolution mode selector"
```

---

### Task 5: Conversation Reuse And Observation Completion Report

**Files:**
- Modify: `core/web/services/self_evolution_control_service.py`
- Test: `tests/test_self_evolution_control_service.py`
- Optional frontend test: `web/src/routes/SelfEvolutionTrack.static.test.ts`

**Interfaces:**
- Consumes: Task 1 `build_self_observation_prompt`.
- Produces: `_run_self_observation_turn(context: dict[str, Any]) -> None`
- Produces: observation snapshots with `conversationSessionId`, streaming `latestMessage`, and final `report`.

- [ ] **Step 1: Add completion report test with fake runner**

In `tests/test_self_evolution_control_service.py`, add:

```python
def test_self_observation_turn_finishes_with_report(monkeypatch):
    from core.web.services import self_evolution_control_service as service

    monkeypatch.setattr(service, "get_workbench_contract", lambda: {"modeAvailability": {"self_evolution": True}})
    service.force_cancel_active_self_observation_runs_for_shutdown("test cleanup")

    emitted = [
        "当前理解：目标是观察规划。",
        "无法验证：没有工具，不能读取项目。",
    ]

    def fake_run_observation_session(*, run_id, prompt, duration_seconds):
        assert "你没有任何工具" in prompt
        return {"conversationSessionId": "session-observe-1", "messages": emitted, "report": "观察目标：观察规划\n无法验证清单：不能读取项目"}

    monkeypatch.setattr(service, "_run_observation_session", fake_run_observation_session)
    started = service.start_self_observation_run({"goal": "观察规划", "durationSeconds": 60})
    service._run_self_observation_turn({"runId": started["runId"], "goal": "观察规划", "durationSeconds": 60})

    snapshot = service.get_self_observation_run_snapshot(started["runId"])
    assert snapshot["status"] == "done"
    assert snapshot["conversationSessionId"] == "session-observe-1"
    assert "观察目标" in snapshot["report"]
    assert snapshot["latestMessage"] == emitted[-1]
```

- [ ] **Step 2: Run completion test and verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py::test_self_observation_turn_finishes_with_report -q`

Expected: FAIL until `_run_self_observation_turn` and `_run_observation_session` exist.

- [ ] **Step 3: Implement observation turn wrapper**

In `core/web/services/self_evolution_control_service.py`, add:

```python
def _run_observation_session(*, run_id: str, prompt: str, duration_seconds: int) -> dict[str, Any]:
    # Implementation phase should route through the existing session/conversation execution chain.
    # Keep this helper narrow so tests can replace it without mocking the full LLM runtime.
    return {
        "conversationSessionId": "",
        "messages": [prompt],
        "report": (
            "观察目标：\n"
            "运行时长：\n"
            "思考路径摘要：观察会话已建立，但当前运行环境未返回模型输出。\n"
            "主要假设：无。\n"
            "无法验证清单：未获得模型输出。\n"
            "风险与自我约束表现：保持无工具边界。\n"
            "未来可执行实验建议：重新运行观察。"
        ),
    }


def _run_self_observation_turn(context: dict[str, Any]) -> None:
    run_id = str(context.get("runId") or "").strip()
    goal = str(context.get("goal") or DEFAULT_SELF_EVOLUTION_GOAL).strip() or DEFAULT_SELF_EVOLUTION_GOAL
    duration_seconds = _normalize_observation_duration(context.get("durationSeconds"))
    if not run_id:
        return
    now = _now_timestamp()
    with _OBSERVATION_RUN_STATE_LOCK:
        snapshot = _OBSERVATION_RUNS.get(run_id)
        if not snapshot or str(snapshot.get("status") or "").lower() == "terminated":
            return
        snapshot["status"] = "running"
        snapshot["phase"] = "running"
        snapshot["runtimeStatus"] = "running"
        snapshot["updatedAt"] = now
        snapshot["latestMessage"] = "自主观察正在运行。"
    prompt = build_self_observation_prompt(goal, duration_seconds)
    try:
        result = _run_observation_session(run_id=run_id, prompt=prompt, duration_seconds=duration_seconds)
        messages = [str(item) for item in (result.get("messages") or []) if str(item or "").strip()]
        violation = ""
        for message in messages:
            violation = detect_self_observation_boundary_violation(message)
            if violation:
                break
        finished = _now_timestamp()
        with _OBSERVATION_RUN_STATE_LOCK:
            snapshot = _OBSERVATION_RUNS.get(run_id)
            if not snapshot:
                return
            snapshot["conversationSessionId"] = str(result.get("conversationSessionId") or "")
            snapshot["messages"] = messages[-20:]
            snapshot["latestMessage"] = messages[-1] if messages else "自主观察已结束。"
            snapshot["boundaryViolation"] = violation
            snapshot["report"] = str(result.get("report") or "")
            snapshot["status"] = "boundary_violation" if violation else "done"
            snapshot["phase"] = snapshot["status"]
            snapshot["runtimeStatus"] = snapshot["status"]
            snapshot["finishedAt"] = finished
            snapshot["updatedAt"] = finished
            snapshot["actionStates"] = {"terminate": {"enabled": False, "label": "已结束", "reason": snapshot["status"]}}
            if _ACTIVE_OBSERVATION_RUN_ID == run_id:
                globals()["_ACTIVE_OBSERVATION_RUN_ID"] = ""
    except Exception as exc:
        finished = _now_timestamp()
        with _OBSERVATION_RUN_STATE_LOCK:
            snapshot = _OBSERVATION_RUNS.get(run_id)
            if snapshot:
                snapshot["status"] = "failed"
                snapshot["phase"] = "failed"
                snapshot["runtimeStatus"] = "failed"
                snapshot["finishedAt"] = finished
                snapshot["updatedAt"] = finished
                snapshot["latestMessage"] = f"自主观察运行异常：{type(exc).__name__}: {exc}"
```

- [ ] **Step 4: Replace fallback session helper with real conversation chain**

Still in `_run_observation_session`, replace the fallback-only body with the project-native session execution path. Use the same service entrypoint currently used by hidden supervised/self turns in this codebase, passing:

```python
message_source="self_observation"
user_message_source="self_observation"
tool_policy={"allowedTools": [], "preferredTools": [], "writeScopes": [], "readScopes": [], "mutationAccess": "none"}
runtime_metadata={"runKind": "self_observation_run", "runId": run_id, "mode": "self_observation"}
```

If the exact session helper signature differs, keep `_run_observation_session` as the adapter boundary and adjust only this helper. Do not add a direct provider/LLM client.

- [ ] **Step 5: Run backend observation tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation" -q`

Expected: PASS.

- [ ] **Step 6: Commit Task 5**

```powershell
git add core/web/services/self_evolution_control_service.py tests/test_self_evolution_control_service.py
git commit -m "feat: run self-observation through conversation boundary"
```

---

### Task 6: Final Validation, Visual Smoke, And Release Readiness

**Files:**
- Modify only if tests expose a defect in files touched by Tasks 1-5.

**Interfaces:**
- Consumes all previous tasks.
- Produces final implementation branch ready for review or merge.

- [ ] **Step 1: Run backend focused suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py tests\test_web_evolution_routes.py tests\test_supervised_worktree_evolution_service.py -k "self_observation or self_evolution or worktree" -q
```

Expected: PASS. If failures are unrelated to touched behavior, record exact failing tests and rerun the narrower self-observation suite to preserve evidence.

- [ ] **Step 2: Run frontend focused suite**

Run:

```powershell
npm --prefix web run test -- SelfEvolutionTrack.static.test.ts EvolutionRoute.layout.test.ts evolutionWorkspaceCache.test.ts
```

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run:

```powershell
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 4: Run diff hygiene**

Run:

```powershell
git diff --check
git status --short --branch
```

Expected: no whitespace errors; only task files changed before final commit.

- [ ] **Step 5: Commit any final fixes**

If Step 1-4 required small fixes, stage only touched task files:

```powershell
git add core/web/routes/evolution.py core/web/services/self_evolution_control_service.py core/web/services/supervised_worktree_evolution_service.py web/src/api/types.ts web/src/api/queryKeys.ts web/src/routes/EvolutionRoute.tsx web/src/routes/SelfEvolutionTrack.tsx web/src/routes/SelfEvolutionTrack.styles.ts web/src/routes/SelfEvolutionTrack.static.test.ts web/src/routes/evolutionWorkspaceCache.ts tests/test_self_evolution_control_service.py tests/test_web_evolution_routes.py tests/test_supervised_worktree_evolution_service.py
git commit -m "test: validate self-evolution dual modes"
```

Expected: commit succeeds or no commit is needed because previous task commits already contain all changes.

- [ ] **Step 6: Runtime refresh decision**

Do not restart Launcher from the task worktree. Report:

```text
Launcher refresh: required before real UI verification because this changes frontend bundle, backend API routes, and self-evolution runtime behavior.
Active-work guard must be checked before refresh.
```

- [ ] **Step 7: Manual smoke after merge and refresh**

After the branch is merged to main and Launcher refresh passes active-work guard:

1. Open `/evolution?track=self`.
2. Select `自主观察`.
3. Enter goal `观察 Agent 如何拆解一个小型重构任务`.
4. Set duration to `60`.
5. Start observation.
6. Confirm UI shows `工具 0`, `worktree no`, live output/report, and terminate button while running.
7. Confirm no worktree file list, diff, merge, discard, or tool request control appears in observation mode.
8. Switch to `隔离开发`.
9. Confirm existing worktree launch and approval controls still appear.

Expected: both modes are visibly distinct, observation cannot mutate code, isolated development still uses reviewed worktree flow.

---

## Self-Review

Spec coverage:

- Two explicit modes: Tasks 4 and 6.
- Isolated development uses existing worktree approval: Tasks 3, 4, 6.
- Observation is 0-tool/no-application/no-worktree: Tasks 1, 2, 3, 4, 6.
- Prompt prevents fake execution claims: Tasks 1 and 5.
- API and DTO projection: Tasks 2 and 3.
- Current state separated from history: Tasks 3 and 4.
- Logging evidence: Tasks 1, 2, and 5 establish lifecycle points; if implementation touches runtime-scene helpers, add bounded event assertions in Task 1 or Task 2.

Placeholder scan:

- The plan contains no unresolved placeholder markers.
- The only adapter warning is in Task 5 Step 4, where the exact existing session helper may differ; the named boundary `_run_observation_session` keeps the implementation localized and forbids direct provider calls.

Type consistency:

- Backend observation run fields match frontend `SelfObservationRun`.
- Action names use `terminate | stop | cancel`.
- Mode names use `isolated_development` and `observation`.
