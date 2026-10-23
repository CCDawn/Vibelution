[教程目录](README.md) · [下一部分 →](02-data-and-rag.md)

# 全栈地图与一次聊天

本文是源码阅读教程，帮助你从界面追到真实执行、存储和恢复边界。先读第 1—6 章建立主链，再读存储、协作与核心机制。版本、阅读次序和现行规范入口见[教程首页](README.md)。所有源码路径相对于仓库根；“教学伪代码”仅解释流程，不是可直接调用的产品 API。

先记住五个结论：

1. **界面是 React/TypeScript，业务后端主要是 Python/FastAPI，桌面外壳是 Electron。** Electron 主进程也是本机启动与生命周期控制面。
2. **桌面版和网页版大量复用同一套界面与业务接口。** 桌面 EXE 主要增加启动、窗口、托盘、原生集成与进程管理，并不是另外训练的一套 AI。
3. **当前核心存储不使用 MySQL。** Agent 可写主配置在 `agents.json`；SQLite 承担会话目录/控制状态与 Agent 引用/编译快照；对话正文权威仍是 JSONL Journal，正式知识也有自己的 JSON/JSONL。
4. **当前向量检索不是连接一个 MySQL 向量插件或独立 Milvus 服务。** 它在 Python 进程里使用 FastEmbed 生成向量，把可重建的索引保存为文件，并进行 BM25、余弦相似度及 RRF 混合排序。
5. **Agent、Session、Turn、工作流、模型是不同对象。** 分清它们，后面的大多数代码就容易理解。

## 1. 先建立整个系统的地图

### 1.1 按“运行在哪里”分层

| 层 | 技术与代码 | 主要任务 | 不负责什么 |
| --- | --- | --- | --- |
| 页面展示层 | `web/src/`；React、TypeScript、VUI、Tailwind | 页面、输入框、聊天消息、人物模型、画布与状态展示 | 不直接打开服务器上的 SQLite，不保管模型服务商密钥 |
| 前端通信层 | `web/src/api/` 与聊天流式传输模块 | HTTP 请求、类型契约、错误处理、控制令牌与 SSE | 不替代后端的授权和业务验证 |
| 本机业务服务 | `core/web/`；FastAPI、Pydantic | 接收请求、校验参数、调用业务服务、提供 JSON/文件/SSE | HTTP route 不应承包全部领域逻辑 |
| Agent 执行层 | `agent.py`、`core/orchestration/`、`core/llm/`、`tools/` | 组装上下文、调用模型、执行工具、继续循环、记录结果 | 模型输出的文本不直接等于操作已经成功 |
| 领域与持久化层 | `core/chat/`、`core/agent_kernel/`、`team_knowledge/`、研究工作流等 | 对话账本、协作事件、知识治理、事务与恢复 | 各类缓存和投影不能随意成为第二份事实源 |
| 桌面控制层 | `desktop/electron/`、`scripts/windows_launcher_entry/` | 启动与停止、窗口、托盘、原生能力、进程身份与构建版本 | 不取代聊天业务后端 |
| 外部系统 | 模型 API、受控 MCP 客户端、网页/行情等来源 | 提供推理或外部数据 | 不自动获得本地全部文件和工具权限 |

```text
                    你的 Windows 电脑
 ┌─────────────────────────────────────────────────────┐
 │ 浏览器标签页            Electron 的 Chromium 窗口      │
 │          └──── 共用 React 工作台 web/src ────┘         │
 │                         │ HTTP JSON / SSE             │
 │                  FastAPI / core/web                  │
 │                         │                             │
 │         Session 服务 → AgentRuntime → 工具执行器        │
 │                         │          │                  │
 │                   core/llm    本地文件/搜索/协作工具     │
 │                         │                             │
 │       SQLite 控制状态 + Journal + 正式知识/派生向量      │
 └─────────────────────────┼───────────────────────────┘
                           │ HTTPS（使用云模型时）
                       你配置的模型服务

 Electron main 另有一条控制链：启动器 → 构建检查 → Python 后端
 Electron renderer 到 main 的原生能力走受限 IPC，不与 HTTP 混为一谈。
```

