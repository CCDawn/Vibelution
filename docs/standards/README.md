# Vibelution Standards

本目录是 Vibelution 跨模块详细规范的唯一权威目录。根目录 `AGENTS.md` 只保留全局红线和路由，不复制这里的流程正文。

## 权威顺序

1. 用户当前明确要求与授权边界；
2. 根目录 `AGENTS.md`；
3. 本目录中对应专项规范；
4. ADR 与模块 README；
5. 历史计划、报告和归档材料。

`core/core_prompt/COMMON.md` 与 `core/core_prompt/SOUL.md` 是运行时 Prompt 资产，不属于详细开发规范，也不扩大权限。

## 当前规范入口

| 任务或问题 | 权威文档 |
| --- | --- |
| **默认规划：每次开发先 BRT** | 本机 `ccdawn-brt` skill · 根 [AGENTS.md §3.0](../../AGENTS.md) · [development-standard.md §2](development-standard.md) · [guides 加载序 0b](../guides/README.md) |
| **Agent 任务路由（非规则正文）** | [../guides/README.md](../guides/README.md) · [route](../guides/route.md) · [loop](../guides/loop.md) |
| 开发分级、BRT、来源权威、结构边界、验证、Git、Launcher、发布、完成条件 | [development-standard.md](development-standard.md) · **章节跳转卡见本页 § development-standard** |
| Windows 产品运行时禁止 cmd/控制台弹窗（永久红线） | [development-standard.md §8.0](development-standard.md) + 根 `AGENTS.md` §2 |
| 多 Agent、worktree、claim、merge 协作 | [../agents/worktree-collaboration.md](../agents/worktree-collaboration.md) |
| 领域词汇 | [../agents/domain.md](../agents/domain.md) |
| 工具授权入口 | [../agents/tool-authorization-entrypoints.md](../agents/tool-authorization-entrypoints.md) |
| 前端 UI / VUI / shadcn（**强制**，根 `AGENTS.md` §2 红线） | [development-standard.md §9.1](development-standard.md) + [../../web/src/components/vui/README.md](../../web/src/components/vui/README.md) + [组件设计索引](../../web/src/components/vui/designs/INDEX.md) + 按钮选型 [../guides/button-selection.md](../guides/button-selection.md) + 门禁 `vuiShadcnRouteContract.test.ts` / `vuiComponentDesignContract` |
| 前端 JSON API / domain transport（**强制**，根 `AGENTS.md` §2 + §24） | [development-standard.md §24](development-standard.md) + [../../web/src/api/README.md](../../web/src/api/README.md) + 门禁 `fullStackApiBoundary.test.ts` / `test_full_stack_contract_guards.py` |
| 测试入口 | [../../tests/README.md](../../tests/README.md) |
| 运行日志实现地图 | [../../core/logging/README.md](../../core/logging/README.md) |
| Operator 配置（config.toml / LLM / 缓存 / 厂商菜谱） | [../ops/config/INDEX.md](../ops/config/INDEX.md) |
| 架构决策（索引） | [../adr/README.md](../adr/README.md) |
| Agent 协作发送（session 落脚 + 保留 inbox） | [../adr/0002-agent-collaboration-session-addressing.md](../adr/0002-agent-collaboration-session-addressing.md) |
| Operator config 在 Documents 外置 | [../adr/0003-operator-config-lives-outside-repo.md](../adr/0003-operator-config-lives-outside-repo.md) |
| 产品 UI = VUI + shadcn only | [../adr/0004-product-ui-uses-vui-shadcn-only.md](../adr/0004-product-ui-uses-vui-shadcn-only.md) |
| 文档权威层与 archive | [../adr/0005-docs-authority-and-archive-policy.md](../adr/0005-docs-authority-and-archive-policy.md) |
| 产品语境 / UI 注册表 | [../product/README.md](../product/README.md) · [../product/design-register.md](../product/design-register.md) |
| Web services 全量 ownership | [../../core/web/services/README.md](../../core/web/services/README.md) |

## 边界

