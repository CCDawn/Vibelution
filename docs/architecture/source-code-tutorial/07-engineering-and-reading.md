[← 上一部分](06-durable-systems.md) · [教程目录](README.md)

# 诊断、前端一致性、CLI 与生命周期

## 37. 用量、预算、日志与 TTFT：怎样证明慢在哪里

### 37.1 Usage 不是把字符串长度当账单

`core/llm/usage_ledger.py` 使用专用 SQLite 账本记录调用用量与汇总，区分 `provider_usage`、`estimated`、`missing`、`not_called`。输入、输出、reasoning、cache read/cache creation、调用次数和耗时分别有语义。

Provider 未返回缓存统计时，不能当作缓存命中为 0，更不能伪造一个完整命中率。代码有 observed/missing/completeness 等字段。估算 token 可以用于容量治理，但不等于服务商最终计费金额。

源码定位：[core/llm/usage_ledger.py](../../../core/llm/usage_ledger.py)；[core/llm/usage_normalize.py](../../../core/llm/usage_normalize.py)；[core/llm/prompt_cache_observation.py](../../../core/llm/prompt_cache_observation.py)。

### 37.2 Reservation、实际消耗、Settlement 不同

科研工作流在尝试前预留预算，完成后按真实证据结算，并处理失败/超限。`budget_stage_admission.py` 在阶段边界做保守容量预判，不能凭空把预留量当实际调用量；它的内部评估失败是 fail-open，真正预算 authority 仍有自己的准入。

这也解释“还没拿到好答案就提示额度不足”：消耗取决于真实调用/尝试，不以最终答案质量为准。不同层预算要查不同 owner，不能只把 Agent max output token 调大就期待整条研究链放行。

源码定位：[core/web/services/team_workflow/research_runtime/budget_stage_admission.py](../../../core/web/services/team_workflow/research_runtime/budget_stage_admission.py)；[core/web/services/team_workflow/research_runtime/budget_authority_adapter.py](../../../core/web/services/team_workflow/research_runtime/budget_authority_adapter.py)；[core/web/services/team_workflow/research_runtime/budget_lifecycle.py](../../../core/web/services/team_workflow/research_runtime/budget_lifecycle.py)。

### 37.3 “回复慢”的计时分段

`ttft_breakdown.py` 由 worker 提供接受/启动锚点，client 在首个规范化流块时观察，不负责改变行为。

| 字段 | 大致范围 | 该查什么 |
| --- | --- | --- |
| queueWaitMs | 接受到 worker 真启动 | 准入/调度/线程饱和 |
| contextBuildMs | worker 启动到进入 LLM 请求流 | 历史/记忆/Prompt/附件读取 |
| payloadBuildMs | client 内请求组装 | 协议转换/工具 schema/图片等 |
| routeGateWaitMs | 赢得这次请求的路由并发等待 | Provider gate 是否占满 |
| streamOpenMs | 发请求到 HTTP headers | 连接/TLS/网络与服务响应 |
| firstRawChunkMs / firstProjectedChunkMs | 原始事件与规范化事件到达 | Provider 事件与适配开销 |
| ttftTotalMs | 接受到首个投影 chunk | 更接近用户感知首输出等待 |

这些字段有重叠计时范围，**不要把表里所有数字直接相加**。缺少锚点时省略，不编造 0。不同进程的 perf_counter 也不能随意相减。

