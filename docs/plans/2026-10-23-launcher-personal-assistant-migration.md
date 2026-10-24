# Launcher 常驻个人助理完整迁移方案

- Status: PROPOSED，待实施；本文不表示迁移已经生效，也不替代现行 ADR。
- 日期: 2026-10-23，Asia/Shanghai。
- 初始化配置设计补充: 2026-10-24；对应本地源码基线 729f390f5，以下新增预设与初始化流程仍待实施。
- Launcher 产品形态与外部调研补充: 2026-10-24；本地基线 b1ecf1709；完整助理入口、打开即桌面形象和关闭常驻契约见第 8 节，外部固定源码与借鉴裁决见第 13.3 节。
- 代码基线: 245f325166f4ebde2a3b7b353f9b1e23fb8c1d24；这是本地核对基线，远端刷新因本机代理连接失败而未完成。
- 交付范围: 架构、职责、接口、数据迁移、实施依赖、验收、切换与回滚方案。本轮仅文档。
- 完成条件: M0–M7 全部关闭，原生桌面、真实模型、断线恢复和回滚演练均有证据；届时更新状态并按 [ADR 0005](../adr/0005-docs-authority-and-archive-policy.md) 归档。
- 约束: [AGENTS.md](../../AGENTS.md)、[开发标准](../standards/development-standard.md) 和原生业务服务继续持有权限、数据与生命周期权威。

## 1. 目标与产品边界

推荐架构是“Launcher 托管一个独立个人助理运行时，各项目保留自己的执行器”。助理的对话、偏好、模型绑定和恢复记录独立于项目；创建 Agent、运行团队、修改项目配置等操作仍由目标项目的原生服务执行。

产品形态进一步确定为：Launcher 提供个人助理的完整功能入口，用户主动打开 Launcher 或助理时即可看到桌面形象，点击形象唤起完整面板。桌面形象、完整面板和工作台快捷入口共享同一助理，不分别创建 Agent、会话或后台规划器。平台业务的执行权威仍在原生服务，无需再复制整套项目管理页面。

用户只需表达结果，例如“在项目 A 建一个开发、审查和测试团队并运行”“把项目 B 的 Agent 模型换掉”“重启项目 A，完成后继续刚才的任务”。助理负责识别目标、检查能力、执行、等待回执和报告结果。只有目标存在实质歧义、缺少凭据、超出授权或确需破坏性确认时，才提出一个合并后的问题。

### 1.1 必须实现的结果

| 场景 | 迁移后的行为 |
| --- | --- |
| 主动打开 Launcher，尚未启动任何项目 | 默认显示收起态桌面形象；完整助理、自己的设置和模型恢复入口可用；项目离线不阻断展示 |
| 使用个人助理的任何既有功能 | 从 Launcher 助理面板可达；桌宠提供快捷交互；不要求先打开项目设置页或启动默认项目 |
| 项目启动、停止、重启或构建失败 | 助理进程和对话保持可用；依赖该项目的步骤显示等待或失败原因 |
| 多项目和同项目多实例 | 操作绑定明确的 projectId、instanceId 和配置权威，不因窗口切换而改目标 |
| 关闭工作台、Launcher 主窗口、助理面板或桌面形象 | 只改变对应窗口的展示；助理由 Launcher 与托盘继续托管，明确退出 Launcher 才关停服务 |
| 新建 Agent、改配置、用户名、头像、壁纸、设置 | 通过已有受控动作完成，按真实作用域说明影响范围 |
| 一句话创建并运行团队 | 自动形成团队规格、创建角色、启动原生工作流并跟踪成果 |
| 连接中断或写入响应丢失 | 先查原操作和目标状态；不重复创建对象或启动团队 |
| 重启 Launcher 或升级助理 | 保存会话和操作状态；重新启动后恢复可确认的工作 |
| 未配置模型或模型失效 | 结构化恢复入口仍能启动、查看状态、修改连接；不承诺此时仍能自然语言推理 |

### 1.2 本次迁移不扩大的范围

首版限定当前桌面用户、已登记的本机项目和实例。退出 Launcher 后无需继续运行，不新增 Windows 系统服务，不开放公网控制口，不自动部署、发布或提权。普通 Agent、项目任务、团队执行、Git、项目记忆及其授权继续留在各自项目。Companion 隔离规则继续生效，桌宠展示不获得普通 Session 的额外执行权限。

## 2. 已核对的现状与迁移约束

| 当前实现 | 对方案的直接约束 |
| --- | --- |
| [ADR 0009](../adr/0009-launcher-control-plane-lives-in-electron-main.md) 将控制平面放在 Electron main，限制产品 Python 角色 | M0 先形成窄范围 ADR 修订，允许独立助理服务；不恢复旧 Python :8765 控制面 |
| [助理服务](../../core/web/services/personal_assistant_service.py) 按当前 Agent 目录查唯一助理，并读取直属 Session | 全局身份需要新作用域；不能把外部 Agent ID 填进旧工具绕过校验 |
| [后端生命周期](../../core/web/lifecycle.py) 启动助理巡检，退出时关闭执行资源 | 新助理不得挂到工作台 startup/shutdown 和项目进程组 |
| [Session facade](../../core/web/services/session_service.py) 和 [directory runtime](../../core/web/services/session/directory_runtime.py) 有根目录和 Store 单例 | 每个进程固定一个运行根；禁止在同一助理进程内反复切换项目全局变量 |
| [Journal](../../core/chat/turn_journal.py) 能按根目录读写；完整 Session 链仍有项目依赖 | 可以复用原生 Session 引擎和 Journal，仍需独立启动宿主与隔离证明 |
| [存储解析](../../vibelution_storage.py) 默认按项目和实例分目录，也支持全局覆盖 | 新增独立助理路径解析；禁止用全局 data_home 覆盖把现有项目合并到同一目录 |
| [桌宠窗口](../../desktop/electron/src/windows/petWindow.ts) 和设置读取仍依赖工作台 origin | 面板、桌宠资源和数据连接都必须迁离项目 origin |
| Launcher 的随包页面、工作台个人助理页和桌面助理页属于不同入口；当前桌宠需显式 openPet，关闭时销毁窗口 | 需要 Launcher 专属助理入口、启动显示与隐藏规则；保留 BrowserWindow 不能证明项目停机时聊天仍可用 |
| 现有工作台 Job 随 workspace 终止整组进程 | 复用无控制台启动原语，新增助理专属 owner 与进程组 |
| 模型目录属于外部 operator config；事务已有锁和校验 | 复用同一配置真源及事务，新增全局助理引用保护；不复制一套可编辑 Provider 目录 |
| [工具审批](../../core/web/services/session/tool_approvals.py) 的 pending、Session grant 以及低风险操作窗口当前是进程内状态 | 旧临时批准不能跨进程或改绑到新 Session；持久 ToolPolicy 与待处理意图分别迁移 |

### 2.1 当前 API 基线

上一轮基线记录了 738 个已注册 HTTP operation：24 个只读网关映射、42 个原生动作映射、672 个受限、专用或尚未映射的 operation。另有 32 项新增语义动作完成真实模型实测。语义动作数量和 HTTP operation 数量不能相加，也不能据此宣布全量 API 已接入。

这些数字只表示上述代码基线和验收快照。实施时必须从目标实例的注册 OpenAPI 与动作注册表重新生成清单；接口文档存在、工具可见、获得授权、实际执行成功分别验证。迁移关闭要求已接入能力完整迁移，并对全部注册 API 给出可解释的支持状态；剩余可面向用户开放的能力按业务分组补齐，不要求把内部接口全部暴露。

## 3. 推荐架构与运行方式

~~~mermaid
flowchart TB
    U["Launcher 完整助理面板"] --> E["Electron main：身份校验、生命周期与连接代理"]
    V["桌面形象：打开即显示"] --> E
    V -.->|"点击唤起同一助理"| U
    E <-->|"私有运行通道"| A["独立 Python 助理服务"]
    A --> S["助理专属存储：原生 Session、偏好、操作记录"]
    A <-->|"受控项目请求"| B["Electron main 项目连接代理"]
    B --> P1["项目 A 原生 API 与执行器"]
    B --> P2["项目 B 原生 API 与执行器"]
    P1 --> D1["项目 A Agent、Journal、团队与任务"]
    P2 --> D2["项目 B Agent、Journal、团队与任务"]
~~~

图中的 E 与 B 是同一 Electron main 的不同职责。连接代理在确定性代码中校验请求并调用目标，不运行第二个规划模型，也不建立第二套项目任务状态。

### 3.1 进程与发布包

1. 一个桌面用户、一个 Launcher owner、一个常驻助理服务。Electron 单例锁之外增加 profile 级服务租约，绑定 PID、进程创建时间、releaseId 和启动 nonce；端口存在不能作为接管依据。
2. 助理运行在独立、版本化的 Python 包和依赖环境中。工作目录、模块搜索路径、解释器及 UI 资源均不依赖当前项目 checkout、项目 .venv 或工作台 web/dist。
3. 首版复用现有 Python Session/LLM 能力，不把执行链重写成 Node，不引入 LangGraph 或 Agents SDK 作为新的运行内核。
4. 固定一个助理专属原生运行根，在初始化任何 Session/Agent 单例前解析完成。它只承载全局助理，不装载不同项目的 Session Store，也不启动项目科研、团队恢复、构建和代码索引后台任务。
5. 独立 bootstrap 只组合助理所需模块；不得直接启动完整工作台 app，再期待开关关掉全部副作用。
6. 产品启动采用 pythonw 或现有无控制台原语，shell=false，并使用助理专属进程 owner。项目 stop/restart/reap 不得覆盖该 owner。
7. 服务就绪分为 process_alive、transport_ready、session_ready、model_ready。前三项完成后才允许提交对话；model_ready 失败进入可恢复状态，不能用 HTTP 200 代替模型可用证明。

