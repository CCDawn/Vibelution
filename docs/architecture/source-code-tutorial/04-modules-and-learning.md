[← 上一部分](03-agents-and-desktop.md) · [教程目录](README.md) · [下一部分 →](05-runtime-deep-dive.md)

# 业务模块、例子与学习路线

## 15. 虚拟人、形象表现与桌宠：表现层和智能层分开理解

### 15.1 虚拟人是 Agent-scoped 插件

`core/agent_plugins/virtual_human_life/` 是第一方虚拟人生活插件。它通过显式 Agent 绑定启用，管理人物身份、日程、情绪、关系、生活活动、长期目标、记忆来源和主动消息。未绑定/禁用的普通 Agent 不应因此额外创建生活数据或注入人物 Prompt。

`manifest.py` 声明插件能力；`service.py` 编排领域；`storage.py` 管 Agent 私有路径和原子 JSON/JSONL；`prompt_pack.py` 加载有界人物 Prompt；`core/web/services/virtual_human_life_service.py` 是 Web/runtime 门面；`tools/virtual_human_life_tools.py` 给该 Agent 受限的生活工具。

主要子模块：

| 模块 | 职责 |
| --- | --- |
| `drives.py` | 长期目标、项目、习惯、技能进展 |
| `affect.py` | 情绪事件与恢复、表达档位 |
| `relationship_events.py` | 关系变化、阶段与限制 |
| `calendar.py`、`commitments.py` | 日历、周期、双方约定与冲突 |
| `environment.py`、`world_model.py` | 环境事实、位置移动、地点/路线/物品 |
| `mailbox.py`、`delivery_plan.py`、`delivery_runtime.py` | 插件私有消息到达顺序与投递计划 |
| `self_continuity.py`、`native_wakeup.py` | 预约行动、到点通过原生链路唤醒 |
| `reflection.py`、来源/证据模块 | 反思、记忆强化、真实来源校验 |
| `interaction_expression.py`、`expression_policy.py` | 表达规则、追问预算等 |
| `embodiment.py` | 可选语音/3D/Live2D provider 的表现与回退 |

重要边界：插件 mailbox 不是第二份聊天 transcript。主动消息也经已有原生 Session/Turn 路径执行；人物不能因为需要“更拟人”而另造一套普通 Session 的 SSE 或历史。

源码定位：[core/agent_plugins/virtual_human_life/README.md](../../../core/agent_plugins/virtual_human_life/README.md)；[core/web/services/session/proactive.py](../../../core/web/services/session/proactive.py)。

### 15.2 人物“做过”什么，要有来源

计划、计时器完成、人物自述和真实工具执行是不同证据。当前插件有 `life_provenance.py`、`native_activity_evidence.py`、`memory_sources.py` 等，区分模拟安排和原生工具回执。不能因为它说“我已经读完新闻”，就证明后台真的联网读了文章。

这与研究工作流的原则一致：**文本输出、执行成功、业务产物、可核实经历要分别验证。**

### 15.3 形象表现和语言智能是两条链

人物身份、记忆、关系和日程属于插件领域；页面头像、背景和桌宠窗口属于表现层。改变图片不会自动改变人物提示词或记忆；模型回答也不会自动变成渲染器的动作或口型。

`embodiment.py` 描述可选表现 provider 与回退边界。声明某种 provider 不等于已包含任意格式的人物模型导入器；具体能力应核对已注册 API、DTO 与实际 renderer，不把实验或下游扩展当成通用功能。

源码定位：[core/agent_plugins/virtual_human_life/embodiment.py](../../../core/agent_plugins/virtual_human_life/embodiment.py)；[web/src/routes/companions/](../../../web/src/routes/companions/)。

### 15.4 桌宠资源、窗口与宠物领域各管什么

`web/public/desktop-pet/` 存放运行资源和素材；`routes/desktopPet/` 是页面；Electron pet window 提供桌面浮窗宿主。Python 的 `core/pet_system/` 是宠物状态/成长等领域模块。这些名字相关，但读取素材、创建窗口和更新领域状态不能合并成一个职责。

## 16. 其余内部模块怎样拼进系统

### 16.1 配置系统

`config/models.py` 定义 Pydantic 配置结构与默认约束；`settings.py` 等提供配置加载/访问；`public_config.py` 负责可公开操作的配置接口、探测等；`operator_bootstrap.py` 处理操作者配置引导；安全模块限制密钥与 endpoint 行为。具体文件职责以模块 README和实现为准。