这里有三种容易混淆的“服务”：FastAPI 是本机业务服务；模型 Provider 是本地或云端推理服务；Electron Launcher 是桌面生命周期控制面。工作台连接不上，不一定是 API Key 错了；可能业务后端根本没启动或仍在加载。

### 1.2 项目采用什么架构风格

它更接近**本地优先的分层模块化应用**：一个较大的 Python 后端里包含很多领域模块，React 负责交互，Electron 管理桌面。源码里的多个 `service`、`bus`、`kernel` 并不意味着全部都是独立部署的微服务。许多调用是同一 Python 进程里的函数调用；部分工作由线程、子进程或独立实例执行。

另一个重要特点是**事实源与读取投影分开**：例如 Journal 记录真正发生的对话事件，UI DTO、会话预览、流式草稿从它派生。研究工作流进一步使用 Ledger、Outbox 和回执。可以借用事件驱动、事件溯源、读写分离这些概念理解，但不要推断整个项目统一使用某个完整的 CQRS 框架。

### 1.3 先认识这些对象

| 概念 | 通俗解释 | 典型身份或代码 |
| --- | --- | --- |
| Provider | 模型供应商或兼容 API 服务端 | `config/`、`core/llm/adapters.py` |
| Model/Profile | 一项模型及其协议、预算、超时等配置 | `config/models.py`、`core/llm/agent_runtime.py` |
| AgentInstance | 一个可配置的“员工”：身份、角色、模型绑定、提示词、工具策略、记忆策略 | `agent_directory_service.py`、`agent_directory/` |
| Session | 该员工的一段具体工作对话 | `session_service.py`、`session/` |
| Turn | 一次被后端接受的任务轮次，可以含多次模型调用和工具调用 | `turnId`、Journal、`worker.py` |
| Tool call | 模型提出一个结构化操作，由程序验证后执行 | `ToolLifecycleBridge` → `ToolExecutor` |
| Team | 多个 Agent 的成员和职责关系 | `team_service.py`、`team/` |
| Chat room | 多成员讨论的组织与时间线 | `chat_room_service.py`、`core/chatroom/` |
| Workflow run | 多步骤任务的一次运行，有状态、绑定、回执与产物 | `team_workflow/`、`core/research/workflow/` |
| Knowledge item | 有归属、来源和治理状态的正式知识条目 | `team_knowledge/` |
| Projection | 为某个页面或读取目的生成的视图 | `projection.py`、`projections.py` 等 |

**一个模型可以被多个 Agent 使用；一个 Agent 可以有多个 Session；一个 Session 可以有多个 Turn；一个 Turn 可以反复调用模型。** 因此“建了 5 个智能体”不等于“电脑安装了 5 个大模型”，也不保证 5 个任务同时运行。

## 2. 根目录：先知道哪些是源码，哪些是数据

### 2.1 根目录地图

