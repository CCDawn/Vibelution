# Vibelution MCP 受管 Agent 网关部署与调用指南

> **Document Status:** Current operational contract
> **Gateway Status:** `PLANNED_NOT_DEPLOYABLE`
> **Guide Version:** `0.1.0`
> **Canonical MCP Name:** `vibelution`
> **Canonical Resource URI:** `vibelution://guide/mcp-managed-agent-gateway`
> **Target stdio Entry:** `<project-root>\.venv\Scripts\python.exe <project-root>\scripts\project_agent_tool.py mcp --project-root <project-root>`
> **Implementation Plan:** [`../archive/plans/2026-08-09/vibelution-mcp-managed-agent-gateway-development-plan.md`](../archive/plans/2026-08-09/vibelution-mcp-managed-agent-gateway-development-plan.md)

本文是其他 Coding Agent、MCP Host 和本机操作者部署、发现、调用 Vibelution MCP 的唯一操作指南。索引文件只链接本文，不复制部署命令或工具语义。

## 1. Agent 首次接入必须先做什么

### 1.1 在 Vibelution 仓库内工作

从根 `AGENTS.md` 或 `docs/README.md` 进入本文，先读取顶部 `Gateway Status`：

- `PLANNED_NOT_DEPLOYABLE`：停止注册和调用；只能进行计划、实现或测试工作。
- `DEVELOPMENT_ONLY`：只允许隔离测试配置，不得写入用户持久 Host 配置。
- `DEPLOYABLE`：完成下文 readiness check 后可以注册。
- `DISABLED`：停止新任务，仅允许诊断、查询和受管取消。

当前状态是 `PLANNED_NOT_DEPLOYABLE`。现有 `core/external_agent/mcp_stdio_server.py` 是不符合正式协议与审批边界的历史原型，**不得部署或注册到 Host**。

### 1.2 已连接到 MCP Server

支持 Resources 的 Host 应在首次工具调用前：

1. 通过 `resources/list` 查找 `vibelution://guide/mcp-managed-agent-gateway`。
2. 通过 `resources/read` 读取该 Markdown Resource。
3. 读取 server instructions 中的最短调用顺序和安全边界。
4. 再执行 `list_project_agents → start_project_agent_task → get_project_agent_task`。

Server 必须在 legacy `initialize.result.instructions` 与 modern `server/discover.result.instructions` 中提供同一条短指引：

```text
Before the first tool call, read vibelution://guide/mcp-managed-agent-gateway.
Only non-team Agents are externally callable. Use list → start → get;
resolve only approvals belonging to your task, and cancel through the managed task API.
```

MCP 规范允许 Host 自行决定是否自动把 Resource 注入模型上下文，因此不能只依赖 Resource。五个工具的 description 必须包含指南 URI 与版本，`list_project_agents` 的结构化结果还必须返回 `guideUri` 和 `guideVersion`，作为降级发现入口。

## 2. 这个 MCP 做什么

Vibelution MCP 是本机 stdio 受管 Agent 网关，让外部 Host 调用项目中的**非团队 Agent**：

```text
MCP Host
  → 官方 SDK stdio adapter
  → 受认证的 Vibelution backend
  → 非团队 Agent + 隐藏任务会话
```

它不是通用进程启动器，也不是第二套会话系统：

- backend 是 Agent、Session、Turn、审批和任务状态的唯一写入者。
- active team 成员及团队专用 Agent 不可发现、不可按 ID 直调、不可通过 MCP 审批。
- MCP 可以显式处理自己创建任务的审批，但不会静默自动批准。
- 外部任务使用隐藏会话，不改变 Chat、Teams 或 Terminal 当前会话。

## 3. 部署前置条件

只有在 `Gateway Status=DEPLOYABLE` 时执行本节。