配置分层要分清：操作者全局服务商/模型库 → Agent 显式绑定和策略 → 接受任务时冻结的 Turn 快照。修改当前 Agent 参数，不应覆盖所有 Agent 的共享模型配置；修改 Provider Key 也不应把明文送回 UI。

源码定位：[config/models.py](../../../config/models.py)；[config/settings.py](../../../config/settings.py)；[config/public_config.py](../../../config/public_config.py)；[config/operator_bootstrap.py](../../../config/operator_bootstrap.py)。

### 16.2 运行管理与 Launcher

`core/runtime_manager/` 维护 WorkRun、实例身份、命令、重启协调、进程清单与后台运行管理；`core/launcher/` 保留 Python 侧桌面准备、维护和兼容桥。当前桌面 open/close/restart 的产品控制权在 Electron，不能用“看到 daemon.py”就推断 Python 仍拥有全部控制权。

`core/restarter_manager/` 是重启/重生相关的专门机制，和一般页面重新加载不是一件事。重启要防止旧进程/旧父子关系被误认成当前实例；PID 可能被复用，所以存在 process identity、createTime、owner lease、registry generation 等字段。

### 16.3 研究、实验与进化

`core/research/` 管研究领域模型、题目、证据、评分、实验适配、报告、工作流等；`experiments/` 放具体实验。`core/evaluation/` 管评估和聊天数据采集等；`core/gym/` 提供评测/训练场景相关组织。`services/team_workflow/` 负责把领域操作与团队执行衔接。

监督进化/自进化不是“程序随意修改自己然后立即投产”。当前模块区分候选改动、验证、审核、集成、运行版本激活及证据。`core/orchestration/agent_modes.py` 决定 chat、supervised_evolution、self_evolution 等模式政策；普通聊天使用 AgentRuntime 不代表开启了无限自进化循环。

任何能力页面存在，都不等于你的本机已经配置其模型、外部服务、实验数据或自动运行授权。学习报告描述代码支持的链路，不承诺所有高级实验开箱即跑。

### 16.4 金融工作台

业务层按职责拆为 financial_market（只读行情）、financial_research（研究投影）、financial_team（多分析员）、financial_jobs（批次/日程）、financial_paper（模拟账本）、financial_backtest（历史回测）、financial_portfolio/rebalance（组合与模拟调仓）、financial_report（正式输出导出）、financial_preferences（用户偏好）等。

这些领域复用 Agent/Session、知识来源与权限，不应该再造第二个 LLM 聊天后端。当前 README 声明的模拟与研究能力不能解释为已经连接券商实盘交易。外部来源有时效、单位、范围和完整性，业务代码对这些条件有专门校验。

### 16.5 个人助理与个人事务

`personal_assistant_service.py` 维护个人助理入口和受控概览；`personal_assistant_project/` 提供有边界的项目读取；`personal_assistant_platform_api/` 是明确开放的内部 API 子集；`personal_affairs` 管待办/日程/目标；computer/desktop services 是受控桌面操作/评估链。助理身份与会话仍来自原生 Agent，不是绕过全局权限的管理员万能号。

### 16.6 基础设施与诊断

`core/infrastructure/` 解决跨模块共用的硬问题：工具执行、文件锁、原子 I/O、工作区路由、子进程、沙箱、Git、代码分析、后台执行器等。`core/logging/` 管日志；`core/diagnostics/` 与 runtime-scene services 组织有界排错证据。

`core/code_context_graph/` 是代码上下文图相关服务；`prompt_manager/codebase_file_index.py` 为代码地图缓存文件版本元数据。它们不是正式知识向量索引，也不是所有检索都靠 RAG 的证据。系统内有多种索引，分别服务代码结构、Git、历史和知识。

### 16.7 测试在哪里、能证明什么

| 测试位置 | 技术 | 典型证明 |
| --- | --- | --- |
| `tests/` | pytest | 后端业务、存储、权限、恢复与契约 |
| `web/src/**/*.test.ts(x)` | Vitest，部分 DOM 测试环境 | 组件、hooks、API/布局/源码边界契约 |
| `desktop/electron/tests/` | Vitest，部分原生执行 | 生命周期、IPC、安全、构建与进程回收 |
| `tests/e2e/` | 端到端辅助与 mock LLM 等 | 多层集成流程，具体覆盖看测试用例 |