子进程环境按明确清单构造，清除项目 PYTHONPATH、PYTHONHOME、Git hook 上下文及意外数据根覆盖；配置源由已验证的 configAuthorityId 解析。保留必要的用户网络和凭据解析环境，不把整个项目环境当作可信启动配置。

### 3.2 服务通信

为保留现有 Session DTO 和事件形状，首版采用“私有 loopback 助理 API + Electron IPC 代理”。Python 仅监听 127.0.0.1 的动态端口，不使用固定 :8765，不提供 Launcher 实例注册、项目生命周期或桌面窗口控制接口。

- Electron 通过继承的私有管道完成 bootstrap、传递一次性会话凭证，并接收协议版本、端口、profileId、releaseId 和健康信息。凭证不得放在 argv、URL、日志或 renderer。
- 助理 API 的业务和事件请求全部认证；不沿用公开 control-token 获取入口，不设置宽泛 CORS。Electron 对每条 IPC 校验 sender、主 frame、窗口角色和参数。
- 面板和桌宠只使用窄的 typed IPC 方法，由 main 转发对话与事件，不获取项目或助理 token。
- 助理向 Electron 发起项目连接、生命周期及动作请求，走同一私有管道的反向 RPC；RPC 使用闭合 method，不接收 shell、任意 URL、任意文件路径或自由 HTTP method。
- 帧必须有 requestId、长度上限、超时和取消语义；日志走独立输出，不混入协议。启动测试必须验证 pythonw 的继承句柄，不能假设 sys.stdin/stdout 始终可用。
- 协议与 API 分别版本化。主版本不兼容时拒绝执行并提供恢复入口；未知可选字段可忽略，未知动作默认拒绝。
- 原生 Session 事件只增加传输适配。事件携带 sessionId、turnId、seq 和 cursor；断线按原生 Journal 水位重放，缓冲超限返回 resync_required。不得由 IPC 或全局操作表生成另一份 transcript。

私有 HTTP 只承载助理 Session 与展示服务；项目 start/stop/restart 和进程回收仍只由 Electron main 执行。因此需要扩展 ADR 0009 的 Python 服务角色，而不是迁回 Python Launcher 控制平面。

## 4. 数据归属与配置权威

### 4.1 唯一写入者

| 数据 | 写入权威 | 迁移规则 |
| --- | --- | --- |
| 全局助理身份、人物和 ToolPolicy | 助理专属原生 Agent 目录 | 一个全局对话身份；显示名与稳定 profileId 分离 |
| 全局助理对话 | 助理运行根中的原生 Session Journal | 同一 Session 引擎读写，不以消息缓存替代 Journal |
| 助理偏好、桌宠选择、主动程度 | 助理专属设置服务，带 revision | 复用现有字段与校验；只迁移选定来源 |
| 助理模型绑定 | 全局助理原生 Agent 配置 | 从共享模型目录引用，保留显式选择和版本 |
| Provider、模型目录、用户名、全局主题等 operator 设置 | 现有外部 operator config 与原生事务 | 不复制第二套可写 TOML，不改变旧字段原有作用域 |
| 项目 Agent、团队、Session、任务成果 | 目标项目原生 service/Journal/WorkRun | 不迁入全局助理目录 |
| 项目 Inbox 和业务回执 | 原生 Kernel/Inbox/执行器 | 全局侧只保存关联 ID、状态投影、游标和证据引用 |
| 项目/实例注册与生命周期 | Electron main 原生注册表与命令队列 | 助理不得自行改 instances.json |
| 全局操作记录 | 助理 OperationStore | 只管理请求与恢复，不取代目标对象状态 |
| 旧助理历史 | 经验证的只读原生历史归档；旧文件保留为回滚源 | 不拼接不同来源 Journal，不重放旧工具调用 |
| 头像、壁纸、附件 | 对应作用域的原生资产服务 | 使用稳定 assetRef，禁止把项目临时 URL 当作全局资产 |

### 4.2 助理存储布局

新增专用路径解析器。建议默认位于 %LOCALAPPDATA%/Vibelution/assistant/profiles/<profileId>/，遵循后续明确记录的单独覆盖配置。这个路径及覆盖项是待实现设计，当前产品尚无此约定。

| 子目录或文件 | 用途 |
| --- | --- |
| profile.json | profileId、schemaVersion、迁移来源和当前 owner epoch；不镜像 Agent 可编辑配置 |
| data/ | 助理原生运行根所需的 Agent、Session、插件账本与设置 |
| assets/ | 已验证并归属助理的头像、附件及展示资产 |
| operations.sqlite | 操作、步骤、去重键、审批关联、回执游标；使用原生 SQLite/helper 和事务 |
| migrations/ | 迁移 manifest、哈希、状态和回滚检查点 |
| runtime/ | 租约、短期连接、进程 owner 和就绪记录 |
| logs/ 与 cache/ | 有界诊断与可重建投影，不承担业务权威 |

路径解析不能靠删除 project identity 后让旧函数回退到源码根，也不能向父进程设置 VIBELUTION_DATA_HOME。助理进程的根在启动后保持不变；现有普通项目路径行为保持不变。

### 4.3 模型与共享配置

- 复用 config/operator_config_transaction.py 的跨进程锁、CAS、字段级修改、校验和回滚；证明助理与两个工作台同时修改时不会丢失更新。
- 为每个实际配置源生成不暴露路径和密钥的 configAuthorityId。同名 projectId 不代表使用同一 operator config；批准和回读均绑定真实配置权威。
- 助理拥有独立模型绑定和最后一次验证可用的连接快照；快照记录模型 ID、协议参数和 credentialRef，不复制明文密钥、不成为第二个模型编辑目录。
- 模型删除、Provider 删除和引用扫描必须覆盖常驻助理及其运行中 Turn；项目离线或引用权威不可确定时，不宣称“没有引用”。
- 使用既有凭据解析。缺凭据时通过受保护的凭据入口补充；不让模型读取密钥，不在普通对话中要求用户粘贴密钥。
- 模型正在使用时，修改后的默认绑定对后续 Turn 生效；正在执行的 Turn 保持受理时快照。
- 切换助理自身模型先做真实连接验证，再事务提交绑定；失败保留原绑定。备用模型必须是用户已授权的候选，不静默切到新的供应商。
- 模型完全不可用时保留确定性的连接修复、状态查询、项目启动和日志摘要入口。自然语言能力恢复以真实模型调用为准。

### 4.4 初始化配置的来源与作用域

初始化配置属于迁移交付范围。首版只适配现有原生配置定义，不新建通用 Agent 配置框架，不在 Launcher 维护第二份 persona、Prompt、ToolPolicy 或模型目录。以下是拟议初始化契约；表中现有默认值是复用起点，不表示全局运行根与 bridge 初始化已经实现。

| 对象 | 配置来源与落点 | 首次创建规则 |
| --- | --- | --- |
| 常驻个人助理 | [personal_assistant_service](../../core/web/services/personal_assistant_service.py) 的角色、PERSONA、TASK、current_policy 与原生 Agent/直属 Session | 一个 profile 一个对话身份；迁移选定来源时保留其配置，只有全新安装才采用默认值 |
| 项目代理身份 | 目标项目唯一的原生 PA Agent、Session、Inbox 与原有策略 | 复用既有身份并显式切入 bridge；缺失时走原生 bootstrap，不能按每次连接重新创建 |
| 普通协作 Agent | [pa_platform_actions](../../tools/pa_platform_actions.py) 的创建动作与原生 Agent 配置 DTO | 用户要求新 Agent 时按任务创建；不在首次启动时预建一组空闲 Agent |
| 团队与角色 | [team_template_service](../../core/web/services/team_template_service.py)、原生角色定义库和 [pa_team_actions](../../tools/pa_team_actions.py) | 按目标项目模板按需实例化，复用原生角色、模型绑定、权限预设及运行入口 |
| 用户资料、主题、壁纸与凭据 | 各自现有 operator config、资产或凭据服务 | 读取并保留原值；不作为 Agent 预设复制或重置 |

Launcher 只负责编排初始化和展示结果。配置写入仍通过各自 service，配置页面与自然语言动作读取同一原生记录。模板目录与能力说明从现有注册表投影，避免再手工维护一套角色清单和工具白名单。

### 4.5 常驻助理的初始预设

