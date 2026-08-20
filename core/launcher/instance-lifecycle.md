# 隔离分支实例生命周期（P0 合同）

**读者：** coding Agent。
**Owner：** Electron desktop shell（监督者）+ 当前 checkout 的 Python JSON CLI。
**非目标（本轮不做）：** checkout / `git worktree add` UI、托盘 HTTP→IPC 迁徙、列表 git-dirty 加速。
**`main` 行：** 仍走 Runtime Manager 队列；本文件不改变该合同。

权威交叉引用：`docs/standards/development-standard.md` §8.0 · ADR 0009 · [`launcher_runtime.md`](../web/services/launcher_runtime.md)。

---

## 1. 问题

隔离 worktree 曾有两套监督者、两套成功定义：

| 路径 | 实际行为 | 错误成功定义 |
| --- | --- | --- |
| 当前 checkout | Electron → JSON CLI → RM 队列 → **202** → 等 HTTP → 开窗 | 后端健康 **且** 窗口 open 才是 `running` |
| 其它 worktree | Electron → JSON CLI → **`subprocess.run` 目标树可能过期的** `scripts/vibelution_launcher.py`（最长 180s） | spawn exit 0 就写 `status=running` |

再叠加：`instances.json` 无跨进程锁、端口两次 upsert、投影优先读 worktree `state.json` 的 `failureMessage`、Electron `openOrchestratedWorkbenchWindow` fire-and-forget（失败只 `console.warn`）、HTTP 等 90s 而 Python start 超时 180s。

P0 只修 **生命周期内核**：一个监督者、一套 READY、desired/observed reconcile、CAS generation、停止时先收割 `spawnPid`。

---

## 2. 成熟方案切片（只借，不引入编排器）

| 来源 | 借什么 | 不借什么 |
| --- | --- | --- |
| 本仓 `main` 行 | desired/observed、命令 **202**、Electron 等 HTTP 再开窗 | 不把隔离行塞进 RM 队列 |
| systemd | `READY` ≠ “进程已 spawn” | unit 文件 / journald |
| Kubernetes | `generation` CAS；过期观察者不得写回 | apiserver / etcd |
| Compose | **一份当前二进制** 操作目标 cwd | YAML / 项目模型 |
| PostHog light worktree | lockfile 字节相同则借用主仓 toolchain/venv，禁止往共享环境写包 | flox / `UV_NO_SYNC` / husky 钩子 |

禁止引入 k8s、systemd、Compose、etcd。

---

## 3. SSOT

| 事实 | Canonical | 唯一写入者 |
| --- | --- | --- |
| `desiredState` + `generation` + 端口 + `spawnPid` + `deadlineAt` + `commandId` | `%LOCALAPPDATA%\Vibelution\instances.json` | **当前壳** Python CLI（经 Electron IPC） |
| 后端 READY | 隔离 slot `launcher/state.json` 或目标树 `.runtime/launcher/state.json`，加上列表投影的 loopback HTTP 活探测 | 该树 Runtime Manager / launcher 子进程写 state；列表投影只读探测，不写 READY |
| 窗口是否 open | Electron `windowProvider` | Electron main（`VIBELUTION_ELECTRON_MAIN_ORCHESTRATES_WINDOWS=1`） |
| `lifecycleState` | **投影**（desired + 后端 READY + 窗口） | 无独立写入者 |

Python `_instance_lifecycle_state` 与 Electron `composeInstanceLifecycleState` **必须同一套规则**（见 §6）。

`instances.json` 的 desired / phase / generation / status **优先于** 目标树 `state.json`。
`registry.status == "running"` **不是** READY。窗口真相只来自 Electron overlay。
隔离行列表投影：后端 PID 仍活、端口已知、磁盘 `backendPortListening`/`backendHealthy` 缺失时，对 `http://127.0.0.1:<port>/` 做一次短超时 GET（与 Electron `waitForWorkbenchHttp` 相同：status 1–499）。成功则视为后端 READY；窗口未开时投影为 `partial`，不得停在 `starting`。

---

## 4. 监督者与 spawn

当前 Electron 桌面壳是 **唯一监督者**。

隔离 start/restart：

1. 当前 checkout 的 `PYTHON_LAUNCHER_SCRIPT_PATH`（`core/runtime_manager/constants.py` → `scripts/vibelution_launcher.py`）。
2. 当前壳 `pythonw`（监督者解释器）。目标树残留的不完整 `.venv` 不得抢先。后端解释器由 launcher 再选：`requirements.txt` 与监督者相同且监督者 `.venv` 可用则复用，禁止往共享环境 `pip install`；只有依赖不同才在目标树建私有 `.venv`。
3. `cwd` = 目标 worktree。
4. `apply_slot_spawn_environment`：`VIBELUTION_WORKSPACE_ROOT`、端口、slot data home。
5. start/restart 额外：`VIBELUTION_ALLOW_DIRTY_LAUNCH=1`、`VIBELUTION_ALLOW_NON_MAIN_LAUNCH=1`、`--no-browser`。
6. **Popen 分离**（Windows：`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB` + hidden STARTUPINFO；禁止可见控制台）。父 JSON CLI 在 202 后立即退出，子树必须能活过父进程。
7. **禁止** `subprocess.run` 等待隔离 start；**禁止** exec 目标树自己的 `vibelution_launcher.py`。

