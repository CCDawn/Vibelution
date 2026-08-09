# Vibelution MCP 受管 Agent 网关部署与调用指南

> **Document Status:** Current operational contract
> **Gateway Status:** `DEPLOYABLE`
> **Guide Version:** `0.3.1`
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

当前实现已完成 M0-M5 自动化、MCP Inspector 与原生 Codex Host 隔离验收，因此状态为 `DEPLOYABLE`。这表示实现可以在 readiness check 通过后受控注册，不表示已经修改用户的 operator 配置或 Host 持久配置；这两类写入仍需当前操作者明确授权。`core/external_agent/mcp_stdio_server.py` 仅保留兼容导入，不是注册入口。

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

### 3.1 Operator 配置

权威配置是 `%USERPROFILE%\Documents\Vibelution\config\config.toml`。首次启用前先备份原文件，只修改 `[external_agent_gateway]`；不要把该配置复制到 Codex MCP 注册中。

```toml
[external_agent_gateway]
enabled = true
permission_ceiling = "read_only"
runtime_permission_ceiling = "workspace_write"
approval_persist_enabled = false
allowed_agent_ids = []
denied_agent_ids = []
max_concurrent_tasks_per_owner = 4
max_concurrent_tasks_per_agent = 1
max_task_seconds = 1800
lease_seconds = 30
```

- `enabled=false` 是默认值，也是紧急停止新任务的开关。
- `permission_ceiling` 只能缩小外部请求权限；首轮部署保持 `read_only`。
- `allowed_agent_ids` 和 `denied_agent_ids` 是 operator 附加收窄，不会让团队 Agent 变成可调用对象。
- `approval_persist_enabled=false` 时，即使 Host 请求 `acceptAlways` 也会被拒绝。
- 配置变更后只通过 Launcher 受管重启；不直接启动第二套 backend。

权限不是由 Host 单方面决定。有效权限是以下上限的交集，只能缩小，不能扩大：

```text
requested profile
  ∩ operator permission_ceiling
  ∩ Agent externalMaximumPermissionProfile
  ∩ runtime_permission_ceiling
  = effectivePermissionProfile
```

| Profile | 外部任务可用范围 | 始终禁止 |
| --- | --- | --- |
| `read_only` | 只读工具 | Team workflow、Team knowledge、跨 Session 历史、Agent 协作、写入与清理 |
| `workspace_write` | 只读 + workspace/code-quality 写工具；非只读调用仍需显式审批 | 上述团队/跨会话能力、项目回滚、删除/清理类高风险工具 |
| `full_access` | 仅表示调用方请求；仍被前三个服务端上限夹紧 | 不能绕过任何固定禁区或审批 |

外部任务统一使用 `request_approval` 语义。即使有效权限为 `workspace_write`，也不会自动接受 Tool approval；`acceptAlways` 还必须同时满足 operator `approval_persist_enabled=true`、调用主体拥有 `approval.persist`、Agent policy 允许且 config revision 未变化。

目标 readiness 输出至少包含：

```json
{
  "status": "ready",
  "deployable": true,
  "sourceRevision": "git-sha",
  "projectRoot": "absolute-path",
  "backend": "healthy",
  "serverVersion": "0.3.0",
  "protocolEras": ["legacy", "modern"],
  "guideUri": "vibelution://guide/mcp-managed-agent-gateway",
  "guideVersion": "0.3.1",
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

以下命令是已验证入口。只有用户明确授权持久 Host 配置写入，且 4.2 自检返回 `deployable=true` 时，才执行注册步骤。

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

### 4.3 解析官方原生 Codex CLI

Windows 上不要直接信任 PATH 中的 `codex`：它可能解析到其他产品的 `codex.cmd` 包装器并引入额外 `cmd.exe`/Node 进程。Codex Desktop 的原生 CLI 可按安装目录解析：

```powershell
$codexBinRoot = Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin'
$codexExe = Get-ChildItem -LiteralPath $codexBinRoot -Recurse -Filter codex.exe -File |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1 -ExpandProperty FullName

