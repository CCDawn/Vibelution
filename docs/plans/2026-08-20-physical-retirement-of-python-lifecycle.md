# Python lifecycle 代码物理清理（执行清单）

Status: **Active**（批次 A、B 已合入；批次 C 已执行：C-1 下线 branch-instances/start|stop|force-stop|restart 四端点 + web 客户端 IPC-only + Electron 死桥删除（branchInstanceBridge.ts，类型移入 isolatedInstanceRegistryHost）；C-2 删除孤儿 observe_isolated_transition；整文件删除与 RM 关闭路径归批次 D）
Authority: [ADR 0009](../adr/0009-launcher-control-plane-lives-in-electron-main.md)（I6 增补已宣告 lifecycle CLI 退役；本计划执行物理删除）· 前置迁移计划（已归档）：`docs/archive/plans/2026-08/2026-08-20-launcher-lifecycle-ts-migration.md`
目标：把已退役的 Python lifecycle 写路径从仓库物理删除；保留 status/settings/维护/演化意图面。**只做本清单内的事，按批次顺序，每批独立合入。**

## 0. 现状事实（已核实）

- 产品路径 lifecycle 已全在 Electron main（TS）：`instanceRegistryStore`/`instanceLifecycleProjection`/`isolatedInstanceSupervisor`/`workbenchBackend`（直接 spawn `pythonw scripts/web_workbench.py`）。
- web 客户端 IPC 优先（`web/src/api/launcher.ts:469`），HTTP 仅浏览器兜底。
- 残留引用链（物理删除的障碍）：`core/web/routes/launcher.py` → `core/launcher/service.py`（生命周期命令函数）→ `branch_instance_lifecycle.py` → `instances_registry`/`isolated_workbench_window`/`scripts/vibelution_launcher.py`；`scripts/vibelution_desktop_entry.py` 与 `core/launcher/app.py` 也调用同一批函数。
- 演化服务只依赖 `submit_lifecycle_intent`/`get_lifecycle_intent`/`get_launcher_status`（**保留**）。

## 1. 批次与手术边界

### 批次 A · HTTP 生命周期命令面下线

删除 `core/web/routes/launcher.py` 中这些端点（含 handler）：
`/launcher/start` `/launcher/stop` `/launcher/force-stop` `/launcher/restart` `/launcher/rebuild-and-start` `/launcher/supervisor/reattach`（约 :314-395、:590 附近）。
同步 `core/launcher/app.py` 中同语义路由。
web 客户端（`web/src/api/launcher.ts`）：对应方法改为 IPC-only——无 bridge 时抛 `LAUNCHER_IPC_HOST_NOT_READY`（浏览器打开工作台时按钮给出明确错误，属预期行为变化，写进提交说明）。
验收：`pytest tests/test_web_runtime_routes.py -q`；web 侧 `npx tsc -b` + launcher 相关 vitest。

### 批次 B · service.py 函数级切除

删除 `core/launcher/service.py` 中：`request_launcher_start` `request_launcher_stop` `request_launcher_restart` `request_launcher_force_stop` `request_launcher_rebuild_and_start` `request_launcher_runtime_shutdown` `request_launcher_supervisor_reattach`，及随之孤儿化的私有链（prequeue 计时/reap 子树/clean proof/`_recover_stale_*` 等——**每删一组必须 grep 全仓确认零引用**）。
保留：`get_launcher_status`、`get_launcher_freshness`、settings 读写、desktop session/action、close transaction、developer mode、maintenance cleanup、`submit/get_lifecycle_intent`。
同步收缩 `scripts/vibelution_desktop_entry.py`：`--action start|stop|force-stop|restart|shutdown` 模式改为返回错误码+文案「lifecycle 已由 Electron 接管」；保留 `--launcher-api-path` 通用转发与维护类动作（Electron main.ts:3181 的桥只允许走这两类）。
验收：`python -m pytest tests/test_launcher_service.py -q`（收缩后）+ `ruff check` 无新告警。

### 批次 C · 死模块整删

前置：A、B 合入后以下文件应零活引用（逐个 grep 验证后再删）：
`core/launcher/branch_instance_lifecycle.py`、`core/launcher/isolated_workbench_window.py`、`scripts/vibelution_launcher.py`、`core/launcher/branch_instance_cleanup.py` 中仅服务 lifecycle start 的部分（`cleanup_launcher_branch_instances` 维护面板仍在用，保留其依赖的最小集）。
`core/runtime_manager/constants.py` 的 `PYTHON_LAUNCHER_SCRIPT_PATH`：若 `workbench_controller.py:1341` 仍是唯一使用者，说明 RM close 路径未死——**先确认 RM workbench 命令是否还有活入口，有则本批次不删该常量**，留批次 D。
验收：全仓 grep 零引用；`pytest tests/test_launcher_branch_instance_runtime.py tests/test_launcher_scripts.py tests/test_launcher_scripts_contract.py`（同步删除或收缩）；启动器 e2e 冒烟（stop→start→health 200）。

### 批次 D · RM workbench 部分切除（最大手术，单独评审后做）