模拟模型通过不等于真实 Provider 服务质量通过；静态契约通过不等于所有用户点击路径都做过可视化验收；生产构建成功也不等于后台已换成新代码。要结合 health 的 serving commit/buildKey 和功能接口验证。

## 17. 把关键设计原则翻译成人话

### 17.1 SSOT：一件事实只能有一个主账本

会话正文认 Journal；目录认 ConversationStore；Agent 配置认 AgentInstance；Team 成员认 Team.members；正式知识认 Owner store；向量是派生；工作流进度认 Workflow Ledger。它们之间可以保存引用和快照，但不应互相盲写覆盖。

如果 A 表显示任务完成、B 文件还说运行中，先找谁是该事实的 owner，而不是“哪个时间戳新就用哪个”。不同字段记录的可能不是同一事实。

### 17.2 Idempotency：同一请求重发不能执行两次

网络断开后，前端可能不知道上一次提交是否成功。幂等键与请求指纹让后端重放已有接收结果；同一个键却不同参数要拒绝。工作流 dispatch、外部 MCP task、消息提交也有类似需求。它不是简单“失败就再调一次”。

### 17.3 CAS：先确认你改的是你看到的版本

Compare-and-Swap 使用 expected revision/head/ledger sequence 等检查。你打开配置页面后别人修改了同一配置，旧页面保存应该得到冲突提示，而不是悄悄覆盖。任务重试、水位校验、实例 registry 等都有版本/代次保护。

### 17.4 Outbox 与 Receipt：跨层操作要留下可恢复的交接

数据库事务只能保证自己的写入；它不能天然保证“提交事务同时外部工作也完成”。Outbox 先在事务中持久记录待派发动作，worker 再执行；receipt 记录可验证的完成。重启后才能分辨“没有派发”“派发过但还没回执”“已完成但 UI 没刷新”。

当前科研正式运行时明确使用这类机制；不要因此推断每条普通聊天消息都使用同一个工作流 Outbox。

### 17.5 投影与快照：可以复制显示，不能复制权威

前端 cache、API DTO、运行 summary、历史配置快照、图谱节点都可以保存派生信息，但需要明确来源和失效策略。你看到的状态是“截至某个 seq/revision 的视图”，不是永久真理。

### 17.6 安全不只靠提示词

提示词描述行为；真正边界还有 control token、来源校验、ToolPolicy、审批、文件路径包含性、Owner ACL、大小限制、模型预算、进程身份和取消。用户上传的文档/网页/Skill 文本都可能携带不可信指令，不能自动获得更高权限。

## 18. 六个端到端例子：把概念串起来

### 18.1 发一条普通问答

输入框 → `api/chat.ts` → `routes/sessions.py` → submit/admission → Journal 与调度 → Agent context → `core/llm` → capture/Journal → SSE turnItems → ConversationView。没有必要在这条链里强行加入 MySQL、MCP 或向量库。

### 18.2 让 A 找 B 评审

A 明确任务和目标 Session → 已授权的 `agent_message_tool` → 验证 B 的 Session 所属/状态 → 正文进入目标历史或有界延后 → B 被唤醒并执行 → B 的 Journal 保存结果 → 按任务要求把评审回执交给 A。Team 成员信息、消息投递、任务完成与正文存储分别有 owner。

### 18.3 上传一份资料并在后续回答中引用

受控文档上传/暂存 → 来源/归属/哈希 → 待审 → 审核形成正式条目 → 可选构建向量 → Agent 调用搜索 → ACL/lifecycle → BM25/semantic/hybrid → 命中片段与引用 → 模型组织回答。上传成功只是第一步，不等于已审、已索引或本轮已检索。

### 18.4 使用一个本机 Skill

技能在发现根存在 → 页面可预览/命令可解析 → 用户在当前会话选择斜杠命令 → 加入受限 runtime context → 模型按步骤行动 → 每个实际工具仍经授权。Skill 让模型有方法，不会把 ToolPolicy 从只读变成可写。

### 18.5 外部工具通过 MCP 调用本项目

操作者先配置并允许网关 → 外部客户端启动 stdio MCP adapter → 读 guide → list 合格 Agent → start 有幂等标识的任务 → backend service 创建原生执行 → get 轮询状态 → 必要时处理自己的审批或取消。业务记录仍来自 native Session，adapter 不自己造一份聊天历史。