if (-not $codexExe) { throw 'Official Codex native CLI was not found.' }
& $codexExe --version
```

验收过的进程路径是原生 `codex.exe → 项目 .venv\Scripts\python.exe → project_agent_tool.py mcp`；任务所属进程树不得出现 `cmd.exe`、PowerShell、Windows Terminal、OpenConsole 或 Node 包装器。

### 4.4 检查现有 Codex 注册

```powershell
& $codexExe mcp get vibelution --json
```

- 不存在：可以继续注册。
- 已存在且命令完全一致：不要重复注册，直接进入验证。
- 已存在但命令、项目根或解释器不同：停止并向用户报告；不要自动覆盖或删除。

### 4.5 注册 stdio Server

```powershell
& $codexExe mcp add vibelution -- $mcpPython $mcpEntry mcp --project-root $mcpProjectRoot
& $codexExe mcp get vibelution --json
& $codexExe mcp list
```

不要把 secret、backend token 或完整 operator config 写入命令行和 Host 配置。adapter 通过受管 runtime descriptor 获取本地 backend 身份与认证材料。

### 4.6 隔离验证（不写持久注册）

实现者或验收 Agent 应优先使用 Codex 的 `-c` 临时配置覆盖，不修改用户级 `~/.codex/config.toml`。以下形式已在 Windows 原生 Codex CLI 上验证：

```powershell
$commandToml = $mcpPython | ConvertTo-Json -Compress
$argsToml = @($mcpEntry, 'mcp', '--project-root', $mcpProjectRoot) |
  ConvertTo-Json -Compress
$acceptancePrompt = @'
你是首次接入 Vibelution MCP 的调用 Agent。仅使用 vibelution MCP，
先依据 server instructions 与可发现 Resource 判断 readiness，
再按指南列出非团队 Agent 并完成一个只读任务。最后返回紧凑 JSON。
'@

& $codexExe exec --ephemeral --ignore-user-config --ignore-rules `
  --color never --sandbox read-only `
  -c "mcp_servers.vibelution.command=$commandToml" `
  -c "mcp_servers.vibelution.args=$argsToml" `
  -c 'mcp_servers.vibelution.enabled=true' `
  $acceptancePrompt
```

`resolve_project_agent_approval` 与 `cancel_project_agent_task` 可能同时触发 Codex Host 自身的高影响工具调用门。非交互验收可把 `--sandbox read-only` 替换为 `--approve-for-me`；Codex CLI 不允许两者同时使用。`--approve-for-me` 只通过 Host 工具调用门，backend 仍要求模型显式调用 `resolve_project_agent_approval` 并提交 `decision`、`approval_id` 与 `expected_revision`，不会变成自动审批。

临时 command、args 和 enabled 只在该进程内生效；退出后不保留 MCP 注册。实际参数仍以当前 `& $codexExe exec --help` 与 `& $codexExe mcp --help` 为准。

### 4.7 禁用与回滚

1. 将 operator 配置中的 `enabled` 改回 `false`，通过 Launcher 受管重启，阻止新任务。
2. 查询现有非终态任务；显式取消并等待真实停止确认，不能只结束 adapter 进程。
3. 只有用户明确授权删除持久注册时，才执行 `& $codexExe mcp remove vibelution`。
4. 恢复此前备份的 operator 配置，再通过 Launcher 受管重启。
5. 用 `& $codexExe mcp list`、`self-check --json`、进程树和桌面观察确认无残留 adapter、孤儿任务或可见控制台。