| 配置项 | 全新安装的初始设计 | 复用与约束 |
| --- | --- | --- |
| 身份与会话 | 显示名“个人助理”；沿用 personal_assistant 角色、prompt-chat-default 与原生直属 Session | profileId、Agent ID 和 Session ID 稳定；改名不换身份，重复启动不新建会话 |
| 人物与任务 | 中文先给结论，执行已授权操作、跟踪派遣与成果，遇到必要决策再集中提问 | 复用现有 PERSONA/TASK；不另写一份整段系统 Prompt，不把人物设定当授权 |
| 展示 | characterId=dafeiyu；showStatus/showTitles/showCompletion=true；idleMessage 为空 | 复用 DEFAULT_PREFERENCES；头像、桌宠与壁纸分别使用正确作用域的 assetRef |
| 对话偏好 | speakingInitiative=natural、questionInitiative=natural、preferenceProposalMode=ask_first | 复用[既有偏好归一化](../../core/agent_plugins/virtual_human_life/companion_preferences.py)及 Agent-scoped 设置；不修改普通 Session 核心 |
| 模型 | 优先采用选定迁移来源的有效绑定；全新安装使用同一配置权威下已配置的默认模型 | 复用 default_session_llm_bindings 与现有参数校验；首次连接真实探测，缺失或失效才集中选择/修复 |
| 工具 | 使用现有 PA 工具集合与动作注册表，保留查询、设置、派遣、团队和个人事务入口 | 工具出现不代表可执行；目标项目、动作 ACL、原生审批与桌面控制同意仍分别校验 |
| 写入与网络 | 现有 private 写入范围、restricted 网络、controlled mutation 为起点 | 能在当前授权内完成的步骤连续执行；只有新增权限或必要歧义才集中询问，不预置任意 HTTP/全盘写入 |
| 单轮资源 | 沿用 web_chat.personal_assistant_max_calls_per_turn，当前默认 16 次工具调用 | 上下文、输出长度、推理参数和超时沿用原生模型/Agent 配置；不另造一套高配默认值 |
| 派遣与唤醒 | 保留 allowSubagents=false、allowWakeMessages=false；跨 Agent 派遣仍走原生消息工具 | 两个开关不等于关闭派遣。受控巡检与事件调度另有边界，不能为“主动”而全部打开 |
| 记忆与个人事务 | 助理自己的 private memory、偏好和事务账本；迁移来源及 revision 可追溯 | 不汇总其他 Agent 私有记忆；按第 7 节迁移唯一来源，不重新生成历史或旧提醒 |
| 项目范围 | 只使用已登记项目及明确的目标授权；当前对话可固定默认目标 | 安装成功不等于获得全部项目写权限；排队任务保留受理时目标，不跟随当前窗口漂移 |
| 空闲与通知 | 复用已有通知偏好、冷却和催办上限；空闲不调用模型 | “常驻”只保证可用；不预建团队、不轮询所有项目、不以无界模型循环维持在线 |

没有可用模型时仍完成身份和存储初始化，展示可操作的连接修复入口，并保持 model_ready=false；不提交无法执行的自然语言 Turn。密钥只进入已有受保护入口。模型已可用时不重复要求用户填写 Provider、模型和人物信息。

项目代理复用原身份的工具策略、对象权限与 Inbox；bridge 模式只接收受认证委托及转交原生回执，不运行第二个规划模型、巡检或自主派遣循环。已禁用、归档或自定义零工具的身份保持原状，不能通过重建身份绕过；只有明确处理冲突后才启用相应能力。

### 4.6 新建 Agent 与团队的初始预设

普通协作 Agent 与开发团队必须采用不同的原生预设。当前 agent_create 默认是 assistant_worker、prompt-chat-default、request_approval 权限预设，仅启用 agent_message_tool；网络为 none、写入为 private、mutation 为 controlled，工具调用上限为 8，allowSubagents=false、allowWakeMessages=true。它适合接收任务和返回结构化回执，创建成功不能作为具备文件编辑、测试或 Git 能力的证明。

用户说“新建一个 Agent 帮我做事”时，助理根据任务选择现有可用预设，并补齐以下配置；可从已知上下文确定的内容不再逐项询问。

| 配置组 | 自动补齐规则 | 必须保留的边界 |
| --- | --- | --- |
| 目标与身份 | 固定项目/实例、显示名、原生 roleKey、职责；保存来源操作与稳定 requestId | 不跨项目复用对象 ID；重复指令的恢复不能再次创建 |
| 模型与参数 | 绑定目标配置权威下可解析且已授权的模型；能沿用有效默认值时直接复用 | 不把另一配置源的 modelId 当有效绑定；不自动创建付费 Provider 或换供应商 |
| 任务与验收 | taskProfile 写明目标、输入/输出、范围、成功证据、停止条件和回执关联 | 原生 Session 保存正文；配置和操作记录只保存所需字段及引用 |
| 工具与权限 | 根据原生角色/权限预设选择完成任务所需能力，再计算实际有效 ToolPolicy | 权限提升按既有规则处理；不能通过创建新 Agent 获得超出来源授权的能力 |
| 执行资源 | 复用原生模型参数、工具上限、超时、团队并发配置和已有预算控制 | 未设置价格或总预算时不虚构成本承诺；派遣链不自行放大并发或调用额度 |
| 记忆与反馈 | 各 Agent 保留自己的私有记忆；回执绑定来源消息和个人助理任务协议 | 不共享私有 memory 目录，不把消息投递成功当作任务成果 |

一键团队首版复用当前 dev-team 模板，其规划、开发 A、开发 B、评审角色从原生角色库读取。现有 PA 工作流按角色串行执行；并行开发、独立测试角色和自动合入都不属于当前已验证能力。一键开发团队交付必须选择并验证具备相应工作目录、工具及授权的原生执行预设；缺少执行预设时列为 M5 的交付缺口，仅有消息权限不能宣称已能开发。角色数量、模型覆盖和权限变更集中生成一次差异，已在授权内的默认组合直接创建并运行。

启动运行前读回每个成员的实际模型绑定、有效工具、权限范围、工作目录和任务职责；有成员无法执行其职责时不启动整套工作流。运行验收同时检查原生运行状态与实际成果；涉及开发时还需文件、测试等证据，不能仅以四个角色都回复文字作为开发成功。

### 4.7 初始化、升级与恢复

1. **先检查再创建**：解析固定运行根和 configAuthorityId，查已有 profile、原生身份、直属 Session 及迁移记录。有旧数据先走选定来源迁移，不把“启动新进程”当成“全新安装”。
2. **显式且幂等地应用**：沿用原生 setup 状态，按 profile/目标项目和稳定初始化键锁定；记录原生 ID，逐项创建或恢复。GET/页面轮询不触发初始化。重复启动、并发窗口和中途崩溃不得产生第二个助理或直属 Session。
3. **区分完成程度**：持久化身份、配置和 Session 后才标记 session_ready；模型探测通过后才标记 model_ready。失败保留 pending 和明确原因，只恢复未完成步骤；重复身份或绑定冲突不靠删除、重建自动解决。
4. **验证生效值**：从原生服务读回 persona/task、偏好、模型、ToolPolicy、有效可执行工具和直属 Session。在隔离验收中用真实模型完成一次有证据的查询及一项已授权、可恢复的受控写入；配置保存成功不能替代行为验收。用户首次安装只做必要连接探测，不为自检创建业务对象；后续普通启动复用有效状态，不自动重复模型验收。
5. **保护用户修改**：拟议在原生 Agent metadata 记录 presetId、presetVersion、系统写入字段与 provisionedFingerprint，复用 revision/CAS；这些只是来源信息，不是另一份可编辑配置。升级只迁移可证明未修改的默认字段，用户改过的姓名、人物、偏好、模型、零工具策略等原样保留。
6. **权限变更单独判断**：新增工具、项目授权或网络/写入权限不能仅因预设版本升级自动启用。复用既有精确历史快照升级规则，并在 M0 固化允许自动迁移的字段；无法确认来源时保留现状。
7. **重置有明确范围**：用户要求恢复默认时，先计算对应 Agent/预设字段差异，按原生授权应用；不连带删除会话、记忆、凭据、团队或任务。升级和重置均保存可读回的版本及结果。

这部分只新增独立运行根适配、bridge 状态和必要初始化元数据；复用现有创建、模型绑定、配置事务、直属 Session、角色模板与任务去重。M0 先列出可以直接调用的原生入口及缺口，避免先复制全部默认配置，再长期维护两套初始化逻辑。

## 5. 项目连接与受控 API

### 5.1 项目寻址

连接代理只解析已登记项目和实例。模型提供 projectRef 或明确的目标对象，不能提供网络地址。内部请求固定携带 projectId、instanceId、instanceGeneration、configAuthorityId、capabilityRevision。

默认目标可继承本次对话明确固定的项目。执行前展示或在操作回执中说明目标；切换工作台窗口不会修改已排队操作。两个项目重名、目标实例改变、配置源改变或对象已移动时，重新核对，不能猜测。

项目离线时，已授权操作可经 Launcher 原生命令队列按需启动该项目，并等待 routesReady、身份和能力握手。只为读取缓存状态时不唤醒项目。只有新建或管理未登记目录时才走单独的项目登记流程。

### 5.2 身份与权限适配

推荐使用“一个全局对话助理 + 每项目一个受控原生代理身份”。项目侧复用合法的 canonical PA Agent/Session 作为消息来源、Inbox 和权限载体；它进入 bridge 模式后不再独立运行规划模型或巡检。项目没有可用身份时，通过显式原生 bootstrap 创建，用户禁用、自定义零工具和自定义策略不能被自动覆盖。