### 18.6 虚拟人主动消息

人物插件形成有来源的计划/到达事件 → 插件私有 mailbox 和投递门判断 → 在 Companion 适配边界调用原生 Session → 原生 Turn 执行并记 Journal → 共用 SSE 与 UI 投影。mailbox 管到达顺序，不能替代聊天正文权威。

## 19. 像上课一样练：七天源码学习路线

每天可以按 45—90 分钟安排；这是学习建议，不会自动启动任何任务或付费请求。

| 天 | 读什么 | 动手观察 | 你应该能解释 |
| --- | --- | --- | --- |
| 1 | 本文 1—4 章、main.tsx、app.py | 画出浏览器、Electron、Python、Provider 四个盒子 | 哪些是前端、后端和桌面控制 |
| 2 | api/chat.ts、sessions route、submit/schedule/worker | 只读搜索发送函数和 URL | 一条消息如何被接受并执行 |
| 3 | Journal、ConversationStore、projection | 在备份副本中观察表结构和事件类型 | 目录、正文、缓存为什么分开 |
| 4 | tools、authorization、PromptManager | 找一个读文件工具的注册与执行边界 | 模型怎样用工具，权限在哪里落实 |
| 5 | team_knowledge、semantic、embeddings | 手工计算两个三维向量的 cosine 与 RRF | RAG、向量、正式知识与来源关系 |
| 6 | agent_message、Kernel、chatroom、generic flow | 画 A→B 的投递/执行/回执状态图 | 不同协作方式的差异 |
| 7 | MCP、Skill、Electron main/preload | 沿快捷方式画启动链；复述一个完整例子 | 如何从 UI 问题定位到对应 owner |

### 19.1 练习一：只读查聊天提交

在你主动打开的 PowerShell 中执行，命令只搜索源码：

```powershell
Set-Location '<project-root>'
rg -n 'submitSessionMessage' web/src/api/chat.ts web/src/routes/chat
rg -n 'def session_submit_message|submit_session_message' core/web/routes/sessions.py
rg -n 'def submit_session_message' core/web/services/session
```

回答三个问题：POST URL 是什么？哪个函数是 route？真正的调度是否在 route 里面直接生成所有回答？

### 19.2 练习二：只读检查后端是否真的就绪

```powershell
$health = Invoke-RestMethod 'http://127.0.0.1:8000/api/health'
$health | Select-Object status, shellReady, routesReady, pid
```

示例使用默认端口 8000；实际使用前先通过项目 resolve-workbench 入口确认地址。健康检查不需要 Provider API Key，也不会发送模型请求。不要把整个配置文件或 control token 输出给别人。

### 19.3 练习三：看 SQL 表，不读取聊天正文

先使用应用支持的一致性备份/干净副本，不要把运行中的 SQLite 主文件单独复制后就假设数据完整。WAL 模式可能还有 `-wal/-shm`；项目的研究存储迁移代码也专门处理一致性快照。

在**备份副本**中可用数据库工具只读查看这些 SQL：

```sql
SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;
PRAGMA table_info(agents);
PRAGMA table_info(sessions);
SELECT COUNT(*) FROM sessions;
```

学习目的只是理解结构；不要对活库执行 UPDATE、DELETE、DROP 或手工 schema migration。表名存在与当前写入权威不是同义词，要回源码确认。

### 19.4 练习四：手工理解向量相似度

设 q=(1,0,0)，d1=(1,1,0)，d2=(0,0,1)。归一化后 cosine(q,d1)≈0.707，cosine(q,d2)=0。这里表达向量方向相近，不是“d1 有 70.7% 的事实正确率”。真实模型向量是学习得到的多维语义表示，维度通常没有可直接命名的中文含义。

再让某文档在向量排名第 1、BM25 第 5，RRF 为 `1/61 + 1/65`；另一个两边均第 3，为 `2/63`。自己比较，理解融合偏好，不把不同量纲的原始分数直接加起来。

### 19.5 练习五：阅读测试来理解边界

选择一类实现和对应测试一起看：