源码定位：[core/llm/ttft_breakdown.py · llm_ttft_chain_context](../../../core/llm/ttft_breakdown.py#L31)；[core/llm/ttft_breakdown.py · build_llm_ttft_breakdown_fields](../../../core/llm/ttft_breakdown.py#L82)；[core/llm/stream_http_timing.py](../../../core/llm/stream_http_timing.py)。

### 37.4 从一次点击追到一次工具调用

W3C traceparent、requestId、traceId/spanId 关联请求与日志；Agent/Session/Turn/invocation/toolCallId 关联业务执行。它们各自有作用域：一次 HTTP span 不等于整个 Turn，toolCallId 也不是 AgentId。

`ContextVar` 在当前逻辑上下文里传播方便，但跨 executor、队列、线程/进程边界不能自动假定完整继承，所以调度 context 要显式携带需要的关联字段。一次日志缺了 traceId，不能仅凭时间接近就认定它属于某个任务。

源码定位：[core/logging/trace_context.py](../../../core/logging/trace_context.py)；[core/web/middleware/runtime_scene_api.py](../../../core/web/middleware/runtime_scene_api.py)；[core/web/services/runtime_scene/README.md](../../../core/web/services/runtime_scene/README.md)。

### 37.5 EventBus、SSE、Journal、Outbox 四种“事件”

| 机制 | 传输/保存范围 | 断进程后如何理解 |
| --- | --- | --- |
| infrastructure EventBus | 进程内发布/订阅回调 | 不能当可靠持久消息队列 |
| SSE | 后端到 UI 的持续 HTTP | 需要重连/回放/校准，不是独立正文真源 |
| Journal | Session 持久对话事件 | 可重建模型/UI 历史与终态 |
| Workflow Outbox | 持久待处理动作及 lease | 由 worker 重试/ack，依赖幂等执行 |

项目 Agent Bus 是领域消息与 Kernel 的组织面，也不要与 infrastructure EventBus 仅因英文都带 bus 就混读。

源码定位：[core/infrastructure/event_bus.py](../../../core/infrastructure/event_bus.py)；[core/web/services/session/publish.py](../../../core/web/services/session/publish.py)；[core/research/workflow/ledger/outbox.py](../../../core/research/workflow/ledger/outbox.py)。

日志应记录有界身份、阶段、计数、耗时、结果分类与 artifact 引用；`safe_payload.py` 做参数形状/长度/hash 摘要。日志中不应为了“方便排错”无界输出密钥、完整 Prompt、工具结果和私人正文。`session/read_health.py` 还统一节流报告降级读取，避免失败被悄悄吞掉或警告刷屏。

源码定位：[core/logging/safe_payload.py](../../../core/logging/safe_payload.py)；[core/web/services/session/read_health.py](../../../core/web/services/session/read_health.py)。

## 38. 前端真正的核心：异步一致性，而不只是 CSS

### 38.1 当前会话以 committed URL 为权威

`useChatRouteSelection()` 解析 React Router 的 search 参数，提供 openSession/openRoom/openProjectBus 等统一写入口。后端 last-viewed pointer、localStorage、轮询和 SSE 不能反过来持续控制当前窗口选中态。

最关键的方法是 `replaceIfStillViewing(expected, next)`：异步创建/删除/归档返回时，先确认你仍在原页面，再允许跳转；否则只更新相关缓存。

```text
t0：打开 A，发起一个异步请求
t1：你主动切到 B
t2：A 的旧请求返回
正确：更新 A 的 cache，保持 B
错误：按旧回调 setActiveSession(A)，把用户拉回 A
```

源码定位：[web/src/routes/chat/useChatRouteSelection.ts · useChatRouteSelection](../../../web/src/routes/chat/useChatRouteSelection.ts#L74)；[web/src/routes/chat/chatSelectionProjection.ts](../../../web/src/routes/chat/chatSelectionProjection.ts)。

### 38.2 缓存分别解决不同问题

React Query 管服务端查询结果；`activeTurnLayersStore.tsx` 管运行中展示桥；`chatSessionPaintCache.ts` 保留最近会话的 last-good 快照，避免切回时空白；`conversationSessionScrollMemory.ts` 记住滚动位置。不能拿后一种 UI 记忆当后台事实源。

paint cache 还有重要规则：运行中很薄的最后几条消息窗口不能覆盖更丰富的已有历史快照，否则切换时会像记录丢了。页面删除会话时也应忘掉对应 paint/scroll 记忆，不能让已删除内容从缓存复活。

源码定位：[web/src/routes/chat/activeTurnLayersStore.tsx](../../../web/src/routes/chat/activeTurnLayersStore.tsx)；[web/src/routes/chat/chatSessionPaintCache.ts](../../../web/src/routes/chat/chatSessionPaintCache.ts)；[web/src/components/conversation/conversationSessionScrollMemory.ts](../../../web/src/components/conversation/conversationSessionScrollMemory.ts)。

### 38.3 同一轮结果为什么需要多重身份

接收流时看 sessionId，避免串会话；看 turnId，避免旧轮覆盖新轮；看 ledgerSeq，避免较旧快照倒灌；看 turnItems 的条目身份，避免工具/答案重复绘制。最终 detail 要和 active layer settle，不能把“流数据到达”简单写成 `messages.push(payload)`。

源码定位：[web/src/routes/chat/sessionEventStream.ts](../../../web/src/routes/chat/sessionEventStream.ts)；[web/src/api/types/chat.ts](../../../web/src/api/types/chat.ts)；[docs/agents/conversation-flow-map.md](../../../docs/agents/conversation-flow-map.md)。

### 38.4 升级后的白屏与 chunk 恢复

代码分块意味着旧页面可能还引用旧 hash 的模块。`routeChunkRecovery.ts` 对动态 import/资源错误做按 buildId/target 记录的有界恢复，防止无限刷新；`primaryRouteChunkLoader.ts` 让预载和真正导航使用同一 loader。

这与 FastAPI 业务错误不是一类问题。Network 中静态 JS 404 应先查 release/chunk，而不是改 Python 模型接口。反过来，构建文件在磁盘并不表示旧浏览器页已经加载了它。

源码定位：[web/src/app/routeChunkRecovery.ts](../../../web/src/app/routeChunkRecovery.ts)；[web/src/app/primaryRouteChunkLoader.ts · loadPrimaryRouteChunk](../../../web/src/app/primaryRouteChunkLoader.ts#L5)。

### 38.5 会话列表事件流与会话正文流分工

侧栏需要知道尚未打开的会话是否有摘要变化，所以有全局 Session index stream；正文 SSE 只服务已经打开的具体会话。索引帧只携带摘要级变化、补丁或移除信息，不能成为第二条 transcript。慢订阅者的有界队列不会反压正在发布的 Turn；客户端仍需按事件语义与重连策略恢复列表投影。

源码定位：[core/web/services/session/session_index_stream.py](../../../core/web/services/session/session_index_stream.py)；[core/web/routes/sessions.py](../../../core/web/routes/sessions.py)。

## 39. CLI Agent、PTY、浏览器与桌面 CUA 的边界

#### 38.6 会话列表事件流与会话正文流分工

侧栏需要知道尚未打开的会话是否有摘要变化，所以有全局 Session index stream；正文 SSE 只服务已经打开的具体会话。索引帧只携带摘要级变化、补丁或移除信息，不能成为第二条 transcript。慢订阅者的有界队列不会反压正在发布的 Turn；客户端仍需按事件语义与重连策略恢复列表投影。

源码定位：[core/web/services/session/session_index_stream.py](../../../core/web/services/session/session_index_stream.py)；[core/web/routes/sessions.py](../../../core/web/routes/sessions.py)。

## 39.1 项目自己的 LLM Agent 与外部 CLI Agent

普通 Agent 由本项目 `core/llm` 调模型、`ToolExecutor` 执行工具；CLI Agent adapter 则启动/连接另一个编码工具的进程，处理其协议、工作目录、模式、会话标识和输出。两者可能最终使用相同厂商模型，也不是同一个执行器。

`cli_agent_service.py` 提供受控非交互式适配、可执行文件配置、超时/输出限制及 readonly/worktree 等模式；不要在 API route 里把用户随意传来的字符串直接当可执行程序。

源码定位：[core/web/services/cli_agent_service.py](../../../core/web/services/cli_agent_service.py)；[tools/cli_agent_tools.py](../../../tools/cli_agent_tools.py)。

#### 38.6 会话列表事件流与会话正文流分工

侧栏需要知道尚未打开的会话是否有摘要变化，所以有全局 Session index stream；正文 SSE 只服务已经打开的具体会话。索引帧只携带摘要级变化、补丁或移除信息，不能成为第二条 transcript。慢订阅者的有界队列不会反压正在发布的 Turn；客户端仍需按事件语义与重连策略恢复列表投影。

源码定位：[core/web/services/session/session_index_stream.py](../../../core/web/services/session/session_index_stream.py)；[core/web/routes/sessions.py](../../../core/web/routes/sessions.py)。

## 39.2 为什么终端需要 PTY/ConPTY

有些 CLI 不只是 stdout 逐行输出，会发光标控制、清屏、重绘、等待输入。`cli_agent_terminal_service.py` 在 Windows 可用 winpty/ConPTY，维护 terminal session、screen buffer、transcript tail、SSE 和进程归属；前端 xterm 展示终端流。

所以“最后收到的一行 stdout”不一定是最终回答；屏幕当前内容、原始字节和模型会话正文不是同一结构。`terminal_screen_buffer.py`、`cli_agent_task_kernel.py` 等承担解析/任务关联，受控 discovery 可以找外部 CLI 自身的 session identity。

源码定位：[core/web/services/cli_agent_terminal_service.py](../../../core/web/services/cli_agent_terminal_service.py)；[core/web/services/terminal_screen_buffer.py](../../../core/web/services/terminal_screen_buffer.py)；[core/web/services/cli_agent_task_kernel.py](../../../core/web/services/cli_agent_task_kernel.py)。

#### 38.6 会话列表事件流与会话正文流分工

侧栏需要知道尚未打开的会话是否有摘要变化，所以有全局 Session index stream；正文 SSE 只服务已经打开的具体会话。索引帧只携带摘要级变化、补丁或移除信息，不能成为第二条 transcript。慢订阅者的有界队列不会反压正在发布的 Turn；客户端仍需按事件语义与重连策略恢复列表投影。

源码定位：[core/web/services/session/session_index_stream.py](../../../core/web/services/session/session_index_stream.py)；[core/web/routes/sessions.py](../../../core/web/routes/sessions.py)。

## 39.3 浏览器自动化和单窗口桌面控制不同

`computer_use_service.py` 管受控沙箱浏览器任务、动作白名单、步数/超时与确认；个人助理的 `personal_assistant_computer_service.py` 管用户选择的单个窗口同意、observation、逐次 action、暂停/接管/取消，再交给固定 driver。

授权某一个窗口不等于授权整个桌面，旧 observation/token 过期或窗口身份变化后要拒绝。一次确认只释放一个等待调用，不应偷偷新建 Turn 或在结果不确定时自动重试按键。

源码定位：[core/web/services/computer_use_service.py](../../../core/web/services/computer_use_service.py)；[core/web/services/personal_assistant_computer_service.py](../../../core/web/services/personal_assistant_computer_service.py)；[core/infrastructure/cua_driver_client.py](../../../core/infrastructure/cua_driver_client.py)。

#### 38.6 会话列表事件流与会话正文流分工

侧栏需要知道尚未打开的会话是否有摘要变化，所以有全局 Session index stream；正文 SSE 只服务已经打开的具体会话。索引帧只携带摘要级变化、补丁或移除信息，不能成为第二条 transcript。慢订阅者的有界队列不会反压正在发布的 Turn；客户端仍需按事件语义与重连策略恢复列表投影。

源码定位：[core/web/services/session/session_index_stream.py](../../../core/web/services/session/session_index_stream.py)；[core/web/routes/sessions.py](../../../core/web/routes/sessions.py)。

## 39.4 Agent 协议路由图不等于又一个任务引擎

`core/agent_protocol/` 定义 adapter、binding、direction、operation、endpoint observation 等不可变契约。`AgentProtocolGraphBuilder` 从声明、适配器、绑定与观测构造有效路由，并报告重复绑定等问题；`admit_protocol_operation()` 校验 authenticated、principal/tenant、binding、operation、policy version 等操作身份。

外部 MCP 的 `protocol_routing.py` 明确只生成兼容路由元数据，任务生命周期仍属于 existing external_agent service。看到一个通用 GraphBuilder 不足以证明所有普通聊天与内部协作都已经迁到该图执行，更不代表现成的完整多租户云平台；应继续核对实际调用者。

源码定位：[core/agent_protocol/resolver.py · AgentProtocolGraphBuilder](../../../core/agent_protocol/resolver.py#L21)；[core/agent_protocol/admission.py · admit_protocol_operation](../../../core/agent_protocol/admission.py#L37)；[core/web/services/external_agent/protocol_routing.py](../../../core/web/services/external_agent/protocol_routing.py)。

## 40. 启动、关机、构建与版本：维护长期运行资源

### 40.1 Lifespan 不只是启动时 import 一次

`core/web/lifecycle.py` 用 FastAPI lifespan 组织路由/目录准备、后台任务、研究运行时、恢复与退出。启动任务也要有 owner 和 stop fence，防止页面退出/后端关闭后旧回调又提交新任务。

`StartupJobGroup`、`run_sync_bounded()` 等把同步阻塞工作移到 worker 并使用共享截止时间；超时可报告不完整，但不能神奇地安全杀掉任意 Python 线程。

源码定位：[core/web/lifecycle.py](../../../core/web/lifecycle.py)；[core/web/startup_jobs.py · run_sync_bounded](../../../core/web/startup_jobs.py#L19)；[core/web/startup_jobs.py · StartupJobGroup](../../../core/web/startup_jobs.py#L66)。

### 40.2 先封生产者，再关消费者

关机时若先关闭 Session executor、却还允许工作流 producer 继续派发任务，就会产生“后台仍提交、执行器已经关闭”的竞争。当前关闭路径先 fence 通用工作流 producer，再按 owner 协调 Session、工具、终端、会议等资源，并检查返回 closed 是否真实成立。

这解释为何“把所有线程 shutdown(wait=False)”不是完整的关机设计。桌面快速退出、后端优雅关闭、最终原生进程树回收还有各自的时间预算，不能把某个模块的 25 秒上限直接说成用户每次点 × 必须等 25 秒。

源码定位：[core/web/lifecycle.py · _shutdown_owned_runtime_resources](../../../core/web/lifecycle.py#L1134)；[core/web/services/session/agent_runtime_retirement.py · SessionAgentRuntimeLease](../../../core/web/services/session/agent_runtime_retirement.py#L35)；[desktop/electron/src/process/fastWorkbenchClose.ts](../../../desktop/electron/src/process/fastWorkbenchClose.ts)。

### 40.3 判断“运行的是新代码”需要三类证据

| 证据 | 能证明什么 | 不能单独证明什么 |
| --- | --- | --- |
| Git HEAD / working tree | 磁盘源码状态 | 已运行的旧进程自动切换了代码 |
| build release/provenance | 某份静态/桌面产物从何构建 | 当前页面或主进程正在使用它 |
| health serving 元数据 + 对应运行进程 | 当前挂载前端与后端来源身份 | 全部高级业务都完成真实端到端验收 |

`serving_version.py` 在进程构造时固定 serving identity，不因 active pointer 变化就谎报已经服务新 release。桌面也有 shell freshness/packaging provenance，不能拿工作台后端版本代替 Launcher 主进程版本。

源码定位：[core/web/services/serving_version.py](../../../core/web/services/serving_version.py)；[desktop/electron/src/packaging/packageProvenance.ts](../../../desktop/electron/src/packaging/packageProvenance.ts)；[desktop/electron/src/process/desktopShellFreshness.ts](../../../desktop/electron/src/process/desktopShellFreshness.ts)。

### 40.4 测试、契约、真实运行是不同证据

UI 类型检查解决编译契约；Vitest/pytest 验证指定输入下的行为；静态源码合同限制模块边界；mock Provider 证明编排，不证明真实服务；native 测试可以证明特定进程回收场景，但不等于所有电脑硬件都表现相同。

读 tests 时特别留意四类场景：竞争与幂等、失败注入、权限拒绝、重启/迟到回调。它们比“输入 1 输出 1”的浅断言更能解释架构为什么这么写。本次是文档补充，没有为生成教程重跑产品构建或真实付费模型请求。

## 41. 核心源码精读练习：学会自己发现重要代码

### 41.1 用一个请求穿过七层，而不是通读 7,000 个文件

找一个功能，按这个模板做阅读笔记：

| 层 | 你要写出的答案 |
| --- | --- |
| UI 操作 | 哪个组件/hook 收到点击？当前 Session 从哪来？ |
| API | 方法、URL、DTO、控制令牌、幂等/expected 字段是什么？ |
| Route | 哪个函数映射 HTTP 错误？是否轻量接受？ |
| Service | 谁检查归属/忙状态、冻结参数、调度？ |
| 执行 | 哪个 worker/adapter/model/tool 真正产生动作？ |
| 持久化 | 哪份 canonical 数据被修改？事务/锁/序号/哈希是什么？ |
| 返回与恢复 | SSE/detail/receipt 怎么回 UI？中途崩溃怎么看？ |

### 41.2 练习 A：停止后为什么子任务没有“复活”父会话

沿 `request_stop_session_turn` → cascade → runtime task stop/notification sealing → branchGeneration/queued notices → worker settlement 阅读。画出停止意图、物理停止、终态、迟到通知四个节点，并指出任何一个节点失败时 UI 应如何诚实报告。

### 41.3 练习 B：为什么同一工具第二轮突然无权执行

沿 Agent canonical config → Turn frozen revision/hash → install_execution_authorization → authorize_tool_execution → approval/plugin/perception 检查。写出 config mismatch、tool_not_executable、approval declined、call budget exhausted 的区别；不要把它们全归因为 Prompt 不够强。

### 41.4 练习 C：模型上下文变短，但历史还在

沿 Journal → context assembler → tool-result budget → microcompact → sticky projection lock → full compression checkpoint → wire payload 阅读。分别找出“原始正文”“模型投影”“UI 投影”“诊断摘要”，证明没有随手把四者覆盖成同一份字符串。

### 41.5 练习 D：重启后是否应该重新调用模型

取一个假想崩溃点：领域产物已写、模型回执到达但 Outbox ack 未提交。找到 dispatch identity、领域回读、receipt registry、lease 与幂等分支，解释为什么可能只需继续完成处理，而不是再启动一个模型任务。

### 41.6 练习 E：一个可控的小型改动如何验收

先只在笔记里设计“给聊天状态增加一个只读说明字段”：写清字段由哪个事实派生，哪个 DTO/类型和 API 需要变化，前端不应该自造什么，预期的空态/错误/旧数据兼容是什么，哪些契约和行为用例足够验证。不要直接在运行的 main 上改源码。

### 41.7 阅读代码的红旗清单

看到以下现象就继续追问，而不是立即判错或直接改：

- 文件名叫 atomic，但是否存在 fallback？
- docstring 写 shadow-mode，实际执行有没有 enforced 分支？
- status 写 stopped，底层 Future/进程是否还活着？
- 页面显示 completed，是 Session、业务产物还是工作流节点完成？
- 版本显示最新，是磁盘 HEAD、build provenance 还是实际 serving？
- 数据有两个副本，哪个是可写主数据，哪个只是快照/缓存？
- 任务恢复重新提交，幂等和原授权是否保持？
- 后台服务默认 off，是否被误写成启动即生效？
- 临时工具输出限长，是否错误归因成历史正文已删除？
- 调用有 timeout，是否错误承诺外部副作用没有发生？

这些问题比记住所有文件名更重要。配套的《核心机制源码精读索引》列出专题、文件、符号和行号；请先掌握 P0 主链，再按你要开发的功能深入 P1/P2。

### 41.8 另三类核心辅助：代码认知、Git 记忆、元认知

`core/code_context_graph/service.py` 对本地代码做确定性的、可缓存的结构索引；PromptManager 的 codebase file index/map 也服务相关代码定位。它们不是把所有源码都送到向量模型的同一套 RAG。读调用/依赖关系时，要区分 AST/符号结构与文本相关性。

`core/infrastructure/git_memory.py` 提供 Git 变更/实体等读取索引和统计；Git 对象、变更派生库、Turn 文件 pre-image 又是三类不同资料。索引可以帮助回答“代码为什么变化”，但不替代真实工作树 diff，也不能代替当前业务产物验证。

`mental_model.py` 则采集 EventBus 等运行信号、做规则诊断并在需要时给 Prompt 有界干预。这里“心智/元认知”是工程命名，不证明模型具有人类意识。是否启用要经 `feature_gate.py` 的可信决策；多数功能受操作者配置约束，部分显式 Turn 开关有专门优先级规则，不能自行发明统一的“请求永远覆盖全局配置”原则。

源码定位：[core/code_context_graph/service.py](../../../core/code_context_graph/service.py)；[core/infrastructure/git_memory.py](../../../core/infrastructure/git_memory.py)；[core/infrastructure/mental_model.py · MentalModel](../../../core/infrastructure/mental_model.py#L171)；[core/infrastructure/feature_gate.py](../../../core/infrastructure/feature_gate.py)。

### 41.9 用真实测试反推机制的失败合同

以下测试路径已确认存在。本次没有重新运行这些产品测试；它们是你的阅读练习入口。

| 专题 | 建议读的测试 | 阅读时找什么 |
| --- | --- | --- |
| 配置身份 | `tests/test_agent_config_authority_migration.py` | revision/hash/迁移兼容与写入边界 |
| 文件可靠性 | `tests/test_atomic_io.py`、`tests/test_file_lock.py` | replace 占用、重试、锁与失败回退 |
| 工具生命周期 | `tests/test_tool_execution_scope.py` | timeout/取消之后仍活着的 Future 如何追踪 |
| 授权 | `tests/test_tool_authorization_execution.py` | 身份不符、缺决策、额度/审批如何拒绝 |
| 微压缩 | `tests/test_microcompact_tier.py` | 组保留、配对、节省阈值、只读投影 |
| 文件回退 | `tests/test_file_change_ledger.py` | 新建/修改/删除、外部修改冲突与幂等 |
| 后台任务 | `tests/test_runtime_task_registry.py` | 原子快照、索引、代次、通知/停止 |
| 启动恢复 | `tests/test_session_startup_recovery.py` | 原授权/模型恢复、重复提交、Companion 跳过 |

先尝试用自己的话写出每个用例要阻止的坏情况，再看断言。测试名和通过数量是入口，真正的学习对象是可观察行为与它的边界。

---

[← 上一部分](06-durable-systems.md) · [教程目录](README.md)