`vibelution_launcher.py` 必须在 `sys.path.insert` **之前** 读取 `VIBELUTION_WORKSPACE_ROOT` 作为工作区根（runtime/state/cwd 语义）。Python 包默认复用监督者 `.venv`（requirements 指纹相同）；私有 `.venv` 仅在指纹不同时创建。同时把 **脚本所在 checkout** 插入 `sys.path`，保证跑的是监督者协议代码而非目标树旧模块。工作台进程仍执行目标树的 `scripts/web_workbench.py`（`Path(__file__).parent.parent` 进 `sys.path`），源码来自该 worktree。

stop / force-stop：仍 **等待** 目标 stop（超时 60s）；但必须 **先** 用 in-process `psutil` 杀掉登记的 `spawnPid` 进程树（含根进程），再跑 `--action stop`。禁止 `taskkill.exe`。

Electron 编排窗口时，Python **不得** 再 `open_isolated_workbench_window` / `close_isolated_workbench_window`（避免双关窗）。窗口由 Electron 在 HTTP READY 之后打开、在 stop 时关闭。

---

## 5. 命令模型与状态机

命令 **202**：CLI 只负责 claim + spawn/reap，不等后端 READY。

```text
closed → starting → (backend READY) partial → (window open) running
                 ↘ timeout / HTTP 失败 / spawn 失败 → error
running|starting|partial|error → stopping → closed
```

- 仅 **后端 READY + 前端资产就绪 + 窗口 open** 才是 `running`。
- stop / force-stop 可取消 in-flight start（先 bump `generation`）。
- 同一实例在 `starting|stopping|restarting` 时第二次 start → **409** `instance_busy`；除非该 in-flight start 已证明死亡（`deadlineAt` 已过、`spawnPid` 不存在或已死、无后端/窗口活信号）→ 先在锁内回收为 `failed` 再放行新 claim。
- 无活进程的 `error` leftover **允许再次 start**（新 generation 清掉旧 `failureMessage`）。
- `main` 行不走本状态机的 registry claim。

Registry 字段（隔离行）：

| 字段 | 含义 |
| --- | --- |
| `desiredState` | `open` / `closed` |
| `status` | `starting` / `restarting` / `stopping` / `failed` / `closed` / `steady`（**不要**把 spawn 成功写成 `running`；READY 后由监督者写成 `steady`） |
| `phase` | 与 status 对齐的投影提示：`starting` / `restarting` / `stopping` / `failed` / `steady` |
| `generation` | 每次 start/restart/stop claim +1 |
| `commandId` | 本次命令 id |
| `spawnPid` | 分离后的监督者 launcher 子进程 |
| `deadlineAt` | start 观察截止（隔离 **180s**） |
| `failureMessage` | 仅当前 generation 的失败文案 |
| `port` / `controlPort` | 一次加锁事务内同时分配 |

`observe-error`（Electron 监督回写）：仅当 `status ∈ {starting, restarting}` 且 `generation` 匹配（或调用方未传 generation）时写成 `failed`。过期 generation **静默 no-op**。

`observe-ready`（HTTP 成功且窗口已开）：仅当 generation 匹配且仍 in-flight 时写成 `status=steady`、`phase=steady`、`desiredState=open`、清空 `failureMessage`。这不是 `running`；`running` 只来自投影。

---

## 6. 投影规则（Python ≡ TypeScript）

输入：`desiredState`、`phase`、`registryStatus`、后端四元组、`frontendReady`、`windowOpen`、`failureMessage`。

顺序：

