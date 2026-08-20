# Launcher 生命周期 TS 化迁移（绞杀者增量 I0–I6）

Status: **Active**（2026-08-20 立项；I0 锁协议 v2 已实现；I1 TS 投影权威 + 双语言 fixture 已实现；I2 TS registry CAS + stop spawnPid 锁内快照已实现；I3 监督循环 TS 化 + `ownerLease` 心跳已实现；I4b main 行 open/close/restart 队列已迁 Electron；I4a 准入控制已实现）
Authority: [ADR 0009](../adr/0009-launcher-control-plane-lives-in-electron-main.md)（由本计划 I0 增补）· 前置执行账本 [CONTROL_PLANE_MIGRATION](../archive/plans/2026-08/CONTROL_PLANE_MIGRATION.md)（已关闭，其关闭条件只覆盖「编排权归 main + :8765 退役」，未覆盖「逻辑本体 TS 化」——本计划补齐这一段）。
验收总则：每个增量独立 worktree、独立合入、独立可回退；全部完成后，**launcher 生命周期逻辑（状态机、registry 写入、命令队列、监督循环、进程收割编排）全部运行在 Electron main（TS）内**；Python 只保留 workbench 后端本体与 git/文件维护 CLI。

---

## 0. 背景与证据（已被代码证实）

用户要求：launcher 全部 TS 开发、控制面单一进程。ADR 0009 已裁决 Electron main 是控制面，但 §Decision 5 允许「剩余 Python launcher 逻辑以无控制台 CLI 子进程形式存在于产品路径」——现状停在这个中间态：**控制面表皮（窗口/托盘/IPC/编排）是 TS，生命周期逻辑本体在 Python CLI 里**，Electron 每次生命周期操作 spawn 一个 pythonw bridge。由此产生的病灶：

| # | 病灶 | 证据 |
| --- | --- | --- |
| D1 | 投影规则双语言手工实现且已分叉 | TS `startable = lifecycleState === "closed"`（`desktop/electron/src/windows/launcherWindowTruthOverlay.ts:247`）vs Python 允许 error 且无活信号时重试（`core/launcher/branch_instance_lifecycle.py:490-492`）；TS 窗口开着把 stopping 改写为 steady（overlay:172-186）；frontendReady 一边看标志一边看 dist 文件（overlay:54 vs branch:546-548）；Python 有算了即弃的 `observed_state` 死参数（branch:322-323）。后果：失败行在桌面 UI 不可重试；未构建 dist 的 worktree 永远 partial |
| D2 | stop 盲写无 CAS | `_claim_isolated_stop`（branch:1194-1213）不查 in-flight、不比对 generation；`upsert_instance`（`core/runtime_manager/instances_registry.py:233-248`）无条件覆盖；stop 用锁外读到的 spawnPid 杀进程（branch:706-709）。文件锁只防撕裂不防逻辑交错 |
| D3 | 监督者死亡恢复脆弱 | ownerPid 记短命 bridge 进程（branch:1164）；回收要求 deadlineAt 已过**且 spawnPid 已死**（branch:401-428）——子进程 hang 则行永久 starting；Electron 180s 等待起点比 registry deadlineAt 晚最多 20s（`pythonJsonBridge.ts:8-9`），两套 deadline 不同源 |
| D4 | 无准入控制/退避 | 用户快速连点即命令风暴（2026-08-20 实测两次打挂系统）；join 只去重同类型 |
| D5 | 收割靠扫描非内核保证 | psutil 候选扫描 + 已知 PID + clean proof（`process_inventory.py`）；崩溃残留仍可能，proof 会被后续 state 写入作废 |
| D6 | 列表刷新 O(N) 串行 | 每行 2× state.json 读 + 最多 0.4s 串行 HTTP（`core/launcher/state_refresh.py:214-226, :500-501, :922`） |
| D7 | 超时预算分散 | stop 最坏 ≈70s（5s 杀树 + 60s 子进程 + 2×5s 锁）贴着 Electron 外层 75s 跑，余量 5s |

## 1. 目标架构

```text
VibelutionLauncher.exe（薄 shim，转发）
  → Electron main（TS，唯一控制面进程）
      · 状态机单一权威（instanceLifecycleProjection）
      · instances.json 唯一写者（instanceRegistryStore，CAS）
      · 命令队列（main 行 + 隔离行）+ 准入控制/退避
      · 监督循环（waitForHttp/observe/租约心跳）
      · 进程收割编排（Job Object 可选增强）
  → Python（子进程，只做三件事）
      · workbench 后端本体（scripts/web_workbench.py + core/web）
      · git / worktree / 文件维护 CLI
      · RM daemon 中非 launcher 域的循环（演化运行、storage migration）——不迁
```

「单一进程」定义：**控制面单宿主**（Electron main 内不再 spawn 任何 lifecycle python CLI）；workbench 后端本来就是独立子进程，不在本计划范围。