1. 用户已授权写入目标 Host 的 MCP 配置。
2. 使用 Vibelution 项目根和项目虚拟环境，不依赖全局 Python/PATH。
3. Launcher、backend、adapter 来自同一 project root 和 source revision。
4. `scripts/project_agent_tool.py self-check --json` 已由实现提供并返回 `deployable=true`。
5. M0-M5 自动化测试和真实 Host 验收已通过。
6. Windows Host 启动 stdio 子进程不会弹出可见控制台。

目标 readiness 输出至少包含：

```json
{
  "status": "ready",
  "deployable": true,
  "sourceRevision": "git-sha",
  "projectRoot": "absolute-path",
  "backend": "healthy",
  "protocolEras": ["legacy", "modern"],
  "guideUri": "vibelution://guide/mcp-managed-agent-gateway",
  "guideVersion": "0.1.0",
  "tools": [
    "list_project_agents",
    "start_project_agent_task",
    "get_project_agent_task",
    "resolve_project_agent_approval",
    "cancel_project_agent_task"
  ]
}
```

任一字段缺失、`deployable=false`、backend/source mismatch 或输出无法解析时均停止部署，不得回退到历史 MCP 原型。

## 4. Codex 本机部署步骤

以下命令是实施必须维持稳定的目标入口；当前 Gateway 状态下不要执行注册。

### 4.1 解析项目入口

```powershell
$mcpProjectRoot = (Resolve-Path 'C:\path\to\Vibelution').Path
$mcpPython = Join-Path $mcpProjectRoot '.venv\Scripts\python.exe'
$mcpEntry = Join-Path $mcpProjectRoot 'scripts\project_agent_tool.py'
$mcpLauncher = Join-Path $env:LOCALAPPDATA 'Vibelution\Launcher\VibelutionLauncher.exe'

Test-Path -LiteralPath $mcpPython
Test-Path -LiteralPath $mcpEntry
Test-Path -LiteralPath $mcpLauncher
```

三个结果必须全部为 `True`。不要把 `$HOME`、`$CODEX_HOME` 或系统 Python 改成项目路径。

### 4.2 启动受管 backend 并自检

```powershell
& $mcpLauncher --project $mcpProjectRoot start
& $mcpPython $mcpEntry self-check --project-root $mcpProjectRoot --json
```

如果 Launcher 报告：

```text
有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。
```

保持现场并等待，不使用 `taskkill`、裸 PowerShell lifecycle 或第二套 backend 绕过 active-work guard。

### 4.3 检查现有 Codex 注册

```powershell
codex mcp get vibelution
```

- 不存在：可以继续注册。
- 已存在且命令完全一致：不要重复注册，直接进入验证。
- 已存在但命令、项目根或解释器不同：停止并向用户报告；不要自动覆盖或删除。

### 4.4 注册 stdio Server

```powershell
codex mcp add vibelution -- $mcpPython $mcpEntry mcp --project-root $mcpProjectRoot
codex mcp get vibelution
codex mcp list
```

不要把 secret、backend token 或完整 operator config 写入命令行和 Host 配置。adapter 通过受管 runtime descriptor 获取本地 backend 身份与认证材料。

### 4.5 其他兼容 Host

只有该 Host 已在兼容矩阵中通过真实验收时，才使用其 stdio 配置。通用结构为：

```json
{
  "mcpServers": {
    "vibelution": {
      "command": "<project-root>\\.venv\\Scripts\\python.exe",
      "args": [
        "<project-root>\\scripts\\project_agent_tool.py",
        "mcp",
        "--project-root",
        "<project-root>"
      ]
    }
  }
}
```

不要假设“支持 MCP”就代表协议时代、Resources、Tasks、取消和 Windows 退出行为已经兼容。

## 5. 自动发现契约

Server 必须暴露以下固定 Resource：