| 路径 | 内容与用途 | 学习优先级 |
| --- | --- | --- |
| `agent.py` | AgentRuntime 组合入口与兼容门面；仍保留单轮高层执行循环，具体责任尽量分到 orchestration | 高 |
| `config/` | Python 配置模型、加载、公共配置、服务商、协议、安全校验等，**这是代码目录** | 高 |
| `core/` | 后端核心、会话、模型、领域、Web、运行管理等 | 高 |
| `web/` | 前端工程，包含源码、构建配置、设计预览、静态素材与测试 | 高 |
| `desktop/` | Electron 桌面程序及原生进程管理组件 | 高 |
| `tools/` | Agent 可以调用的工具实现与统一注册入口 | 高 |
| `vibelution_storage.py` | 用户目录、配置、工作区、日志等路径解析，是理解“数据在哪里”的重要入口 | 高 |
| `scripts/` | 安装、启动、诊断、打包、迁移、协作与测试选择等运维/开发入口 | 中高 |
| `schemas/` | 研究任务、候选、契约等 JSON Schema；说明输入输出的数据结构 | 中 |
| `tests/` | Python 单元、集成、契约、端到端及测试材料 | 高；学习时配合实现阅读 |
| `docs/` | 架构决策、操作教程、规范、产品设计、历史档案等 | 高；注意现行文档与 archive 的区别 |
| `assets/` | 项目使用的静态资源；具体子目录依内容划分 | 低；目录地图有细分 |
| `prompts/` | 专项提示词模板，如研究任务提示词；不是模型权重 | 中 |
| `experiments/` | 特定研究实验代码，不是普通聊天必须执行的主流程 | 按需要 |
| `.github/` | GitHub Actions、Issue 模板等仓库协作配置 | 中 |
| `.githooks/` | Git 提交或引用更新等本地钩子 | 中 |
| `.cursor/` | 编辑器/Agent 开发辅助技能配置 | 低；不能视为聊天运行主入口 |
| `.vibelution/` | 版本控制中的项目专用元配置；和用户正式工作区、临时 `.runtime` 分开辨认 | 中 |
| `.git/` | Git 对象、分支、引用、任务证据等，不是产品业务数据库 | 不手工修改内部对象 |
| `.worktrees/` | 开发任务隔离 checkout；不是日常会话历史目录 | 了解即可 |
| `.venv/` | Python 环境与已安装依赖；第三方代码，不应直接当项目源码改 | 了解即可 |
| `.runtime/` | 启动、实例、进程状态等运行资料，通常不入 Git | 排错时看，不随意删除 |
| `logs/` | 可能出现的日志入口/兼容目录；正式位置需由路径解析确认 | 排错时看 |
| `dist/` | 本机生成/遗留构建内容；不能凭目录名认定它一定是当前运行版本 | 了解即可 |
| `.pytest_cache/`、`__pycache__/` | 测试与 Python 字节码缓存 | 不当成产品数据 |

`README.md` 是产品和安装入口；`INDEX.md` 是目录地图；`AGENTS.md` 是开发约束；`requirements.txt` 是 Python 依赖；`VERSION` 是产品版本；`web/package.json` 和 `desktop/electron/package.json` 分别声明前端、桌面工程。**它们的版本号不必相同，不能只看某一个 package.json 判断整套程序是否已更新。**

### 2.2 代码根与用户数据根不同

源码 checkout 与用户数据根分开。Windows 常规安装的业务工作区通常位于：

```text
%USERPROFILE%\Documents\Vibelution\data\workspace
```

实际路径以路径解析结果为准；开发沙箱或隔离实例可能使用不同位置。

活跃操作者配置是 `%USERPROFILE%\Documents\Vibelution\config\config.toml`。这里只列路径，不展开密钥。不要把仓库 `config/` 这个 Python 包和用户 `config.toml` 混为一谈；也不要因为源码文件夹没有 `workspace/`，就判断聊天记录丢失。

不同 checkout、开发沙箱、隔离实例可以改变路由位置，因此程序必须通过 `vibelution_storage.py` 和 `core/infrastructure/developer_sandbox.py` 解析，不能在业务里硬编码当前用户名。这也解释了为什么“复制整个源码文件夹”不一定包含你所有会话和模型素材。

源码定位：[vibelution_storage.py](../../../vibelution_storage.py)；[core/infrastructure/developer_sandbox.py](../../../core/infrastructure/developer_sandbox.py)；[INDEX.md](../../../INDEX.md)。

## 3. 前端：从界面到请求

### 3.1 前端技术分别解决什么问题

本地 `web/package.json` 声明 React 19、TypeScript 5、Vite 8、React Router 7、TanStack Query 5、Zustand 5、Tailwind 4 等依赖系列。这里说的是源码声明的版本范围，锁文件才决定解析版本；不要当作已逐项检查 `node_modules` 的运行时版本。

