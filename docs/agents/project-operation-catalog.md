# 项目操作目录（Project Operation Catalog · Phase 1 baseline）

**读者：仓库内 / 外部 coding Agent。**
**定位：现行 Agent 指南（Phase 1 baseline），不是计划，也不是执行面真源。**
它登记项目级可操作对象（Agent / Session / 后台 API）、治理访问类、检索卡片与安全生命周期语义。
**真源是代码：** 路由注册表 + 路由模块、canonical 工具注册表。本指南与其 `--inventory` 输出都是**派生投影**。
全局红线见根 [`AGENTS.md`](../../AGENTS.md)，开发标准见 [`docs/standards/`](../standards/)，工具注册见 [`tools/README.md`](../../tools/README.md)。

---

## 1. SSOT 与派生投影（Layer Boundaries）

只有两类真源（SSOT）；其余都是派生投影。

| 层 | 角色 | 权威 |
| --- | --- | --- |
| 路由注册表 + 路由模块 | **SSOT**：`core/web/router_registry.py`（include 顺序与 `/api` 前缀）+ `core/web/app.py` + `core/web/routes/**/*.py` | 是后端 API 面的唯一事实来源 |
| Canonical 工具注册表 | **SSOT**：`tools/Key_Tools.py`（`create_key_tools()`）+ `core/web/services/tool_catalog.py`（`TOOL_CATALOG`） | 是 Agent 可见工具 canonical 名的唯一事实来源 |
| 业务与状态 | `core/web/services/<domain>/` | 一切状态与写入的权威；projection 不得成为第二写入者 |
| `scripts/api_contract_audit.py --inventory` | **派生投影**：静态路由定义盘点（扫描 `core/web/routes/**/*.py` 与 `app.py` 中的装饰器） | 只读；**不改变运行时行为**；静态定义 ≠ 运行时可调用证明 |
| 本指南的表格 | **派生投影**：索引锚点 | 精确端点以 `--inventory` 为准；禁止手工维护第二份全量端点表 |

规则：
- 新增/变更路由或工具后，重跑 `--inventory`；先改 SSOT（代码/注册表），再刷新投影。
- `--inventory` 与指南**永远不**参与 joint SSOT；出现不一致时以代码/注册表为准并修正投影。
- **`--inventory` 是静态路由定义盘点**：只扫描路由源文件中的装饰器，可能包含尚未注册（未进 `router_registry.py`）的模块；**运行时可执行性必须与 router 注册 / runtime OpenAPI 对账**，不能把静态定义直接当作可调用证明。
- 本指南第 5 节矩阵是锚点索引，不是注册表。

## 2. 治理访问类（Governance Access Classes）

治理访问类是**声明式契约**，与当前审计脚本的传输/漂移分类**不同层、不混用**：

- `scripts/api_contract_audit.py` 的 `_classify_backend_without_frontend` 只是**传输/漂移**分类（`direct_fetch_*`、`binary_or_url_resource`、`agent_inbox_api` 等），**不机器执行治理访问类**，也不代表授权生效。
- 治理访问类由本指南与后续治理实现共同持有；当前只登记为声明，**不得声称已由机器强制**。

| 治理类 | 含义 | 典型对象 |
| --- | --- | --- |
| `AUTO_READ` | 只读、无副作用；**非无条件读取**，仍受 ToolPolicy、ACL 与 owner/team scope 约束 | 列表、详情、状态端点 |
| `GOVERNED_WRITE` | 有状态写入，须经 governed tool 或已授权调用方 | session 创建、消息发送、子会话创建 |
| `APPROVAL_REQUIRED` | 高风险写入，需用户/操作者显式审批 | agent reset、批量操作、删除类操作 |
| `OPERATOR_ONLY` | 仅操作者可执行；普通 Agent 不开放 | agent purge（不可逆） |
| `INTERNAL_ONLY` | 仅供系统服务内部使用 | 内部辅助 / 无外部面的端点 |

## 3. 检索知识卡片 Schema（Retrieval-Oriented）

