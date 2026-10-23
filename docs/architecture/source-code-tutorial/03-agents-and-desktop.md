[← 上一部分](02-data-and-rag.md) · [教程目录](README.md) · [下一部分 →](04-modules-and-learning.md)

# 多智能体、MCP、Skill 与桌面

## 11. 多智能体如何交互：不是把几个 Prompt 拼起来

### 11.1 先区分四种协作路径

| 路径 | 适合场景 | 核心代码 | 记录与执行特点 |
| --- | --- | --- | --- |
| 会话定向消息 | A 把任务/资料发给 B 的指定对话 | `tools/agent_message_tools.py` | 正文归目标 Session 历史；inbox 只保留索引/投递信息 |
| 项目 Agent Bus | 项目范围的定向、提及、广播等消息 | `project_agent_bus_service.py` + Agent Kernel | 解析目标与来源，形成事件、投递及关联 ID |
| 群聊讨论 | 多成员按轮次/调度规则讨论 | `chat_room_service.py`、`core/chatroom/` | 群聊有自己的组织与时间线；成员执行仍有明确运行上下文 |
| 多步骤工作流 | 固定角色按步骤产出、审核、交接 | generic/research workflow modules | 冻结绑定、持久任务、产物验证、失败/恢复与下一步准入 |

此外 `spawn_agent_tool` / `send_message_tool` 提供聚焦子代理能力：本地 `tools/agent_tools.py` 中仍有子进程执行、地址/子会话登记、超时取消与继续执行逻辑。它和团队里常驻的 Agent、面向具体 Session 的消息工具不能混为同一个 API。

### 11.2 Agent 的身份与能力从哪里来

`agent_directory_service.py` 及其 pack 管理 AgentInstance。成员在 Team 中出现，并不表示 Team 复制了一份模型/Prompt/权限配置；当前团队成员关系是 role → agentId，实际配置仍以 AgentInstance 为准。

可以把它理解成：Team 是项目通讯录与组织关系；Agent 是员工档案与能力配置；Session 是一项具体任务的工作记录。只在团队画布画一条线，不等于给某个 Agent 增加了写文件权限，也不必然让它立即运行。

源码定位：[core/web/services/agent_directory/README.md](../../../core/web/services/agent_directory/README.md)；[core/web/services/team/README.md](../../../core/web/services/team/README.md)；[core/web/services/team_workflow/research_runtime/README.md](../../../core/web/services/team_workflow/research_runtime/README.md)。

### 11.3 会话定向消息：A 让 B 查一个问题

真实工具的关键参数是 `target_session`，可附加 `target_agent` 做归属校验。只知道“B 这个人”不总能定位“B 的哪一个任务窗口”。一名 Agent 同时可能在多个 Session 工作，发错对话会污染任务上下文。

```text
A 的模型决定使用 agent_message_tool
  → tools/agent_message_tools.py
  → 确认当前 source agent/session
  → 解析指定 target_session 与可选 target_agent
  → 组织/权限/目标状态检查
  → 目标 Session 收到消息；正文进入其 canonical 历史
  → wake_target 允许且目标空闲时唤醒
  → B 按自己的模型、Prompt、ToolPolicy 执行
  → 结果保存在 B 的 Session
```

当前工具明确说明：目标正忙时不会直接打断对方，可能返回 `wakeStatus=skipped_busy`、`historyStatus=deferred`。**投递成功、正文落库、目标已开始、任务已完成是四种状态**，不能都显示成一句“已完成”。

调用返回 messageId、targetSessionId、historyStatus、inboxStatus 等投递信息。接收者是否再回复 A，要看具体任务与授权，不能默认所有消息都自动双向循环，否则容易互相唤醒不停止。