| 技术 | 在项目里的作用 | 典型位置 |
| --- | --- | --- |
| React | 把页面拆成组件，随状态重新渲染 | `main.tsx`、各 `*.tsx` |
| TypeScript | 定义组件参数与后端 DTO 的类型；构建前发现类型不匹配 | `api/types/`、组件 Props |
| Vite | 开发服务、模块编译、生产静态资源打包、代码分块 | `vite.config.ts`、`web/scripts/` |
| React Router | URL 到页面的路由；当前窗口选中的会话由 URL 管理 | `app/router.tsx`、聊天 selection hooks |
| TanStack Query | 请求结果缓存、查询生命周期、刷新与失效 | `app/providers.tsx`、各页面 hooks |
| Zustand | 少量客户端共享 UI 状态 | `store/`；不应与后端业务事实混淆 |
| VUI + shadcn/Radix 思想 | 项目统一的按钮、表单、布局及交互组件边界 | `components/vui/` |
| React Flow / ELK | 团队、流程、图布局等可视化能力 | 页面与 VUI workflow 组件 |
| CodeMirror / xterm | 工作区代码编辑与终端表现 | editor、chat 相关组件 |
| react-markdown / KaTeX | Markdown、数学公式的展示 | conversation 与预览组件 |

### 3.2 页面怎样出现

```text
web/src/main.tsx
  → VuiProvider
  → app/App.tsx
  → app/providers.tsx（QueryClientProvider）
  → app/router.tsx（React Router）
  → AppShell / LauncherShell
  → routes/ChatCodingRoute.tsx 等页面
  → 具体组件与 hooks
```

`main.tsx` 把 React 挂到 HTML 的 `root`；`App.tsx` 提供路由；`router.tsx` 使用懒加载按页面拆包。你打开 `/companions` 才进入人物大厅对应模块，而不是每次启动就一次性把全部金融、科研、团队页面都渲染出来。

源码定位：[web/src/main.tsx](../../../web/src/main.tsx)；[web/src/app/App.tsx](../../../web/src/app/App.tsx)；[web/src/app/router.tsx](../../../web/src/app/router.tsx)；[web/src/app/providers.tsx](../../../web/src/app/providers.tsx)。

### 3.3 前端目录的内部关系

`routes/` 是业务页面及其 hooks，`components/` 是展示和交互组件，`api/` 是与后端的接口封装，`design/` 提供样式和设计预览，`app/` 提供全局壳和导航。`i18n/` 管翻译，`shortcuts/` 管快捷键，`logs/` 是前端日志展示/辅助，`agent-thread/` 是 Agent 线程/消息视图的组织模块，`vendor/` 是本地维护的第三方适配代码，`visual-regression/` 是视觉回归支持。

例如，想调整聊天提交后的显示，先看 `routes/chat/`；想改变调用的 URL，查 `api/chat.ts`；想改变消息卡片交互，再沿 VUI 公共组件进入 renderer；想改变准入或保存行为，则转向 Python Session service。不要用页面 CSS 修复后端调度问题。

### 3.4 VUI 为什么还要分好几层

```text
业务页面（routes）
  → VButton / VSplitWorkspace 等公开 API
      → 产品组件或 recipe（components/vui/product、layout 等）
          → renderers/shadcn 内部交互实现
              → Radix、DOM 等底层能力
```

页面应该使用项目公开的 VUI 组件；具体 DOM 交互集中在 renderer。这种隔离让页面不依赖某个底层控件库的私有细节，便于统一主题、可访问性、布局记忆和测试。`designs/` 是组件设计规范，不是另一套运行时 UI。`web/preview/` 大量目录是设计样机或对照实验，**存在 HTML 样机不表示它就是用户正在使用的正式页面**。

源码定位：[web/src/components/vui/README.md](../../../web/src/components/vui/README.md)；[web/src/components/vui/index.ts](../../../web/src/components/vui/index.ts)。

## 4. 后端：HTTP 层不是整个 Agent

### 4.1 后端入口与启动阶段

`core/web/app.py::create_app()` 创建 FastAPI 实例，设置 JSON 响应、中间件、健康检查、路由和静态页面。`router_registry.py` 汇总要加载的业务路由；`lifecycle.py`、`startup_jobs.py`、`route_bootstrap.py` 处理初始化与后台生命周期。