0. **监督丢失的 in-flight start**（`startSupervisorLost`）：`deadlineAt` 已过、`spawnPid` 缺失或已死、后端未 READY 且窗口未开 → `error` / `start_supervisor_lost`。监督进程承诺在 `deadlineAt` 前写 `observe-error`；它死了就不能让行永远停在 `starting`/`restarting`。
1. `phase ∈ {restarting, restart}` 或 `registryStatus == restarting` → `restarting`
2. `phase ∈ {closing, stopping, force_stopping}` 或 `registryStatus == stopping` → `stopping`
3. **in-flight start**：`(desiredState == open 且 registryStatus ∈ {starting, restarting})` 或 `phase ∈ {opening, starting}`，且后端未 READY、窗口未开 → `starting`（**忽略** leftover `failureMessage`）
4. `backendConflict` → `error` / `backend_port_conflict`
5. `phase == failed` 或 `registryStatus == failed` 或（有 `failureMessage` 且非步骤 3）→ `error`
6. 后端 READY 且 `frontendReady !== false` 且 `windowOpen` → `running`
7. 有活信号（进程/监听/窗口）→ `partial`
   **禁止**把 `registryStatus == running` 或仅磁盘 `observedState ∈ {open, partial, running, healthy}` 当作活信号。列表 overlay 在 daemon 未跑且后端端口未听时，必须把 leftover `opening/open` 收成 `closed`。
8. 否则 `closed`

Electron overlay 在写入 `window.open` 后必须用同一函数重算 `lifecycleState`，并传入 `desiredState` / `registryStatus`。

---

## 7. `instances.json` 原子性

- 旁路锁协议 v2：`instances.json.lockdir` 目录锁（Python `core/runtime_manager/instance_lock.py` 与 TS `desktop/electron/src/lifecycle/instanceLock.ts` 同一协议）。
- claim：原子 `mkdir` + `holder.json` `{pid, startedAt}`；轮询 10ms，超时 5s。
- stale：holder `startedAt` 超过 10s，或 lockdir 存在但无合法 holder 超过 100ms，可破锁并写事件 `launcher.registry.lock_stale_broken`。
- release：仅当 holder 仍是本进程本次 claim 时递归删除 lockdir。
- 所有读-改-写（upsert、端口分配、claim、observe-error）走同一把锁。
- `allocate_instance_ports`：**一次** lock 内选互斥的 backend+control，**一次** `save_registry`。禁止两次 upsert 之间被并发插入。
- 锁不可重入：锁内不得再调用会取锁的 `upsert_instance`。

---

## 8. Electron 监督循环（Critical Path）

隔离 start/restart 在 JSON CLI **202** 之后：

1. 等待 `http://127.0.0.1:<port>/`，超时 **180_000 ms**（`ISOLATED_INSTANCE_READY_WAIT_MS`）。当前 checkout `main` 行仍用 90s。
2. HTTP 成功 → `openOrFocusInstanceWorkbench` → 对同一 `generation` 调 `observe-ready`。
3. HTTP 超时 / 非就绪 / 开窗失败 → 对 **同一 generation** 调 `observe-error`。禁止只 `console.warn`。
4. 监督循环可 fire-and-forget 以免堵住 IPC 202，但失败路径必须写回 registry。

当前 checkout 的窗口等待保持 `WORKBENCH_START_READY_WAIT_MS`（90s），不走 `observe-error`。

---

## 9. 验收（测试必须锁住）

1. start 之后、HTTP 之前：`lifecycleState=starting`，`desired=open`，不是 `running` / `error`。
2. HTTP 超时：同一 `generation` → `error`；stop 能收割 `spawnPid`。
3. 先前 `failureMessage` + 新 start：不卡在 `error`。
4. 窗口未开：不是 `running`。
5. 第二次 start（in-flight）：409 `instance_busy`。
6. 并发 start / 并发端口分配：端口不重复。
7. 监督死亡（`deadlineAt` 过 + `spawnPid` 死 + 无活信号）的 `starting` → `error` / `start_supervisor_lost`，且重试 start 在锁内回收旧 claim 后放行；监督仍活或期限未到的 in-flight 仍 409。
8. Electron-owned close 后端验证关闭后立即清 launcher `state.json`（同 fast path），不等窗口 ack；ack 缺失不得留下 `open/steady` + 死 `backendPid` 的残留。
9. in-flight `starting` + 后端 PID 活 + loopback HTTP READY + 窗口未开 → `partial`，不是 `starting`。

---

## 10. 无控制台

后台 spawn：`pythonw` + `detached_no_console_popen_kwargs` / `CREATE_NO_WINDOW` 等待路径。
禁止产品路径弹出 `cmd.exe` / `powershell.exe` / WT / OpenConsole。禁止 `taskkill.exe`。

---

## 11. 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_instances_registry.py tests\test_branch_instance_lifecycle.py tests\test_launcher_branch_instance_runtime.py tests\test_windowless_subprocess.py -q
cd desktop\electron
node node_modules\vitest\vitest.mjs run tests/launcherWindowTruthOverlay.test.ts tests/isolatedInstanceSupervisor.test.ts tests/branchInstanceBridge.test.ts tests/desktopMainLauncherIpc.test.ts
npx tsc -p tsconfig.json --pretty false --noEmit
```

不改 `web/`，不必跑 `web` 的 `tsc -b`。
Launcher refresh：**recommended before user testing**（Python + Electron 内核）。