源码定位：[tools/agent_message_tools.py · agent_message_tool](../../../tools/agent_message_tools.py#L15)；[core/web/services/session/agent_sessions.py](../../../core/web/services/session/agent_sessions.py)。

### 11.4 项目消息总线与 Agent Kernel

`send_project_agent_bus_message()` 校验正文、目标范围、interrupt 模式，解析显式目标与提及，然后调用 `_submit_bus_message_to_kernel()`。Kernel adapter 构造带来源、发送者、接收者、correlation id、source ref 的事件，交给 Kernel。

```text
project_agent_bus_service
  → core/agent_kernel/adapters.py：构造/提交消息事件
  → core/agent_kernel/service.py：Event → Task → Execution → Outcome
  → 目标 inbox / native session 执行适配
  → 投递状态、回执、关联 ID
  → Bus 自身事件投影与界面时间线
```

Kernel 在这里是应用级调度与事件模型，不是操作系统内核。`store.py` 使用 JSONL 领域记录；`source_authority.py` 管来源引用和投影编辑契约。它有自己的任务/事件事实，但不能据此宣称它取代了所有 native Session 的对话 Journal。两者记录的是不同层次的事实。

源码定位：[core/web/services/project_agent_bus_service.py · send_project_agent_bus_message](../../../core/web/services/project_agent_bus_service.py#L57)；[core/agent_kernel/adapters.py](../../../core/agent_kernel/adapters.py)；[core/agent_kernel/service.py](../../../core/agent_kernel/service.py)；[core/agent_kernel/store.py](../../../core/agent_kernel/store.py)。

### 11.5 群聊如何决定谁发言

`core/chatroom/scheduler.py` 声明 `ChatRoomScheduler` 协议，并提供轮流等调度实现。调度器根据成员、主题、历史和配置返回本轮发言者；`chat_room_service.py` 再协调运行、流式捕获、持久状态与时间线。

群聊不是让每个 Agent 无限制监听并自动抢话。它有发言人数/顺序、启用状态、讨论上下文等限制。`context_payload.py`、`context_runtime.py`、`context_checkpoint.py` 管讨论上下文和摘要轮转；`timeline.py` 管有序时间线。

还要避免死锁：room、team、chat-state 这些锁不应互相嵌套做阻塞工作。当前 `chat_room_service.py` 开头专门写了锁顺序约束。理解这个设计后，就知道“在保存群聊锁里面顺便启动一个 Session”可能让系统卡住。

源码定位：[core/chatroom/scheduler.py](../../../core/chatroom/scheduler.py)；[core/web/services/chat_room_service.py](../../../core/web/services/chat_room_service.py)；[core/web/services/chat_room_stream_capture.py](../../../core/web/services/chat_room_stream_capture.py)。

### 11.6 子代理和子会话有什么区别

`tools/agent_tools.py::spawn_agent()` 的聚焦执行路径可启动受控子进程，登记子运行地址、继承受约束的上下文，跟踪输出与超时，收尾时注销和回收；某些路径可以快速完成或复用已有执行，因此不能说每次调用都一定生成相同数量的 OS 进程。

`tools/session_child_tools.py` 则提供创建/查询子会话等会话组织能力。子会话可以承担长期分支工作；有 childSessionId 不必然等于一个独立常驻模型进程。`core/orchestration/subagent_address.py` 等帮助把子运行与可定位的记录关联起来。

源码定位：[tools/agent_tools.py · spawn_agent](../../../tools/agent_tools.py#L842)；[tools/agent_tools.py · continue_subagent](../../../tools/agent_tools.py#L794)；[tools/session_child_tools.py](../../../tools/session_child_tools.py)；[core/orchestration/subagent_address.py](../../../core/orchestration/subagent_address.py)。

### 11.7 通用工作流与科研工作流

**通用工作流**在 `services/team_workflow/generic/`：用户定义步骤，显式启动 run，保存步骤输入、执行者、原生 Session/Turn 引用及回执，按顺序推进；已分配的输出可以由 Agent 执行，未分配输出有对应传递语义。读取列表不应暗中启动任务。

**科研工作流**更复杂：`core/research/workflow/` 定义阶段、节点、handoff、Ledger、checkpoint 等；`services/team_workflow/research_runtime/` 组装正式执行。其核心链路是：

```text
WorkflowCommandService 接受命令
  → Ledger transaction + graph_dispatch outbox
  → Graph Worker invoke/resume LangGraph
  → PendingAction interrupt
  → adapter_dispatch outbox
  → Adapter Worker
       → 检查绑定/预算/可执行性
       → 创建原生任务与 Session Turn
       → 回读并验证业务产物与模型调用回执
  → Ledger 写 receipt / handoff
  → graph resume → 下一节点 readiness 检查
```

其中 LangGraph checkpoint 保存“流程运行到哪里”，Workflow Ledger 保存“工作流发生了什么”，领域 store 保存“业务产物是什么”，Session Journal 保存“Agent 那一轮做了什么”。这四种存储有关联，但不能相互替代。

例如模型写“实验成功”，Session Turn 也正常结束，仍不代表工作流节点已成功：还要看关联产物和回执验证。任务执行成功与业务目标成功是不同条件。

源码定位：[core/web/services/team_workflow/generic/README.md](../../../core/web/services/team_workflow/generic/README.md)；[core/research/workflow/ledger](../../../core/research/workflow/ledger)；[core/web/services/team_workflow/research_runtime/README.md](../../../core/web/services/team_workflow/research_runtime/README.md)。

### 11.8 并发并不是免费性能

多个 Agent 同时运行会消耗 Provider 并发额度、token、线程/进程、磁盘 I/O，并争用共享文件。代码里有 executor、gate、锁、reservation、预算和取消，不是为了把事情复杂化，而是防止重复运行、孤儿进程和失控成本。

学习时先做“两个 Agent、一个明确任务、一个可核实产物”的小实验，比一开始配置十几个人持续互聊更容易看懂状态转换。

## 12. MCP：本项目实际在哪些地方使用

### 12.1 MCP 的角色

MCP 是工具/资源调用协议。它可以让一个客户端发现服务端工具，用结构化参数调用并拿到结果。它不负责替你训练模型，也不自动授予任意本地执行权限。Agent 内部的 tool calling 是模型/执行器机制；MCP 是连接工具或能力的一种协议，两者相关但不等同。

### 12.2 主要实现是“向外提供受管 Agent 网关”

当前最明确的通用 MCP 入口是 `core/external_agent/mcp_server.py`，使用官方 MCP Python SDK。它通过 stdio 服务外部客户端，再由 `backend_client.py` 调用本地 loopback API，而不是在协议进程里直接 import 业务写服务。

```text
外部 MCP 客户端（例如支持 MCP 的开发工具）
   ↔ stdio JSON-RPC / MCP
core/external_agent/mcp_server.py
   → backend_client.py
   → 受控本机 HTTP API
   → core/web/services/external_agent/
   → 原生 Agent / Session / Turn
```

固定五个工具名来自 `contracts.py`：

| 工具 | 含义 |
| --- | --- |
| `list_project_agents` | 列出外部可调用的合格 Agent |
| `start_project_agent_task` | 创建受管任务，带明确权限配置和幂等身份 |
| `get_project_agent_task` | 读取有归属的任务状态和结果投影 |
| `resolve_project_agent_approval` | 只处理该任务拥有的审批 |
| `cancel_project_agent_task` | 通过正式任务 API 取消 |

还暴露引导 Resource：`vibelution://guide/mcp-managed-agent-gateway`。server instructions 要求先读说明，再按 list → start → get 使用。

源码定位：[core/external_agent/mcp_server.py · build_server](../../../core/external_agent/mcp_server.py#L92)；[core/external_agent/backend_client.py](../../../core/external_agent/backend_client.py)；[core/external_agent/contracts.py](../../../core/external_agent/contracts.py)。

### 12.3 默认权限与数据归属

`[external_agent_gateway]` 操作者策略默认关闭并采用只读限制；外部可调用资格限定非 Team Agent，具体以 `policy.py` 为准。网关 store 保存任务归属、lease、权限和 Session/Turn 引用等有界投影，**不另存一份完整 transcript**。

外部调用可能触发已有原生审批；不能用 MCP 直接取消别人的任务、处理无归属审批或绕过 ToolPolicy。MCP 暴露的是受管能力，并不意味着把整个本地工作台变成无需验证的远程命令执行器。

源码定位：[core/web/services/external_agent/README.md](../../../core/web/services/external_agent/README.md)；[core/web/services/external_agent/policy.py](../../../core/web/services/external_agent/policy.py)；[docs/agents/mcp-managed-agent-gateway.md](../../../docs/agents/mcp-managed-agent-gateway.md)。

### 12.4 另一条 MCP 使用：受控桌面驱动

`core/infrastructure/cua_driver_client.py` 是面向固定 CUA driver 的有界 JSON-lines MCP 传输，含服务端身份校验、消息大小、并发、超时、取消与关闭语义。这是一条专用的驱动链，而不是普通 Agent 任意添加任意 MCP Server 就能操作整个桌面的通用后门。

因此学习或写课程报告时，可以说项目具有 MCP 网关和特定 MCP 驱动集成；不要写成“所有内置工具都通过一个万能 MCP 插件管理器调用”。当前源码没有支持这一概括。

源码定位：[core/infrastructure/cua_driver_client.py](../../../core/infrastructure/cua_driver_client.py)。

## 13. Skill 与 Prompt：知识、方法、权限的边界

### 13.1 Skill 是一份方法说明，不是新的模型

本地技能常见结构是某个目录下的 `SKILL.md`，里面用 frontmatter 声明名字、描述，再写工作步骤。`core/chat/skill_registry.py` 默认发现用户主目录下 `.codex/skills` 和 `.agents/skills`，解析别名、内容与内容哈希。

当聊天斜杠命令解析命中技能时，系统可生成 `Slash Skill Context`，包含命令、技能名、路径、hash、参数和受限长度的技能内容，然后作为本轮运行上下文使用。它明确要求保留用户消息为用户请求，不把技能上下文伪装成用户亲自写下的话。

```text
/某技能 参数
  → core/chat/slash_commands.py
  → skill_registry.resolve_skill()
  → build_skill_runtime_context()
  → Session 的命令/上下文路径
  → Prompt/message assembly
  → 模型遵循方法，并在已有权限内调用工具
```

源码定位：[core/chat/slash_commands.py](../../../core/chat/slash_commands.py)；[core/chat/skill_registry.py · default_skill_roots](../../../core/chat/skill_registry.py#L27)；[core/chat/skill_registry.py · build_skill_runtime_context](../../../core/chat/skill_registry.py#L56)；[core/context/skill_contract.py](../../../core/context/skill_contract.py)。

### 13.2 “技能页面”和“外部技能记忆库”是两条路径

| 能力 | 文件 | 数据来源 | 作用 |
| --- | --- | --- | --- |
| 本机 Skill 浏览与详情 | `skill_service.py`、`routes/skills.py` | 本机 `.codex/skills`、`.agents/skills` 等发现根 | 有界只读预览、列出斜杠命令 |
| 外部 skills memory library | `skill_library_service.py`、`tools/skill_library_tools.py` | 工作区外部记忆技能索引 | 按 Actor/范围搜索已索引技能材料 |

`skill_library_search_tool` 明确不回退扫描 `.codex/skills` 或 plugin cache。看到两者名字都有 skill，不要把一份库的结果当另一份已经加载/执行了。

有文件、有索引、界面可预览、某一轮真的使用了该技能，也是四种不同状态。判断是否应用，应看命令解析、runtime context 与该轮记录，而不是只看硬盘上存在 SKILL.md。

源码定位：[core/web/services/skill_service.py](../../../core/web/services/skill_service.py)；[core/web/services/skill_library_service.py](../../../core/web/services/skill_library_service.py)；[tools/skill_library_tools.py](../../../tools/skill_library_tools.py)。

### 13.3 Prompt 如何装配

`core/prompt_manager/` 负责系统提示词章节。当前三核心来源由 `core_prompt_sources.py` 定义：COMMON、SOUL、项目 AGENTS，顺序固定；还有会话/角色快照、目标、工具能力和动态运行段。

```text
受保护核心 + Agent/角色快照
   + 按能力允许的章节
   + 当前任务与工具说明
   + 有界个人记忆/运行上下文/技能
   + 历史与当前用户输入
   → token/章节预算裁决
   → 静态前缀与动态段排序
   → 模型协议投影
```

静态段稳定，有利于 Provider prompt cache；动态状态不应插到稳定前缀最前面，导致每次缓存都失效。`assembly_resolver.py` 处理能力门与预算，受保护段不能静默裁掉；`builder.py` 产出装配结果/manifest。

已有会话的有效核心快照不一定随着你改 Prompt 文件立即变化，这是为了保证执行的一致性。另有 `IDENTITY.md/USER.md/DYNAMIC.md` 工作区动态章节保留代码，但 README 明确生产默认未启用；不能把潜在能力写成每轮已自动加载。

源码定位：[core/prompt_manager/README.md](../../../core/prompt_manager/README.md)；[core/prompt_manager/core_prompt_sources.py](../../../core/prompt_manager/core_prompt_sources.py)；[core/prompt_manager/assembly_resolver.py](../../../core/prompt_manager/assembly_resolver.py)；[core/prompt_manager/builder.py](../../../core/prompt_manager/builder.py)。

### 13.4 RAG、Skill、MCP、Tool 之间的关系

| 名词 | 回答的问题 | 例子 |
| --- | --- | --- |
| Prompt | “你是谁、按什么规则理解任务？” | Agent 角色与项目纪律 |
| Skill | “这类任务建议按什么方法做？” | 调试步骤、文档写作流程 |
| RAG | “完成任务需要哪些可引用资料？” | 从正式知识库检索相关段落 |
| Tool | “程序实际可以执行哪个动作？” | 读文件、查知识、给指定会话发消息 |
| MCP | “怎样跨进程/客户端发现并调用某组能力？” | 外部客户端调用受管 Agent 网关 |
| ToolPolicy/Approval | “这次动作是否被授权？” | 是否允许写文件、启动任务或处理审批 |

它们可以串在一起：外部客户端通过 MCP 给 Agent 一个任务 → Agent 按 Skill 的方法分析 → 调用知识工具进行 RAG → 在授权范围内执行文件工具 → 结果写进 Session Journal。但没有哪一个名词可以自动代替其他层。

## 14. 桌面 EXE 与网页版的区别：从官方启动链讲起

### 14.1 桌面图标与官方入口

Windows 安装入口使用稳定位置的官方无控制台 Launcher。快捷方式的具体参数由安装脚本和安装位置确定，可沿 `scripts/windows_launcher_entry/`、桌面入口脚本和 Electron main 追踪。

```text
%LOCALAPPDATA%\Vibelution\Launcher\VibelutionLauncher.exe --project "<project-root>" start
```

EXE 负责选择和唤起正确桌面控制面；它不意味着把全部 Python、Node、模型权重和用户数据打成一个独立文件。安装细节以[Windows 安装指南](../../guides/install-windows.md)为准。

### 14.2 从双击到窗口出现

```text
Windows 桌面快捷方式 .lnk
  → 官方 VibelutionLauncher.exe 无控制台 shim
  → 按 provenance/构建新鲜度选择当前桌面代码
     ├─ 可用且匹配的 packaged Electron
     └─ 当前 checkout 的 unpackaged Electron
  → desktop/electron/src/main.ts
     ├─ 单实例/托盘/窗口/IPC/生命周期
     ├─ 检查/准备正确前端 build release
     └─ 无控制台方式启动 pythonw 工作台后端
  → FastAPI 分阶段就绪
  → Electron BrowserWindow 加载工作台 origin
  → 共用的 React 前端开始调用业务 API
```

项目内 C# 官方入口源码在 `scripts/windows_launcher_entry/VibelutionLauncher.cs`；主控制面已经迁入 Electron main。`core/launcher/` 和 Python desktop entry 仍有路径、准备、兼容与维护职责，不能因为它们存在就再另外启动一个 Python `:8765` 作为平行产品控制面。

源码定位：[scripts/windows_launcher_entry/VibelutionLauncher.cs](../../../scripts/windows_launcher_entry/VibelutionLauncher.cs)；[scripts/vibelution_desktop_entry.py](../../../scripts/vibelution_desktop_entry.py)；[desktop/electron/src/main.ts](../../../desktop/electron/src/main.ts)；[core/web/services/launcher_runtime.md](../../../core/web/services/launcher_runtime.md)；[docs/adr/0009-launcher-control-plane-lives-in-electron-main.md](../../../docs/adr/0009-launcher-control-plane-lives-in-electron-main.md)。

### 14.3 Electron 的三个安全边界

| 部分 | 可以做什么 | 对应位置 |
| --- | --- | --- |
| Main 主进程 | 创建窗口、控制进程、系统集成、处理受限 IPC | `src/main.ts`、process/lifecycle/windows 等 |
| Preload 预加载 | 通过 contextBridge 暴露一小组桥接方法 | `src/preload.ts`、`src/ipc.ts` |
| Renderer 渲染进程 | 运行 React 页面；通过桥请求允许的原生动作 | 与 Web 工作台相同的 UI |

`workbenchWindow.ts` 设置 `contextIsolation: true`、`nodeIntegration: false`、`sandbox: true`。所以页面代码不是随便 `require('fs')` 就能读所有文件。`window.vibelutionLauncher` 里有受控打开路径、外链、窗口/Launcher 等能力，main 侧还要复核来源与参数。某些方法只对特定窗口角色暴露。

源码定位：[desktop/electron/src/windows/workbenchWindow.ts · createWorkbenchWindow](../../../desktop/electron/src/windows/workbenchWindow.ts#L6)；[desktop/electron/src/preload.ts](../../../desktop/electron/src/preload.ts)；[desktop/electron/src/ipc.ts](../../../desktop/electron/src/ipc.ts)。

### 14.4 桌面和网页逐项比较

| 问题 | Electron 桌面工作台 | 浏览器工作台 |
| --- | --- | --- |
| 聊天界面是谁写的？ | 同一 React 前端为主 | 同一 React 前端 |
| 业务 API | 本机 FastAPI | 同一后端地址，前提是服务已运行 |
| 关闭页面 | 可经过桌面生命周期/后端回收策略 | 通常只是关闭标签页，不等于停止 Python 服务 |
| 托盘与窗口管理 | Electron main 提供 | 普通浏览器页没有同一原生桥 |
| 打开系统文件/显示目录 | 可走受限 preload IPC | 受浏览器权限限制，采用上传等网页方式 |
| 桌面浮窗/桌宠 | 依赖桌面窗口和对应运行支持 | 不能仅凭普通标签页拥有同样原生行为 |
| 后端未启动怎么办 | Launcher 尝试检查并启动/重建 | URL 会连不上；浏览器不能替代 Launcher |
| 模型和知识能力 | 由 Agent/后端配置决定 | 连接同一后端、同一 Actor 时大体共用 |
| 网络请求去哪里 | 云模型仍由本机后端向 Provider 发出 | 一样，不会因网页显示就自动变成云端部署 |

**网页版不等于“纯前端离线 AI”；桌面 EXE 也不等于“所有逻辑都在 EXE 内”。** 这个区分可以直接用于答辩。

### 14.5 生产前端和 Vite 开发服务

生产模式先把 TypeScript/React 构建成静态资源，由工作台固定到一个版本 release；当前项目有 `web/.vibelution-builds/release-*` 一类不可变资源目录，实际运行位置要看 health 的 serving metadata，不能只看 `web/dist/` 时间。

开发模式运行 Vite，默认前端端口 5173、后端 8000，`/api` 代理到后端；这些是默认值，可以通过项目端口解析/配置改变。Vite 是前端开发服务，不负责执行 Python Agent。仅运行 `npm run dev` 不会自动补齐全部后端与桌面生命周期。

源码定位：[web/vite.config.ts](../../../web/vite.config.ts)；[core/launcher/frontend_build.py](../../../core/launcher/frontend_build.py)；[core/web/services/serving_version.py](../../../core/web/services/serving_version.py)。

### 14.6 图标无法启动或点 × 关闭慢时，从哪里理解

图标无法启动时，先检查快捷方式的项目路径和官方 Launcher 是否存在；密钥是否正确不是这一阶段的决定因素。启动还可能需要 Node、Python、Git 运行环境和匹配构建，路径与虚拟化目录解析也会影响结果。

点 × 时桌面不只是把 HTML 隐藏：它还要协调活动任务、保存终态、停止后台及回收子进程。当前源码包含有界快速退出实现，包含 Windows Job 进程树管理、超时回收等。`native/workbench-job/job_object.c` 是真实的原生进程管理代码，不是 Python 聊天模型的一部分。

源码定位：[desktop/electron/src/process/fastWorkbenchClose.ts](../../../desktop/electron/src/process/fastWorkbenchClose.ts)；[desktop/electron/src/shutdown/shutdownCoordinator.ts](../../../desktop/electron/src/shutdown/shutdownCoordinator.ts)；[desktop/electron/native/workbench-job/job_object.c](../../../desktop/electron/native/workbench-job/job_object.c)。

### 14.7 为什么“服务未连接”时旧界面仍在

React 页面、上次查询缓存和草稿可以继续留在窗口里，而 HTTP/SSE 后端已经停止或尚未就绪。你看到人物背景和旧消息，只能证明页面资源/缓存还在，不能证明后台仍活着。

排查顺序是：启动图标/日志 → Launcher 进程与窗口 → `/api/health` 的 routesReady → 普通接口与控制令牌 → SSE → 模型 Provider。不要从“背景还显示”直接跳到“必定是模型接口坏了”。

---

[← 上一部分](02-data-and-rag.md) · [教程目录](README.md) · [下一部分 →](04-modules-and-learning.md)