## 2. 迁移原则

1. 绞杀者：一个增量一个分支一个合入，任何时刻 main 可发布。
2. 契约冻结（§5）：改契约必须先改本文档再改代码。
3. 双语言等价用共享 fixture 驱动（不是字符串合同测试）。
4. 迁移期双写一致：TS 新权威 + Python 旧实现并存时，行为差异必须为零（fixture 保证）。
5. 遵守 AGENTS §2 全部红线：无控制台、无 taskkill、active-work 固定文案、根 main 只读。

## 3. 增量任务图

依赖：I0 → I1 → I2 → I3 → I4b；I4a 可在 I2 后任意时点并行；I5 在 I4b 后；I6 收口。

### I0 · ADR 0009 增补 + 锁协议 v2（双语言互操作）

- ADR 0009 增补（Status 行 + Decision 5 收窄）：Python 产品路径合法角色收敛为 (a) workbench 后端本体；(b) git/worktree/文件维护 CLI；(c) 过渡期 lifecycle CLI（按本计划逐增量退役）。生命周期状态机与 instances.json 写入权威 = Electron main。引用本计划。
- 锁协议 v2（替换 `instances_registry.py` 的 msvcrt/fcntl 字节锁）：`instances.json.lockdir` 目录锁。claim = `mkdir`（原子）+ 写入 `holder.json` `{pid, startedAt}`；轮询 10ms、超时 5s；stale（holder `startedAt` >10s，或 lockdir 存在但无合法 holder 超过 100ms）可破锁并记录事件 `launcher.registry.lock_stale_broken`；release = 仅在仍持有时递归删除 lockdir。Python 与 TS 各实现一份，互操作。共享常量见 `tests/fixtures/launcher/instance_lock_protocol.json`。
- TS 侧新 `desktop/electron/src/lifecycle/instanceLock.ts`。
- 验收：互操作测试（Python 持锁时 TS 写等待、反之、双方 stale 破锁各一例）；`pytest tests/test_instances_registry.py -q` 全绿；锁开销不明显回退（<50ms 量级）。

### I1 · TS 单一权威投影 + 双语言等价 fixture（修 D1）

- 新 `desktop/electron/src/lifecycle/instanceLifecycleProjection.ts`：按 Python 顺序忠实移植（branch:304-358：start_supervisor_lost → restarting → stopping → in-flight starting → conflict error → failed error → running → partial → closed），并把三处分叉定为规范：
  1. `startable`：`lifecycleState === "closed"` **或** `error 且无活信号`（采 Python 语义）；
  2. 窗口开着不得把 stopping 改写为 steady（删 overlay:172-186 的改写）；
  3. `frontendReady` 由监督者显式提供 build 状态；dist 文件探测仅 Python 过渡实现，TS 不做文件探测。
- Fixture：`desktop/electron/src/lifecycle/__fixtures__/instanceLifecycleProjection.cases.json`（≥30 用例，覆盖 D1 全部分叉 + 边界：in-flight、supervisor-lost、port conflict、partial、terminal 状态表）。pytest 参数化与 vitest 读同一文件。
- `launcherWindowTruthOverlay.ts` 切换到权威模块，删除本地规则；Python 投影标注 `# Deprecated by docs/plans/2026-08-20...（迁移期保留）`。
- 验收：fixture 双语言全等价；`branchInstanceBridge` / overlay / `launcherWindowTruthOverlay` vitest 绿；web UI 行为不回退。

### I2 · TS registry 写入 + CAS 补全（修 D2）

- 新 `desktop/electron/src/lifecycle/instanceRegistryStore.ts`（锁 v2 + 类型化读写）：
  - `claimStart`：锁内 in-flight 检查（409 语义）+ `generation+1` + 端口分配单事务（对齐 instances_registry.py:785-834 语义）；
  - `claimStop`：**先 `generation+1` 取消 in-flight start**，再登记收割；
  - `observeReady/observeError`：generation CAS，旧回写静默丢弃（对齐 branch:1046-1051）；
  - `upsert(entry, expectedGeneration)`：收敛所有写入口，禁无条件盲写。
- Electron 分支实例 start/stop 的 claim/observe 改走 store（backend spawn 仍经 pythonw，I5 换）；杀树快照必须在锁内取。
- Python `_claim_isolated_stop` 同步补 generation bump（迁移期一致性，双向修）。
- 验收：stop-during-start 场景双语言测试（start 声明的 spawnPid 不被 stop 后的旧 claim 复活）；快速连点注入不再交错盲写；`tests/test_branch_instance_lifecycle.py`、`tests/test_instances_registry.py` 全绿。

### I3 · 监督循环 TS 化 + 租约心跳（修 D3）