- Journal/会话：搜索 `test_turn_journal`、`test_session_submit`、`test_session_retry` 相关测试。
- RAG：`tests/test_rag_retrieval_service.py`、`tests/test_rag_vector_index_service.py`、semantic 相关测试。
- 授权：`tests/test_tool_authorization_execution.py` 等。
- 桌面：`desktop/electron/tests/fastWorkbenchCloseNative.test.ts` 与 lifecycle/IPC 测试。

先问“这个用例防止什么坏行为”，再看 mock 和断言。不要只记住通过的测试数量。

## 20. 如果以后要自己改功能，改动应该落在哪里

| 你想做的事 | 应先找的 owner | 要同时核对 |
| --- | --- | --- |
| 加按钮、调整人物/聊天布局 | routes + 公开 VUI API | 类型、可访问性、布局记忆、对应 route/layout 测试 |
| 新增 JSON API | route + Pydantic DTO + service | api/types、api 封装、权限/错误码与契约 |
| 新增 Agent 工具 | tools 实现 + Key_Tools 注册 | ToolPolicy、可见性、执行授权、结果与 Journal |
| 修流式内容错乱 | capture/Journal/publish + 前端 stream/active-turn | turnItems、turnId、ledgerSeq、终态校准 |
| 新增知识来源 | source inbox + canonical knowledge service | Owner、来源哈希、审核、失效、索引重建 |
| 修改向量检索 | embeddings/semantic/index boundary | 模型准备、维度、内容 hash、ACL、降级状态 |
| 改启动/退出 | Electron process/lifecycle/shutdown | 官方 Launcher 链、无控制台、活动任务与进程树 |
| 改 Agent 对话风格 | Agent persona/角色 Prompt、插件 Prompt | 现有快照、预算、工具权限不随 Prompt 擅改 |
| 接数据库 | repository/database 边界 | 事务、迁移、并发、备份、一致性与旧数据兼容 |

实际开发前请从根 AGENTS.md 和规范索引确认工作区与验证要求。这里的“代码位置”是学习导航，不代替该功能的 owner、权限边界或验收契约。

## 21. 常见错误理解与正确说法

| 容易说错 | 当前版本应怎样说 |
| --- | --- |
| 后端连接 MySQL 保存所有数据 | 主要使用 SQLite、JSONL、JSON 和文件，按事实分工 |
| 所有历史都在 SQLite | 目录/控制状态在 SQLite；transcript 仍在 Journal JSONL |
| 引入 LangChain 就是所有 Agent 都由 LangGraph 调度 | 普通 Agent 有现有 turn 循环；科研工作流有专门 LangGraph/Ledger 链 |
| 向量数据库就是储存完整文档的主库 | 当前文件索引保存派生向量和指纹，正式知识另有 canonical store |
| 有向量库就会自动 RAG | 还需要有效资料、权限、准备好的模型/索引和本轮检索路径 |
| README 写 BGE，所以当前一定跑 BGE | 当前源码默认 voyage-4-nano；模型实际就绪另查 health |
| Skill 就是一个新模型/插件权限 | Skill 是方法上下文，不会自动扩大执行权限 |
| MCP 是所有 Agent 之间的聊天协议 | 当前内部有 native messaging、Kernel、群聊与工作流；MCP 有明确外部网关等边界 |
| 选了 Agent 就等于选了 Session | 一个 Agent 可有多个 Session，要看具体目标地址 |
| 保存到 inbox 就等于目标处理完 | 投递、正文落库、唤醒、完成须分别看状态 |
| SSE 消息就是持久历史 | SSE 只是传输，Journal 才是 durable transcript |
| 桌面 EXE 里包含全部 Python/模型权重 | 官方 shim→Electron→后端形成启动链 |
| 浏览器关闭就停掉后端 | 浏览器标签页与后端进程生命周期分开 |
| 看见页面就说明后端正常 | 静态壳/缓存可能存在；还要看 routesReady 与业务请求 |
| build 成功就是已部署这个版本 | 需核实实际 serving build/commit 和运行进程 |
| AI 写“已完成”就表示执行成功 | 工具回执、Journal 终态、领域产物分别核实 |

## 22. 排错时照着走的顺序

### 22.1 页面打不开

快捷方式目标/项目路径 → 启动包装器日志 → 官方 Launcher → Electron 窗口与后端进程 → health → 前端 release 是否匹配。先不要反复换 API Key。

### 22.2 能打开但聊天不回复