```json
{
  "uri": "vibelution://guide/mcp-managed-agent-gateway",
  "name": "mcp-managed-agent-gateway-guide",
  "title": "Vibelution MCP Managed Agent Gateway Guide",
  "description": "Read before deploying or calling the Vibelution managed Agent gateway.",
  "mimeType": "text/markdown",
  "annotations": {
    "audience": ["assistant", "user"],
    "priority": 1.0
  }
}
```

实现约束：

- `resources/read` 只读取仓库中这一个 allowlisted 权威文件，不接受任意文件路径或 URI template。
- 返回内容必须对应 server 当前 `sourceRevision`；运行时旧于文档时 fail closed，不把新指南用于旧 server。
- legacy `initialize` 与 modern `server/discover` 都声明 `resources` capability 和同一 instructions。
- Host 不支持 Resources 时，工具 description 和结构化结果中的 `guideUri`/`guideVersion` 仍能引导调用 Agent。
- 指南变化时同步更新 `Guide Version`、Resource `lastModified` 和相关契约测试。

## 6. 五个工具的标准调用顺序

### 6.1 发现非团队 Agent

```json
{
  "name": "list_project_agents",
  "arguments": {
    "limit": 50
  }
}
```

只使用返回结果中的 `agentId`。不要从 Teams、Session、文件或历史日志中猜测 Agent ID。

### 6.2 创建异步任务

```json
{
  "name": "start_project_agent_task",
  "arguments": {
    "agent_id": "agent-from-list",
    "task": "明确、有界、可验证的任务描述",
    "permission_profile": "read_only",
    "client_request_id": "host-generated-idempotency-key",
    "title": "短标题"
  }
}
```

保存返回的 `taskId`。不得请求任意 backend URL、project root、session ID 或团队 Agent。

### 6.3 查询任务

```json
{
  "name": "get_project_agent_task",
  "arguments": {
    "task_id": "opaque-task-id"
  }
}
```

尊重返回的 `pollAfterMs`，不要高频轮询。终态前持续保存同一不透明 `taskId`，不要转换成内部 Session/Turn ID。

### 6.4 显式处理审批

当状态为 `awaiting_approval` 时，只处理 `pendingApprovals` 中属于当前任务的 ID：

```json
{
  "name": "resolve_project_agent_approval",
  "arguments": {
    "task_id": "opaque-task-id",
    "approval_id": "opaque-approval-id",
    "decision": "accept",
    "expected_revision": "revision-from-get",
    "reason": "short-auditable-reason"
  }
}
```

| Decision | 作用 | 额外边界 |
| --- | --- | --- |
| `accept` | 仅批准当前请求 | 推荐默认 |
| `acceptForSession` | 批准当前隐藏任务会话内同类请求 | 不跨任务 |
| `acceptAlways` | 写入非团队 Agent 持久 ToolPolicy | 必须有 `approval.persist` |
| `decline` | 拒绝当前工具请求 | Agent 可按业务语义继续或失败 |
| `cancel` | 取消审批并进入任务停止路径 | 等待真实停止确认 |

禁止自动接受全部 pending approvals。相同决策可以安全重试；不同决策冲突时重新 `get`，不要覆盖已有决定。

### 6.5 取消任务

```json
{
  "name": "cancel_project_agent_task",
  "arguments": {
    "task_id": "opaque-task-id"
  }
}
```

`cancelling` 和 `stop_unconfirmed` 都不是已停止。继续按 `pollAfterMs` 查询，直到可信终态；不要把 JSON-RPC `notifications/cancelled` 当作后台任务取消。

## 7. 状态处理

| 状态 | 调用 Agent 动作 |
| --- | --- |
| `queued` / `running` | 等待 `pollAfterMs` 后查询 |
| `awaiting_approval` | 展示清洗摘要；按授权显式决定，或保持等待 |
| `cancelling` | 等待实际执行器确认 |
| `stop_unconfirmed` | 报告降级状态，继续有界查询，不宣称完成 |
| `succeeded` | 使用有界结构化结果 |
| `failed` | 读取稳定错误码，判断是否可重试新任务 |
| `cancelled` / `timed_out` | 终止轮询并报告原因 |

