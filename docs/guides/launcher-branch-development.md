# 分支工作台开发与验收

内部和外部 Agent 使用相同流程。隔离单位是一个固定路径的 Git worktree；同一目录内切换 branch 不会创建新的运行实例。每个 worktree 有独立的后端端口、工作台窗口、实例数据目录和生命周期记录。

## 开发顺序

1. 按 [协作规范](../agents/worktree-collaboration.md) 从当前本地 `main` 创建任务 worktree，并检查任务范围与 claim。
2. 先运行与修改有关的测试。需要真实后端或界面验收时，用 Launcher 启动**任务目录**，或在 Launcher 中启动对应分支行：

   ```powershell
   & "$env:LOCALAPPDATA\Vibelution\Launcher\VibelutionLauncher.exe" --project "<task-worktree>" start
   if ($LASTEXITCODE -ne 0) { throw "Launcher start failed: $LASTEXITCODE" }
   ```

   交互式 PowerShell 可以用调用运算符 `&` 等待原生 Launcher 并读取 `$LASTEXITCODE`。自动化程序应使用 `.NET System.Diagnostics.Process`，设置 `UseShellExecute = false`、`CreateNoWindow = true`，并只对返回的原生 Launcher 进程调用 `WaitForExit()`。禁止用 `Start-Process -Wait` 做退出码验收；它可能把后代 Electron/Python 生命周期也纳入等待，无法证明原生命令自身已经结算。
3. 原生 Launcher 通过 Python bridge 启动或复用共享 Electron 壳。Electron 的 single-instance `additionalData` envelope 携带目标 `projectRoot`、`openWorkbench` 和 lifecycle command；共享壳据此把 `start`、`restart`、`stop` 路由到指定 worktree，而不是默认路由到 `main`。
4. `%LOCALAPPDATA%\Vibelution\instances.json` 是隔离实例的运行权威，不依赖 worktree 内的 `state.json`。启动完成后核对目标项的 `desiredState == "open"`、`phase/status == "steady"`、generation 已前进、`spawnPid != 0`，并且 `portLeaseStatus == "held"`。启动 claim 必须原子持有端口租约；停止完成后应为 `closed/closed`、`spawnPid == 0`，租约转为 `reclaimable`。
5. 用 `scripts/desktop_debug.py --project "<integration-root>"` 发现当前 Launcher，再从目标实例记录取得端口和工作台 URL。不要默认使用 `8000`，不要用 `main` 工作台代替任务实例。Launcher 分支列表应显示目标 `alive == true`、`startable == false`；实际后端 PID 以目标健康响应和 registry 进程身份校验为准。
6. 对目标实例请求 `/api/health`，核对：`routesReady == true`、`workspaceRoot` 精确等于任务目录、`serving.backend.head` 对应任务版本，以及 `serving.frontend.builtFromCommit` 和构建产物来自任务目录。`workspaceRoot` 是当前健康端口属于哪个 checkout 的直接代码归属证据。未提交开发态同时记录 `dirty`、`dirtyTreeDigest`；提交或修改后重新判断该证据是否仍对应被验收内容。
7. 在这个 URL / 窗口完成任务行为验证。记录实例目录、端口、真实 PID、版本和实际操作结果；CLI 返回零或 registry 接收命令，只代表该层结果，不能替代健康、窗口和行为验证。
8. 完成自审及最终检查后，使用 `scripts/task_closeout.py` 合入本地 `main`。合入前先停止本任务试验进程，合入后清理本任务资源。不得停止别人的实例来帮助自身合入。

如果 CLI 返回成功而目标实例仍未运行，记录原生命令退出码、目标 registry 项、健康响应和 CDP 窗口；禁止直接运行另一套后台监督进程，或把其他实例的 HTTP 200 当作成功。任何一层不一致都应停止无人值守验收和合入，先定位 Launcher 路由或实例身份问题。

## 实验团队

长期实验使用固定版本、固定路径、单独保留的 worktree，并保留其实例 `dataHome`。普通开发在其他任务实例完成，合入 `main` 不会自动升级实验实例；实验目录和实例数据不属于普通任务的清理范围。

实例后端、端口、窗口和业务数据彼此隔离，但共享 Electron 桌面壳、operator 配置、Python 工具链、只读依赖缓存和整机 GPU 资源。不得为了一个开发分支修改共享环境或共享配置。确需不同配置或依赖时，先建立独立配置/环境方案；GPU 并发仍要使用项目的全局设备租约，不能把多进程理解成独立 GPU。

Launcher 桌面壳是所有实例的共同控制进程。重启一个分支只替换该实例的后端和窗口；刷新、升级或退出整个壳会影响全部实例，必须单独安排实验停机边界。

## 2026-09-15 实测证据与边界

在 `916cc99f3` 上创建零改动验收 worktree，并使用已安装的原生 `VibelutionLauncher.exe` 完成 `start → restart → stop`。三条命令都由原生进程返回退出码 0：启动后 registry 为 `steady/open`、generation 1、端口租约 `held`；重启后 generation 前进到 3，后端 PID 从 `30336` 变为 `39924`；停止后 generation 4、`closed/closed`、`spawnPid == 0`、租约可回收。

全过程中目标后端使用 `8001`，健康响应的 `workspaceRoot`、backend head 和 frontend commit 都精确属于验收 worktree 与 `916cc99f3`。CDP 只出现该实例工作台，停止后目标窗口和健康端口消失；`main` 的 `8000` 始终关闭。此前 A、B、实验三个 worktree 的并行试点还验证了不同端口可同时运行，停止或重启 A 时其余实例 PID 与健康路由保持不变。

本轮没有执行付费模型、真实研究任务或 GPU 负载，因此已证明的是代码、进程、窗口、端口和实例数据生命周期隔离。共享壳、配置、工具链与 GPU 的资源隔离仍需按上节约束管理。当前自动合入质量门尚未强制读取运行验收证据，Agent 仍须按本契约完成并记录真实运行检查。