发送请求是否被接受 → control token/HTTP 状态 → Session 是否运行/排队/等待审批 → worker 是否进入模型调用 → Provider 协议/连接/额度 → capture/Journal 是否有输出 → SSE 和前端 projection。区分“模型没产出”和“产出了但没显示”。

### 22.3 知识搜不到

资料是否仅上传待审 → Owner/Actor 是否匹配 → 审核与来源生命周期 → query_mode/effectiveMode → Embedding 准备状态 → 当前正文 hash/维度 → 是否真的调用搜索工具 → 命中片段是否足够 → 是否需要全文分页。

### 22.4 Agent 之间消息没生效

目标 sessionId 是否明确 → Agent 归属/组织与工具权限 → historyStatus/inboxStatus → wakeStatus 是否 busy/deferred → 目标 Turn 何时运行 → 产物/回复是否按任务交回。不要只看总线 UI 上出现一行。


### 22.5 用项目自己的诊断入口

`scripts/agent_log_context.py`、`diagnose_session_turn.py` 等能按 Session/Turn 找最小证据。避免把整份日志、完整 Prompt、密钥和会话正文随意复制到聊天或公开报告。日志字段应按问题选取；先诊断而不是先删除 `.runtime`、数据库和知识索引。

源码定位：[docs/guides/agent-log-routing.md](../../../docs/guides/agent-log-routing.md)；[scripts/agent_log_context.py](../../../scripts/agent_log_context.py)；[scripts/diagnose_session_turn.py](../../../scripts/diagnose_session_turn.py)。

## 23. 用于答辩或复述的完整解释

你可以这样解释这个项目，但要能指出后面的代码：

“Vibelution 是本地优先的多智能体工作台。React/TypeScript 构建页面，前端通过统一 API 客户端向本机 FastAPI 提交任务，并通过受保护 SSE 接收会话实时投影。后端以 Agent 配置、Session 和 Turn 分层，执行层组装提示词、历史和有权限的资料，使用统一模型协议层调用 Provider，再通过工具执行与授权边界完成动作。SQLite 管目录和控制状态，JSONL Journal 管对话事件；知识按归属和审核维护，FastEmbed 生成可重建向量索引并结合 BM25/RRF 检索。多智能体既有会话定向消息、项目 Kernel/Bus、群聊，也有持久化工作流。MCP 向外提供受管 Agent 调用，Skill 提供本轮方法上下文。Electron 复用 Web 界面并承担桌面启动、窗口、托盘与生命周期管理。”

如果老师问“为什么不用 MySQL”，可以回答：当前部署目标是本机工作台，嵌入式 SQLite 与文件型存储减少独立服务安装，同时用事务、单写者、Journal 和领域 owner 控制一致性；这不代表 MySQL 不能用，而是替换必须重新处理连接、事务、迁移、权限和事实源分工。

介绍二次开发时，应分别说明项目原有架构与自己实现的改动，并指向实际提交与验证。

## 24. 阅读索引与事实边界

本文关键事实优先依据当前实现，其次依据现行模块 README/ADR。以下文件适合反复打开：

1. `docs/agents/conversation-flow-map.md`：从发送到显示、事实源与单轨投影。
2. `core/web/services/session/README.md`：submit/worker/persist/publish 等分工。
3. `core/orchestration/README.md`：Agent 单轮 owner 地图。
4. `core/llm/PROTOCOL.md`：Provider、wire、协议和缓存边界。
5. `tools/README.md`：工具实现与统一授权链。
6. `core/web/services/memory_rag_services.md`、`team_knowledge/README.md`：知识/记忆职责。
7. `knowledge_embeddings.py`、`team_knowledge/semantic.py`：当前 Embedding 模型和真实排序。
8. `core/web/services/launcher_runtime.md`、`desktop/electron/README.md`：现行桌面控制面。
9. `core/web/services/team_workflow/research_runtime/README.md`：Ledger、checkpoint、回执与执行区别。
10. `docs/agents/mcp-managed-agent-gateway.md`：MCP 的受管范围。

说明：教程描述已核对快照中的实现，不承诺所有高级功能已在读者部署中启用。阅读时优先核对现行模块 README、ADR 和源码；升级后请用同名符号重新定位。

完整目录职责见[目录地图](directory-map.md)。目录摘要是导航线索，不代替每个文件的语义审计。

---

[← 上一部分](03-agents-and-desktop.md) · [教程目录](README.md) · [下一部分 →](05-runtime-deep-dive.md)