全局调用通过新的受认证入口取得目标域短期委托。目标服务重新校验全局 profile、项目代理身份、目标对象和有效权限，创建受审计的 gateway 执行上下文，随后调用提取出的原生动作 service。旧 personal_assistant_tools.py 继续严格校验本地唯一助理，不接受外部传入 Agent ID 或一个 governed=true 作为授权。

有效权限是全局助理策略、项目授权、项目代理策略、动作能力和原生对象 ACL 的交集。新 gateway 是独立执行入口，必须进入原生最终授权检查与测试清单；不能通过伪造普通聊天 Turn 或直接调用未鉴权 handler 绕过 ToolExecutor。

现有按 (agent_id, action) 记忆的低风险操作窗口，需要在新入口绑定 profileId、projectId、instanceId、作用域、动作和到期时间。项目 A 的批准不得用于项目 B。权限提升、远端 push/PR/发布、破坏性删除仍按既有规则处理。

M3 可为新 gateway 增加专用持久审批回执，绑定上述作用域、参数 hash、策略/配置版本与到期时间，重启后仍需目标原生授权重新校验。它不能替代原生执行检查，也不能改变普通 Session 临时 grant 的语义。若目标批准已经过期或丢失，重新 prepare 并按当前原生策略请求批准；全局操作表中的 approvalRef 本身不构成有效授权。

### 5.3 拟议能力和动作契约

以下是设计中的逻辑接口，路径和字段尚未在产品实现；M0 输出正式 DTO/OpenAPI，禁止把本节当成可调用 API 文档。

| 逻辑操作 | 必需信息 | 返回与约束 |
| --- | --- | --- |
| projects.list/get | 用户级身份、分页与过滤 | 登记项目、实例、连接状态、最后确认时间；不暴露 token |
| project.capabilities | 明确目标、协议范围 | operation/action、schema、风险、作用域、支持状态、版本与恢复能力 |
| action.prepare | action、结构化参数、目标、operationId | 参数校验、差异、原生 revision、approvalRequired；不产生业务写入 |
| action.execute | prepareId、相同参数摘要、授权引用、原 revision | operationId、受理状态、native IDs；202/accepted 不代表完成 |
| operations.get/reconcile | operationId、同一目标 | 原生读回结果、证据和下一步；不会自动重新发出写入 |
| operations.cancel | operationId、预期状态、原生 Turn/run ID | 取消观察或请求原生停止；区分两者 |
| events.subscribe | 用户身份、项目过滤、cursor | 有界元数据事件与来源引用；过期 cursor 要求快照重建 |

每个能力描述至少包含作用域、前置条件、参数 schema、风险、副作用、授权方式、原生 owner、幂等模式、成功证据、超时与恢复方式。字段投影来自现有动作和注册 OpenAPI，不维护第二份手工全量接口清单。

保持旧工具名和已接入参数语义。先新增版本化 gateway，再迁移 Launcher/桌宠/工作台消费者；旧 HTTP 面在兼容窗口内保留原行为。旧入口若无法代理，返回结构化 assistant_moved 与受信任的导航提示，不能静默执行在另一项目。

### 5.4 API 覆盖补齐

| 能力组 | 迁移要求 | 验收重点 |
| --- | --- | --- |
| 助理偏好、用户资料、头像、壁纸、普通设置 | 区分 assistant、operator、project、instance 作用域；复用资产服务 | 一句话修改与原生回读、界面同步、重启后保持 |
| Agent 创建、配置、模型、会话与任务派遣 | 保留字段白名单、revision、工具授权和原生通信 | 正确项目、无重复创建、自定义权限不漂移 |
| Provider/模型目录与默认模型 | 保护 credentialRef、全局引用和正在运行的 Turn | 真实探测、原配置回退、跨进程并发、助理自身可恢复 |
| 团队、房间与工作流 | 使用 native IDs 和稳定幂等键 | 部分创建、运行中断、成果核验、重复请求不重跑 |
| 项目启动/停止/重启、实例切换 | 只经 Electron main；保留 active-work guard | 项目重启不影响助理；停止受理和实际终态分开 |
| 知识、研究、诊断和其他专用能力 | 按业务动作与安全字段投影逐类接入 | 私有内容权限、分页/预算、未支持原因可解释 |
| 凭据、管理授权、内部维护、破坏性操作 | 保留专用受保护入口或显式拒绝 | 不因“覆盖 API”获得任意 HTTP 写入和提权能力 |

完成率同时报告用户场景覆盖、语义动作覆盖、HTTP operation 映射与真实模型通过项。分母固定代码和能力版本；只读发现结果不计为执行通过。

## 6. 操作记录、派遣与失败恢复

### 6.1 全局 OperationStore

使用独立的事务性 SQLite 操作表，复用项目现有 SQLite 基础设施，不引入分布式工作流引擎。主键和唯一约束覆盖 (profileId, targetScope, operationId)，步骤键由父 operationId 与稳定 stepKey 派生。

必要字段包括 action、参数摘要、目标身份、capabilityRevision、预期 revision、授权引用、状态、native IDs、最后确认时间和 evidenceRefs。为恢复保留的有界结构化参数仅在服务端私有业务存储中保存；不把凭据、完整组装 Prompt 或项目 transcript 复制进操作表和诊断日志。

状态采用 prepared、awaiting_approval、submitted、running、waiting_for_project、reconciling、completed、failed、cancelled、unknown。每次状态转换 CAS 更新；原生业务状态与操作记录不一致时以原生来源为准。unknown 必须可见，不能被普通超时包装为失败后自动重做。

操作策略按动作声明：

- read_only：允许有界重试。
- native_idempotent：同一原生幂等键重送，目标保证去重。
- cas_write：先读 revision，只有预期版本匹配才写。
- non_replayable：丢失确认后只 reconcile；无法核实时暂停，不自动重送。

本方案不承诺跨进程崩溃下的普遍 exactly-once。只有目标端持久去重或可证明的 CAS 允许安全重试；项目侧进程内锁不能替代跨进程保证。

### 6.2 一句话操作的正常路径

~~~mermaid
sequenceDiagram
    participant U as 用户
    participant A as 常驻助理
    participant E as Electron 连接代理
    participant P as 项目原生服务
    U->>A: 在项目 A 建团队并运行
    A->>E: 解析目标与能力
    E->>P: 校验实例身份和授权
    P-->>E: 能力、revision 与受控代理身份
    E-->>A: 返回已验证目标与能力
    A->>A: 保存 operationId 与分步规格
    A->>E: prepare / execute
    E->>P: 转发受控原生动作
    P-->>E: 原生对象 ID、运行 ID 和后续回执
    E-->>A: 转发有界状态与证据
    A->>E: 请求原生读回核验
    E->>P: 查询已记录的目标
    P-->>E: 原生状态
    E-->>A: 核验结果
    A-->>U: 完成结果或明确待处理步骤
~~~

所有项目消息均经 Electron 项目连接代理转发；助理不直接获取项目 token。

### 6.3 团队搭建与派遣

一次用户指令生成一个父操作，包含目标、角色、职责、模型、预算、并发上限和成功条件。能用现有模板时自动补全；权限与预算超出当前授权时只集中确认差异。

创建团队、创建成员、绑定角色、启动 native team_run 分别记录稳定步骤和原生 ID。失败时展示已完成步骤，只继续未完成且可证明安全的步骤。只允许补偿本次创建且未被使用的对象；运行中团队或已产生用户成果的对象不得自动删除。

“运行成功”以原生 workflow/WorkRun 与成果验收为准。工具调用结束、普通 Agent Turn 结束、Inbox 投递成功分别只能证明该层完成。既有 personalAssistantTask 结构化回执及 replyToMessageId 继续承载业务完成关联，全局操作表只索引这些引用。

项目侧代理身份保留原生 Inbox。迁移前已派出的任务继续回复原来源身份；新助理通过受控 relay 读取自己的既有回执和游标，不改写发送者、不扫描其他 Agent Inbox、不复制一套消息系统。

### 6.4 故障处理表

| 故障点 | 必须采取的行为 |
| --- | --- |
| 请求尚未发送，项目断开 | 保存步骤并等待该目标恢复；允许用户撤销 |
| 写入发出，响应丢失 | 标记 reconciling，按 operationId/native IDs 查询；无幂等证据不重发 |
| 项目重启或实例 PID 改变 | 重新握手 instanceGeneration、权限和能力，再核对原对象；不把同端口当同实例 |
| 原生停止请求已受理 | 等待目标 turnId/runId 的终态；不能立即报告“已停止” |
| 助理崩溃或电脑异常退出 | 原生 Journal 恢复对话；OperationStore 对未终结操作逐项读回 |
| 模型请求中断 | 标记本轮中断；按原生失败恢复/重试语义继续，不重放已完成写入 |
| 授权被撤销、对象 revision 改变 | 立即停止后续步骤，保留结果；按新的差异重新准备 |
| 事件 cursor 失效 | 读取有界原生快照并重建游标；不靠全量高频轮询 |
| 一个项目不可用 | 仅阻塞该项目的依赖步骤；其他项目和助理对话继续 |
| 用户暂停/取消 | 停止新步骤；已开始的原生任务分别请求停止并核对结果 |

