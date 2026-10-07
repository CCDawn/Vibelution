# 在研草案（非正式规范）

本文件是在研草案的唯一清单。[docs/README.md](../README.md) 只指向这里，不复制状态。
**不是**现行规则；权威顺序见 [ADR 0005](../adr/0005-docs-authority-and-archive-policy.md)。

关闭条件达到后：改 Status 为 `implemented` / `superseded` / `historical`，然后 `git mv` 到 `docs/archive/plans/<yyyy-mm>/`，并只更新本文件。

| 文件 | Status | 说明 |
| --- | --- | --- |
| [2026-09-12-session-ledger-archival-constraints.md](2026-09-12-session-ledger-archival-constraints.md) | PROPOSED（未实施） | 账本归档设计约束（9 条必处理 + 8 风险点）+ 2026-09-12 体检基线（854 个 / 98.1MB）；配套只读工具 `scripts/report_session_ledgers.py` |
| [research-flow-v2.md](research-flow-v2.md) | 通用科研流程在研入口 | 三阶段（方向与假说、基线实验、按证据迭代）与决策 Agent；CUDA 第三阶段验收不再作为关闭条件 |
| [2026-09-02-meeting-store-physical-sharding.md](2026-09-02-meeting-store-physical-sharding.md) | 设计阶段（调研进行中） | 会议轮次按 meetingRoundId 物理分片；是已归档 10 并发计划的写入层延伸，尚未实施 |
| [2026-08-20-physical-retirement-of-python-lifecycle.md](2026-08-20-physical-retirement-of-python-lifecycle.md) | ACTIVE | Python lifecycle 退役代码物理清理；批次 D 仍未完成 |
| [2026-08-20-physical-retirement-of-python-lifecycle.prompt.md](2026-08-20-physical-retirement-of-python-lifecycle.prompt.md) | execution attachment | 随上述 Active 计划保留，主计划关闭后一起归档 |
| [2026-08-15-deep-architecture-decoupling-plan.md](2026-08-15-deep-architecture-decoupling-plan.md) | ACTIVE PLAN | Agent / Chat / API 契约分 Gate；全部 Gate 关闭后归档 |
| [2026-08-15-research-graph-outcome-memory.md](2026-08-15-research-graph-outcome-memory.md) | 草案 | 三层记忆 + 公共结构策展/保鲜 + 研究成败图 v2.3（非正式规范） |
| [2026-08-14-llm-config-runtime-routing-optimization-plan.md](2026-08-14-llm-config-runtime-routing-optimization-plan.md) | active-plan | 模型配置与运行时协议路由 |
| [2026-08-14-multi-agent-configuration-and-protocol-routing-research-design.md](2026-08-14-multi-agent-configuration-and-protocol-routing-research-design.md) | user-approved | 多 Agent 配置与协议路由设计 |

历史快照（已迁出）：

- `2026-08-30-challenge-cup-automatic-chain-reliability-plan.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-30-challenge-cup-automatic-chain-reliability-plan.md)（historical；挑战杯结束，生产核对与 T8 不再收口）
- `2026-08-25-challenge-cup-canonical-workflow-state-plan.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-25-challenge-cup-canonical-workflow-state-plan.md)（historical；官方题库到 H1–H4 的验收停止）
- `2026-08-22-challenge-cup-hypothesis-scoped-sessions.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-22-challenge-cup-hypothesis-scoped-sessions.md)（historical；不删公共房间，不按 SCI-096 清空重建）
- `2026-08-21-research-workflow-three-pane-current-task-redesign.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-21-research-workflow-three-pane-current-task-redesign.md)（historical；赛题浏览器验收停止，currentTask 可另用于通用工作台）
- `2026-09-11-command-code-headless-transport-poc.md` → [archive/plans/2026-09/](../archive/plans/2026-09/2026-09-11-command-code-headless-transport-poc.md)（NO-GO / historical；G2 未通过，G1 未测出，不改产品传输路径）
- `2026-08-26-challenge-workflow-recovery-closure.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-26-challenge-workflow-recovery-closure.md)（Implemented；terminal run 归档、collection 孤儿恢复与恢复动作面已合入 main）
- `2026-09-02-challenge-cup-10-parallel-concurrency-plan.md` → [archive/plans/2026-09/](../archive/plans/2026-09/2026-09-02-challenge-cup-10-parallel-concurrency-plan.md)（implemented；A/B/C 与 D2 已合入。D1 集中 marker、sideflow 混跑和 B5 上限 e2e 仍是后续增量）
- `2026-09-05-independent-operator-experiment-flow-plan.md` → [archive/plans/2026-09/](../archive/plans/2026-09/2026-09-05-independent-operator-experiment-flow-plan.md)（superseded；产品流程见 [research-flow-v2.md](research-flow-v2.md)，本文只留调研和早期证据）
- `2026-08-13-portable-branch-workspace.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-13-portable-branch-workspace.md)（superseded；目录池与分支清单见 worktree-collaboration / instance-lifecycle，整树替换晋升未采用）
- `2026-08-11-multi-instance-branch-isolation.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-11-multi-instance-branch-isolation.md)（superseded；实例身份与注册表见 ADR 0009 / instance-lifecycle）
- `2026-08-31-challenge-cup-hypothesis-quality-efficiency-plan.md` → [archive/plans/2026-09/](../archive/plans/2026-09/2026-08-31-challenge-cup-hypothesis-quality-efficiency-plan.md)（superseded；实施已改走仓外 Stage1 方案）

- `2026-08-26-development-loop-throughput.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-26-development-loop-throughput.md)（Implemented；测试去重、短时集成锁与 gate-definition 并行自测）
- `2026-08-11-vui-wave-migration-backlog.md` → [archive/plans/2026-08-11/](../archive/plans/2026-08-11/2026-08-11-vui-wave-migration-backlog.md)
- `2026-08-16-compat-ssot-closeout-plan.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-16-compat-ssot-closeout-plan.md)（Implemented；长期规则见 [development-standard §25](../standards/development-standard.md)）
- `2026-08-20-launcher-lifecycle-ts-migration.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-20-launcher-lifecycle-ts-migration.md)（Closed；长期规则见 [ADR 0009](../adr/0009-launcher-control-plane-lives-in-electron-main.md)）
- `2026-08-26-test-regression-baseline-recovery.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-26-test-regression-baseline-recovery.md)（Implemented；Pet 测试隔离与完整回归命令修正）
- `2026-08-26-test-selector-import-closure.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-26-test-selector-import-closure.md)（Implemented；未映射 Python 改动的最近测试 import 前沿选择）
- `2026-08-31-challenge-cup-nodes-1-7-high-roi-repair-plan.md` → [archive/plans/2026-09/](../archive/plans/2026-09/2026-08-31-challenge-cup-nodes-1-7-high-roi-repair-plan.md)（Implemented / DEV Closed；T6 Launcher/G1 未执行）
