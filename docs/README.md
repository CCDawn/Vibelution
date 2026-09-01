# Vibelution 文档地图

`docs/` 是跨会话文档总目录。
**现行规范真源**：根 [AGENTS.md](../AGENTS.md) + [standards/README.md](standards/README.md)。
历史材料可检索，**不得**与现行规范竞争。

---

## 现行入口（Agent 优先）

| 需求 | 打开 |
| --- | --- |
| **Agent 开发路由（非用户手册）** | [guides/README.md](guides/README.md) · [route](guides/route.md) · [ownership](guides/ownership.md) · [loop](guides/loop.md) |
| 全局红线 / 路由 | [../AGENTS.md](../AGENTS.md) |
| 开发标准全图 | [standards/README.md](standards/README.md) |
| 开发标准正文 | [standards/development-standard.md](standards/development-standard.md) |
| **Operator 配置（LLM/缓存/厂商）** | [ops/config/INDEX.md](ops/config/INDEX.md) |
| LLM 协议运行时 | [../core/llm/PROTOCOL.md](../core/llm/PROTOCOL.md) |
| 领域词汇 | [agents/domain.md](agents/domain.md) |
| Worktree / claim | [agents/worktree-collaboration.md](agents/worktree-collaboration.md) |
| 工具授权 | [agents/tool-authorization-entrypoints.md](agents/tool-authorization-entrypoints.md) |
| **外部 Agent MCP 部署与调用** | [agents/mcp-managed-agent-gateway.md](agents/mcp-managed-agent-gateway.md) |
| 对话链路图 | [agents/conversation-flow-map.md](agents/conversation-flow-map.md) |
| GitHub Issue / triage | [agents/issue-tracker.md](agents/issue-tracker.md) · [agents/triage-labels.md](agents/triage-labels.md) |
| ADR | [adr/](adr/) |
| 测试 | [../tests/README.md](../tests/README.md) · 补充 [testing/README.md](testing/README.md) |
| 运行日志 | [../core/logging/README.md](../core/logging/README.md) |
| VUI 前端 | [../web/src/components/vui/README.md](../web/src/components/vui/README.md) |
| 项目记忆（状态，非规范） | 运行 `python scripts/migrate_project_storage.py inventory`，读取 `activePaths.memory` 下的 `INDEX.md` |
| Linux 部署 | [ops/linux-bootstrap.md](ops/linux-bootstrap.md) |
| 本地模型监控 | [ops/local-model-monitor.md](ops/local-model-monitor.md) |
| Gym / Evolution 产品意图 | [prds/README.md](prds/README.md) |
| **产品语境 / UI 注册表** | [product/README.md](product/README.md) · [product/design-register.md](product/design-register.md) |
| ADR 索引 | [adr/README.md](adr/README.md) |
| **Web services 全量（71）** | [../core/web/services/README.md](../core/web/services/README.md) |

---

## 目录分类（2026-08 整理）

| 目录 | 分类 | 规则 |
| --- | --- | --- |
| [guides/](guides/) | **Agent 路由** | 任务→READ/EDIT/TEST；不面向最终用户；不复制标准正文 |
| [standards/](standards/) | **现行规范** | 跨模块规则只在此维护 |
| [agents/](agents/) | **现行参考** | 协作、授权、领域、对话流 |
| [product/](product/) | **现行产品语境** | 目的、原则、UI 注册表（非组件表） |
| [adr/](adr/) | **现行决策** | 为何这样设计；见 [adr/README.md](adr/README.md) |
| [ops/](ops/) | **现行运维** | config/、bootstrap、local-model-monitor |
| [ops/config/](ops/config/) | **现行配置** | Operator config 索引与菜谱 |
| [testing/](testing/) | **现行测试补充** | 见 [testing/README.md](testing/README.md)；报告不替代 tests |
| [security/](security/) | 生成物/参考 | 见 [security/README.md](security/README.md) |
| [prds/](prds/) | 产品意图 | 见 [prds/README.md](prds/README.md)；对照 ADR/代码 |
| [assets/](assets/) | 静态资源 | README 截图等 |
| [archive/](archive/) | **归档** | 一切历史计划/规格/审计；见 [archive/README.md](archive/README.md) |