### 4.8 其他兼容 Host

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
  "mimeType": "text/markdown"
}
```

实现约束：

- 首版 Resource descriptor 只返回上述跨协议稳定字段；`annotations`、`_meta`、`lastModified` 等可选字段在当前 Codex Host 上未通过兼容验收，不得在缺少真实 Host 复验时重新加入。
- `resources/read` 只读取仓库中这一个 allowlisted 权威文件，不接受任意文件路径或 URI template。
- 返回内容必须对应 server 当前 `sourceRevision`；运行时旧于文档时 fail closed，不把新指南用于旧 server。
- legacy `initialize` 与 modern `server/discover` 都声明 `resources` capability 和同一 instructions。
- Host 不支持 Resources 时，工具 description 和结构化结果中的 `guideUri`/`guideVersion` 仍能引导调用 Agent。
- 指南内容或 Resource schema 变化时同步更新 `Guide Version` 和相关契约测试；只有兼容 Host 实测通过后才增加新的可选 descriptor 字段。

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

尊重返回的 `pollAfterMs`，不要高频轮询。终态前持续保存同一不透明 `taskId`，不要转换成内部 Session/Turn ID。终态在当前 adapter 连接内可重复查询；adapter 正常退出后 capability 被清理，新的连接不能仅凭旧 `taskId` 接管任务。

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

当前固定依赖 `mcp==2.0.0` 未提供 MCP Tasks extension 的服务端 API，因此本版本始终使用上述五工具兼容流程，`self-check` 明确返回 `tasksExtension=not_available_in_mcp_sdk_2.0.0`。Host 即使声明 Tasks capability，也不会获得原生 Task handle；升级 SDK 后必须先补双协商测试与真实 Host 验收，才能改变这一边界。

## 8. 常见错误与恢复

| 错误/现象 | 处理 |
| --- | --- |
| `GATEWAY_NOT_READY` | 检查本文状态和 `self-check`；不得注册历史原型 |
| `BACKEND_UNAVAILABLE` | 只通过 Launcher 检查受管 backend；不启动第二套服务 |
| `RUNTIME_IDENTITY_MISMATCH` | 停止调用，核对 project root/source revision；不忽略 |
| `BACKEND_PROTOCOL_ERROR` | 停止调用并检查 backend/adapter 版本，不按业务错误重试 |
| `AGENT_NOT_FOUND` | 重新调用 `list_project_agents`；该错误也用于隐藏团队 Agent |
| `TASK_NOT_FOUND` | 只使用当前 adapter 返回并保存的 task ID；不要猜测 Session/Turn ID |
| `TASK_CONFLICT` | 重新查询或等待已有任务；不要绕过并发与幂等门 |
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

### 9.1 2026-08-09 首版验收基线

本节记录“哪些边界已经被真实执行过”，不替代部署当时的 `self-check`：

- 依赖：Python MCP 官方 SDK `mcp==2.0.0`；MCP Inspector 使用官方 `@modelcontextprotocol/inspector` CLI。
- Host：Windows 原生 `codex.exe`，`codex-cli 0.147.0-alpha.6.5`；隔离 `-c` 配置，没有写入用户级 Codex MCP 注册。
- 身份：每次验收均要求 `self-check.sourceRevision == git rev-parse HEAD == backend.runtimeSourceRevision`；部署时必须重新满足，指南不固定可能过期的 SHA。
- 协议与发现：官方 SDK 进程测试覆盖 legacy `initialize` 与 modern `server/discover`；Inspector/Codex 均发现五个工具和唯一固定指南 Resource。Codex CLI 不展示最终协商的 wire protocol version，因此不能把 Host 版本号当作具体 era 证明。
- 隔离：外部列表只返回 A001/A005 两个非团队 Agent；猜测内部 Agent ID 返回 `AGENT_NOT_FOUND`，不创建 task/session。
- 任务：真实 Codex Host 完成只读成功、终态重复查询、显式 `accept` 后继续执行、真实取消、`full_access → workspace_write` 夹紧。
- 负向审批：错误 task capability 返回 `TASK_NOT_FOUND`；无 `approval.persist` 时 `acceptAlways` 返回 `APPROVAL_FORBIDDEN`。
- 资格撤销：运行中 Agent 加入 active Team 后任务进入 `stop_unconfirmed`，真实 Turn 停止后落为 `cancelled`；临时 Team 在移除成员后归档。
- 会话与 lease：外部 Session 为 hidden，active conversation 保持不变；强制结束 adapter 后任务经 lease 进入 `timed_out`，Turn journal 以 `turn_interrupted:stopped_by_user` 收口。
- Windows：任务所属进程树只出现原生 Codex 与 Python adapter，没有 `cmd.exe`/PowerShell/Terminal/Node 包装器；正常退出无 adapter 子进程，故障注入后的 Host 也按精确 PID 清理。
- 能力边界：SDK 2.0.0 没有服务端 MCP Tasks extension，首版只承诺五工具闭环；Agent/Session/Turn/审批/取消均走真实 backend，LLM provider 使用隔离 loopback 确定性 fixture，因此这不是外部模型厂商兼容性证明。

## 10. 禁止事项

- 不把 `core/external_agent/mcp_stdio_server.py` 兼容导入模块作为 Host 注册入口。
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

本文已按 M4/M5 完成首版命令演练与真实 Codex Host 调用。后续任何入口、权限、Host 或协议变化都必须重新降级状态并复验，不能沿用本节旧证据自动宣称兼容。

协议依据：[MCP Resources](https://modelcontextprotocol.io/specification/draft/server/resources)、[MCP Discovery](https://modelcontextprotocol.io/specification/draft/server/discover)、[MCP Versioning](https://modelcontextprotocol.io/specification/draft/basic/versioning)。
