# Agent 任务路由表

**用法：** 匹配「任务类型」一行 → 只打开 **READ** 列 → 只改 **EDIT** 列 → 跑 **TEST** 列。
未匹配：回 `ownership.md` 搜路径，再按 `loop.md` 分级。

---

## 路由表

| 任务类型 | READ（按序） | EDIT（优先） | TEST（最小） | 禁止 |
| --- | --- | --- | --- | --- |
| **任意开发（默认）** | `AGENTS.md`§3.0；本机 `ccdawn-brt/SKILL.md`；本 `route.md`；`ownership.md` | — | 按 BRT 分级选最小验证 | 不读 BRT 就广扫/写入；跳过路由叠 process 框架 |
| **任意非平凡** | `AGENTS.md`；`ccdawn-brt`；本 `route.md`；`ownership.md` | — | `tests/select_tests.py --from-git main --commands-only` | 先广扫全仓 |
| **Bug/回归/卡住** | storage inventory 的 `activePaths.logs/runtime_scenes/`；对应链路地图 | 根因位点；必要时补日志 | 复现相关 pytest/vitest | 无日志瞎猜；把 fallback 当修完 |
| **用户可见 UI** | `AGENTS.md`§2 前端；`development-standard`§9.1；`docs/guides/button-selection.md`；`web/src/components/vui/designs/INDEX.md` | `web/src/routes/<domain>/`；`components/vui`；**不**改 renderer 除非扩展交互 | `vuiShadcnRouteContract` + 触及 `*.layout.test` / route contract | `@heroui`；route→`renderers/shadcn`；未登记新 `V*`；通用裸 `<button>` |
| **前端数据/API 调用** | [`web/src/api/README.md`](../../web/src/api/README.md)；`development-standard`§24；目标 `web/src/api/<domain>.ts` | `web/src/api/<domain>.ts` + `types/` + queryKeys | 相关 `<domain>.test.ts`；`fullStackApiBoundary` 预算保持 0 | Route 内新 `fetchJson`/硬编码 path |
| **后端 API/行为** | `core/web/services/README.md` 定 facade；有 pack 再读 pack README；§24 | pack 优先 / 否则 facade → 薄 `routes/` | `test_*service*` + route/contract；`response_model` 预算不升 | route 内业务/直写 store/LLM |
| **Chat 链路/投影** | `docs/agents/conversation-flow-map.md`；`session/README.md` | `session/{submit,worker,stream_capture,persist,projection,publish}.py`；FE active-turn / ConversationView | session 相关 pytest + chat contract | 客户端乱合成 `turnItems`；delta 当 SSOT |
| **LLM/协议/缓存** | `core/llm/PROTOCOL.md`；`docs/ops/config/04`+`05` | `core/llm/{protocols,payload_builder,client,wire/*}`；**Documents** config | `test_llm_*`；`test_turn_status_bar*` 等 | 仓库根 config 当生效；可变块插 prefix 中段 |
| **Operator 配置字段** | `docs/ops/config/INDEX.md`；ADR0003 | Documents `config.toml` 语义 + `config/models.py` | `test_llm_config*` / config 相关 | 密钥入库；只改 UI 不改 schema |
| **Teams/SC/研究流** | `web/src/routes/teams/README.md`；`team_workflow/README.md` | controller/composition/pack；`team_workflows/` routes 包 | teams `*.contract.test.ts`；`test_team_workflow_*` | 胀 `TeamsRoute`；绕 panels registry |
| **Agent 目录/工具权** | `docs/agents/tool-authorization-entrypoints.md`；`agent_directory/README.md` | `tools/*`；governance/policy packs | tool/governance pytest；工具变更按 tests README prompt 要求 | 扩权无门；日志打满 payload |
| **Launcher/Runtime/进程** | §8.0；§12；§23.4；[ADR 0009](../adr/0009-launcher-control-plane-lives-in-electron-main.md)；`desktop/electron/README.md` | **目标** `desktop/electron/`；遗留 `core/launcher/` · `scripts/vibelution_desktop_entry.py`；RM 仍 `core/runtime_manager/` | `desktop/electron` vitest；`test_launcher_*`；`test_runtime_*` | 可见控制台路径；`taskkill` 绕 guard；控制窗口 `fetch :8765` 当产品路径 |
| **协作发送/inbox** | ADR0002 | session 落 history；inbox 仅索引字段 | 相关 collab/session 测试 | body 双写 session+inbox |
| **Gym/进化** | ADR0001；`docs/prds/README.md` | `core/gym/`；`core/evaluation/`；evolution services | evolution/gym 相关测试 | v1 自动改 baseline |
| **Worktree/claim/合并** | `docs/agents/worktree-collaboration.md` | 任务 worktree；claim 状态机 | preflight/merge 相关 | 脏 main 强并；覆盖他人 diff |
| **纯文档/规范** | ADR0005；`docs/README.md` | 现行树 standards/guides/adr/ops；噪声→`docs/archive/` | 链接自检 | 在 archive 写「现行规则」不提炼 |
| **全栈新能力** | §24 全节；本表 UI+API 两行 | 先 SSOT 表 → service → route → api.ts → VUI | §24.5 全行 | 只交 FE 或只交 BE 当完成 |

§ = `docs/standards/development-standard.md` 章节。

---

## 快速关键词 → 行

| 关键词 | 行 |
| --- | --- |
| 按钮/弹窗/布局/VUI/样式 | 用户可见 UI |
| session/消息/SSE/turnItems | Chat 链路 |
| DeepSeek/Anthropic/cache/wire | LLM/协议/缓存 |
| Teams/source collection/experiment | Teams/SC |
| 启动失败/tsc preflight/workbench | Launcher/Runtime |
| config.toml/provider/model | Operator 配置 |
| claim/worktree/merge | Worktree |
| 无反应/卡住/runtime_scenes | Bug |

---

## 打开预算（控上下文）

| 分级 | 最多先读 |
| --- | --- |
| `FAST_PATCH` | `ccdawn-brt`（可 silent/micro）+ `AGENTS.md` 相关红线 + 本表一行 + 目标文件 |
| `STANDARD_TASK` | `ccdawn-brt` + `AGENTS.md` + 1 个模块 README + 1 个标准相关 § + ownership 相关节 |
| `HIGH_RISK` | `ccdawn-brt`（ALIGN/FULL 按需）+ worktree 文档 + §23 相关 + 测试 README 相关段 |

**禁止：** 无目标地 `list` 整个 `docs/archive` 或 `docs/superpowers`；未加载 `ccdawn-brt` 默认规划门就开写。
