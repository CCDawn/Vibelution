# 在研草案（非正式规范）

本目录只放尚未关闭、且已在 [docs/README.md](../README.md) 白名单中的草案。
**不是**现行规则；权威顺序见 [ADR 0005](../adr/0005-docs-authority-and-archive-policy.md)。

关闭条件达到后：改 Status 为 `implemented` / `superseded` / `historical`，然后 `git mv` 到 `docs/archive/plans/<yyyy-mm>/`，并更新本文件与 `docs/README.md`。

| 文件 | Status | 说明 |
| --- | --- | --- |
| [2026-08-22-challenge-cup-hypothesis-scoped-sessions.md](2026-08-22-challenge-cup-hypothesis-scoped-sessions.md) | user-approved / active-plan | 挑战杯节点根会话、逐假说 Child Session 与结构化聚合 |
| [2026-08-15-deep-architecture-decoupling-plan.md](2026-08-15-deep-architecture-decoupling-plan.md) | ACTIVE PLAN | Agent / Chat / API 契约分 Gate；全部 Gate 关闭后归档 |
| [2026-08-15-research-graph-outcome-memory.md](2026-08-15-research-graph-outcome-memory.md) | 草案 | 三层记忆 + 公共结构策展/保鲜 + 研究成败图 v2.3（非正式规范） |
| [2026-08-14-llm-config-runtime-routing-optimization-plan.md](2026-08-14-llm-config-runtime-routing-optimization-plan.md) | active-plan | 模型配置与运行时协议路由 |
| [2026-08-14-multi-agent-configuration-and-protocol-routing-research-design.md](2026-08-14-multi-agent-configuration-and-protocol-routing-research-design.md) | user-approved | 多 Agent 配置与协议路由设计 |
| [2026-08-13-portable-branch-workspace.md](2026-08-13-portable-branch-workspace.md) | 草案 | 仓内 `.worktrees` + Launcher 分支清单 |
| [2026-08-11-multi-instance-branch-isolation.md](2026-08-11-multi-instance-branch-isolation.md) | 待立项 | 多实例端口隔离与注册表 |

历史快照（已迁出）：

- `2026-08-11-vui-wave-migration-backlog.md` → [archive/plans/2026-08-11/](../archive/plans/2026-08-11/2026-08-11-vui-wave-migration-backlog.md)
- `2026-08-16-compat-ssot-closeout-plan.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-16-compat-ssot-closeout-plan.md)（Implemented；长期规则见 [development-standard §25](../standards/development-standard.md)）
- `2026-08-20-launcher-lifecycle-ts-migration.md` → [archive/plans/2026-08/](../archive/plans/2026-08/2026-08-20-launcher-lifecycle-ts-migration.md)（Closed；长期规则见 [ADR 0009](../adr/0009-launcher-control-plane-lives-in-electron-main.md)）
