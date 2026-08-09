# Vibelution MCP 受管 Agent 网关后续开发计划

> **Status:** Revised / Product Boundaries Confirmed / Awaiting Implementation Review
> **Date:** 2026-08-09
> **Owner Surface:** `agent-runtime-core` / `external-agent gateway`
> **Base Commit:** `b9b324d4b537fbde4a1629f90f4e059bb1bedd85`
> **Initial Target Host:** Codex（本机 stdio MCP）
> **Follow-up Hosts:** Claude Desktop、Cursor 等兼容 MCP Host（完成兼容矩阵后再启用）
> **Plan Mode:** `TASK_GRAPH`
> **Default Release State:** Disabled until end-to-end acceptance

## 0. 文档定位与关闭条件

本文是带日期的执行规划，不是新的长期规范。当前用户要求、根 `AGENTS.md`、`docs/standards/`、现行 ADR 和模块 README 始终高于本文；实现过程中若权威规范或代码事实变化，应先修订本计划再继续受影响的写入。

本计划在以下条件全部满足后关闭并将 `Status` 更新为 `Complete`：

1. 关键路径任务 M0-M5 已合入本地集成分支，且没有遗留的高风险兼容分支。
2. MCP 官方客户端完成 legacy `initialize` 与 modern `server/discover` 双协议时代兼容验证，并完成 `tools/list`、`tools/call` 的真实进程握手。
3. Codex 完成至少一次非团队 Agent 任务、一次显式审批、一次取消任务和一次权限越权拒绝的端到端验收；团队 Agent 在发现和按 ID 直调两条路径均不可访问。
4. 外部任务不会切换当前工作台会话，也不会污染普通会话列表。
5. 超时和取消能够停止后端实际执行，而不是只停止等待方。
6. Windows 启动、运行、取消、退出全链路没有可见控制台窗口，也没有遗留子进程。
7. 聚焦测试、后端测试、配置校验和运行时场景证据均为绿色；未覆盖边界已明确记录。

## 1. 执行摘要

当前 MCP 实现证明了“外部 Host 可以发现 Vibelution Agent 并触发一次会话任务”的方向，但仍属于内部原型，不应直接作为生产入口启用。主要问题不是工具数量不足，而是协议、写入所有权、权限、任务生命周期和会话隔离尚未形成受管闭环：

- `core/external_agent/mcp_stdio_server.py` 自行实现 `Content-Length` framing；MCP stdio 规范要求以换行分隔 JSON 消息。
- MCP 子进程直接导入后端 service，可能成为绕过受管 Web Runtime 的第二写入者。
- `permission_mode` 由调用方传入，当前还存在自动接受审批的路径，无法形成服务端强制上限。
- 当前 Agent 枚举没有排除 active team 成员；只按 `conversationIndexKind` 过滤也会漏掉被团队引用的普通 Agent。
- 同步轮询把长任务绑在一次工具调用中；等待超时不等于停止后端执行，也没有完整取消状态机。
- 外部任务复用普通聊天会话创建路径，可能改变当前会话并在用户会话列表中产生噪声。
- 单元测试覆盖了本地 dispatch，但发现工具不等于真实 Host 端到端可用。

后续开发的推荐主线是：

> 将现有“进程内同步调用器”升级为“薄 MCP stdio 适配器 + 受管 Vibelution 后端任务 API + 隐藏执行会话”的本地 Agent 网关。

MCP 进程只负责协议、参数校验和后端连接；Agent 外部资格判断、任务创建、会话/Turn 写入、权限计算、显式审批、取消和审计均由正在运行的 Vibelution 后端负责。这样既能复用项目现有 Agent 能力，又能保持单一写入者和现有治理边界。

## 2. 当前基线

### 2.1 已存在能力

| 能力 | 当前入口 | 当前结论 |
| --- | --- | --- |
| Agent 枚举 | `list_project_agents_for_tool` | 可返回 Agent 摘要，但当前未排除 active team 成员和团队专用 Agent |
| 同步运行 | `run_project_agent_tool` | 可创建会话、提交消息并轮询结果 |
| MCP 基础方法 | `initialize`、`tools/list`、`tools/call` | 仅完成手写 legacy dispatch 级验证，未覆盖 modern `server/discover` |
| 审批 | `tool_approvals` + `_auto_accept_pending_approvals` | 已有完整审批决策语义，但外部原型当前会静默自动接受 |
| CLI | `scripts/project_agent_tool.py` | 可直接调用进程内 service |
| 聚焦测试 | `tests/test_project_agent_tool_service.py` | 当前基线为 7 个测试通过 |

### 2.2 已确认缺口

| 维度 | 缺口 | 影响 |
| --- | --- | --- |
| stdio 协议 | 使用 LSP 风格 `Content-Length`，不是 MCP newline-delimited JSON | 官方 Host 可能无法握手 |
| 写入权威 | MCP 子进程直接导入会话和审批 service | 形成第二写入者，运行时与存储状态可能漂移 |
| 权限 | 调用方可请求高权限，审批可自动接受 | 外部输入可能扩大执行权限 |
| Agent 暴露 | 没有按 active team membership 做硬过滤 | 团队成员或团队专用 Agent 可能被外部发现或按 ID 调用 |
| 生命周期 | 单次调用同步等待；无可靠取消 | Host 断开或超时后任务仍可能继续 |
| 会话隔离 | 使用普通会话路径 | 当前会话可能被切换，普通会话索引产生噪声 |
| 运行时身份 | 未强校验 backend、project root、source revision | 可能连接到错误项目或旧运行时 |
| 验收 | 单元 dispatch 为主 | 不能证明 Codex/其他真实 Host 可用 |
| 运维 | 未形成正式注册、禁用、诊断和回滚说明 | 故障时难以定位和安全停用 |

## 3. 目标与非目标

### 3.1 本轮目标

1. 让 Codex 能通过标准 stdio MCP 只发现非团队 Vibelution Agent，并以异步任务方式调用。
2. 保持 Vibelution 后端为 Agent、会话、Turn、审批和任务状态的唯一写入者。
3. 默认使用最小权限；调用方可以显式处理自己任务的审批，但不能突破服务端、operator 和 Agent policy 上限。
4. 使每个任务拥有可查询、可取消、可审计的稳定生命周期。
5. 让外部任务使用隐藏会话，绝不改变工作台当前会话。
6. 提供运行时来源校验、结构化错误、最小日志和 Windows 无控制台保证。
7. 通过真实 Codex Host 验收 legacy/modern 协议兼容、非团队隔离和显式审批，而不是停在 `tools/list` 或单元测试。

### 3.2 明确非目标