## 7. 旧助理数据迁移与单一 owner 切换

### 7.1 迁移前清点

只清点用户选定的已登记项目及实例：canonical PA 身份、直属和历史 Session、设置 revision、模型绑定、ToolPolicy、个人事务插件账本、附件、未完成派遣、持久策略和待审批意图。旧临时批准只作审计，不作为可恢复授权。记录数据解析来源，不扫描全部用户目录。

只有一个合法来源且目标为空时可给出默认推荐。存在多个助理、归档身份、自定义提示或策略冲突、同名不同项目时，展示来源及差异并让用户一次选择；不得按“最新”自动合并。零工具、禁用状态和用户自定义配置保留。

### 7.2 迁移状态机

~~~mermaid
flowchart LR
    I["inventory"] --> P["prepared"]
    P --> Q["source_quiesced"]
    Q --> C["copied"]
    C --> V["verified"]
    V --> S["switched"]
    S --> F["finalized"]
    P --> R["rollback_pending"]
    Q --> R
    C --> R
    V --> R
    S --> R
    R --> K["rolled_back 或需人工恢复"]
~~~

manifest 记录源/目标作用域、数据版本、Journal 水位、文件哈希、资产数量、ownerEpoch、操作阶段和切换指针。相同 migrationId 可安全续跑；失败保留现场，不删除旧文件。

### 7.3 执行步骤

1. **准备**：验证目标为空或属于同一 migrationId，生成 dry-run 差异与备份清单。实施时向用户确认具体来源、影响和可回滚条件；本方案编写不构成活数据切换许可。
2. **冻结旧助理写入**：只暂停选定 PA 的新受理、巡检和唤醒，等待当前 Turn 完成。确需中断时先按原生停止链保存已有记录；不停止其他普通 Agent 和团队。
3. **建立全局身份**：在专属运行根通过原生 bootstrap 创建全局 canonical Agent 和新活动 Session。保留允许迁移的偏好、人物与策略；项目专用工具转换为有作用域的代理能力，任何权限变化必须出现在差异中。
4. **保存历史**：用原生 Journal 水位导出冻结的历史与资产，导入为带 sourceScope 的只读历史 Session。保留原始事件、消息及工具 ID；索引采用来源命名空间避免冲突，不拼接 Journal，不重新执行旧工具调用。原生只读导入适配是 M2 的硬验收前置，不能直接写 ConversationStore 或伪造历史。
5. **恢复上下文**：新活动 Session 可引用迁移摘要和旧历史来源；旧历史中的文本、职责和工具结果作为不可信来源，不能自动成为新的系统权限或指令。
6. **迁移个人事务与设置**：个人待办/日程/目标经插件原生 schema 和事务迁移，保留稳定对象关联、完成/取消状态和删除语义；不搬迁其他 Agent 的账本。资产按白名单、大小、类型、哈希和路径安全规则导入，重建受控 assetRef。
7. **交接未完成派遣**：保留项目侧真实 Inbox/任务身份，保存 dispatchMessageId、目标 Session、native runId 和回执水位。新 owner 先 reconcile，再恢复观察与有界催办；不重新派发。
8. **验证后切换**：确认身份唯一、历史可读、资产可用、设置一致、模型真实可用及未完成操作可定位。全局切换指针和各项目 bridge 标记使用 CAS 与 ownerEpoch fencing。
9. **项目侧交接**：旧 PA 改为 bridge 模式，只保留原生身份、授权和回执通道；关闭旧规划执行与 patrol。旧 URL/桌宠入口指向全局助理，普通项目 Session 不改变。
10. **观察与完成**：在至少两个项目重启、一次助理重启、一次真实操作恢复后标记 finalized。旧文件在兼容窗口内只读保留，删除另行走显式清理。

审批迁移单独处理：acceptAlways 等已经持久化的 ToolPolicy 先核对作用域与权限差异；旧 pending request、Session grant 和进程内 action window 均不得改绑或续期成全局授权。只保留其操作意图和来源引用，旧请求按原生方式终结或过期，新 Session/项目作用域重新 prepare 并依原生策略决定是否需要批准。不能序列化恢复的旧临时状态须明确显示“需要重新确认”，不假定进程退出后仍可读回。

### 7.4 不存在全局原子事务时的处理

全局目录与多个项目不能假定一次原子提交。采用可续跑的逐项目交接：先持久化切换意图、再冻结旧 owner、再激活带新 epoch 的 owner。项目写入口与巡检必须检查当前 owner epoch。

未确认交接的项目保持 legacy 或 read-only，不允许新旧两套规划器同时写入。全局助理可先管理已交接项目；未交接状态对用户明确可见。迁移崩溃后依据 manifest 和真实租约恢复，不凭一个 completed 标志推断所有项目已切换。

## 8. 前端与降低操作成本

Launcher 使用随包资源承载独立助理路由。桌宠和面板连接同一全局 Session，不因项目窗口、前台标签或后端 origin 改变而切换身份。UI 继续使用 VUI 产品 API、现有 recipe 与统一 pane persistence；新增组件先登记 designs，并通过既有守卫。

### 8.1 Launcher 承载完整个人助理

“完整集成”的验收对象是用户能完成的助理场景，不以增加一个跳转按钮或显示形象作为完成。以下既有能力全部在 Launcher 助理面板可达，并复用原页面的业务模块；项目业务编辑器仍可作为成果详情打开。

| 能力 | Launcher 中的交互 | 后端与复用边界 |
| --- | --- | --- |
| 对话、历史、附件和流式输出 | 直接进入同一活动会话；可查原生历史，输入与附件在切换展示时保留 | 复用 ChatCodingRoute/原生 composer 和 Session DTO，不另建聊天状态机或 transcript |
| 平台、项目与实例管理 | 在面板固定目标，查看状态，一句话启动、停止、重启、切换和管理 | Launcher 原生项目注册及命令队列；实际对象与权限仍由目标域校验 |
| Agent 与团队 | 一句话新建、改配置、换模型、建团队并运行，显示分步成果 | 第 4.6 节预设及原生 action/team workflow；创建和运行分别核验 |
| 派遣、进度、审批与恢复 | 在同一操作卡查看进度、批准必要差异、停止任务、继续观察和打开成果 | 复用原生审批、Inbox、WorkRun 与持久回执，不以本地卡片状态替代结果 |
| 个人事务、记忆与偏好 | 待办、日程、目标、对话偏好和可见的记忆管理在面板内完成 | 助理自己的原生插件和设置服务；不读其他 Agent 私有记忆 |
| 模型与助理设置 | 直接选择有效模型、诊断连接，修改人物、主动程度、通知和形象 | 复用原生配置 DTO、校验和凭据入口，不复制 Provider 目录 |
| 用户资料、头像、壁纸和普通平台设置 | 自然语言完成，必要时在面板内展示结构化选择及结果 | 使用现有受控动作及资产服务；明确 operator/project/assistant 作用域 |
| 电脑操作与能力说明 | 在面板内发现能力、处理原生同意、查看受控操作及未支持原因 | 保留现有观察/执行授权；不向 Launcher renderer 开放任意系统命令 |

“全部既有功能迁移”与“全部 HTTP API 开放”分别统计。第 2.1 节已接入能力必须零遗漏，尚未支持的 API 按第 5.4 节分类；迁移不能把受限或内部 API 自动变成任意调用工具。

Launcher 主界面、桌面形象、托盘和工作台入口最终都唤起同一助理面板。嵌入视图与独立面板复用同一功能模块和 domain transport；项目上下文由明确目标参数传入，不重新初始化助理。不得通过伪装成 Workbench 窗口放宽原有 IPC 权限；为 Launcher/助理窗口新增窄的、校验角色和来源的专用方法。

### 8.2 打开即显示的桌面形象

首版复用现有 DesktopPetCharacter、大飞鱼/小洛 renderer、透明窗口、边界钳制与展开聊天能力。形象资产随助理包交付，与页面和配置一起脱离项目 origin；启动时无需先下载模型、启动项目或成功连接 LLM。缺模型时形象仍可显示，并提供连接修复入口。

| 用户动作或事件 | 预期行为 |
| --- | --- |
| 首次安装或用户主动打开 Launcher/个人助理 | 默认启动已启用的助理并显示一个收起态形象；已有窗口时复用，不重复创建。明确禁用助理的设置仍受尊重 |
| 点击形象或托盘“打开助理” | 一步唤起完整面板并定位当前会话；只在用户主动操作时将输入焦点交给面板 |
| 后台自启、通知和恢复连接 | 遵循明确的自启/可见性偏好；不抢焦点、不突然展开面板；事件不会把刚隐藏的形象重新弹出 |
| 关闭聊天区 | 收起聊天；保留形象和后台服务，未发送输入不丢失 |
| 隐藏形象 | 只隐藏展示；托盘/Launcher 一步恢复，进行中操作继续 |
| 拖动形象、调整大小、切换屏幕 | 复用窗口位置与边界 helper；屏幕移除、DPI/任务栏变化后仍在可见工作区；尺寸和位置不写回项目配置 |
| 形象资产加载失败 | 使用随包的轻量占位形象及恢复入口，不让聊天、任务或设置不可用 |

