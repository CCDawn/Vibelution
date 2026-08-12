# PRDs

产品意图文档。用于理解「为什么做」，**不**自动覆盖现行实现与规范。

| 文档 | 关联 |
| --- | --- |
| [2026-05-15-task-driven-agent-evolution-gym.md](2026-05-15-task-driven-agent-evolution-gym.md) | Gym / Evolution Engine；决策见 [ADR 0001](../adr/0001-gym-v1-uses-promotion-proposals-before-baseline-rewrite.md) |
| [2026-08-07-research-process-flow-single-page-workspace.md](2026-08-07-research-process-flow-single-page-workspace.md) | 挑战杯科研流程单画布工作台；三个阶段同画布分区；当前运行与科研效能合同见 [v2.1 完整方案](2026-08-09-challenge-cup-research-workflow-v2-repair-plan.md) |
| [2026-08-07-research-workflow-canvas-elk-layout-handoff.md](2026-08-07-research-workflow-canvas-elk-layout-handoff.md) | 科研工作流画布 ELK 自动布局开发交接；复合分区、固定端口、正交边路由、几何与实机验收契约 |
| [2026-08-07-research-workflow-canvas-elk-layout-design.md](2026-08-07-research-workflow-canvas-elk-layout-design.md) | ELK 自动布局实现技术方案；ExtendedEdge 端口、真实决策拓扑、Worker 生命周期、multi-section 路径与 bundle 门 |
| [2026-08-09-challenge-cup-research-workflow-v2-repair-plan.md](2026-08-09-challenge-cup-research-workflow-v2-repair-plan.md) | 挑战杯科研工作流 v2.1 完整修复、科研效能优化与验收合同；LangGraph 单运行时、teamId 单一事实源、真实 Agent/会话、科研质量与预算门禁、Handoff/fork、旧页面硬切换及 Launcher 实机门禁 |
| [2026-08-12-challenge-cup-research-workflow-runtime-architecture.md](2026-08-12-challenge-cup-research-workflow-runtime-architecture.md) | 挑战杯科研工作流正式运行架构与硬切换实施方案；Workflow Ledger 单写入、NodeReadiness、事务命令/outbox、LangGraph interrupt/resume、领域事实源、纯点击验收与收尾清理 |
| [2026-08-12-challenge-cup-research-workflow-runtime-implementation-spec.md](2026-08-12-challenge-cup-research-workflow-runtime-implementation-spec.md) | 挑战杯科研工作流可执行技术方案；SQLite schema、事务顺序、Runner/Adapter、16 节点 readiness、API/VUI 硬切换、迁移、T0-T9 TDD 任务卡与执行 Agent 主提示词 |

实现与安全边界以 ADR + owning README / 代码为准。过时 PRD 应标注 superseded 或迁入 archive。