当前应用分阶段就绪：先让健康检查、控制入口和静态壳可用，再加载业务路由与存储。`/api/health` 的 `shellReady`、`routesReady` 反映不同阶段。**HTTP 200 不等于所有业务功能都准备完毕**；所以第一次重建后，窗口先出现、业务稍后可用是有实现依据的。

源码定位：[core/web/app.py · create_app](../../../core/web/app.py#L40)；[core/web/router_registry.py](../../../core/web/router_registry.py)；[core/web/lifecycle.py](../../../core/web/lifecycle.py)；[core/web/static_spa.py](../../../core/web/static_spa.py)。

### 4.2 route、service、pack、store 各是什么

| 名称 | 用“发送消息”理解 | 应有职责 |
| --- | --- | --- |
| Route | HTTP 的接线员 | 从 URL 与请求体取参数，校验 DTO，映射状态码，调用 service |
| DTO / Pydantic model | 双方约定的表单格式 | 约束 `content`、`clientSubmissionId` 等字段与类型 |
| Service facade | 对外稳定的业务入口 | 其他模块统一 import 它，不必知道内部拆分细节 |
| Service pack/slice | 真正分工的实现模块 | submit、schedule、worker、persist、projection 等 |
| Store / repository | 领域事实的读取与写入 | 事务、SQL、JSONL、原子写与路径约束 |
| Projection | 给页面看的形状 | 从事实源生成 SessionDetail、列表、图谱、状态卡 |

因此 `core/web/services/session_service.py` 很重要，但不意味着你要把所有新逻辑继续塞进去。它大量保留公共导出，具体热路径在 `core/web/services/session/`。`team_knowledge_service.py`、`agent_directory_service.py` 也采用类似的 facade + pack 结构。

### 4.3 后端哪些大目录最值得先读

`core/web/` 管 Web 边界；`core/chat/` 管对话事实与投影基础；`core/orchestration/` 管一次 Agent 执行；`core/llm/` 管模型协议；`core/authorization/` 管工具授权；`core/infrastructure/` 管文件锁、原子 I/O、进程、工具执行器等基础设施。其余领域目录在后续章节和全目录地图逐项解释。

注意：`core/ui/` 位于 Python 后端，不是 React 前端。它包含终端 UI 以及历史兼容的 chat-state API；名字叫 `ui` 不代表全部代码都运行在浏览器。

### 4.4 统一的本地请求保护

`core/web/control.py` 使用 `X-Vibelution-Control-Token`，并校验本地请求来源。前端 `api/client.ts` 从 `/api/control-token` 获取令牌，再把它放在受保护请求头中。健康检查和令牌引导接口不要求先拥有该令牌；部分浏览器原生图片/附件加载有严格限定的例外。

这里的 **control token 是本机工作台访问令牌，不是通义千问等服务商的 API Key**。二者不能互换。只输入 `http://127.0.0.1:8000/api/...` 而不带头，某些接口返回 401/403 是符合设计的；不应该为了调试把保护删掉。

源码定位：[core/web/control.py](../../../core/web/control.py)；[web/src/api/client.ts](../../../web/src/api/client.ts)。

## 5. 前后端究竟怎样交互：完整走一条聊天链

### 5.1 三条通信线要分清

| 通信 | 方向 | 用途 | 关键文件 |
| --- | --- | --- | --- |
| HTTP + JSON | React → FastAPI → React | 创建/查询会话、发送消息、保存参数、读取知识等 | `web/src/api/` ↔ `core/web/routes/` |
| SSE（Server-Sent Events） | FastAPI → React 的持续 HTTP 响应 | 运行中的消息、工具过程与状态更新 | `session/publish.py` ↔ 聊天流模块 |
| Electron IPC | renderer ↔ preload ↔ main | 窗口、系统路径、托盘/启动器等桌面能力 | `preload.ts`、`ipc.ts`、`main.ts` |

普通聊天实时输出主要走 SSE，不能看到“实时”两个字就断言使用 WebSocket。项目还可能在特定模型协议等位置使用 WebSocket，那是另一条传输链。

### 5.2 按实际文件追踪一次发送

```text
① 你点击发送
web/src/components/conversation/ConversationView.tsx
  + web/src/routes/chat/ 中的提交/工作台 hooks
        ↓
② submitSessionMessage(sessionId, ...)
web/src/api/chat.ts
        ↓  POST /api/sessions/{session_id}/messages
③ Pydantic 校验 → route 调用 submit_session_message / lightweight 入口
core/web/routes/sessions.py
        ↓
④ 提交准入、幂等、Journal、运行状态
core/web/services/session/submit.py
        ↓
⑤ 调度 → 后台 worker
session/schedule.py → session/worker.py
        ↓
⑥ Agent 构造、上下文与单轮执行
session/agent_runtime.py → core/orchestration/turn_runner.py → agent.py
        ↓
⑦ 模型调用与工具循环
turn_llm_adapter.py → core/llm/；tool_lifecycle.py → ToolExecutor → tools/
        ↓
⑧ 流式捕获与持久事件
session/stream_capture.py → core/chat/turn_journal.py
        ↓
⑨ 发布流与最终结果
session/publish.py / persist.py / projection.py
        ↓  SSE assistant_delta / session_detail
⑩ 前端校验流序号，维护 active-turn，渲染 turnItems
routes/chat/ → components/conversation/ConversationView.tsx
```

源码定位：[web/src/api/chat.ts · submitSessionMessage](../../../web/src/api/chat.ts#L546)；[core/web/routes/sessions.py · session_submit_message](../../../core/web/routes/sessions.py#L1050)；[core/web/services/session/submit.py](../../../core/web/services/session/submit.py)；[core/web/services/session/worker.py](../../../core/web/services/session/worker.py)；[docs/agents/conversation-flow-map.md](../../../docs/agents/conversation-flow-map.md)。

### 5.3 发送 HTTP 请求与“模型答完了”不是同一时刻

`web/src/api/chat.ts` 的发送封装可请求异步响应。后端接收任务后先返回接受结果与会话信息，后台继续执行；页面通过流拿到进度。所以请求已返回，并不表示模型生成结束。一个稳定的 `clientSubmissionId` 用于区分“同一条消息因网络问题重发”和“用户确实又发了一条”，避免重复创建任务。

教学伪代码：

```typescript
// 示意：省略本项目的其他参数和错误处理。
const accepted = await submitSessionMessage(sessionId, request);
// 这里是任务被接收，而非最后一句回复已经生成。
// 最终显示由会话流和 detail 校准继续推进。
```

### 5.4 SSE 为什么专门使用 fetch 流

当前聊天流入口 `sessionEventStream.ts` 实现了类似 EventSource 的接口，但底层调用 `consumeGuardedEventStream`，通过 fetch 携带控制令牌。浏览器原生 `EventSource` 不便设置这个自定义请求头，因此不能把 token 放到 URL 上图省事。

它保存 SSE 的 `id:`，重连时用 `Last-Event-ID` 传给服务器；可重试的网络错误和永久性的会话删除/权限错误分开处理。前端还利用 `turnId`、`ledgerSeq` 与协议校验拒绝过期帧。否则快速切换会话时，迟到的 A 会话响应可能覆盖正在显示的 B，会表现成“消息串了”或“旧回复跳回来”。

源码定位：[web/src/routes/chat/sessionEventStream.ts](../../../web/src/routes/chat/sessionEventStream.ts)；[web/src/routes/chat/guardedEventStream.ts](../../../web/src/routes/chat/guardedEventStream.ts)；[core/web/services/session/publish.py](../../../core/web/services/session/publish.py)。

### 5.5 turnItems、流式草稿和最终记录

当前 UI 的主要消息包是 `turnItems`：可以表达回答、过程、工具等项目。`assistant_delta` 名字虽然叫 delta，当前契约发送的是完整的 turnItems 快照及 `stage/done/ledgerSeq`，不应自行假设“每次只加一个字符”。

运行中的 active-turn layer 是临时显示桥；同一 `turnId` 的最终结果被 Journal 持久化，并由 `session_detail` 到达后，前端清理 live overlay，防止同一回复出现两遍。`codexTranscript` 是为 cells 渲染派生的适配视图，不是另一份可以独立写入的聊天记录。

源码定位：[core/web/services/session/projection.py](../../../core/web/services/session/projection.py)；[web/src/components/conversation/assistantDisplayPlan.ts](../../../web/src/components/conversation/assistantDisplayPlan.ts)；[web/src/components/conversation/ConversationView.tsx](../../../web/src/components/conversation/ConversationView.tsx)。

### 5.6 一张“功能 → 接线文件”速查表

| 功能 | 前端通信 | 后端 route | 核心业务 |
| --- | --- | --- | --- |
| 普通会话 | `api/chat.ts` | `routes/sessions.py` | `services/session/` |
| Agent 管理 | `api/agents.ts` | `routes/agents.py` | `agent_directory/` 等 |
| 团队 | `api/teams.ts` | `routes/teams.py` | `services/team/` |
| 项目消息总线 | `api/projectAgentBus.ts` | `routes/project_agent_bus.py` | `project_agent_bus_service.py` + Agent Kernel |
| 正式知识 | `api/knowledge.ts`、`teamKnowledge.ts` | `routes/knowledge.py` | `team_knowledge/`、RAG services |
| 记忆管理 | `api/memory.ts` | `routes/memory.py` | memory、cleanup、graph 等 service |
| 模型/服务配置 | `api/config.ts` | `routes/config.py` | `config/`、config services |
| 本地技能 | `api/skills.ts` | `routes/skills.py` | `skill_service.py` |
| 人物生活 | `api/virtualHumanLife.ts` | `routes/virtual_human_life.py` | 插件与 `virtual_human_life_service.py` |
| 运行/启动管理 | `api/launcher.ts`、`runtime.ts` | launcher/runtime routes | Electron 控制面与 Python bridge |
| 文件/Git | `api/files.ts`、`git.ts` | files/git routes | workspace、Git 相关 service |

这些是主入口，不是每个功能的唯一文件。具体方法和 URL 可从对应 route 装饰器与前端 API 封装反查。

## 6. 模型调用与工具循环：Agent 的“脑”和“手”

### 6.1 一次 Turn 不止一次模型请求

用户说“看一下文件并总结”，通常可能发生：模型先决定调用读文件工具 → 程序执行工具 → 把工具结果补回上下文 → 模型再生成总结。每次模型返回工具调用，执行层都要解析、授权、运行、记录，再判断继续还是结束。

```text
构建消息 → 调用模型 → 得到文本/工具调用
                          │
                   有工具且允许执行？
                    ├─ 是：执行 → 记录 ToolResult → 回到模型
                    └─ 否/完成：结果分类 → 持久化 Turn 终态
```

具体责任分布：`turn_message_assembly.py` 排消息；`context_engine.py` 收运行上下文；`turn_llm_adapter.py` 做主备尝试适配；`core/llm/` 负责协议与收发；`response_processor.py` 理解响应；`tool_lifecycle.py` 执行工具桥；`turn_outcome.py` 判断停止、生命周期和结果；`round_state.py` 提供本轮状态。

`agent.py` 不是一个可随便删掉的历史文件：其组合入口和高层 `_run_orchestrated_turn` 仍连接这些模块。项目明确避免再建另一套平行的内部 turn pipeline。

源码定位：[core/orchestration/README.md](../../../core/orchestration/README.md)；[agent.py · AgentRuntime](../../../agent.py#L391)；[core/orchestration/tool_lifecycle.py](../../../core/orchestration/tool_lifecycle.py)。

### 6.2 模型协议为什么要单独做一层

界面看到的“通义千问”是厂商/模型选择，HTTP 请求实际还要确定协议、认证、模型名、工具 schema、思考参数、流式格式、用量格式等。项目把这些分开：

| 层 | 主要文件 | 问题 |
| --- | --- | --- |
| Agent 模型绑定与槽位 | `core/llm/agent_runtime.py` | 当前 Agent 的对话、摘要、子任务等用哪个配置 |
| 语义请求 | `semantic_messages.py`、`semantic_projector.py` | 用统一结构表达消息和生成设置 |
| 协议选择 | `protocols.py`、`protocol_resolver.py` | 是 Chat Completions、Responses 还是其他 wire |
| Payload 构造 | `payload_builder.py`、`schema.py` | 生成合法请求，规范工具 schema 与缓存策略 |
| Wire 适配 | `core/llm/wire/` | 具体请求/响应/流式事件的编码解码 |
| 厂商差异 | `adapters.py` | 思考、tool_choice、usage 等兼容行为 |
| 客户端与调用边界 | `client.py`、`invocation.py`、`streaming.py` | 真正调用、计时、取消、结果规范化 |
| 恢复与统计 | recovery、error_classification、usage 等 | 分类失败、受控重试、主备与用量证据 |

源码定位：[core/llm/PROTOCOL.md](../../../core/llm/PROTOCOL.md)；[core/llm/client.py](../../../core/llm/client.py)；[core/llm/wire/registry.py · build_default_wire_adapter_registry](../../../core/llm/wire/registry.py#L66)。

### 6.3 模型配置与连接探测怎样理解

模型标识、Provider endpoint 和服务商凭据由操作者配置及 Agent 模型绑定解析。不能仅由模型名称判断 wire 协议。前端调用本机配置接口，后端通过 `core/llm` 发起探测或推理；浏览器不直接持有服务商密钥。

探测是一次有时间/输出预算的简短调用。探测通过只能证明该探测路径正常，不能证明全部工具能力、长任务、余额和限流条件都正常。排错时分别检查配置解析、协议、网络、预算与返回结构。

源码定位：[config/public_config.py · _probe_llm_runtime](../../../config/public_config.py#L2475)；[config/public_config.py · _probe_llm_http](../../../config/public_config.py#L2402)。

### 6.4 工具不是模型直接执行的代码

```text
tools/Key_Tools.py 统一注册工具
  → 根据 Agent ToolPolicy 生成可见工具集合
  → 模型返回 tool call
  → ToolLifecycleBridge
  → core/infrastructure/tool_executor.py
  → core/authorization/tool_authorization_service.py
  → tools/ 对应实现
  → 结构化结果 + Journal 事件
```

至少有两道边界：**可见性**决定把哪些工具描述交给模型；**执行授权**决定这次实际调用是否准许。不能只在页面把按钮藏起来就说安全，也不能认为 Skill 文档里写“可以执行命令”就绕过 ToolPolicy。

`tools/Key_Tools.py` 的统一注册与 `core/web/services/tool_catalog.py` 的目录元数据有关，但注册目录本身不会执行每一个工具。若模型说“已经保存文件”，还要看真实 ToolResult 与文件/领域回读；文本陈述不是成功凭证。

源码定位：[tools/README.md](../../../tools/README.md)；[tools/Key_Tools.py · create_key_tools](../../../tools/Key_Tools.py#L4018)；[core/infrastructure/tool_executor.py](../../../core/infrastructure/tool_executor.py)；[core/authorization/tool_authorization_service.py](../../../core/authorization/tool_authorization_service.py)。

### 6.5 参数冻结为什么重要

后端接受新消息时，会冻结本轮模型身份、上下文窗口、推理设置与 Agent 配置修订等参数。你在模型思考中途修改设置，不应悄悄改变已经执行一半的同一 Turn。新的提交、显式重试等再按对应准入规则捕获新快照。

这是一种可复现性设计：后续知道“这次回答到底用了什么”。但冻结的是执行快照，不应拿历史快照回写覆盖用户现在的默认 Agent 配置。

源码定位：[core/web/services/session/turn_model_parameters.py](../../../core/web/services/session/turn_model_parameters.py)；[core/web/services/session/README.md](../../../core/web/services/session/README.md)。

---

[教程目录](README.md) · [下一部分 →](02-data-and-rag.md)
