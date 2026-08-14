# Agent Ownership（写入落点）

**规则：** 先定表内 owner，再编辑。无 owner → 搜 facade/`README` → 仍无则停并问用户，勿新建平行树。

**后端 service 全量索引（69 facades）：** [`core/web/services/README.md`](../../core/web/services/README.md)

---

## FE

| Surface | 入口 / 落点 | README |
| --- | --- | --- |
| App shell | `web/src/app/` | — |
| Chat/Coding | 薄入口 `ChatCodingRoute.tsx` → `chat/ChatCodingRouteWorkbench.tsx`；模块在 `web/src/routes/chat/` | `web/src/routes/chat/README.md` · 按钮 [button-selection.md](button-selection.md) |
| Agents | `AgentsRoute.tsx` + `AgentWorkspaceLayoutPanel`（`VListDetailPage`） | `data-vui-recipe=agents-management-workbench` |
| Teams | `web/src/routes/teams/`；`TeamsRoute.tsx`→workbench | `web/src/routes/teams/README.md` |
| SC panels | `TeamSourceCollection*` + `teams/source-collection/` + `teamSourceCollectionPanels.ts` | teams README |
| VUI | `web/src/components/vui/`；designs 必登 | `web/src/components/vui/README.md` |
| API | `web/src/api/<domain>.ts`；`types/`；queryKeys | `fullStackApiBoundary.test.ts` |

**FE MUST NOT**

- import `components/vui/renderers/shadcn/*` from routes
- import `@heroui/react`
- 新 endpoint 字符串堆在 Route

---

## BE HTTP / services

| Domain | routes | pack / facade | README |
| --- | --- | --- | --- |
| **全量 69 facades** | — | 全部 `*_service.py` | **[`services/README.md`](../../core/web/services/README.md)** |
| Session 热路径 | `core/web/routes/sessions.py` | `session/*` · `session_service.py` | `session/README.md` |
| Team workflow | `core/web/routes/team_workflows/` | `team_workflow/*` · facade | `team_workflow/README.md` |
| Team CRUD | `core/web/routes/teams.py` | `team/*` · `team_service.py` | `team/README.md` |
| Team knowledge | knowledge routes | `team_knowledge/*` | `team_knowledge/README.md` |
| Agent directory | `core/web/routes/agents.py` | `agent_directory/*` | `agent_directory/README.md` |
| Runtime scene | log/runtime routes | `runtime_scene/*` | `runtime_scene/README.md` |
| 其它 | 见全量索引 Domain 表 | 无 pack 则改 facade | 全量索引 |

**BE MUST NOT**

- 厚 route 业务
- projection 第二写入
- 无预算涨 untyped `response_model` 缺口

---

## Runtime core

| 关注 | 路径 | 备注 |
| --- | --- | --- |
| 单轮编排 | `agent.py` | 新逻辑进 `core/` |
| 模式 | `core/orchestration/` | |
| LLM | `core/llm/` | `PROTOCOL.md` |
| Prompt | `core/prompt_manager/` · `core/core_prompt/` | 不扩权 |
| Tools | `tools/*_tools.py` | 授权文档 |
| Turn SSOT | `core/chat/turn_journal.py` | UI 主包 turnItems |
| Gym | `core/gym/` · `core/evaluation/` | ADR0001 |

---

## Process

| 组件 | 路径 |
| --- | --- |
| Launcher scripts | `scripts/vibelution_launcher.*` |
| **Launcher 控制面 / 桌面壳** | `desktop/electron/`（目标 writer，[ADR 0009](../adr/0009-launcher-control-plane-lives-in-electron-main.md) · [迁移账本](../../desktop/electron/CONTROL_PLANE_MIGRATION.md)）；当前 HTTP 仍在 `core/launcher/` |
| Runtime manager | `core/runtime_manager/` |
| Workbench build | `web/`；open_workbench 含 `tsc -b` |

**Process MUST：** 后台 spawn → `pythonw` / `CREATE_NO_WINDOW` / shared helper（§8.0）。

---

## Config / data SSOT

| 事实 | Canonical | 非权威 |
| --- | --- | --- |
| Operator config | `%USERPROFILE%\Documents\Vibelution\config\config.toml` | 仓库根 config |
| Turn 记录 | `turn_journal.jsonl` | `assistant_delta` |
| Collab body | target session history | inbox body（ADR0002） |
| Session 壳 | workspace chat state via session service | 仅 RQ cache |

---

## Tests（改哪测哪）

| 改 | 测 |
| --- | --- |
| 未知 | `python tests/select_tests.py --from-git main --commands-only` |
| service/pack | `tests/test_*service*.py` |
| routes | `tests/test_web_*.py` / `test_*_routes.py` |
| FE UI | colocated `*.test.ts(x)` + `vuiShadcnRouteContract` |
| Teams 结构 | `web/src/routes/teams/**/*.contract.test.ts` |
| LLM | `tests/test_llm_*.py` |
| launcher | `tests/test_launcher_*.py` · `test_runtime_*.py` |

权威分组：`tests/README.md`。

---

## 热文件（改前 claim）

`agent.py` · `session/*` 热路径 · `team_workflow` residual/facade · `ChatCodingRoute` / Teams workbench model · `core/llm/payload_builder.py` · `client.py` · wire registry · 共享 DTO · VUI 公共 primitive

→ 标准 §7；多 Agent：`docs/agents/worktree-collaboration.md`。

---

## Docs 写入

| 内容 | 写 |
| --- | --- |
| 红线 | `AGENTS.md` |
| 规则正文 | `docs/standards/` |
| **Agent 路由** | `docs/guides/`（本目录） |
| 配置语义 | `docs/ops/config/` |
| 决策 | `docs/adr/` |
| 计划/噪声 | `docs/archive/` only |