- Electron 直接执行 waitForHttp / observe 回写（删除 markReady/markError 的 python bridge spawn；杀树暂仍走 Python CLI）。
- `instances.json` 增 `ownerLease {ownerId, expiresAt}`，`schemaVersion` 2→3。借 Kubernetes Lease 的 holder + TTL + renew（`coordination/v1.LeaseSpec`：expired = `now >= renewTime + leaseDurationSeconds`），不引入 apiserver / leader election。TTL **15s**，心跳 **5s**（TTL/3，对齐 systemd `WatchdogSec` 续期节奏）。Electron 心跳只续当前 `ownerId` + matching generation。
- hang 判定 = **租约过期 + `deadlineAt` 已过**（不再要求 `spawnPid` 已死）。缺 `ownerLease` 视为租约已过期。活信号（后端/窗口）仍阻止回收。
- deadline 单源：隔离 start 的 HTTP 等待读 registry `deadlineAt` 剩余时间，不再从 wait 起点另开 180s。180s 只用于 claim 时写入 `deadlineAt`。
- 验收：kill Electron 注入后，行在租约过期 + deadline 后投影为 `error/start_supervisor_lost`（即使 spawnPid 仍 hang），不再永久 starting；observe/waitForHttp 产品路径 0 个 lifecycle python CLI spawn（backend 本体与 stop 杀树除外）。

### I4 · 准入控制 + main 行队列 TS 化（修 D4；拆 I4a/I4b）

- **I4a 准入控制**（独立可先行，已实现）：per-instance 速率限制（默认 burst 3 / 10s，参照 systemd `StartLimitBurst` / `StartLimitIntervalSec`：只计通过条件检查的 start-like 操作，拒绝不计入窗口）+ 连续失败指数冷却（10s→20s→40s…封顶 5min，k8s CrashLoopBackOff 语义；成功 `observeReady` 清零，不借 10min 成功窗）。`stop` / `force-stop` 不限流、不进冷却。冷却中 UI 显示原因与剩余时间；冷却状态持久化到 `%LOCALAPPDATA%\Vibelution\instance-admission.json`（**不**写入 `instances.json`，避免与 I4b intent 抢同一热文件）。
  - 新文件：`desktop/electron/src/lifecycle/instanceAdmissionControl.ts`、`instanceAdmissionStore.ts`、`__fixtures__/instanceAdmission.cases.json`。
  - 接入：隔离 `claimIsolatedStart` / `observeIsolatedReady` / `observeIsolatedError`；IPC 对 main 行 `start|restart|rebuild-and-start` 先 `admit`；overlay 写 `startBlockReason` + `admissionMessage` + `admissionRetryAfterMs`。
  - **不改** `main.ts` 命令队列、`daemon.py`、`instanceRegistryStore.ts`。杀树仍 Python。
  - 验收：1s 内 10 次 restart，前 3 次放行、后 7 次 `rate_limited`；冷却态重启 Electron 后仍在；列表显示原因与剩余秒数；计时埋点口径不变（本增量不改 wait/observe 路径）。
- **I4b main 行队列迁移**：open/close/restart 命令队列与 idle reconcile 从 RM daemon 迁 Electron main（进程内队列 + 崩溃恢复用持久化 intent；观测复用 I1 投影）。**边界：daemon.py 中 self/supervised 演化循环、hot-restart 会话、storage migration 不迁**（workbench 域）。main 行观测在 TS 内实现：net.connect 健康门槛 + 已知 pid 存活检查（TS 自己 spawn 的进程，属主信任链简化，不需要 Win32 端口属主表——那是 Python 多进程观测域的需求）。
  - 落点：`desktop/electron/src/lifecycle/mainLine/`（`commandQueue` / `commandIntent` / `observation` / `idleReconcile` / `ownerMarker`）；`runWorkbenchLifecycle` 先入队再 spawn 既有 lifecycle CLI（杀树与 backend spawn 仍 Python，I5 再换）。
  - 崩溃恢复 intent 写在 `runtime-manager/main_line_intent.json`，**不**改 `instances.json` 契约。Electron 另写 `main_line_queue_owner.json`；daemon 在 owner pid 存活时跳过 workbench idle reconcile / `browser_missing` 自动关，演化循环仍跑。
  - daemon.py workbench 耦合面（I4b 只停 idle reconcile，不抽执行器）：`_handle_open_workbench` / `_handle_close_workbench` / `_handle_restart_workbench` / `_handle_force_close_workbench` 仍由 lifecycle CLI → 文件队列执行；`hot_restart_workbench`、`_process_self_evolution_restart_intent`、storage migration 不迁。
- 验收：注入风暴（1s 内 10 次 restart）被合并/拒绝且终态正确；main 行 e2e 启停计时对照埋点基线（`restart_initial_observation_ms` 等口径，当前重启 ≈7.3s）不劣化。I4b 把 join 提到 Electron，不改变 daemon 内 `restart_initial_observation_ms` 探针位置。