透明的非交互区域必须允许鼠标穿透；拖动区域、菜单和聊天区保留命中测试。默认采用包围形象的有限窗口，不照搬跨全部显示器的全屏透明覆盖层。显示使用不抢焦点的原生方式，不能为展示常驻而持续获取鼠标或键盘焦点。

动画只投影权威事件：受理/模型输出、受控动作执行、等待用户、等待项目、失败和有证据的完成分别展示；idle/ready 只能表示等待或就绪，不能显示为任务成功。投影关联 sessionId、turnId、operationId 及原生来源，过期回执不覆盖当前状态；不为形象改写普通 Session 或统一各领域状态枚举。

Live2D、VRM、口型、语音输入输出和复杂动作作为可选增强，采用 renderer 适配边界。它们不成为本次迁移的必装依赖，也不另建对话、记忆或权限内核；任何角色资产和 SDK 的许可证分别核对。

### 8.3 关闭、常驻与退出

| 操作 | 窗口与服务生命周期 |
| --- | --- |
| 关闭项目工作台 | 关闭该窗口，项目是否停止按现有规则；常驻助理和桌面形象独立 |
| 关闭 Launcher 主窗口或助理面板 | 隐藏对应界面，托盘与助理运行时继续；首次发生时用简短提示解释，无需每次确认 |
| 关闭桌面形象 | 隐藏形象，不清空会话、不停止派遣、不终止服务；后续明确打开可恢复 |
| 隐藏全部窗口 | 托盘仍可恢复；窗口数量为零不能自动触发退出或清除服务 owner |
| 明确退出 Launcher | 按第 9.1 节停止新受理、保存并关停自己的服务；不自动终止项目中已派出的任务 |

开机自启是独立的显式用户偏好，不因“常驻”自动开启。用户本轮确认的是打开 Launcher 后具备完整助理与形象；本机后台安装、系统服务与开机常驻不在授权范围内。

### 8.4 共享交互与最小改造面

- 保留当前输入、流式输出、附件、偏好和待审批操作意图；审批是否有效按当前 scope 与原生状态判断，不能搬用旧临时批准。窗口隐藏只降低展示更新频率，不关闭后台执行。
- 操作卡清楚展示项目/实例、实际作用域、变更摘要、当前步骤与成功证据。共享用户名、模型或壁纸变更标明影响所有使用该配置源的实例。
- 常规已授权操作自动完成；只有有意义的目标歧义或权限差异才集中询问，不要求用户逐项进入设置页。
- 断线显示最后确认时间和等待对象；不把缓存状态绘制为实时状态。
- 提供“继续观察、停止任务、打开成果、修复连接”的受控动作；取消观察与停止任务使用不同文案。
- 偏好通过 revision 和成功事件更新，窗口重新显示时做一次读回；不让旧异步响应覆盖新设置。
- 工作台内保留轻量入口和嵌入视图，连接全局服务。浏览器单独访问项目时仅展示受控状态/跳转，不向普通网页下发全局服务凭证。

本地源码落点已经核对：

| 现有实现 | 直接复用 | 必要适配 |
| --- | --- | --- |
| [PersonalAssistantRoute](../../web/src/routes/PersonalAssistantRoute.tsx)、personalAssistant/ | 全功能模块、偏好、概览、事务和操作 UI | 移除必须处于 Workbench 壳内的装配依赖，注入助理 transport 与目标作用域 |
| [DesktopAssistantRoute](../../web/src/routes/desktopPet/DesktopAssistantRoute.tsx) 与 DesktopPetCharacter | 收起形象、展开聊天、同一身份和活动投影 | 改用全局助理连接和随包资产；完整管理能力由同一面板承接，不塞入另一套概览 |
| [petWindow](../../desktop/electron/src/windows/petWindow.ts)、petWindowBounds | 透明安全窗口、位置恢复、屏幕边界 | URL 不再从 Workbench origin 派生；打开时自动显示；关闭改为隐藏 |
| [petSettingsControl](../../desktop/electron/src/windows/petSettingsControl.ts)、preload/IPC | 窗口请求的集中校验与单实例控制 | 增加独立助理窗口角色与窄方法；移除由某个项目 origin 独占形象的语义，不放开通用控制接口 |
| [electronWindowProvider](../../desktop/electron/src/windows/electronWindowProvider.ts) 与 Launcher 随包协议 | 窗口复用、托盘存活、资源协议与安全默认值 | 固定助理独立资源和生命周期 owner，工作台启停不影响助理 |

先完成“无项目启动 Launcher → 显示已有形象 → 打开完整面板 → 一次真实对话”的切片，再迁移全部功能。可复用内容以现有模块为单位提取，不重新实现聊天页、角色引擎或一套 Launcher 专用设置页。

本方案不规定最终视觉布局；可见 UI 改动实施前按项目现行 UI 契约完成预览或明确复用路径，禁止临时引入第二套设计系统。

## 9. 生命周期、发布与运行恢复

### 9.1 监督与关停

Electron 启动后按用户启用状态启动助理，关闭工作台不退出服务。项目回收列表、工作台 Job 和 runtime-manager registered PIDs 中不包含助理。助理有自己的租约、日志、健康探测和有界崩溃退避；建议初始策略为 1/2/4 秒退避，10 分钟内超过 3 次异常退出转为 degraded，由恢复入口处理，避免无限拉起。具体时间为待测初始值。

退出 Launcher 时先关闭新对话与新动作准入，保存原生 Session 和操作记录，取消订阅并有界关停助理。取消退出不得提前停止服务；退出超时需说明未确认状态。助理退出不自动停止项目中已经派出的任务，除非用户明确请求停止这些任务。

### 9.2 构建与升级

构建产物包含 Electron、助理代码闭包、锁定 Python 依赖、独立 UI 资源与协议清单。release provenance/freshness 必须覆盖这些内容，不能只比较 Electron tree hash。运行包不从活 checkout import，产品启动不现场 pip install，也不临时回退项目 .venv。

升级采用 prepare、quiesce、switch、verify、commit：先检查协议/数据版本兼容，旧 owner 保存检查点并退出，新包验证后接管；失败保持可回到旧包。最少保留一个匹配数据 schema 的可用旧包。schema 升级优先可扩展变更，无法逆向读取的数据升级必须先形成独立迁移与备份方案。

Launcher 自身退出/更新仍会中断助理进程。本方案保证持久化恢复，不承诺跨 Launcher 退出的连续 TCP、模型请求或运行内存。

### 9.3 可观测性与成本

建立独立 assistant runtime scene，关联 profileId、operationId、projectId、instanceId、sessionId、turnId、native runId、协议与 release。默认日志只记有界元数据、错误码和证据引用；用户消息与原生对话仍按 Session 原有隐私与删除规则管理。

空闲不发模型请求；项目事件、用户消息和明确到期事项才触发处理。复用现有催办次数、冷却和每小时唤醒限制；全局调度再加总预算，防止多个项目各自满足额度却导致整体放大。低频健康探测只面向已连接或有待恢复操作的实例。

## 10. 实施任务与依赖

~~~mermaid
flowchart LR
    M0["M0 契约与 ADR"] --> M1["M1 独立运行宿主"]
    M0 --> M3["M3 项目连接与授权"]
    M1 --> M2["M2 数据与迁移工具"]
    M3 --> M2
    M1 --> M4["M4 助理界面与桌宠"]
    M3 --> M5["M5 原生动作与团队恢复"]
    M2 --> M6["M6 兼容切换"]
    M4 --> M6
    M5 --> M6
    M6 --> M7["M7 故障与真实模型验收"]
~~~

共享文件和运行资源采用单一 writer。M1 与 M3 可以分别在独立边界推进；M2 在宿主与项目授权切片通过后实施，M4 可在宿主契约冻结后并行。main.ts、preload、共享 DTO、全局模型引用和最终切换由集成 owner 串行收口。

| 阶段 | 责任与具体落点 | 产出和验收出口 |
| --- | --- | --- |
| M0 契约和 ADR | 维护者；ADR 0009 窄修订、能力/身份/存储/审批 DTO、兼容消费者清单、初始预设来源 | 冻结 owner、scope、协议、授权交集、迁移/回滚语义及默认字段升级规则；列出所有旧消费者；无业务切换 |
| M1 独立宿主 | Launcher owner；新增 process/assistantRuntime、bootstrap、路径与打包清单 | 无项目可启动；单例、无控制台、固定包、健康、独立进程组、崩溃退避通过 |
| M2 原生数据与迁移 | Session/存储 owner；助理专属 bootstrap/paths、只读历史导入、OperationStore、迁移工具 | 首次初始化及重入恢复；无模型可修复；自定义配置保持；dry-run/apply/resume/rollback；哈希与水位核对；普通 Session 核心回归 |
| M3 项目连接与授权 | Launcher/业务授权 owner；连接代理、项目 capabilities/action gateway、受控代理身份 | project/instance/config 权威绑定；恶意目标、跨项目批准、过期凭据、策略撤销拒绝；读回和去重契约通过 |
| M4 面板与桌宠 | 前端 owner；Launcher 全功能助理入口、独立随包路由、typed IPC/domain API、VUI 与 pet origin | 打开即显示形象；关闭仅隐藏；项目停机仍可显示和对话；既有功能零遗漏、单一会话、输入/设置同步；VUI 与类型检查通过 |
| M5 动作与恢复 | 各原生领域 owner；pa_* adapters、模型引用、Team/Kernel/原生任务关联 | 已接入能力零遗漏；Agent/团队预设实际可执行；团队分步恢复；并发配置保护；未知结果不重做；生成全 API 分类清单 |
| M6 兼容切换 | 单一迁移 owner；feature flag、manifest、owner epoch、旧入口转接 | 单写者证明；多项目逐项切换；legacy/bridge 状态可见；回滚演练通过 |
| M7 发布前验收 | 独立验收者与集成 owner；故障注入、原生桌面、真实模型与包 provenance | 第 11 节全部强制场景有证据；关闭高风险缺口后才切默认；部署/发布另需授权 |