- 全局规则正文只写一次；其他文档使用链接。
- 模块 README 只负责局部 ownership、目录和实现地图，不声明竞争性的全局规则。
- 外部 project `memory/` 是恢复投影，Git common-dir registry 是实时协作权威；旧 `.docs/project-memory/` 只读兼容，二者都不是规范目录。
- `docs/archive/`（含原 `docs/plans/`、`docs/superpowers/`）不是现行规则来源，除非本索引或 `AGENTS.md` 明确提升。
- 文档总图：[../README.md](../README.md)；配置入口：[../ops/config/INDEX.md](../ops/config/INDEX.md)。
- 新增或修改全局规则时，必须同步检查 `AGENTS.md` 路由、相关守卫测试和项目记忆决策。

当前 `development-standard.md` 保留完整章节编号以降低迁移风险；后续只有在不复制规则正文且链接守卫可验证时，才按专题继续拆分。

## development-standard 章节跳转卡（R21）

**全文约 ~880 行 — 禁止默认通读。** 先在本表命中任务类型，只打开对应 §；仍不够再下钻链接列。

| 任务类型 | 先读 § | 常见下钻 |
| --- | --- | --- |
| **任意开发 / 分级** | §2 · §2.1 | `docs/guides/loop.md` §1 |
| **Bug / 回归 / 卡住** | §4 · §5 | `docs/guides/agent-log-routing.md` |
| **SSOT / 双写 / 投影** | §3.1 · §7.1 | 完成报告 SSOT 表 |
| **Worktree / claim / 热文件** | §6 · §7 · §17 | `docs/agents/worktree-collaboration.md` |
| **Windows 无控制台 / spawn** | **§8.0** | §12 · §23.4 · `launcher_runtime.md` |
| **文件体量 / 拆分** | §8.3 | `briefbound-code-structure-guard` 触发时 |
| **用户可见 UI / VUI** | **§9.1** · §23.10 | `web/src/components/vui/README.md` · `button-selection.md` |
| **前端 API / domain transport** | **§24** · §24.1–§24.5 | `web/src/api/README.md` |
| **后端 route/service** | §8 · §24.3 | `core/web/services/README.md` |
| **LLM / 协议 / 缓存** | §23.1 · §5.1 | `core/llm/PROTOCOL.md` · `docs/ops/config/04`+`05` |
| **Operator config** | §23.8 | `docs/ops/config/INDEX.md` · ADR0003 |
| **Launcher / Runtime / 进程** | §12 · **§23.4** | ADR0009 · `launcher_runtime.md` |
| **Memory / RAG** | §23.5 | `memory_rag_services.md` |
| **工具授权 / ToolPolicy** | §23.7 | `tool-authorization-entrypoints.md` · `tools/README.md` |
| **删除 / 归档 / Reset** | §23.9 | `memory_cleanup` 触面时 + reset 相关测试 |
| **Agent / Session / Chat 生命周期** | §23.2 · §18 | `conversation-flow-map.md` |
| **Runtime scene 证据** | §23.3 · §5 | `core/logging/README.md` |
| **Teams / SC / 研究流** | §20 · §20.1 | teams README · `team_workflow/README.md` |
| **Gym / 进化** | §20 | ADR0001 · `evolution_services.md` |
| **测试策略** | §11 | `tests/README.md` · `tests/test_matrix.yaml` |
| **Git / 合入 / remote** | §13 · §14 · §16 | 根 `AGENTS.md` §2 合入门 |
| **版本 / 发布** | §15 | §12 refresh 决策 |
| **完成报告 / Done** | §21 · §22 | `docs/guides/loop.md` §6 |
| **Fallback / degraded 语义** | §3.2 | 不得静默当 success |
| **Project memory** | §19 · §19.1 | `migrate_project_storage.py inventory` |
| **全栈新功能** | **§24 全节** | §24.5 DoD 清单 |

§ 链接格式：`development-standard.md#` + 锚点（GitHub/IDE 可跳转）；子节如 `§8.0` = `### 8.0 Windows No-Console...`。

**最小常态集（多数 STANDARD_TASK）：** §2.1 + 上表 1 行 + §21/§22 收束 ≈ **~120 行**，非全文 880 行。
