# 开发链路吞吐与收口修复方案

## 目标

在不削弱现有正确性门禁、claim 隔离和 `main` 只读开发规则的前提下，修复测试子进程泄漏，缩小错误测试选择，避免 closeout 因并发合入反复作废，并把验证、ff-only 合入与任务资源清理串成一个失败即保留现场的受管闭环。

## 当前证据

- `test_v2_scope_lock_serializes_cross_process_claim_and_side_effect` 在 barrier 失败时没有 `finally`，已留下等待 `start.txt` 数小时的 worker。
- SCI 修复的 7 文件 diff 被 selector 扩成 7 条命令；`test-tool-authorization.paths` 中的 `tests/**` 使任意测试文件都触发授权契约。
- 两轮 closeout 各约 5.7 分钟，第二轮通过命令后因 `main` 漂移成为 `stale_main`；现有 gate 检查漂移，但没有在昂贵验证期间持有 integration lease。
- 当前 merge queue 为空，同时存在 review、blocked 和 cleanup-ready worktree；规则要求合入后立即清理，但没有统一执行器。

## 复用与方案裁决

候选按项目贴合度排序：

1. **改造本地现有能力（采用）**：复用 `local_quality_gate.py` manifest、Briefbound coordination claim、Git `--ff-only`、Launcher branch cleanup 的安全判定和本地受控进程终止模式。改造量最小，能保持现有 SSOT。
2. **借鉴 OpenAI Codex 的进程组收口（采用其模式）**：先 terminate，短 grace period 等待，再 kill；生命周期结束时必须触发，不依赖 worker 自行退出。这里只借终止顺序和 fail-safe 原则，不引入 Rust/process-group 子系统。
3. **引入 Bazel/Nx/pytest 插件式缓存（不采用）**：会增加依赖、环境指纹和缓存正确性治理。当前浪费首先来自错误选择、孤儿进程和缺少 main lease，先消除无效工作。
4. **把全部回归迁到 CI（不采用）**：会缩短本地等待，但削弱本地 main 的交付门，不符合项目规则。

## 实施路径

### Task 1：测试进程必须随测试退出

- 在跨进程 scope-lock 测试中用 `try/finally` 包围 barrier 与 `communicate`。
- 对仍存活 worker 执行 terminate → bounded wait → kill → bounded wait；读取 stderr 仍保持有界。
- 增加可控的 barrier 失败回归，断言所有 worker 都已退出。

### Task 2：测试选择只覆盖真实 owning surface

- 从 `test-tool-authorization` 删除兜底 `tests/**`，保留 authorization 专属文件、fixture 和 helper。
- 增加 selector 回归：普通 workflow 测试修改不再触发授权契约；authorization 测试仍触发。
- 保留 Teams 后端、前端、VUI 与 TypeScript 的既有风险边界，本轮不以“提速”为由跳过它们。

### Task 3：closeout 获取稳定 main 租约

- 新增受管 `task_closeout.py`：从稳定 main worktree 运行，验证 task worktree、branch、claim 和 clean 状态。
- 在昂贵 closeout 前通过现有 Briefbound coordination CLI 获取 `integration/main` 短租约；获取失败即停止，不运行测试。
- 租约内执行 closeout、verify-manifest 和 `git merge --ff-only`；任何一步失败都释放 integration claim，并保留 task branch/worktree/development claim 供修复。
- 不加入不安全的测试结果缓存；稳定基线先消除整轮作废，后续再以同 SHA/命令/环境指纹评估缓存收益。

### Task 4：合入成功立即事务化收口

- ff-only 成功后，将 development claim 标记 completed，再安全移除仅属于任务的 junction、干净 worktree 和已吸收本地分支，最后 `git worktree prune`。
- 删除前逐项验证绝对路径位于 `.worktrees`、worktree clean、branch tip 已被 main 包含、没有其他 active claim。
- 清理任一步失败时返回“已合入但 cleanup pending”，不 force、不回滚已成功 merge。

## 保护边界

- 不终止归属不明的现有进程；历史孤儿进程由单独的精确 PID 处置完成。
- 不修改产品运行时、科研工作流数据、SCI 题目数据或 operator config。
- 不远端 push/PR，不 force 删除分支/worktree，不在 root `main` 写业务文件。
- 当前 `tests` 被另一 reviewing claim 广泛占用；测试文件写入必须等该 claim 释放后重新 preflight。

## 验证与成功证据

- 失败 barrier 回归完成后无存活 worker；正常并发测试结果保持 `created=1/reused=1`。
- selector 对普通测试文件不再包含 `test_tool_authorization_test_contract.py`，authorization 路径仍包含。
- task closeout 测试覆盖：租约冲突时零测试执行、成功 ff-only 后顺序清理、验证失败保留现场、dirty/越界路径 fail closed。
- 相同 SCI 文件集合的 selector 命令减少 1 条；closeout 在 main 已被租约占用时快速失败，而不是运行约 5.7 分钟后 `stale_main`。
- 所有相关测试、selector-selected gate、diff 自审通过后才合入本地 main。

## 回滚

Task 1/2 可按各自 commit 独立回滚。Task 3/4 是新增受管入口，不替换现有 `local_quality_gate.py closeout`；异常时仍可退回原手工 closeout + verify + ff-only 流程。合入前任何失败只保留隔离 worktree，不触及 main。