不把纯调试脚本、临时验收缓存或合作 envelope 写进 checkout；使用 Git common-dir 的任务目录或系统临时目录。实现阶段各子任务按现行规则验证、自审并合入本地 main；push、PR 和发布不由本文授权。

### 10.1 主要文件与新增边界

| 现有 owning surface | 计划变更 |
| --- | --- |
| desktop/electron/src/main.ts、preload.ts、ipc.ts | 装配与窄 IPC；新进程/连接逻辑放 slice 模块，避免继续膨胀 main.ts |
| desktop/electron/src/process/、lifecycle/、windows/ | 助理专属 owner/Job、监督、退出协调；桌宠使用随包 origin |
| desktop/electron/electron-builder.json、desktop/electron/scripts/buildDesktopPackage.js | 助理代码/依赖/UI 打包与 manifest；实施时以实际构建入口复核 |
| core/launcher/desktop_shell.py、Electron serving/provenance | 将助理包指纹纳入 freshness 和换包判断 |
| 新 core/assistant_runtime/ 与专用入口 | bootstrap、app、paths、认证、事件适配、项目客户端、操作记录和迁移；不装载完整工作台 lifecycle |
| core/web/services/personal_assistant*、tools/pa_* | 提取可复用动作 service；保留旧 wrapper 身份门；新增委托入口及 bridge 模式 |
| config/operator_config_transaction.py、model_reference_service.py | 共享事务复用、常驻助理引用与并发删除保护 |
| Session facade、Journal、directory runtime | 优先无行为变化复用；只新增专属初始化/导入适配；若须改普通核心，拆独立任务证明回归 |
| web/src/routes/personalAssistant、desktopPet、web/src/api | 连接全局服务的 domain transport、状态/审批/恢复 UI；复用 VUI |
| tests/ 与 Electron/Vitest 契约测试 | 由对应阶段添加业务与负例；记录独立运行、跨进程和原生桌面证据 |

新增目录和入口名是建议落点，M0 通过现有索引检索确认后登记；不得把拟议文件当作已经存在的模块。

## 11. 验收矩阵与通过标准

| 场景 | 方法与必须取得的证据 |
| --- | --- |
| 全新安装与首次配置 | 空数据启动仅创建一个常驻助理及直属 Session；默认值来自原生定义；既有有效模型直接复用，缺模型时恢复入口可用；真实模型与受控动作验证生效 |
| 初始化重入和配置升级 | 并发启动、各持久化点崩溃后恢复，身份数量不增加；用户自定义人物/模型/偏好和零工具策略不被重置；预设版本变化不自动扩权 |
| 项目代理与新 Agent 初始权限 | bridge 没有第二个规划/巡检循环；新协作 Agent 和开发角色分别验证有效工具、模型、工作范围和回执；无执行能力时不误报可开发 |
| 没有项目运行时启动和真实对话 | 原生 Launcher 启动；助理 PID/包身份/Session；真实模型收到并完成 Turn |
| 项目连续重启 | 对话中重启目标项目至少两次；助理 PID 和活动 Session 不变，其他项目操作继续 |
| 目标错误与同名项目 | 两项目、两实例；明确目标实际生效；伪造 projectRef/instance/配置源被拒 |
| 写入成功但丢响应 | 在每个持久化边界注入断连；原生对象数量不增加，重连关联同 operation/native ID |
| 一句话建立并运行团队 | 真实模型选择动作，原生工作流完成、成员有真实模型执行、成果与证据可读；重复请求不新增团队或运行 |
| 长任务交办、回复与完成 | 关联原消息、目标 Session、业务回执；投递成功和普通 Turn 完成不误报业务成功 |
| 偏好、用户名、头像、壁纸与模型 | 真实模型逐项调用；原生回读、实际 UI、重启后状态三者一致；测试后恢复原值 |
| 助理自身模型修改与失败 | 正常切换后后续 Turn 使用新绑定；错误连接保留旧绑定；全失效时确定性修复入口可用 |
| 模型被其他实例引用或同时删除 | 两个真实进程竞争，引用检查/事务/CAS 有效；常驻助理不会被漏扫 |
| 权限与审批 | 零工具、自定义策略、其他项目批准、过期 token、参数替换、权限撤销均拒绝；旧 requestId/grant/window 不能用于新 Session/项目/配置；新 gateway 合法持久批准经目标重验后才可恢复 |
| 服务崩溃、PID 复用和租约冲突 | 可控异常退出；有界退避、Journal/操作恢复；不接管错误 owner，不产生双实例 |
| 迁移过程中任一点崩溃 | 每个状态前后停止进程；resume/rollback 幂等，历史哈希一致，资产与派遣引用完整 |
| 迁移后回滚 | 有新对话、新配置、新任务时演练；不丢数据、不重复任务、不出现双 owner |
| 个人事务迁移与回滚 | resident 期间增改删待办/日程/目标后回滚；稳定 ID、删除标记、完成状态和提醒游标一致，只有一个 collector，旧提醒不复发 |
| 桌宠/面板与工作台解耦 | 无项目冷启动即出现随包形象；项目停止/重启时实际形象与完整面板可用，真实对话成功；两入口同一 Session，输入及设置保持 |
| Launcher 功能完整性与操作成本 | 按第 8.1 节逐项以真实模型执行并读回；用户无需打开项目设置页；点击形象/托盘一步打开完整助理，必要确认集中展示 |
| 窗口隐藏、恢复与桌面交互 | 隐藏全部窗口后 PID/Session/操作继续；再次打开无重复实例；多屏/DPI、鼠标穿透、拖动、焦点和资产失败回退在原生桌面验证 |
| 普通 Agent/Session 回归 | admission、Journal、worker、persist、SSE、归档和工具授权关键回归保持原行为；Companion 无越界 |
| 无控制台与资源成本 | 原生桌面观察启动/崩溃恢复/项目重启/升级均无弹窗；空闲无模型请求、无全项目唤醒 |
| 升级与发布包 | 实际运行的 Electron、助理 Python/UI、依赖与协议指纹匹配；旧包回退和数据兼容证明 |

通过标准是每行都有对应运行版本、输入、原生状态、日志或回执和结论。单元测试、类型检查、构建、端口健康、真实模型、原生 UI 和故障恢复分别记录，不能互相替代。测试未知结果必须保留 unknown，不能通过放宽断言或扩大超时掩盖重放问题。

建议把“空闲连续 30 分钟无模型调用”“项目重启期间助理进程不变”“重复请求对象与运行数不增加”作为首版强制断言。更长时间稳定性观察在 M1 获取基线后确定，不能在实施前宣称已经满足资源或延迟指标。

## 12. 切换、回滚与停止条件

### 12.1 功能开关和兼容窗口

建议新增 legacy、bridge、resident 三种明确模式；这些配置项尚未实现。一次只能有一个持有写入 epoch 的助理 owner。先在隔离测试数据上试运行，再迁移一个来源，随后覆盖多项目；全部强制验收通过后才将 resident 设为默认。

兼容窗口以证据关闭：至少一个目标发布周期，且旧入口调用清单清零、旧格式恢复已测、用户历史与资产完整、无待迁移操作。时间届满本身不能触发旧数据删除或旧 API 退役。

### 12.2 回滚规则

- **尚未切换**：丢弃未激活目标或将其封存，恢复旧 PA 准入；源数据不变。
- **已切换但无新业务写入**：核对源/目标水位与 epoch 后切回旧 owner；保留全局快照。
- **已产生新对话或配置**：先冻结全局 owner，保存其原生历史和差异；不把旧文件覆盖回新状态。全局新对话保留为只读历史；受支持的设置经原生事务做有版本检查的反向迁移，冲突集中交由用户选择。
- **个人事务账本已有增改删**：同时冻结全局与旧项目提醒 collector，按稳定对象 ID、删除标记、完成/取消状态、源 revision 和已消费提醒游标，执行插件原生反向迁移并核验。只有最新账本及提醒游标的唯一 owner 确认后才恢复写入和提醒，不能重新启用旧快照。无法证明回迁完整时保持 rollback_pending 和最新账本的只读恢复入口，不启动旧 PA 的个人事务写入或提醒；明确说明回滚未完成。
- **已派出新任务**：原生项目任务继续存在，操作账本和回执游标保留；回滚只改变观察 owner，不能重新派发。旧模式不具备观察能力时保持只读恢复/观察服务，直到任务有可交接的终态。
- **新旧包不兼容**：退到已验证匹配 schema 的包；无法证明兼容时保持恢复模式，不能强行启动旧写入者。
- **回滚失败或身份不明**：维持单写者冻结状态和可读证据，明确标记 rollback_pending；不自动清空数据或重新初始化。