卡片用于**检索与决策**，不复制运行时状态；正文最小，指针指向 SSOT。schema 字段：

```json
{
  "card_id": "session-stop-turn",
  "kind": "operation",
  "title": "停止 Session turn",
  "summary": "请求停止某 Session 当前正在运行的 turn。",
  "retrieval_keys": ["停止", "stop turn", "/api/sessions/{id}/stop", "session_stop_turn"],
  "when_to_call": "用户要求停止正在运行的回答/任务时。",
  "when_not_to_call": "Session 空闲、无运行中 turn 时不要调用（避免无效调用；接口在 idle 时可幂等返回当前 detail，但不应依赖它做轮询）；停止后如需恢复应走正常续接流程。",
  "preconditions": ["session 存在", "session 当前有运行中 turn"],
  "inputs": ["session_id", "turn_id(可选)"],
  "outputs": ["HTTP 202 + Session detail 快照（响应）；idle 时接口可幂等返回当前 detail"],
  "side_effects": ["当前 turn 被请求中止，实际停止为异步过程"],
  "risk": "低；停止结果不保证立即生效，需观察稳定状态",
  "permission_approval": "GOVERNED_WRITE（HTTP-only，无 canonical governed tool，见 §6）",
  "success_evidence": ["HTTP 202：停止请求已受理", "通过 session detail / events 观察到终止/暂停/停止类稳定状态"],
  "failure_recovery": ["404 NotFound：session 不存在，修正 id 后重试", "409 Busy：本次无法受理停止，稍后重试或人工介入"],
  "api": { "method": "POST", "path": "/api/sessions/{id}/stop" },
  "access_class": "GOVERNED_WRITE",
  "lifecycle": "safe",
  "sources": ["core/web/routes/sessions.py"],
  "revision": { "updated_at": "2026-08-17", "by": "project-operation-catalog@phase1" }
}
```

约束：
- `when_to_call` / `when_not_to_call` 必须成对写；`preconditions` / `inputs` / `outputs` 描述调用契约。
- `side_effects` / `risk` 必须声明副作用与风险；`success_evidence` / `failure_recovery` 描述成败判定与恢复。
- `permission_approval` 引用治理访问类；若当前无 governed tool 必须如实标注（见 §6）。
- `api.path` 用 `{param}` 归一化形式，与 `--inventory` 输出一致。
- `revision` 记录更新时间与归属。
- 卡片是**派生投影**，当前**无独立归档生命周期**；对象归档时经 `sources` 指针追踪，**不要把卡片自身标为 archived**。

## 4. 安全生命周期语义（delete / archive / purge）

来源：`core/web/routes/agents.py`（archive/purge/reset）、`core/web/routes/sessions.py`、`core/web/services/agent_directory/lifecycle.py`、`core/web/services/agent_bulk_delete_service.py`、`core/web/services/session/agent_sessions.py`。

| 对象 | 操作 | 端点/入口 | 语义 |
| --- | --- | --- | --- |
| Agent | Archive | `DELETE /api/agents/{agent_id}`（`agent_archive`） | **归档**（非删除）：Agent 自身成功字段写 `status=archived`；关联 Session 走 Session lifecycle 归档（只读密封），可拒绝处于 queued/running/stopping/paused 的关联 Session（409）。`PATCH /agents/{id}` 置 `status=archived` 也走同一归档链路 |
| Agent | Purge | `DELETE /api/agents/{agent_id}/purge`（`agent_purge`） | **独立、不可逆、仅 archived**：删除已归档 Session + 私有 workspace；拒绝 active；引用清理失败整批回滚 |
| Agent | Restore | **无公开通用 restore** | `PATCH` **拒绝** archived→active 隐式复活；`reactivate_agent_instance` 仅供内部系统服务（team repair、supervised、bulk delete）使用，不是通用公开入口 |
| Agent | Reset | `POST /api/agents/{agent_id}/reset`（`agent_reset`） | 重置 Agent 运行时/策略；高风险 |
| Session | Delete | `DELETE /api/sessions/{session_id}`（`session_delete`） | **删除该 Session**；busy/validation 失败返回 409/422 |
| Session | Archive/Restore | **无公开单 Session archive/restore** | Agent archive 会协调其关联 Session 归档；不存在独立公开的 session_archive/session_restore 端点 |
| Session | Stop | `POST /api/sessions/{session_id}/stop`（`session_stop_turn`） | **202 异步受理**停止请求；成功证据是经 session detail / events 观察到终止/暂停/停止类稳定状态；失败边界 404（NotFound）/ 409（Busy） |

