# Closeout 重试与提示词效率修复方案

- Status: implemented
- Owner: `codex-closeout-throughput-hardening-20260827`
- Branch: `codex/closeout-throughput-hardening`
- Scope: managed closeout、quality-gate claim、复用研究证据、核心提示词与现行协作指南

## 目标

消除三类剩余浪费：测试已经通过却因 integration claim 竞争被无参重跑；本地 `main` 已成功合入却因 Windows worktree 清理失败被当作整轮失败；简单已定位修改被强制执行仓外候选研究。保留 task HEAD、当前 `main`、changed files、claim、命令白名单和 merge preflight 的正确性绑定。

## 推荐路径

1. 统一 development claim 的 `active` / `ready` 语义，quality gate 与 coordination registry 使用同一活动状态集合。
2. managed closeout 在已有 manifest 通过后对 integration claim 做一次短时有界等待；竞争仍未结束时返回 manifest 和明确重试动作，不再次运行 selector。
3. 清理前把当前进程目录移出 task worktree，对 Windows 短暂占用做有界重试；增加幂等 `--cleanup-only`，允许合入后部分清理失败时只恢复资源，不再进入验证或 merge。
4. `--reserve-integration` 保留为 `stale_main` 后的一次性防饿死路径，并让权威文档明确它是昂贵验证锁外规则的唯一例外。
5. 复用研究证据增加 `LOCAL_ONLY` 快速模式：已定位小修只记录 owning surface、复用裁决、边界与验证，不要求仓外候选或 source ref；架构、依赖、复杂能力和真实复用分歧继续使用 `EXTERNAL` 模式。
6. 压缩 `AGENTS.md` 中重复的调研、路由、测试与合入细节，把稳定核心从 6000-token 边缘拉回有余量区间；操作细节继续由按需指南承载。

## 保护边界

- 不跨 `main` SHA 盲目复用测试结果；不相干 base 变动的增量复用需要独立的依赖证明与 manifest 设计，本轮不放宽。
- 不删除 serial、Launcher、真实进程、端口、共享 workspace 或 Git 测试。
- 不允许 cleanup-only 删除未合入、dirty、仍被其他活动 Agent 占用或路径不在 `.worktrees/` 直接子级的资源。
- 不把短时 integration 等待扩成无界轮询；不把 reserve 模式作为首轮默认。

## 本地与成熟方案裁决

1. 项目内 `task_closeout.py`、`local_quality_gate.py`、coordination registry 和 reuse-research contract 是现有 SSOT，采用改造后复用，不创建第二套合入器。
2. 项目已有 `state_store.py` 的 deadline + bounded retry 适合 Windows 短暂文件占用；只借重试结构，不复用运行时状态代码。
3. OpenAI Codex 固定提交中的 capped backoff/retry 思路用于“短暂冲突可重试、达到上限即返回显式状态”；不复制网络客户端实现。
4. pre-commit 的小范围、按输入决定验证思路继续作为参考；不引入新依赖或外部服务。

## 验证

- 单元契约覆盖：`ready` claim 可 closeout；锁冲突等待不重跑 selector；冲突结果保留 manifest；cleanup-only 不验证/不 merge；当前目录在 task worktree 时先迁出；Windows busy 只做有界重试。
- 复用证据契约覆盖 `LOCAL_ONLY` / `EXTERNAL` 两种模式和 manifest 复核。
- Prompt 契约要求 stable core 保留明确余量，并保持验证去重与主动本地合入语义。
- 最终 closeout 只运行 selector 一次；若 `main` 前进，按现行 stale 流程同步后重跑，不跨 SHA 冒险复用。

## 回滚

若有界等待造成额外阻塞，只回滚等待循环，保留 manifest 结果与明确 retry action。若 cleanup-only 的安全判断不能覆盖部分状态，禁用该入口但保留 cwd 迁移与有界删除重试。若 `LOCAL_ONLY` 证据削弱高风险任务研究，收紧其允许范围，不恢复所有代码改动强制仓外候选。