- 本轮不开发 MCP 管理 UI。
- 本轮不开放远程 HTTP/SSE/Streamable HTTP MCP 服务。
- 本轮不把多个外部用户映射为 Vibelution 员工或设备身份。
- 本轮允许外部 Host 显式处理其自身外部任务的审批，但不允许查看或处理团队任务、其他调用来源任务或超出服务端能力上限的审批。
- 本轮不向外部 Host 暴露任何 active team 成员或团队专用 Agent；仅隐藏列表不算完成，按 ID 直调也必须拒绝。
- 本轮不重构通用聊天、Teams 或 Terminal 页面。
- 本轮不把 MCP Tasks 扩展作为关键依赖；先保留稳定应用层工具契约，并在 Host 协商支持时提供可选原生 Tasks 投影。
- 本轮不承诺 Claude Desktop、Cursor 的正式兼容，仅在 Codex 验收后建立兼容矩阵。

## 4. 已锁定的架构决策

### 4.1 外部复用决策

| 候选 | 决策 | 使用边界 |
| --- | --- | --- |
| [官方 Python SDK v2](https://github.com/modelcontextprotocol/python-sdk) | `REUSE` | 生产协议栈；使用普通 `mcp` 运行依赖，隔离探针通过后固定精确 patch 版本 |
| [MCP Inspector](https://github.com/modelcontextprotocol/inspector) | `REUSE_FOR_TEST` | 真实 stdio 子进程、工具发现和调用 smoke；不进入产品运行时 |
| [MCP Conformance](https://github.com/modelcontextprotocol/conformance) | `REUSE_WHEN_FIT` | Wire Schema/协议版本检查；不为迁就测试工具把生产 stdio 架构改成 HTTP |
| [GitHub MCP Server](https://github.com/github/github-mcp-server) | `REFERENCE_ONLY` | 借鉴 toolset、只读上限优先和 scope filtering，不复制其 GitHub 领域实现 |
| [Docker MCP Gateway](https://github.com/docker/mcp-gateway) | `REFERENCE_ONLY` | 借鉴 profile、allowlist、secret 隔离和 tracing；首版不增加 Docker 依赖 |
| [官方 Reference Servers](https://github.com/modelcontextprotocol/servers) | `EXAMPLE_ONLY` | 只参考 schema、annotation 和测试写法，不把示例服务当生产架构 |

### D1. MCP 使用标准 stdio，协议实现由官方 Python SDK 承担

- 不继续维护手写 framing 和 JSON-RPC 生命周期。
- 第一阶段使用官方 SDK v2 做 SDK/Host 兼容探针，再在项目依赖中固定精确 patch 版本。
- 同时覆盖 legacy era（`initialize`）与 modern era（`server/discover` + 每请求 `_meta`）；实际 Codex Host 支持范围必须现场记录，禁止只凭版本号假定。
- 双时代协商、newline framing、stdin EOF、request cancellation 和 shutdown 均交由 SDK/标准生命周期处理，不再手写两套协议。
- 参考：[MCP versioning](https://modelcontextprotocol.io/specification/draft/basic/versioning)、[MCP stdio transport](https://modelcontextprotocol.io/specification/draft/basic/transports/stdio)、[官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk)。

### D2. MCP 适配器不是业务运行时，也不是数据写入者

- MCP 进程不得直接导入 `session_service`、Turn journal、审批 store 或其他有写副作用的 backend service。
- 它只通过 loopback 受管 API 调用当前 Vibelution backend。
- backend 不可达、项目不匹配或协议版本不兼容时直接 fail closed；禁止静默回退到进程内直写。

### D3. 后端保持单一事实源和单一写入者

- Agent 可用性由 Agent Directory 决定。
- Agent 是否属于 active team 由 Team membership 权威状态决定，`conversationIndexKind`/metadata 只作为团队专用 Agent 的补充防线。
- 会话和 Turn 继续由现有 session/turn 权威路径写入。
- 审批继续由现有审批 service 管理。
- 外部任务 service 只负责编排和投影，不建立第二份 Agent 或消息存储。

### D4. 对外契约采用显式异步任务句柄

- `start` 快速返回不透明 `taskId`，不长时间占用一次 MCP 调用。
- `get` 查询状态和有界结果。
- `cancel` 幂等请求停止实际执行。
- 应用层 `start/get/cancel` 对所有 Host 保持可用；Host 协商支持 MCP Tasks 时，再将同一后端任务投影为原生 `tasks/get`、`tasks/update`、`tasks/cancel`。
- 协议级 Tasks 只是兼容投影，不建立第二套任务状态或存储，也不成为首版可用性的硬依赖。

### D5. 外部执行使用隐藏会话

- 新会话类型建议为 `conversationIndexKind=external_agent_task`，其 conversation index visibility 固定映射为 `hidden`。
- 如果存量枚举迁移风险高，可在首个兼容步骤复用现有 hidden kind，并添加明确 `source=external_agent_task` 元数据；最终仍应收敛到可区分的独立 kind。
- 创建、提交、查询和结束外部任务均不得修改全局 active conversation。
- 普通会话列表默认不返回外部任务；诊断接口可显式查询。

### D6. 权限由服务端计算并强制执行

- 默认外部权限为 `read_only`。
- 外部请求可以进一步降权，但不能覆盖 operator 上限和 Agent 策略。
- 允许 MCP Host 显式处理其自身任务的待审批请求；不允许后台自动接受审批。
- `full_access` 只能由 operator 配置显式开启，且请求参数不能临时提权。

### D7. 功能在真实端到端验收前保持禁用

- 新依赖、API 和 adapter 可以先合入，但不自动写入用户 Host 配置。
- 只有 M5 验收绿色后，才提供受控的注册/启用步骤。

### D8. 外部任务使用有界租约，Host 消失后不无限运行

- 每个非终态任务绑定 backend 签发的短期 lease；lease 只在 adapter 与 Host 仍存活时续期。
- adapter 正常 shutdown 时主动取消其非终态任务；异常退出时由 lease expiry 触发同一受管停止路径。
- adapter 在 lease 到期前重启并以同一本地运行时身份重连，可以继续查询并续期任务。
- 首版不提供 detached/background forever 模式；如以后需要，必须作为独立权限和产品决策规划。

### D9. 只有非团队 Agent 可以通过 MCP 发现和调用

- 外部资格硬条件为：Agent 当前可用、未属于任何 active team、且不是显式或推断出的团队专用 Agent。
- “未出现在列表”不是授权边界；`start`、审批、状态迁移和后台 reconciliation 必须复用同一 `external_mcp_eligible` 判定。
- 外部调用方猜中团队 Agent ID 时统一返回不可发现语义，不泄露其存在、团队 ID 或成员关系。
- Agent 在任务运行期间加入 active team 后，禁止继续批准或启动新工具调用，并让任务进入受管停止/对账路径；原调用方仍可查询终态和发出取消，以便安全收尾。

### D10. MCP 审批是显式、任务级、可审计的写能力

- `get_project_agent_task` 返回经过清洗的待审批摘要；`resolve_project_agent_approval` 对指定审批执行显式决策。
- 复用现有 `accept`、`acceptForSession`、`acceptAlways`、`decline`、`cancel` 语义，不在 adapter 发明第二套审批状态机。
- `acceptAlways` 会修改非团队 Agent 的持久 ToolPolicy，只有服务端授予 `approval.persist` 时才允许；调用参数本身不能获得该能力。
- 每次审批重新校验 task owner、Agent 外部资格、当前 config revision、审批状态和服务端能力上限；团队任务、其他来源任务和已失效审批均 fail closed。
- 同一决策重试应返回已有结果；冲突决策返回稳定 conflict，不重复触发执行。

### D11. 协议错误与任务业务失败严格分层

- JSON-RPC malformed request、未知方法和 adapter 内部协议故障使用标准协议错误；可恢复的参数、权限、Agent 不可调用和任务业务失败返回结构化 Tool result，并按契约设置 `isError=true`。
- 不把 Python exception 类型、堆栈、绝对敏感路径或原始内部消息直接返回 Host；对外只返回稳定 code、短 message、retryable 和必要 correlation ID。
- MCP Tasks 投影中的 `failed` 只表示协议任务自身无法执行/保存；Agent 业务失败投影为 `completed` + `CallToolResult.isError=true`，避免 Host 错误重试已完成的业务任务。

## 5. 目标架构

```text
Codex / compatible MCP Host
          │
          │ stdio · newline-delimited JSON
          ▼
Official-SDK MCP Adapter
  - legacy/modern protocol lifecycle
  - input/output schema
  - fixed tool registry + negotiated Tasks projection
  - bounded backend client
  - no project-data writes
          │
          │ loopback HTTP · local auth · runtime identity
          ▼
Vibelution Managed Backend
  ├─ thin external-agent routes
  ├─ external-agent task facade / projection
  ├─ Agent Directory + Team membership ← identity/exposure SSOT
  ├─ Session + Turn Journal          ← execution SSOT
  ├─ Tool Approval Service           ← explicit approval SSOT
  └─ Runtime Scene Logging           ← diagnostic evidence
          │
          ▼
Hidden external-agent session + auditable task state
```

### 5.1 事实源分配

| 数据或决策 | 唯一事实源 | 禁止做法 |
| --- | --- | --- |
| Agent 身份、启用状态、能力摘要 | Agent Directory | MCP 自建 Agent 注册表 |
| 外部调用资格 | Agent Directory + active Team membership + team-agent classification | 只按工具列表或单一 UI 字段过滤 |
| 消息、Turn、终态 | Session / Turn Journal | MCP 子进程写第二份任务历史 |
| 外部任务状态投影 | Backend external-agent task service | 仅保存在 MCP 进程内存中 |
| 工具审批 | 现有 Tool Approval Service | Headless adapter 自动批准，或 adapter 自建审批账本 |
| operator 权限上限 | operator config + Agent policy | 信任调用方传入的权限字符串 |
| backend 地址和运行时身份 | Launcher/runtime descriptor | 猜测固定端口或连接任意本机服务 |
| 诊断事件 | `logs/runtime_scenes/` 现有链路 | 记录完整 Prompt、回复或 secret |

## 6. MCP 工具契约

首版固定暴露五个工具，不为每个 Agent 动态创建一个工具。工具描述和 annotations 只帮助 Host 展示与决策，真正的 Agent 外部资格、任务归属和权限检查仍由后端执行。

### 6.1 `list_project_agents`

用途：列出允许通过外部网关使用的 Agent。

- 输入：可选的能力/名称过滤和分页参数。
- 候选集必须排除任何 active team 的 `members[].agentId`，并排除显式或推断出的团队专用 Agent；operator 规则只能继续收窄，不能把团队 Agent 重新加入。
- 输出：`agentId`、名称、短描述、可用状态、外部最大权限与审批能力摘要。
- 不输出内部 Prompt、secret、完整工具策略或敏感配置。
- annotation：`readOnlyHint=true`、`destructiveHint=false`。

### 6.2 `start_project_agent_task`

用途：创建异步 Agent 任务。

建议输入：

```json
{
  "agent_id": "string",
  "task": "string",
  "permission_profile": "read_only",
  "client_request_id": "optional-idempotency-key",
  "title": "optional-short-title"
}
```

建议立即输出：

```json
{
  "taskId": "opaque-id",
  "status": "queued",
  "effectivePermissionProfile": "read_only",
  "createdAt": "ISO-8601",
  "pollAfterMs": 500
}
```

约束：

- `client_request_id` 在同一 Host/项目边界内幂等，避免 Host 重试创建重复任务。
- 创建前必须重新计算 `external_mcp_eligible`；不能信任此前列表结果，也不能接受团队 Agent 的猜测 ID。
- 不向 Host 暴露可用于越权访问其他会话的原始 session ID；如需诊断，可放入受限 `_meta`。
- Prompt 按不可信输入处理，长度和内容边界由后端校验。

### 6.3 `get_project_agent_task`

用途：查询任务状态和有界结果。

状态集合：

```text
queued
running
awaiting_approval
cancelling
stop_unconfirmed
succeeded
failed
cancelled
timed_out
```

输出至少包含：`taskId`、`status`、时间戳、有限长度的结果摘要、结构化错误、是否仍需轮询，以及经过清洗的 `pendingApprovals`。审批摘要只包含批准决策所需的 tool、risk、目标摘要、config revision 和稳定 ID，不暴露 secret、完整参数或内部 session ID。

所有工具均定义 output schema，并优先返回 `structuredContent`；同时提供简短 text fallback，兼容只读取文本结果的 Host。两者来自同一结构化结果，不维护两套业务语义。

### 6.4 `resolve_project_agent_approval`

用途：显式处理当前外部任务的一条待审批请求。

建议输入：

```json
{
  "task_id": "opaque-id",
  "approval_id": "opaque-approval-id",
  "decision": "accept | acceptForSession | acceptAlways | decline | cancel",
  "expected_revision": "optional-optimistic-version",
  "reason": "optional-short-reason"
}
```

约束：

- adapter 只提交决策；task ID 到隐藏 session、turn 和 approval request 的映射由 backend 完成。
- 只允许处理同一 MCP 调用主体创建任务中的 pending approval；团队 Agent、其他主体任务或失效审批统一拒绝。
- `accept` 只批准当前请求，`acceptForSession` 只影响当前隐藏任务会话，`acceptAlways` 需要服务端 `approval.persist` 能力并由现有 Agent ToolPolicy 持久化。
- 每次决策前重新校验 Agent 仍为非团队、config revision 未失效、权限未被 operator 收紧。
- 相同决策重试返回当前审批投影；不同决策竞争返回稳定 conflict，禁止重复执行。
- annotation：`readOnlyHint=false`、`destructiveHint=true`；只有实现上述幂等语义后才声明 `idempotentHint=true`。

### 6.5 `cancel_project_agent_task`

用途：幂等取消任务。

- 对运行中任务：进入 `cancelling`，向实际 Turn/执行器发出停止信号。
- 对终态任务：返回原终态，不制造错误。
- 只有在后端确认执行已停止后才能进入 `cancelled`。
- 超时必须复用同一停止路径，不能只让 polling caller 返回。

### 6.6 旧 `run_project_agent` 的迁移

- 正式工具列表不再把同步 `run_project_agent` 作为主入口。
- 若兼容期确有需要，可保留一个有界 wrapper：内部调用 `start`，在很短预算内查询；未完成时返回 `taskId`，不无限阻塞。
- wrapper 不得保留自动审批或直接 service 导入。
- Codex 端到端迁移完成后删除兼容 wrapper；删除条件写入实现 PR/变更记录。

### 6.7 可选 MCP Tasks 投影

- 五个应用层工具是所有 Host 的稳定兼容面；Host 声明支持 `io.modelcontextprotocol/tasks` 时，adapter 才声明对应 `execution.taskSupport` 并投影原生 Tasks 方法。
- `taskId`、TTL、状态与结果都来自同一 backend task，不复制状态；创建结果只有在 durable task 已写入且可立即查询后才能返回。
- 内部状态投影规则：`queued/running/awaiting_approval/cancelling/stop_unconfirmed` → `working`；`succeeded` → `completed`；业务失败 → `completed` + `CallToolResult.isError=true`；协议或任务存储自身失败 → `failed`；`cancelled` → `cancelled`；实际停止已确认的 `timed_out` → `cancelled` + timeout `statusMessage`。
- `awaiting_approval` 默认仍投影为 `working` + `statusMessage`；只有未来明确允许 Host 通过 Tasks 输入通道回答时，才使用 `input_required`。
- `notifications/cancelled` 只取消当前 JSON-RPC 请求，不得当作 durable Agent 任务取消；后台任务只能通过 `cancel_project_agent_task` 或协商后的 `tasks/cancel` 停止。

## 7. Backend API 与任务状态机

### 7.1 建议 API（内部 loopback）

| Method | Path | 作用 |
| --- | --- | --- |
| `GET` | `/api/v1/external-agent/agents` | 获取允许暴露的 Agent |
| `POST` | `/api/v1/external-agent/tasks` | 创建任务 |
| `GET` | `/api/v1/external-agent/tasks/{task_id}` | 查询任务 |
| `POST` | `/api/v1/external-agent/tasks/{task_id}/approvals/{approval_id}/resolve` | 显式处理任务审批 |
| `POST` | `/api/v1/external-agent/tasks/{task_id}/cancel` | 幂等取消 |
| `POST` | `/api/v1/external-agent/tasks/{task_id}/heartbeat` | adapter 续期任务 lease；不暴露为 MCP 工具 |

路径为本计划建议值；实现前先检查现有 FastAPI prefix 和 DTO 约定，避免形成第二套 API 风格。

### 7.2 状态迁移

```text
queued ──► running ──► succeeded
  │           │  ├──► awaiting_approval ──显式决策──► running / failed / cancelling
  │           │  ├──► failed
  │           │  └──► cancelling ──► cancelled / timed_out
  │           │                 └──► stop_unconfirmed ──► reconciled terminal state
  │           └─────► cancelled
  └─────────────────► cancelled
```

规则：

- 终态不可逆：`succeeded`、`failed`、`cancelled`、`timed_out`。
- 每次迁移写入统一时间戳、原因码和相关 Turn 标识。
- `awaiting_approval` 不是成功；只有通过受管审批界面或 `resolve_project_agent_approval` 的显式、已授权决策才能推进，adapter 不得自行推进。
- `timed_out` 仅在实际停止已确认后写入；若停止确认超出预算，进入非终态告警状态 `stop_unconfirmed`，由 reconciliation 继续确认真实执行状态，不能伪造关闭。
- backend 重启后必须能从权威会话/Turn 状态恢复任务投影，不能依赖 MCP 进程内存。
- lease 过期等价于受管取消请求；它必须进入相同的 stop acknowledgement 状态机。

### 7.3 本地连接与身份校验

MCP adapter 每次启动必须确认：

1. backend 为当前项目的受管 Runtime，而不是同端口上的其他服务。
2. backend 返回兼容的 external-agent API protocol version。
3. runtime source revision 和 project root 可用于诊断；不匹配时默认拒绝执行，除非存在明确兼容策略。
4. 使用用户级、本机 loopback 的受限认证材料；secret 不写入 Host 配置正文或日志。
5. 连接失败有短超时和结构化错误，不自动启动另一套 backend。
6. task lease ID、续期时间和 adapter connection ID 只在 adapter/backend 之间传递，不作为可伪造的工具输入暴露。

stdio Host 的 `clientInfo`、`serverInfo` 和协议 `_meta` 均属于自报/传递信息，可用于兼容诊断和审计标签，不能单独作为身份或授权事实。外部任务句柄必须绑定 backend 验证的本地调用主体，并在每次查询、审批和取消时重新授权。

认证材料和 runtime descriptor 的具体来源由 M0 探针确认；优先复用 Launcher 已有受管运行时事实，不增加长期静态 token。

## 8. 权限、审批与安全模型

### 8.1 权限档位

建议对外只公开以下稳定档位：

| Profile | 默认 | 能力边界 |
| --- | --- | --- |
| `read_only` | 是 | 读取项目和诊断信息；禁止文件写入、Git 写入和外部副作用 |
| `workspace_write` | 否 | 仅在 Agent policy 与 operator 上限允许时写指定工作区；高风险动作仍进入审批 |
| `full_access` | 否 | 仅显式 operator 授权；不能通过单次请求临时开启 |

Profile 只是能力集合的稳定别名，backend 展开后按集合交集计算有效权限：

```text
effective_capabilities = requested ∩ operator_ceiling ∩ agent_policy ∩ runtime_policy
```

旧的 `auto_review`、`request_approval` 等内部模式不得由 adapter 原样透传为授权事实；它们应由 backend 统一映射并测试。

### 8.2 审批策略

- 删除所有外部路径上的“自动接受 pending approvals”。
- 需要审批时，任务进入 `awaiting_approval`。
- 审批可以由现有 Vibelution 受管界面完成，也可以由 `resolve_project_agent_approval` 显式完成；两条入口复用同一 Tool Approval Service 和审计事实源。
- MCP 调用方只能审批自己创建的非团队 Agent 任务；不能查看或处理 Teams、普通 Chat、Terminal 或其他 MCP 调用主体的审批。
- `acceptAlways` 是持久策略变更，必须额外满足 `approval.persist` 服务端能力、Agent policy 和当前 config revision；普通 `accept`/`decline` 不自动获得持久授权。
- 同一审批只能产生一个最终决策；相同决策重放幂等，冲突决策返回稳定 conflict。
- Host 断开不会改变审批结果，也不会默认放行。

### 8.3 非团队 Agent 暴露边界

backend 提供单一 `external_mcp_eligible(agent_id)` 判定，至少组合以下事实：

1. Agent Directory 中的当前状态与有效身份。
2. Team membership 权威状态中不存在包含该 Agent 的 active team。
3. Agent 不是显式或推断出的团队专用 Agent；不能仅依赖 `conversationIndexKind`，但该字段和团队 metadata 必须作为补充防线。
4. operator/external gateway 配置没有进一步禁用该 Agent。

该判定由 `list`、`start`、审批、运行检查点和 reconciliation 复用。Agent 加入 active team 后立即撤销新的外部执行/审批资格；已有任务进入受管停止，原 owner 仅保留查询和取消能力。对不合格 Agent 的直接调用使用不可发现错误，避免形成团队目录枚举侧信道。

### 8.4 其他安全边界

- Agent 列表只包含满足非团队硬条件且未被 operator 进一步禁用的 Agent；任何 active team 成员都不能通过 external exposure 配置重新开放。
- 所有输入设置长度、类型、分页和并发上限。
- 不接受任意 project root、backend URL、session ID 或文件路径作为工具参数。
- 任务读取和取消必须校验调用来源与 task capability，不能只凭可猜测 ID。
- 任务审批必须校验调用来源、Agent 外部资格、approval ID、config revision 和 capability，不能只凭 approval ID。
- 错误结果不返回绝对 secret 路径、Prompt、环境变量或内部堆栈。
- MCP 工具 annotation 不是安全机制，服务端必须重复验证。

## 9. 会话、数据与保留策略

### 9.1 外部任务会话

- 元数据至少记录：`source=external_agent_task`、Host 类型、MCP client 信息、task ID、Agent ID、有效权限、创建/结束时间和 runtime revision。
- `conversationIndexVisibility=hidden`，普通会话列表默认排除。
- 不写全局 active conversation，也不触发前端导航。
- 允许诊断接口按 task ID 查询，但不得通过普通会话路由无意暴露。

### 9.2 任务投影与恢复

- task service 保存的是指向权威 session/Turn 的稳定投影，而不是第二份完整对话。
- backend 重启时根据 task metadata、session phase 和 Turn journal 重建非终态任务。
- 恢复和每次状态变更时重新检查 Agent 是否已加入 active team；资格撤销后不再执行或批准新工具调用，并进入取消/对账。
- MCP 进程异常退出后，只要 lease 尚未过期，Host 可重新启动 adapter 并继续使用 task ID 查询；lease 已过期则任务进入受管停止流程。
- 任务结果必须有界；完整消息仍留在 Vibelution 权威存储中。

### 9.3 保留与清理

- 首版沿用项目现有会话保留政策，不在运行中硬删除。
- 后续清理必须按 `external_agent_task` 类型单独统计、可审计、可恢复判断。
- 清理动作不属于首版 MCP 工具面，避免给 Host 增加删除权限。

## 10. 日志与可诊断性

### 10.1 必要事件

每个任务至少产生以下结构化 runtime-scene 事件：

- adapter 启动及 protocol/SDK 版本（不含 secret）。
- backend 身份校验成功/失败。
- task create、state transition、approval wait、显式 approval decision、cancel request、stop confirm、terminal result。
- Agent discovery/execution eligibility 拒绝及稳定 reason code；不记录团队详情或泄露不可见 Agent 身份。
- Host disconnect 和 adapter shutdown。
- 失败的稳定 reason code、耗时和 task ID。

### 10.2 禁止记录

- 完整 Prompt 或完整 Agent 回复。
- 完整代码 diff、文件内容或工具参数原文。
- token、认证材料、环境变量和模型 secret。
- 无界 stdout/stderr。

日志正文只保留 ID、状态、长度、耗时、稳定错误码和必要来源摘要。

## 11. 预计代码与文档落点

最终文件名以 ownership/preflight 结果为准，建议落点如下：

| Surface | 建议落点 | 责任 |
| --- | --- | --- |
| MCP adapter | `core/external_agent/mcp_server.py` | 官方 SDK server、工具 schema、stdio 生命周期 |
| backend client | `core/external_agent/backend_client.py` | 有界 loopback 调用、身份和错误映射 |
| shared contracts | `core/external_agent/contracts.py` | 请求、响应、状态和错误契约 |
| 兼容入口 | `core/external_agent/mcp_stdio_server.py` | 临时转发或删除旧手写 framing |
| CLI | `scripts/project_agent_tool.py` | 改为受管 backend client；不直接导入写 service |
| API route | `core/web/routes/external_agents.py` | 薄 FastAPI route 和 DTO 校验 |
| task service | `core/web/services/external_agent_task_service.py` 或新 pack | task 编排、投影、权限、显式审批和取消；复杂时建 pack + README |
| exposure policy | external-agent task pack 内的独立 policy 模块 | 复用 Agent Directory 与 Team membership 权威状态，集中实现 `external_mcp_eligible` |
| app wiring | 现有 Web app/router 注册入口 | 注册内部 API route |
| dependency | `requirements.txt` / 项目既有锁定入口 | 固定经探针验证的官方 MCP SDK 版本 |
| tests | `tests/test_external_agent_*.py` | 契约、权限、状态机、恢复、取消和进程测试 |
| ops docs | `docs/ops/config/` 对应现行配置文档 | 注册、禁用、诊断、兼容矩阵和回滚 |

实现时同步更新 `core/web/services/README.md` 的 service/pack 索引。首版不修改 `web/`；若后续增加管理界面，必须另开 VUI 规划和 claim。

## 12. 任务图与实施顺序

### 12.1 依赖关系

```text
M0 协议/SDK兼容探针 ───────┐
                           ├──► M3 官方SDK MCP adapter ──► M4 运维注册 ──► M5 真实Host验收
M1 后端任务SSOT ─► M2 权限/取消/会话隔离 ┘
```

M0 与 M1 的“契约设计”可并行；共享 DTO 定稿由同一 owner 串行收口。M1/M2 触及 session/Turn 热路径，必须等待当前 `conversation-turn-item-convergence` claim 释放，或与其 owner 完成明确的路径和契约协调。

| Task | Execution Policy | Primary Surface | Hard Dependency |
| --- | --- | --- | --- |
| M0 | BDD/TDD | protocol probe + `core/external_agent` | 无 |
| M1 | BDD/TDD | backend task API + non-team exposure + session/Turn integration | M0 contract draft；session claim gate |
| M2 | BDD/TDD | permission、explicit approval、cancel、lease | M1 |
| M3 | BDD/TDD | official SDK adapter + five tools + optional Tasks projection | M0、M1、M2 |
| M4 | Simple implementation + runtime verification | config、lifecycle、ops docs | M3 |
| M5 | Acceptance-only | real Codex Host + managed runtime | M0-M4 |

### M0. 协议、SDK 与 Host 兼容探针

**目标：** 用失败测试固定当前协议缺口，并选择可被 Codex 实际加载、同时覆盖 legacy/modern 协议时代的官方 SDK v2 精确版本。

**允许范围：** `core/external_agent/` 的隔离探针、`tests/test_external_agent_*.py`、临时 fixture；探针定版后才允许更新项目依赖 pin，不改会话写路径。

**工作项：**

1. 增加真实子进程测试：newline JSON 请求必须获得合法响应，旧 `Content-Length` 行为只作为失败基线记录。
2. 使用官方 Python SDK v2 client/server 分别验证 legacy `initialize` 与 modern `server/discover`、每请求 `_meta`、`tools/list`、`tools/call` 和回退行为。
3. 核对 Python 3.11、Pydantic 2、FastAPI 现有依赖兼容性；生产依赖使用普通 `mcp`，Inspector/conformance 保持开发工具隔离。
4. 使用 MCP Inspector 做真实 stdio 进程 smoke；conformance 只在适配 stdio/wire-schema 时加入，不为工具强制引入生产 HTTP transport。
5. 用本机 Codex 的隔离/临时配置做只加载/发现 smoke，记录实际 protocol era、启动命令、解释器和退出行为；如必须修改用户持久 Codex 配置，先单独取得授权。
6. 产出明确的 SDK 精确 pin、双时代兼容矩阵、tool schema 约定、EOF/request cancellation 和 adapter shutdown 约定。

**验证：** 新测试先红后绿；legacy/modern 两组协议测试、真实进程退出码、stdout framing、stderr 有界；无残留进程。

**停止条件：** 官方 SDK 与当前依赖冲突，或 Codex Host 不支持目标工具输出契约时，停止后续实现并重新对齐版本/协议，不自建第二套协议。

### M1. 后端 external-agent task API 与事实源

**目标：** 后端提供异步任务创建、查询和恢复，成为唯一写入者。

**前置：** M0 的 shared contract 初稿；session 热路径 claim 已释放或协调完成。

**允许范围：** external-agent route/service/contracts、必要的 session/Turn integration seam、对应测试和 service 索引；不改前端、不复制会话存储。

**工作项：**

1. 先写 route/service 契约测试和状态机失败测试。
2. 增加薄 route、明确 DTO、稳定错误码和 API protocol version。
3. 建立唯一 `external_mcp_eligible` policy：组合 Agent Directory、active Team membership 和团队专用 Agent classification；operator 配置只允许继续收窄。
4. 在列表与按 ID 创建任务两条路径复用该 policy；团队 Agent 返回不可发现语义，避免只隐藏 discovery 却允许直调。
5. 创建隐藏 external task session，不改变 active conversation。
6. 将 task ID 稳定映射到 session/Turn 权威记录和本地调用主体。
7. 支持 backend 重启后的任务投影恢复，并在恢复/状态变更时重新检查团队归属。
8. 更新 service 索引和模块 README（如建立 pack）。

**验证：** route/service 单测；active team 普通成员、团队专用 Agent、猜测 ID 三类负例；创建后普通会话索引不出现；active conversation 前后相同；重启投影与团队归属撤销测试。

**停止条件：** 必须复制 session/Turn 存储才能实现，或现有权威路径无法表达隐藏任务时，先形成 ADR/架构对齐，不增设影子账本。

### M2. 权限、审批、取消与超时闭环

**目标：** 外部任务 fail closed，服务端限制权限，并能停止实际执行。

**前置：** M1 基本状态机可用。

**允许范围：** external-agent task service、现有 approval/Turn stop 的窄适配点、审批 backend endpoint、operator config schema、runtime-scene 事件和对应测试；MCP Tool 绑定留到 M3。

**工作项：**

1. 先补越权、自动审批、任务归属、团队隔离、重复审批、重复取消、超时和 Host 断开测试。
2. 实现 operator/Agent/runtime/request 的权限交集。
3. 删除外部自动审批；审批进入 `awaiting_approval`，通过现有 Tool Approval Service 暴露任务级显式决策 endpoint。
4. 支持 `accept`、`acceptForSession`、`acceptAlways`、`decline`、`cancel`；`acceptAlways` 额外校验 `approval.persist`、Agent policy 和 config revision。
5. 对相同审批决策实现幂等投影，对竞争决策返回稳定 conflict；不重复唤醒 Turn。
6. 把 cancel 接到实际 Turn/执行器停止能力，并等待确认。
7. 把 timeout、Agent 加入 active team 和资格撤销接到同一停止路径。
8. 实现 task lease、heartbeat、graceful shutdown cancel 和 expiry reconciliation。
9. 增加并发数、任务时长、Prompt 长度和结果长度限制。
10. 增加最小 runtime-scene 事件和敏感字段清洗。

**验证：** `full_access` 越权被降级或拒绝；审批不自动通过；任务 owner 可显式审批、其他主体和团队任务不可审批；`acceptAlways` 无 capability 时拒绝；cancel/timeout/团队归属撤销最终停止；正常 shutdown 主动取消；异常断开在 lease 到期后受管停止；日志无敏感正文。

**停止条件：** 现有执行器无法提供可确认的停止语义时，不把“停止轮询”标成取消完成；保留功能禁用并先修执行器契约。

### M3. 官方 SDK MCP adapter 与 backend client

**目标：** 替换手写协议和进程内业务调用，暴露五个稳定工具，并在 Host 协商支持时提供同一后端任务的可选 MCP Tasks 投影。

**前置：** M0 SDK pin；M1/M2 API 和安全契约稳定。

**允许范围：** `core/external_agent/`、`scripts/project_agent_tool.py`、项目依赖 pin 和协议/CLI 测试；不得直接修改 backend 数据 store。

**工作项：**

1. 实现 `backend_client` 的短连接超时、身份检查和结构化错误映射。
2. 用官方 SDK 实现五个 MCP 工具和 input/output schema，其中 `get` 返回清洗后的 pending approvals，`resolve` 只提交显式决策。
3. 添加合适 annotations，但不依赖 annotation 做授权。
4. 支持 legacy/modern protocol era；处理未知方法、无效参数、request cancellation、Host 断开、stdin EOF 和 shutdown。
5. 对声明 Tasks extension 的 Host 增加可选 `tasks/get/update/cancel` 投影；不支持时保持五工具兼容面。
6. 在 adapter 存活期间续期非终态任务 lease，shutdown 时有界请求取消。
7. 将 CLI 改为调用 backend client。
8. 删除或隔离旧手写 framing；禁止 direct-write fallback。
9. 为兼容 wrapper 设置明确删除条件。

**验证：** 官方 client 双时代进程测试；五工具 schema/structured output；Tasks 支持与不支持两种协商路径；backend 不可达/版本不匹配 fail closed；CLI/MCP 都不导入后端写 service；退出无残留进程。

**停止条件：** adapter 需要直接访问存储才能完成工具调用，或 backend 身份无法确认时，禁止继续注册到 Host。

### M4. 启用、配置、诊断与 Windows 生命周期

**目标：** 提供可重复、可禁用、无可见控制台的本机注册方式。

**前置：** M3 进程测试绿色。

**允许范围：** 受管启动/诊断入口、当前 operator 配置文档、Host 注册说明和 Windows 生命周期测试；持久 Host 配置写入仍需用户单独授权。

**工作项：**

1. 使用项目虚拟环境中的明确 Python 解释器，不依赖全局 PATH。
2. 形成 Codex MCP 注册说明和诊断命令；不自动覆盖用户现有配置。
3. 说明 backend 不可达、版本不匹配、权限拒绝和取消失败的处理。
4. Windows 后台启动必须使用项目 shared no-console helper、`pythonw`、`CREATE_NO_WINDOW` 或等价受管路径。
5. 增加禁用和回滚步骤；关闭 Host 后确认 adapter/child 无残留。
6. 记录 Launcher/runtime refresh 判定。

**验证：** 干净用户态注册演练；桌面观察无 `cmd.exe`/PowerShell/Windows Terminal/OpenConsole 弹窗；进程树和 runtime scene 一致。

**停止条件：** 任何非用户主动终端路径出现可见控制台，或注册必须写入 secret 明文，则不得进入 M5。

### M5. Codex 端到端验收与受控启用

**目标：** 证明真实 Host 能安全完成任务闭环，之后才允许用户启用。

**前置：** M0-M4 全绿；源代码、运行时和配置来源一致。

**允许范围：** 真实运行时和隔离 Host 配置的验收操作与证据；发现代码问题时退回对应 M0-M4 owner 修复，不在验收步骤夹带无计划改写。

**验收场景：**

1. Codex 加载 server，记录实际 legacy/modern protocol era，并完成 tools discovery。
2. `list_project_agents` 只返回非团队 Agent；active team 普通成员和团队专用 Agent 均不出现，也不泄露内部配置。
3. 对不可见团队 Agent 使用猜测 ID 调用 `start`，确认返回不可发现错误且不创建 session/task。
4. 启动一个只读任务，轮询至成功，结果有界。
5. 触发需审批任务，确认不会自动接受；通过 `resolve_project_agent_approval` 完成一次显式 `accept`，任务继续执行。
6. 用其他调用主体、团队任务或无 `approval.persist` capability 尝试审批/`acceptAlways`，确认 fail closed。
7. 启动长任务并取消，确认后端实际停止且无残留。
8. 任务运行中把 Agent 加入 active team，确认新的审批/执行资格撤销并进入受管停止；查询和取消仍可用于收尾。
9. 请求超出 operator 上限的权限，确认被拒绝或降权。
10. 任务前后当前工作台会话不变，普通会话列表无外部任务噪声。
11. backend 停止或 revision 不匹配时，adapter fail closed 并给出可诊断错误。
12. Host 关闭后 adapter 正常退出，无可见控制台和孤儿进程。
13. 强制结束 adapter，确认 lease expiry 会触发受管停止，且不会留下无限运行任务。
14. 若 Codex 声明 Tasks extension，验证原生 task 创建/查询/取消；若未声明，记录为 Host 能力边界，五工具闭环仍必须通过。

**交付门：** 全部场景有命令、时间、source revision、结果和未覆盖边界；仅 tools discovery 不能算完成。

## 13. 测试与验收矩阵

| 层级 | 必测内容 | 完成证据 |
| --- | --- | --- |
| Contract | 五个 tool input/output schema、错误码、状态枚举、审批决策 | schema snapshot / focused tests |
| Protocol | newline framing、legacy initialize、modern server/discover、request cancellation、EOF/shutdown | 官方 SDK client 双时代子进程测试 |
| Exposure | active team 普通成员、团队专用 Agent、猜测 ID、运行中加入团队 | policy/service/route negative tests |
| Service | task 状态机、恢复、幂等、结果有界 | backend service tests |
| Permission | 默认只读、服务端 clamp、调用主体与 task capability | negative tests |
| Approval | 不可自动审批、显式五类决策、重放/冲突、`approval.persist` | approval service + route + MCP contract tests |
| Session | hidden kind、普通索引排除、不改 active conversation | session/conversation tests |
| Cancellation | queued/running/approval 中取消、timeout、重复取消 | bounded end-to-end tests |
| Lease | heartbeat、graceful shutdown、adapter crash、expiry reconciliation | clock-controlled tests + process test |
| Runtime identity | project root、revision、API version 不匹配 | fail-closed tests |
| CLI | 明确解释器、后端不可达、结构化输出 | CLI subprocess tests |
| Windows | 启动/运行/退出无控制台、无孤儿进程 | 桌面观察 + process evidence |
| Tasks | extension 协商有/无两条路径、状态映射、durable cancel | SDK process tests + compatible Host smoke |
| Host | Codex 真实发现、非团队隔离、显式审批、任务、取消、越权拒绝 | live acceptance record |

建议聚焦命令在实现阶段按实际测试文件确定；每个任务先跑最窄测试，再跑相关 backend 套件。若触及全局 session/Turn hot path，追加 `tests/README.md` 规定的相关回归矩阵。首版不触及 `web/`，因此不需要前端 `tsc -b`；一旦范围扩展到 UI，必须另行执行 VUI contract 和完整类型检查。

## 14. 迁移与发布策略

### Stage A：冻结原型行为

- 保留现有测试作为基线，但新增测试明确证明旧 framing、自动审批和同步取消语义不合格。
- MCP 默认未注册、未启用，不改变现有用户环境。

### Stage B：先建后端受管能力

- 合入 disabled 的内部 task API、非团队 exposure policy、显式审批和权限/取消闭环。
- 不让 MCP adapter 直写存储，也不引入 UI。

### Stage C：切换 adapter 和 CLI

- 官方 SDK adapter 与 CLI 都只走 backend client。
- 五工具兼容面始终可用；原生 MCP Tasks 只在 Host 协商支持时开启。
- 旧同步入口进入短兼容期，添加弃用说明和删除条件。

### Stage D：Codex 受控启用

- 用户明确确认后写入/更新 Codex MCP 配置。
- 先只启用 `read_only`，通过 live acceptance 后再评估 `workspace_write`。

### Stage E：兼容矩阵扩展

- 分别验证 Claude Desktop、Cursor 等 Host 的启动、schema、输出、取消和退出差异。
- 每个 Host 独立启用，不用“协议兼容”替代真实验收。

## 15. 回滚方案

1. 从 Host 配置禁用或移除 Vibelution MCP 注册，不删除用户其他 MCP 配置。
2. backend external-agent API 保持 disabled/inert，不影响普通聊天和 Agent 运行。
3. 回滚 adapter/依赖代码到已知绿色提交；不回滚或删除用户会话数据。
4. 已生成的隐藏任务保留审计信息，后续按独立清理流程处理。
5. 若新 session kind 引发索引问题，停止新建并回到兼容 hidden kind；禁止批量破坏性迁移。
6. 回滚后复验普通 Chat/Teams/Terminal 会话不受影响，并确认无残留进程。

## 16. 主要风险与控制

| 风险 | 概率/影响 | 控制 |
| --- | --- | --- |
| MCP SDK 版本漂移 | 中/高 | M0 隔离探针、精确 pin、真实 Host 测试 |
| 连接到错误 backend | 中/高 | project root + runtime revision + API version 身份校验 |
| session 热路径并发修改 | 当前/高 | 等待现有 claim 释放或明确协调，避免重叠写 |
| 调用方提权 | 高/高 | 服务端权限交集、默认只读、禁止单次请求提权 |
| 团队 Agent 被发现或按 ID 直调 | 中/高 | active Team membership + team-agent classification 双重判定；list/start/approval/reconcile 复用 |
| 审批能力越界 | 中/高 | task owner、非团队资格、config revision、capability 重验；`acceptAlways` 单独授权 |
| 自动审批残留 | 中/高 | negative tests + 删除 adapter 自动处理逻辑，只保留显式决策 |
| 取消只停等待方 | 高/高 | actual stop acknowledgement；失败不伪造终态 |
| Host 崩溃留下无限任务 | 中/高 | 有界 lease、heartbeat、expiry 复用 cancel 路径 |
| 外部任务污染会话 UI | 中/中 | hidden kind + active conversation 不变量测试 |
| Prompt 注入/数据泄露 | 中/高 | 不可信输入、最小工具面、日志清洗、结果有界 |
| Windows 控制台弹窗 | 中/高 | shared no-console 路径 + 桌面实测 |
| Host 发现成功但执行失败 | 高/中 | M5 强制真实任务、取消和失败场景验收 |

## 17. Definition of Done

只有同时满足以下条件才可以宣称“Vibelution MCP 首版完成”：

- [ ] 使用官方 SDK v2，legacy/modern stdio 兼容矩阵与真实 Host 握手通过。
- [ ] MCP adapter 不直接导入或调用有写副作用的 backend service。
- [ ] backend 为唯一写入者，任务可在 adapter 重启后查询。
- [ ] 五个工具契约稳定，输入输出有 schema、有界且可诊断；不支持 Tasks 的 Host 也能完整闭环。
- [ ] 只有非团队 Agent 可发现和启动；active team 普通成员、团队专用 Agent 与猜测 ID 均被服务端拒绝。
- [ ] 默认 `read_only`，服务端权限上限不可被调用方突破。
- [ ] 不存在自动接受审批的外部路径；任务 owner 可以显式审批，其他主体/团队任务不能审批。
- [ ] `acceptAlways` 只有在 `approval.persist`、Agent policy 和 config revision 同时允许时生效并留下审计证据。
- [ ] cancel/timeout 能停止实际执行并到达可信终态。
- [ ] graceful shutdown 和异常断开均受 lease 管理，不产生无限运行任务。
- [ ] 外部任务使用隐藏会话，不改变 active conversation。
- [ ] backend 身份或版本不匹配时 fail closed。
- [ ] Windows 全链路无可见控制台、无孤儿进程。
- [ ] Codex 端到端验收记录完整，source/runtime/config 一致。
- [ ] Host 支持 Tasks 时原生投影通过；不支持时能力边界已记录且不影响五工具闭环。
- [ ] 运维文档包含启用、禁用、诊断、回滚和兼容边界。
- [ ] Git claim、测试证据、runtime refresh、version impact 和遗留项均已关闭记录。

## 18. 延后项

以下内容应在首版稳定后单独规划：

- 多轮任务的显式 `continue_project_agent_task` 输入协议。
- MCP 远程 transport、远程身份认证和多用户租户隔离。
- 外部任务管理 VUI、审批 VUI 的专用视图。
- MCP Resources 或 Apps 扩展，以及把 Agent catalog 镜像为 Resource 的 Host 体验优化。
- 对 MCP Tasks 的强依赖、Tasks 专属交互或脱离五工具兼容面的能力；首版仅做协商可选投影。
- Host 主动推送进度通知，而不是轮询。
- 跨设备/跨节点 Agent 调用和员工权限映射。
- 外部任务的独立保留、导出和清理策略。

## 19. 实施建议

推荐按 M0 → M1 → M2 → M3 → M4 → M5 推进，不从“先把 MCP 注册进 Codex”开始。首个开发任务应只建立真实 stdio/SDK 双时代兼容契约和失败测试；它不触及 session 热路径，可以在当前会话收敛工作完成前独立推进。M1 必须先落唯一的非团队 exposure policy，再创建任何外部 session；开始前重新执行 coordination preflight，并确认 `conversation-turn-item-convergence` 已释放相关路径。

版本影响建议：在功能保持 disabled 时按内部新增能力处理；正式对用户启用时视为一个新的本地集成功能，更新对应版本说明和 operator 配置文档。Launcher/runtime refresh 在纯规划阶段不需要；实现依赖、route 或运行入口变化后，按每个任务的实际触面重新判断。

下一步建议：完成本计划自检后，从 M0“官方 SDK v2、legacy/modern 协议与 Codex Host 兼容探针”开始实施。