### 12.3 必须停止推进的条件

出现跨项目误操作、重复业务写入、旧自定义策略被放宽、双 owner、凭据进入 renderer/Prompt、普通 Session 行为漂移、历史校验失败、无法恢复的 schema 变化或可见控制台弹窗时，停止切默认和发布。先隔离受影响入口、保留现场、修复并补对应证据；不能用“主流程可用”覆盖这些缺口。

## 13. 复用依据与关键风险

### 13.1 复用决策

直接复用现有 Electron 单例和窄 IPC、无控制台原语、原生 Session/Journal、动作 schema、最终工具授权、配置事务、Kernel/Inbox、团队工作流和 VUI。对宿主、项目授权桥、原生历史导入及操作恢复进行适配，不另建 Agent 框架。

外部机制仅用于核对边界，当前方案不新增相关依赖：

| 官方来源 | 借鉴点 | 本项目边界 |
| --- | --- | --- |
| [Electron 安全指南](https://www.electronjs.org/docs/latest/tutorial/security/) | IPC sender 校验、隔离 renderer 权限 | 使用现有 main/preload 边界，不给面板任意本机控制接口 |
| [OpenAI Agents SDK 人工审批与恢复](https://openai.github.io/openai-agents-python/human_in_the_loop/) | 服务端保存审批中断和可恢复状态 | 继续使用 Vibelution ToolPolicy/原生审批，不替换会话执行器 |
| [LangGraph 持久化](https://docs.langchain.com/oss/python/langgraph/persistence) | 区分会话检查点与跨会话持久数据 | 继续使用 Journal 和独立操作元数据；检查点本身不提供副作用去重或项目权限 |

### 13.2 主要风险及关闭方式

| 风险 | 必须关闭的证据 |
| --- | --- |
| 同进程切换项目全局根造成串写 | 固定单运行根；两项目并行负例和普通 Session 回归 |
| 只移界面，仍加载项目代码/资源 | 独立运行包检查与原生桌面停项目验收 |
| 项目代理身份成为提权旁路 | 原生最终授权覆盖、作用域交集、伪造身份/参数/批准的负例 |
| 项目重启后重复写入 | 持久化操作键、目标去重/CAS、每一故障边界注入 |
| 多个助理/历史/设置发生冲突 | 单来源选择、dry-run、原生只读历史与完整哈希、逐项目 owner 交接 |
| 共享配置变化破坏常驻模型 | 跨进程事务、全局引用检查、最后可用绑定、确定性恢复入口 |
| 多项目通知与模型成本放大 | 事件去重、统一预算、催办上限、冷却与空闲实测 |
| 旧 UI、旧服务包被误判最新 | provenance 同时覆盖 Electron、Python、依赖、UI；核对实际运行资产 |

M0 冻结契约后，M1 与 M3 应先交付“无需项目即可启动的最小宿主 + 只读项目握手 + 一条带去重的受控写操作”的联合验证切片。该切片通过后再扩展数据迁移、所有现有动作和界面，避免先搬动全部个人助理代码后再补身份与恢复边界。

### 13.3 相关高价值项目调研与借鉴裁决

调研日期为 2026-10-24。先检查本地个人助理、桌宠、Launcher 和任务简报列出的已有参考，再查以下官方仓库、文档、发布页与许可证。仓库 HEAD 由只读 ls-remote 固定；源码以该提交读取，不执行外部代码、不安装新依赖。本轮是静态调研，不代表候选已在本机或 Vibelution 中通过运行验收。

| 优先级与项目 | 高价值部分及证据 | 许可证、维护信号与适配成本 | 本项目裁决 |
| --- | --- | --- | --- |
| 1：[AIRI](https://github.com/moeru-ai/airi) | 桌面人物、聊天/设置窗口组织、透明形象与独立展示；固定源码的 [main window](https://github.com/moeru-ai/airi/blob/d759427ba696db2875b5d4ce72f7701c54feba28/apps/stage-tamagotchi/src/main/windows/main/index.ts) 包含透明窗口、hide-on-close 与不抢焦点的展示路径 | 固定 HEAD d759427ba696db2875b5d4ce72f7701c54feba28；[代码 MIT](https://github.com/moeru-ai/airi/blob/d759427ba696db2875b5d4ce72f7701c54feba28/LICENSE)；[发布页](https://github.com/moeru-ai/airi/releases) 可见 v0.12.0。整体 UI/人物与服务栈搬入成本高，局部窗口交互参考成本低；角色资产不随代码许可证自动获准 | 优先参考形象/面板共存、窗口生命周期、渲染适配与测试场景；首版仍复用本项目现有形象，不引入整套 AIRI 或其聊天内核 |
| 2：[OpenClaw](https://github.com/openclaw/openclaw) | [常驻 Gateway 架构](https://docs.openclaw.ai/concepts/architecture)、多个客户端连接同一执行权威；[固定架构源码](https://github.com/openclaw/openclaw/blob/b7b7415ae65bb230632a31ee5bcc302d23cf31a2/docs/concepts/architecture.md) 区分 accepted 与最终结果、握手身份及事件通道 | 固定 HEAD b7b7415ae65bb230632a31ee5bcc302d23cf31a2；[MIT](https://github.com/openclaw/openclaw/blob/b7b7415ae65bb230632a31ee5bcc302d23cf31a2/LICENSE)；[发布页](https://github.com/openclaw/openclaw/releases) 可见 2026.10.6。引入其完整 Gateway/Agent/插件栈会重复现有能力；只参考边界和故障用例成本低 | 参考常驻服务与客户端解耦、身份握手、版本和回执；保留 Electron 控制面、原生 Session/ToolPolicy，不引入第二个 Gateway 内核或默认系统 daemon |
| 3：[OpenCode](https://github.com/anomalyco/opencode) | [官方 Server 文档](https://opencode.ai/docs/server/) 展示 OpenAPI、生成 SDK、全局/会话 SSE 与多客户端接口；与本项目 API 解释文档及 transport 适配直接相关 | 固定 HEAD 43f7997bfa7b6cd710ea08274a5eb9b603a73a40；[MIT](https://github.com/anomalyco/opencode/blob/43f7997bfa7b6cd710ea08274a5eb9b603a73a40/LICENSE)；[固定 README](https://github.com/anomalyco/opencode/blob/43f7997bfa7b6cd710ea08274a5eb9b603a73a40/README.md) 已指向 v2，桌面端标记 BETA。发布页仍有更新，但公开 Server 文档与当前开发头必须分开看；旧 event-reducer 路径在此 HEAD 已不存在 | 只参考由 schema 生成能力文档/客户端、共享事件连接和缓存隔离；不按本地旧参考路径复制代码，不替换本项目会话引擎，不将公开文档直接当当前 v2 可调用契约 |
| 4：[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) / [Web](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web) | [固定 WindowManager](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/d176e7df2366952e3bacbf12cf9a8b18a4315932/src/main/window-manager.ts) 提供 window/pet 模式、窗口位置、鼠标穿透和显示切换；[发布说明](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/releases) 描述模式间共享上下文 | 前端固定 HEAD d176e7df2366952e3bacbf12cf9a8b18a4315932；[Open-LLM-VTuber License 1.0](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/d176e7df2366952e3bacbf12cf9a8b18a4315932/LICENSE) 有额外商用条件，不能按后端历史 MIT 推定前端可直接集成；发布页可见 v1.2.1。还需独立核对 Live2D 资产；整套接入成本高 | 仅参考窗口/形象共享上下文及鼠标交互。源码中的 sandbox=false、nodeIntegration=true 与本项目更严格默认值不兼容，不复制安全配置或全屏透明窗口实现 |

借鉴顺序是：先用 AIRI 对照桌面体验，用 OpenClaw 对照常驻边界，用 OpenCode 对照接口投影；Open-LLM-VTuber 仅补交互参考。排名按本任务适配价值，不按 stars，也不是对稳定性或安全性的认证。许可证描述是本轮固定文件的观察，不给未来版本或附带资产作授权结论。

可以立即转入实施清单的四项：

1. **统一助理模块与传输**：复用现有个人助理模块、Session/LLM/Journal、动作 schema 和配置事务，只增加独立宿主及窄 transport，不维护两份聊天与设置逻辑。
2. **独立窗口 owner**：复用本项目透明窗口和边界 helper，参考 AIRI 的展示/隐藏/焦点分工，先实现已有形象随 Launcher 冷启动可见。
3. **可解释能力目录**：从本项目注册表生成说明、参数和支持状态，参考 OpenCode 的 schema/SDK 思路；文档、工具与执行授权使用同一能力版本。
4. **持续服务与恢复**：参考 OpenClaw 的客户端握手和受理/完成区分，使用本项目原生游标、审批与回执补重连负例；不为桌宠再建状态库或任务调度器。

新增 Live2D/VRM 或外部模块前另做窄验证：许可证及资产来源明确，renderer 可替换，不携带新的 LLM/记忆内核；测量实际 Windows 启动、空闲资源、焦点、鼠标穿透和断线恢复。当前常驻迁移无需等待这些增强，也没有新增第三方运行依赖。