硬规则：
1. **Purge 前必须 Archive**；Purge 不可逆，`OPERATOR_ONLY`，仅接受 `status=archived` 的 Agent。
2. **Agent archive 不是无条件可用**：仅当 Agent 当前可归档（对象非 protected）且关联 Session 不处于 queued / running / stopping / paused 状态时允许；满足条件时**合法的 active Agent 也可以 archive**。
3. Archive/Purge 引用清理失败必须整批回滚，不得半删。
4. 不存在公开的通用 Agent restore 或单 Session archive/restore；不要发明或调用不存在的端点。
5. 仅**业务对象**按各自 lifecycle 执行（Agent/Session 见上表）；**卡片是投影，无独立归档生命周期**，只更新 `sources`/`revision` 投影，不做 archive 优先。

## 5. P0 Agent / Session 标准操作矩阵

锚点以 `core/web/routes/` 当前实现为准；精确路径/方法以 `--inventory` 输出为准。

| 操作 | 端点锚点 | 治理类 | 生命周期 |
| --- | --- | --- | --- |
| List sessions | `GET /api/sessions` | `AUTO_READ` | safe |
| Session detail | `GET /api/sessions/{id}` | `AUTO_READ` | safe |
| Create session | `POST /api/sessions` | `GOVERNED_WRITE` | safe（`session_create_tool`） |
| Update session | `PATCH /api/sessions/{id}` | `GOVERNED_WRITE` | safe（HTTP-only） |
| Stop turn | `POST /api/sessions/{id}/stop`（202 异步受理） | `GOVERNED_WRITE` | safe（`session_stop_tool`） |
| Delete session | `DELETE /api/sessions/{id}` | `APPROVAL_REQUIRED` | delete（`session_delete_tool`） |
| List child sessions | `GET /api/sessions/{id}/child-sessions` | `AUTO_READ` | safe（已有 `list_child_sessions_tool`） |
| Create child session | `POST /api/sessions/{id}/child-sessions` | `GOVERNED_WRITE` | safe（已有 `create_child_session_tool`） |
| List agents | `GET /api/agents` | `AUTO_READ` | safe |
| Agent detail | `GET /api/agents/{id}` | `AUTO_READ` | safe |
| Inbox list | `GET /api/agents/{id}/messages` | `AUTO_READ` | safe（HTTP-only，无 governed tool） |
| Send message | `POST /api/agents/{id}/messages` | `GOVERNED_WRITE` | safe（已有 `agent_message_tool` 语义能力，仅覆盖 send） |
| Consume message | `POST /api/agents/{id}/messages/{message_id}/consume` | `GOVERNED_WRITE` | safe（HTTP-only；`agent_message_tool` 不覆盖 GET/consume） |
| Consume all messages | `POST /api/agents/{id}/messages/consume-all` | `GOVERNED_WRITE` | safe（HTTP-only；`agent_message_tool` 不覆盖） |
| Create agent | `POST /api/agents` | `APPROVAL_REQUIRED` | safe（`agent_create_tool`） |
| Update agent | `PATCH /api/agents/{id}` | `APPROVAL_REQUIRED` | safe（HTTP-only） |
| Archive agent | `DELETE /api/agents/{id}` | `APPROVAL_REQUIRED` | archive（`agent_archive_tool`） |
| Reset agent | `POST /api/agents/{id}/reset` | `APPROVAL_REQUIRED` | reset（`agent_reset_tool`） |
| Purge agent | `DELETE /api/agents/{id}/purge` | `OPERATOR_ONLY` | purge（HTTP-only） |

## 6. 已知治理缺口（Missing Governed Tools）