`docs/plans/` **不是**规范权威（见 [ADR 0005](adr/0005-docs-authority-and-archive-policy.md)）。仅下列在研草案可留在该目录；升格前不覆盖 `AGENTS.md` / `standards/`。清单真源：[plans/README.md](plans/README.md)。

| 草案 | 说明 |
| --- | --- |
| [plans/2026-09-02-challenge-cup-10-parallel-concurrency-plan.md](plans/2026-09-02-challenge-cup-10-parallel-concurrency-plan.md) | USER-REQUESTED：10 并发链路改造任务清单（搜索 circuit/fan-in P0、dispatch 并行化、串线丢写修复、并发验收） |
| [plans/2026-08-30-challenge-cup-automatic-chain-reliability-plan.md](plans/2026-08-30-challenge-cup-automatic-chain-reliability-plan.md) | USER-REQUESTED：挑战杯群聊、摘要、LangGraph/Ledger 自动运行链路的 deadline、durable recovery、run 隔离、上下文与自动推进修复计划 |
| [plans/2026-08-25-challenge-cup-canonical-workflow-state-plan.md](plans/2026-08-25-challenge-cup-canonical-workflow-state-plan.md) | USER-REQUESTED：挑战杯从官方题目冷启动到产出登记与 H1–H4 审核的规范化状态 V2、服务端动作和真实链路闭环验收 |
| [plans/2026-08-22-challenge-cup-hypothesis-scoped-sessions.md](plans/2026-08-22-challenge-cup-hypothesis-scoped-sessions.md) | user-approved：挑战杯节点根会话、逐假说 Child Session 与结构化聚合 |
| [plans/2026-08-21-research-workflow-three-pane-current-task-redesign.md](plans/2026-08-21-research-workflow-three-pane-current-task-redesign.md) | USER-APPROVED：科研流程统一 currentTask 投影、三栏信息架构、画布恢复、档案分层与一轮真实验收 |
| [plans/2026-08-20-physical-retirement-of-python-lifecycle.md](plans/2026-08-20-physical-retirement-of-python-lifecycle.md) | ACTIVE：Python lifecycle 退役代码物理清理；批次 D 仍未完成 |
| [plans/2026-08-20-physical-retirement-of-python-lifecycle.prompt.md](plans/2026-08-20-physical-retirement-of-python-lifecycle.prompt.md) | 上述 Active 计划的执行附件；随主计划关闭后归档 |
| [plans/2026-08-15-research-graph-outcome-memory.md](plans/2026-08-15-research-graph-outcome-memory.md) | 三层记忆 + 公共结构策展/保鲜 + 研究成败图 v2.3（非正式规范） |
| [plans/2026-08-15-deep-architecture-decoupling-plan.md](plans/2026-08-15-deep-architecture-decoupling-plan.md) | ACTIVE：Agent / Chat / API 契约分 Gate 解耦 |
| [plans/2026-08-14-llm-config-runtime-routing-optimization-plan.md](plans/2026-08-14-llm-config-runtime-routing-optimization-plan.md) | active-plan：模型配置与协议路由 |
| [plans/2026-08-14-multi-agent-configuration-and-protocol-routing-research-design.md](plans/2026-08-14-multi-agent-configuration-and-protocol-routing-research-design.md) | user-approved：多 Agent 协议配置设计 |
| [plans/2026-08-13-portable-branch-workspace.md](plans/2026-08-13-portable-branch-workspace.md) | 仓内 `.worktrees` + Launcher 全部分支清单 |
| [plans/2026-08-11-multi-instance-branch-isolation.md](plans/2026-08-11-multi-instance-branch-isolation.md) | 多实例端口隔离与注册表 |

### 本轮迁入 archive