### I5 · action 脚本产品路径退役

- backend spawn / 健康等待 / 端口释放全部 TS：Electron 直接 spawn `pythonw scripts/web_workbench.py`（参数与 `vibelution_launcher.py` 的 `_start_backend` 一致），健康等待 net.connect 门槛 + HTTP /api/health（对齐 2026-08-20 已合入的 health-probe-gate 语义）。
- `vibelution_launcher.py` / `vibelution_desktop_entry.py` 产品路径退役（unpackaged 测试与原生 shim 路径可保留）。
- 验收：产品路径生命周期操作 0 个 lifecycle python CLI spawn（backend 本体除外）；冷启/重启计时不劣化；无可见控制台。

### I6 · 收口

- 删除 Python 侧：branch_instance_lifecycle 的 claim/observe 写路径、state_refresh 的 reconcile 写路径、RM daemon 的 workbench 队列（演化循环保留）、锁 v2 简化为 TS-only。
- 事件统一：TS 成为 events.jsonl 单写者（或保留 TS 独立事件文件 + 工具合并视图，二选一在增量内决策并记录）。
- 文档同步：`core/launcher/instance-lifecycle.md`、`docs/ops/config/07-launcher-runtime-workbench.md`、`desktop/electron/README.md`、`core/web/services/launcher_runtime.md`、AGENTS §3 路由表；`tests/test_launcher_*.py` 收缩为 child/CLI 契约。
- 可选增强（独立评审后再做）：子树挂 Windows Job Object（kill-on-close），替代扫描式收割（D5）。
- 验收：全测试矩阵绿 + e2e + 文档一致性检查（无引用已删符号）。

## 4. 明确不做（Out of scope）

- 工作台后端（FastAPI/uvicorn/core/web）TS 化；Chat/Agent/LLM/演化循环。
- Tauri/WinUI/Electron 外的第二个 Node HTTP 控制面。
- web/ Launcher 页面重写（仅 transport 跟随 IPC 变化，VUI 红线照旧）。
- 远端 push / PR（需用户单独授权）。
- Job Object（除非 I6 后单独评审通过）。

## 5. 契约冻结清单（改前先改本文档）

- `instances.json` 字段：`schemaVersion`（I3 起为 **3**）, `instances[]{id,branch,desiredState,status,phase,generation,commandId,spawnPid,deadlineAt,failureMessage,port,controlPort,ownerLease{ownerId,expiresAt}}`。
- 事件名与 payload：`workbench.*` / `launcher.*` / `electron.*`（含本计划新增 `launcher.registry.lock_stale_broken`、I4a `launcher.admission.rate_limited` / `launcher.admission.cooldown`）。
- IPC 通道（`preload.ts` IPC_CHANNELS）与 C# shim 转发协议。
- active-work guard 固定中文文案（AGENTS §4）。
- 超时常量现值：180/60/240（start/stop/restart）、75/20（bridge）、8（browser-missing 宽限）、30（close tx lease）、**15/5（I3 `ownerLease` TTL/心跳，秒）**、**I4a 3/10s burst 与 10s→300s 失败冷却**（systemd StartLimitBurst=3 严于默认 5；冷却公式对齐 kubelet CrashLoopBackOff，成功即清零）——调整需在增量内显式声明并给理由。
- 无控制台红线与 CREATE_NO_WINDOW 路径。

## 6. 测试与验证

- 每增量必跑：
  - `python -m pytest tests/test_instances_registry.py tests/test_branch_instance_lifecycle.py tests/test_launcher_branch_instance_runtime.py -q`
  - `cd desktop/electron && node node_modules/vitest/vitest.mjs run && npx tsc -p tsconfig.json --pretty false --noEmit`
- 触及 web transport 时另跑 web 契约门（见 AGENTS §4）。
- e2e：Launcher 实测启停/重启，事件流埋点计时口径对比（禁止计时回归无说明合入）。
- 风暴注入：脚本化 1s 内 10 次生命周期命令，断言终态与队列健康（I4a 起纳入）。

## 7. 风险与对策

| 风险 | 对策 |
| --- | --- |
| 迁移期双写竞态 | 锁 v2 + CAS + fixture 等价；每增量后跑风暴回归 |
| 事件文件跨进程并发追加 | 迁移期 TS 写独立事件文件，I6 统一 |
| Electron main 改动需 asar 重建才生效 | 沿用 ADR 0009 既有的打包刷新机制；验收含实测 |
| daemon 演化循环与 workbench 队列耦合 | I4b 前先做耦合面清单（grep daemon.py 的 workbench 符号引用），拆不干净就再细分增量 |
| 计时回归 | 埋点口径基线（重启 ≈7.3s）写进每增量验收 |
