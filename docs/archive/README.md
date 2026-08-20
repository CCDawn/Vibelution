# 文档归档

历史材料可帮助 Agent 还原决策，**不得**当作现行操作规范。

现行入口：[`docs/README.md`](../README.md) · 规范：[`docs/standards/`](../standards/) · 配置：[`docs/ops/config/`](../ops/config/)

## 内容索引

| 路径 | 说明 |
| --- | --- |
| [plans/2026-05/](plans/2026-05/) | 2026-05 早期实现计划 |
| [plans/2026-06-07/](plans/2026-06-07/) | 原 `docs/plans/`（2026-06～07 计划与 service 优化阶段报告） |
| [plans/2026-08/](plans/2026-08/) | 2026-08 控制面迁移 ledger（Closed）、Launcher 生命周期 TS 化（Closed → [ADR 0009](../adr/0009-launcher-control-plane-lives-in-electron-main.md)）、Chat 路由单一权威（Implemented → [ADR 0010](../adr/0010-chat-route-is-window-local-authority.md)）、兼容层 SSOT 关闭账本（Implemented → [development-standard §25](../standards/development-standard.md)）、会话 SQLite 迁移提案（superseded，见该文 §0） |
| [previews/](previews/) | 一次性 UI/流程 HTML 预览（非产品文档） |
| [plans/2026-08-07/](plans/2026-08-07/) | Challenge Cup 工作流历史计划 |
| [plans/2026-08-09/](plans/2026-08-09/) | MCP 受管 Agent 网关历史计划 |
| [plans/2026-08-10/](plans/2026-08-10/) | Electron workbench 事务关闭历史计划 |
| [plans/2026-08-11/](plans/2026-08-11/) | VUI 波次迁移待办快照（契约清单已迁回测试；非正式规范） |
| [plans/2026-08-15/](plans/2026-08-15/) | 团队 Agent 感知 / 点对点 / 会话团队标签历史计划 |
| [ops/2026-05/](ops/2026-05/) | 原 ops 根下治理/审计快照 |
| [ops/efficiency-baselines/](ops/efficiency-baselines/) | 效率基线快照 |
| [frontend/](frontend/) | 一次性前端预算/计划笔记 |
| [superpowers/](superpowers/) | 原 `docs/superpowers/`（specs / plans / evidence） |
| [testing/](testing/) | 一次性测试报告与迁移 ledger |
| [product/](product/) | 根 `PRODUCT.md` / `DESIGN.md` 全文快照（现行见 `docs/product/`） |
| [ai-knowledge-search-dashboard.html](ai-knowledge-search-dashboard.html) | 旧知识检索仪表盘 HTML |

## 清理规则

1. **优先移动，不删除**（保留 Git 历史与文件名）。
2. 成组移动时更新本索引与 [`docs/README.md`](../README.md)。
3. 现行规范只在 `docs/standards/`、`docs/agents/`、`docs/ops/`（现行子集）、ADR、模块 README。
4. 不把 runtime logs、project-memory、生成包塞进本目录，除非专项清理任务要求。
5. 归档内交叉链接可能仍写旧路径（`docs/plans/…`）；**不必批量改历史文件**，以本索引与文件名为准。

## 如何引用归档

- 可以说「历史依据见 `docs/archive/…`」
- 不得写「按 archive/xxx 现行规定执行」
- 若归档内容仍正确，应**提炼进现行文档**再引用现行文档

## Superpowers 子树

见 [superpowers/README.md](superpowers/README.md)。路径已从 `docs/superpowers/` 迁入本目录（2026-08）。
