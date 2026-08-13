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
| **Web services 全量（69）** | [../core/web/services/README.md](../core/web/services/README.md) |

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

**不存在** 现行 `docs/plans/` 或 `docs/superpowers/` 顶层目录作为规范权威（计划正文曾归档）。

在研草案（**不是**规范，升格前不覆盖 `AGENTS.md` / `standards/`）：

| 草案 | 说明 |
| --- | --- |
| [plans/2026-08-13-portable-branch-workspace.md](plans/2026-08-13-portable-branch-workspace.md) | 仓内 `.worktrees` + Launcher 全部分支清单 |
| [plans/2026-08-11-multi-instance-branch-isolation.md](plans/2026-08-11-multi-instance-branch-isolation.md) | 多实例端口隔离与注册表 |

### 本轮迁入 archive

| 原路径 | 现路径 |
| --- | --- |
| `docs/plans/*` | `archive/plans/2026-06-07/`（及既有 `2026-05/`） |
| `docs/ops/2026-05-*`、efficiency-baselines | `archive/ops/` |
| `docs/frontend/*` | `archive/frontend/` |
| `docs/superpowers/*` | `archive/superpowers/` |
| 一次性 testing 报告 / Electron 迁移 ledger | `archive/testing/` |
| `docs/ai-knowledge-search-dashboard.html` | `archive/` |
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
| [INDEX.md](../INDEX.md) | 结构索引；细节冲突时以本文件与 AGENTS 为准 |
| [CHANGELOG.md](../CHANGELOG.md) | 变更日志 |
| [PRODUCT.md](../PRODUCT.md) / [DESIGN.md](../DESIGN.md) | **入口桩** → `docs/product/`；全文在 `archive/product/` |
| [THIRD_PARTY_COMPONENTS.md](../THIRD_PARTY_COMPONENTS.md) | 第三方组件 |

---

## 归档说明

见 [archive/README.md](archive/README.md)。