**D 耦合面清点（2026-08-21 已完成，实测与 grep 证实）：**
- 主线启停已 Electron 原生：RM 队列最后一次受理 restart 是 2026-08-20T11:52（迁移收口前）；此后重启只产生 settings 事件，无 command_queue 事件。
- **演化域仍依赖 RM 队列的 workbench handler，不可全删**：`supervised_control_service` 提交 `pause/resume/retry/stop_supervised_run`；`lifecycle_action_dispatcher` 把演化意图映射为 `hot_restart_workbench`（apply 后热重启）、`close_workbench`（request_app_exit）、`recover_workbench`。daemon 切除只能针对确认零提交者的 handler（open_workbench / restart_workbench 待逐个验证），hot_restart/close/recover 必须保留或随演化热重启通道一起迁移。
- `vibelution_launcher.py` 仍被两处夹持：cleanup 停实例的 `--action stop` 子进程、`workbench_controller.py` 的 RM close 路径。删除该脚本前必须先替换这两条。

**D-1 已执行（2026-08-21）**：`run_isolated_operation` 的 start/restart 分支替换为 control_plane_is_electron 拒绝；孤儿 helper（`_open_instance_window`/`_existing_matching_start_claim`/`_reclaim_stale_in_flight_start`/`current_live_ports`）删除；`isolated_workbench_window.py` 的窗口打开机器删除（314→228 行），关窗/回写/标题/overlay 保留。
**D 剩余**：列表/清理只读面搬迁后整删 `branch_instance_lifecycle.py` 与 `isolated_workbench_window.py`；替换 cleanup stop 与 RM close 的脚本调用后删除 `vibelution_launcher.py`；daemon 逐 handler 切除。

**D-2 提交者清点（2026-08-21 已验证，可直接执行）：**
- `open_workbench` / `restart_workbench`：**零队列提交者**（window_provider_dispatcher 的同名 desktop action 不是队列命令；演化只派发 hot_restart/close/recover）。daemon 中这两个 handler 及其专属 helper 链（open 的 fast-path/verification 链、restart 的 `_perform_restart_workbench`、build-preflight 家族——确认无 force-rebuild 残留引用后）可整体切除。注意共享面：`_close_workbench_with_fast_path`、`_finish_command`、observe/reconcile 家族被 close/hot_restart 共用，必须保留。
- 测试规模（实测）：`tests/test_runtime_manager.py` 内 175 处引用，另牵连 5 个测试文件（test_launcher_service / test_launcher_scripts / test_vibelution_desktop_entry / test_web_runtime_routes / test_runtime_scene_package_diagnosis）。收缩按「删 handler 用例、保留 close/hot_restart/演化用例」执行，预期是本计划最大的一次测试手术，建议独立 worktree 单独一批合入。
- `close_workbench` / `force_close_workbench` / `hot_restart_workbench` / `recover_workbench`：演化意图与关窗事务仍在用，**本轮不切**；它们的最终归宿是随演化热重启通道一起迁移到 Electron（另行评审）。

`core/runtime_manager/daemon.py`（5859 行）中 workbench 命令队列/reconcile/observe 与 `workbench_controller.py` 的 launcher-action 链。**边界：演化循环（self/supervised）、hot-restart 会话、storage migration 必须原样保留。** 先产出 daemon 内 workbench↔evolution 耦合面清单（符号级 grep），耦合拆不干净就再细分批次。本批次不做就不做，禁止半途合入。

## 2. 测试收缩对照表

| 文件 | 处置 |
| --- | --- |
| `tests/test_launcher_service.py` | 删生命周期命令用例，保留 status/settings/maintenance/intent 用例 |
| `tests/test_branch_instance_lifecycle.py`、`tests/test_launcher_branch_instance_runtime.py` | 批次 C 随模块删除 |
| `tests/test_launcher_scripts.py`、`tests/test_launcher_scripts_contract.py` | 删 action 脚本用例；desktop_entry 只留转发/维护用例 |
| `tests/test_native_launcher_sync.py`、`tests/test_native_launcher_entry.py` | 按剩余面收缩 |
| `tests/test_web_runtime_routes.py` | 删已下线端点的路由测试 |
| Electron/desktop 侧测试 | 不动（TS 权威面已有覆盖） |

## 3. 硬规则

- 每批次独立 worktree（`codex/<batch-slug>`）、全绿后 ff-only 合入；顺序 A→B→C，D 单独评审。
- 删除任何函数/常量前必须全仓 grep（含 tests/、desktop/、web/、scripts/）确认零活引用；发现清单外引用即停下上报，不扩大手术面。
- 产品路径禁止可见控制台红线继续适用；本清理不新增任何行为，只删除退役代码。
- 完成判定：批次 A-C 合入 + Launcher 实测（stop→start→重启→health 200）+ `grep -rn "request_launcher_start" core/ scripts/` 为空。

## 4. Out of scope

- workbench 后端本体、演化循环、storage migration（永不删）。
- `core/web/services/launcher_service.py` 的非生命周期转发面。
- daemon.py 的演化部分（批次 D 之前不动）。