Host 声明 `io.modelcontextprotocol/tasks` 时，可以接收原生 Task handle 并使用 `tasks/get`/`tasks/cancel`；未声明时始终使用上述五工具兼容流程。

## 8. 常见错误与恢复

| 错误/现象 | 处理 |
| --- | --- |
| `GATEWAY_NOT_READY` | 检查本文状态和 `self-check`；不得注册历史原型 |
| `BACKEND_UNAVAILABLE` | 只通过 Launcher 检查受管 backend；不启动第二套服务 |
| `RUNTIME_IDENTITY_MISMATCH` | 停止调用，核对 project root/source revision；不忽略 |
| `AGENT_NOT_FOUND` | 重新调用 `list_project_agents`；该错误也用于隐藏团队 Agent |
| `APPROVAL_FORBIDDEN` | 不提权；重新读取任务、调用主体和审批 capability |
| `APPROVAL_CONFLICT` | 重新查询任务，接受已存在决策或报告冲突 |
| `STOP_UNCONFIRMED` | 继续有界查询并保留告警，不伪造 cancelled |
| Host 只发现工具但不能执行 | discovery 不是端到端证据；检查 backend、身份和真实 tool call |
| 出现 `cmd.exe`/PowerShell/Terminal 弹窗 | 立即停用该注册并记录桌面证据；不得作为可发布状态 |

## 9. 部署验收清单

- [ ] 顶部 `Gateway Status=DEPLOYABLE`。
- [ ] `self-check --json` 返回 `deployable=true`，project root/source revision 与 backend 一致。
- [ ] Host 能看到 server instructions。
- [ ] `resources/list` 能发现固定指南，`resources/read` 内容与本文件版本一致。
- [ ] Host 不支持 Resources 时，工具描述仍给出 guide URI 和最短调用顺序。
- [ ] 只发现非团队 Agent；团队成员按猜测 ID 调用也失败。
- [ ] `list → start → get` 完成一次真实任务。
- [ ] 完成一次显式 `accept`，并验证没有自动审批。
- [ ] 完成一次真实取消，后端执行已停止。
- [ ] 普通会话列表和当前工作台会话不变。
- [ ] Host 退出后没有孤儿进程和可见控制台。

只有以上项目都有当前 source/runtime/config 证据时，调用 Agent 才能报告部署完成。

## 10. 禁止事项

- 不注册 `core/external_agent/mcp_stdio_server.py` 历史原型。
- 不绕过 backend client 直接导入 Session、Turn 或审批写 service。
- 不暴露或猜测 active team 成员和团队专用 Agent。
- 不自动批准 pending approvals。
- 不把 `clientInfo` 当认证身份。
- 不向 Host 配置写 secret、token 或完整 operator config。
- 不自动覆盖、删除其他 MCP 注册；`codex mcp remove vibelution` 需要用户明确授权。
- 不把 `tools/list` 成功当作部署完成。

## 11. 维护规则

以下任一契约变化时，同一变更必须更新本文、运行时 Resource、server instructions 和测试：

- stdio 入口或 Host 注册命令。
- 五个工具的名称、参数、返回或审批语义。
- 非团队 Agent 的资格判定。
- protocol era、Resources 或 Tasks capability。
- Launcher/backend 身份、诊断或回滚步骤。

本文进入 `DEPLOYABLE` 前，M4 必须把所有目标命令替换为真实可执行命令并逐条演练；M5 必须由真实 Codex Host 从自动发现指南开始完成完整调用，而不是由实现者跳过指南直接调用。

协议依据：[MCP Resources](https://modelcontextprotocol.io/specification/draft/server/resources)、[MCP Discovery](https://modelcontextprotocol.io/specification/draft/server/discover)、[MCP Versioning](https://modelcontextprotocol.io/specification/draft/basic/versioning)。
