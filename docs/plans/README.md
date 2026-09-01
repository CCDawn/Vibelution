# 在研草案（非正式规范）

本目录只放尚未关闭、且已在 [docs/README.md](../README.md) 白名单中的草案。
**不是**现行规则；权威顺序见 [ADR 0005](../adr/0005-docs-authority-and-archive-policy.md)。

关闭条件达到后：改 Status 为 `implemented` / `superseded` / `historical`，然后 `git mv` 到 `docs/archive/plans/<yyyy-mm>/`，并更新本文件与 `docs/README.md`。

| 文件 | Status | 说明 |
| --- | --- | --- |
| [2026-09-02-challenge-cup-10-parallel-concurrency-plan.md](2026-09-02-challenge-cup-10-parallel-concurrency-plan.md) | USER-REQUESTED / ACTIVE PLAN | 10 并发链路改造与并发缺陷修复任务清单：搜索 circuit/fan-in 双花 P0、dispatch 并行化关键路径（B1–B5）、串线与丢写批次（C1–C7）、并发测试与 10 并发验收（D1–D2） |
| [2026-08-30-challenge-cup-automatic-chain-reliability-plan.md](2026-08-30-challenge-cup-automatic-chain-reliability-plan.md) | USER-REQUESTED / ACTIVE PLAN | 挑战杯群聊、摘要、LangGraph/Ledger 调度的 deadline、durable recovery、run 隔离、上下文与自动推进完整修复任务图 |
| [2026-08-25-challenge-cup-canonical-workflow-state-plan.md](2026-08-25-challenge-cup-canonical-workflow-state-plan.md) | USER-REQUESTED / ACTIVE PLAN | 挑战杯从官方题目冷启动到正式运行、产出登记和 H1–H4 审核的规范化状态 V2、服务端动作与真实链路验收 |
| [2026-08-22-challenge-cup-hypothesis-scoped-sessions.md](2026-08-22-challenge-cup-hypothesis-scoped-sessions.md) | user-approved / active-plan | 挑战杯按题目/假说隔离群聊与 Child Session、三类 checkpoint 绑定、旧数据清空及 SCI-096 初始化重建 |
| [2026-08-21-research-workflow-three-pane-current-task-redesign.md](2026-08-21-research-workflow-three-pane-current-task-redesign.md) | user-approved | 科研流程统一 currentTask 投影、三栏信息架构、画布恢复、档案分层与一轮真实验收 |
| [2026-08-20-physical-retirement-of-python-lifecycle.md](2026-08-20-physical-retirement-of-python-lifecycle.md) | ACTIVE | Python lifecycle 退役代码物理清理；批次 D 仍未完成 |
| [2026-08-20-physical-retirement-of-python-lifecycle.prompt.md](2026-08-20-physical-retirement-of-python-lifecycle.prompt.md) | execution attachment | 随上述 Active 计划保留，主计划关闭后一起归档 |
| [2026-08-15-deep-architecture-decoupling-plan.md](2026-08-15-deep-architecture-decoupling-plan.md) | ACTIVE PLAN | Agent / Chat / API 契约分 Gate；全部 Gate 关闭后归档 |
| [2026-08-15-research-graph-outcome-memory.md](2026-08-15-research-graph-outcome-memory.md) | 草案 | 三层记忆 + 公共结构策展/保鲜 + 研究成败图 v2.3（非正式规范） |
| [2026-08-14-llm-config-runtime-routing-optimization-plan.md](2026-08-14-llm-config-runtime-routing-optimization-plan.md) | active-plan | 模型配置与运行时协议路由 |
| [2026-08-14-multi-agent-configuration-and-protocol-routing-research-design.md](2026-08-14-multi-agent-configuration-and-protocol-routing-research-design.md) | user-approved | 多 Agent 配置与协议路由设计 |
| [2026-08-13-portable-branch-workspace.md](2026-08-13-portable-branch-workspace.md) | 草案 | 仓内 `.worktrees` + Launcher 分支清单 |
| [2026-08-11-multi-instance-branch-isolation.md](2026-08-11-multi-instance-branch-isolation.md) | 待立项 | 多实例端口隔离与注册表 |

历史快照（已迁出）：

- `2026-08-26-development-loop-throughput.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-26-development-loop-throughput.md)（Implemented；测试去重、短时集成锁与 gate-definition 并行自测）
- `2026-08-11-vui-wave-migration-backlog.md` → [archive/plans/2026-08-11/](../archive/plans/2026-08-11/2026-08-11-vui-wave-migration-backlog.md)
- `2026-08-16-compat-ssot-closeout-plan.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-16-compat-ssot-closeout-plan.md)（Implemented；长期规则见 [development-standard §25](../standards/development-standard.md)）
- `2026-08-20-launcher-lifecycle-ts-migration.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-20-launcher-lifecycle-ts-migration.md)（Closed；长期规则见 [ADR 0009](../adr/0009-launcher-control-plane-lives-in-electron-main.md)）
- `2026-08-26-test-regression-baseline-recovery.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-26-test-regression-baseline-recovery.md)（Implemented；Pet 测试隔离与完整回归命令修正）
- `2026-08-26-test-selector-import-closure.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-26-test-selector-import-closure.md)（Implemented；未映射 Python 改动的最近测试 import 前沿选择）
- `2026-08-31-challenge-cup-nodes-1-7-high-roi-repair-plan.md` → [archive/plans/2026-09/](../archive/plans/2026-09/2026-08-31-challenge-cup-nodes-1-7-high-roi-repair-plan.md)（Implemented / DEV Closed；T6 Launcher/G1 未执行）