| 原路径 | 现路径 |
| --- | --- |
| `docs/plans/*` | `archive/plans/2026-06-07/`（及既有 `2026-05/`） |
| `docs/plans/2026-08-11-vui-wave-migration-backlog.md` | `archive/plans/2026-08-11/` |
| `docs/plans/2026-08-16-compat-ssot-closeout-plan.md` | `archive/plans/2026-08/`（Implemented；长期规则 [development-standard §25](standards/development-standard.md)） |
| `docs/plans/2026-08-20-launcher-lifecycle-ts-migration.md` | `archive/plans/2026-08/`（Closed；长期规则 [ADR 0009](adr/0009-launcher-control-plane-lives-in-electron-main.md)） |
| `docs/plans/2026-08-26-test-regression-baseline-recovery.md` | `archive/plans/2026-08/`（Implemented；Pet 测试隔离与完整回归命令恢复） |
| `docs/plans/2026-08-26-test-selector-import-closure.md` | `archive/plans/2026-08/`（Implemented；未映射 Python 改动按最近测试 import 前沿选择测试） |
| `docs/plans/2026-08-31-challenge-cup-nodes-1-7-high-roi-repair-plan.md` | `archive/plans/2026-09/`（Implemented / DEV Closed；来源血缘、pinned definition、检索预算/质量与真实回执绑定） |
| `docs/plans/2026-08-26-development-loop-throughput.md` | `archive/plans/2026-08/`（Implemented；测试去重、短时集成锁与 gate-definition 并行自测） |
| `docs/archive/plans/2026-08-26-challenge-workflow-recovery-closure.md` | `archive/plans/2026-08/`（Implemented；terminal run 归档、collection 孤儿恢复与恢复动作面已合入 main） |
| `docs/ops/2026-05-*`、efficiency-baselines | `archive/ops/` |
| `docs/frontend/*` | `archive/frontend/` |
| `docs/superpowers/*` | `archive/superpowers/` |
| 一次性 testing 报告 / Electron 迁移 ledger | `archive/testing/` |
| `docs/ai-knowledge-search-dashboard.html` | `archive/` |
| `docs/previews/*` | `archive/previews/` |
| 根 `PRODUCT.md` / `DESIGN.md` 全文 | `archive/product/`（根文件改为入口桩） |

新计划若需要：带 Status 元数据，**完成后尽快迁入 `docs/archive/`**，勿长期堆在现行树。权威策略见 [ADR 0005](adr/0005-docs-authority-and-archive-policy.md)。

---

## 权威顺序

1. 用户当前明确要求
2. 根 `AGENTS.md`
3. `docs/standards/`
4. ADR / 模块 README（ownership）
5. `docs/ops/config/`（配置语义）+ `core/llm/PROTOCOL.md`（协议运行时）
6. `docs/guides/`（Agent 路由）· `docs/agents/` · `docs/product/`
7. archive / 历史 PRD 报告 → **仅考古**

（锁定说明：[ADR 0005](adr/0005-docs-authority-and-archive-policy.md)）

---

## 治理规则

- 全局规则正文只写一次；索引与 README 用链接。
- 模块 README 不声明竞争性全局规则。
- 外部 project `memory/` 是可变状态，不是规范；`.docs/project-memory/` 仅是迁移前只读来源。
- 现行前端：**Tailwind-first + VUI + shadcn/Radix**（HeroUI 已移除；[ADR 0004](adr/0004-product-ui-uses-vui-shadcn-only.md)）。
- 活跃配置：`%USERPROFILE%\Documents\Vibelution\config\config.toml`（[ADR 0003](adr/0003-operator-config-lives-outside-repo.md)）。
- service README 的 Related 只链现行入口；历史阶段计划统一指向 `docs/archive/plans/`。

---

## 仓库根文档（非 docs/）

| 文件 | 状态 |
| --- | --- |
| [AGENTS.md](../AGENTS.md) | **现行** Agent 入口 |
| [README.md](../README.md) | 产品/仓库说明 |
| [INDEX.md](../INDEX.md) | 目录地图；流程与规范以本文件与 AGENTS 为准 |
| [CHANGELOG.md](../CHANGELOG.md) | 变更日志 |
| [PRODUCT.md](../PRODUCT.md) / [DESIGN.md](../DESIGN.md) | **入口桩** → `docs/product/`；全文在 `archive/product/` |
| [THIRD_PARTY_COMPONENTS.md](../THIRD_PARTY_COMPONENTS.md) | 第三方组件 |

---

## 归档说明

见 [archive/README.md](archive/README.md)。