Phase 2 已实现以下 canonical governed tools（`tools/project_operation_tools.py`）：

| 工具 | 语义 | 治理类 |
| --- | --- | --- |
| `agent_create_tool` | 创建 Agent（与 `POST /api/agents` 同服务语义） | `APPROVAL_REQUIRED` / write · on_request |
| `agent_archive_tool` | 归档 Agent（完整 archive lifecycle） | `APPROVAL_REQUIRED` / destructive · always |
| `agent_reset_tool` | 重置 Agent（`reset_agent_instance`） | `APPROVAL_REQUIRED` / destructive · always |
| `session_create_tool` | 为已有 Agent 创建根 Session（不隐式创建 Agent） | `GOVERNED_WRITE` / write · on_request |
| `session_stop_tool` | 停止 Session turn（必须带 `turn_id`） | `GOVERNED_WRITE` / write · on_request |
| `session_delete_tool` | 删除 Session（`delete_chat_session`） | `APPROVAL_REQUIRED` / destructive · always |

以下操作仍有后端 HTTP 端点，但 **canonical governed tool 不存在**：

1. **Agent update 无 governed tool** — HTTP-only。
2. **Root Session update 无 governed tool** — HTTP-only。
3. **Agent inbox list（GET）、consume、consume-all 无 governed tool** — HTTP-only。
4. **无 pause/resume、无通用 restore、无单 Session archive/restore 工具** — 这些能力不存在或为内部服务，**不要发明**对应工具名。

例外与既有面：
- `create_child_session_tool` / `list_child_sessions_tool`（`tools/session_child_tools.py`）**已存在**。
- `agent_message_tool`（`tools/agent_message_tools.py`）**已存在**，仅提供 **send** 语义能力，**不覆盖 inbox list（GET）或 consume**。
- **Purge 是有意 `OPERATOR_ONLY`**，不是缺失的普通工具，**不得**补成 `agent_purge_tool` 或任何 governed tool。

## 7. 上线顺序（Rollout Order）

1. **Phase 1（本指南）**：静态路由定义盘点 + `--inventory` + 治理访问类 / 卡片 / 生命周期语义 baseline。
2. 逐端点卡片化：以 `--inventory --json` 生成静态端点定义集合，逐类补 `when_to_call` 等决策字段与治理类；运行时可执行性单独与 router 注册 / runtime OpenAPI 对账。
3. 审计分类与治理类分离落地：`_classify_backend_without_frontend` 只保留传输/漂移语义，不承担治理执行。
4. 治理工具补齐（§6）：按治理类逐个补 governed tool + 授权 + 聚焦测试（Pause/Resume 不在范围内）。
5. 全量验收：focused pytest + §8 验证命令绿后，才可声称 Phase 1 完成。

## 8. 验证 / 更新命令

```powershell
# 盘点全部 backend 端点（静态路由定义盘点；递归，含 team_workflows 嵌套；
# 运行时可执行性需与 router 注册 / runtime OpenAPI 对账，静态定义 ≠ 可调用证明）
.\.venv\Scripts\python.exe scripts\api_contract_audit.py --project-root <root> --inventory
.\.venv\Scripts\python.exe scripts\api_contract_audit.py --project-root <root> --inventory --json

# 默认 drift / type 语义（传输/漂移，非治理）
.\.venv\Scripts\python.exe scripts\api_contract_audit.py --project-root <root>
.\.venv\Scripts\python.exe scripts\api_contract_audit.py --project-root <root> --types

# 聚焦测试
.\.venv\Scripts\python.exe -m pytest tests\test_project_operation_tools.py tests\test_api_contract_audit.py -q
```

> **SSOT 重申：** 后端 API 面的唯一事实来源是 `core/web/router_registry.py` + 路由模块；Agent 工具面的唯一事实来源是 `tools/Key_Tools.py` + `tool_catalog.py`。`--inventory` 与本指南均为派生投影，任何不一致以代码/注册表为准并修正投影；Phase 1 只登记治理访问类与缺口，**不声称其已由机器执行**。
