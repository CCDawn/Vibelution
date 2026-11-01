# Personal assistant

## LauncherShell / LauncherNavigation

### 功能
统一左栏承载个人助理与 Launcher 功能。普通启动先显示桌宠，点击直接打开或聚焦唯一的完整 Launcher；关闭或“回到桌面”隐藏主窗口并恢复桌宠，会话和任务继续由原生 runtime 持有。
### 适用范围
Launcher 控制窗口。显式工作区 start/open 和深链仍执行对应动作；普通工作台、分支工作台和 Companion Session 核心不受导航改动影响。
### 使用方式
`LauncherShell` 组合 `LauncherTitlebar`、`VSplitWorkspace` 和同一份 `LauncherNavigation`。左栏主入口为对话、项目与分支；网页属于对话右侧按需面板，不单列导航页。有更新或更新失败时在底部单独显示更新入口，状态与名称分开对齐；设置菜单提供诊断、维护、启动设置和版本更新。无常驻的关闭窗口说明。旧的助理功能深链仍可访问，待办、电脑操作与偏好由助理按需处理。右侧只渲染选中内容，无常驻右功能栏。窄屏通过 `VDialog` 展开同一目录，切换后关闭。标题栏只承担身份和原生窗口拖动。

`LauncherProjectRoute` 保留原项目/分支与启动设置的服务和操作保护；未选择项目有独立原生目录选择入口，取消不创建项目、不启动工作区。失败显示错误，不能将所有错误解释为没有项目。`LauncherUpdatesRoute` 复用原 Launcher 更新、确认、保存与序列化重启组件。

### 视觉与边界
浅色 rail、白色工作面与细分隔线；不再将完整主区域包在重复圆角卡片里。左栏固定两列 recipe，不引入额外宽高持久化。窗口 IPC 只接受已登记 Launcher 主框架及可信 URL，顶层外域导航和重定向拒绝。选择项目不再是打开助理的前置步骤。

## LauncherUpdatesRoute / LauncherUpdateTopbar

### 功能与适用范围
Launcher 更新页直接展示真实版本状态、当前版本、目标版本和更新操作。沿用既有更新 API 与序列化生命周期，不提供第二套更新器。
### 使用方式
复用 `VDenseOpsPage`、`VButton`、`VConfirmDialog`；不在页面内再嵌标题栏或下拉层。更新按钮仅出现一次确认；确认说明保存记录和重启的影响，有活动任务时明确中断。版本查询失败和未知状态提供重新检测，不把缓存结果当成本次检测成功。更新错误保留，重新检测不清除真实失败。共享 Query/mutation cache 在导航后仍反映更新中与失败，防止重复发起。Workbench 的更新操作在同一操作锁内重新读取版本，无法确认时不先重启工作区。
### 视觉与边界
Launcher 页面标题统一 `text-vui-title` 与 semibold，边距 24px/20px，窄屏横向 16px。辅助信息使用 caption token，不显示桌面壳、前端构建职责和重复关闭提示。更新不拉取远端代码，目标为已有本地代码；版本标识保持可查。

## LauncherStartupSettingsPanel / LauncherBranchInstancesPanel

### 功能与适用范围
Launcher 的启动设置和项目工作区管理；继续使用现有设置草稿、冲突保护与实例生命周期。
### 使用方式
设置页以 `VSettingsFormPage`、`VSettingsGroupCard`、`VSettingsRow` 展示窗口、尺寸和语言；运行环境、自检和 `.venv` 放在高级设置。只显示一次生效时机，环境变量覆盖时保留真实警告。无改动时不显示状态文字。
项目列表优先呈现当前、主项目和未停止实例；更多工作区按需展开，搜索仍覆盖全部记录。名称去掉无歧义的 `codex/` 前缀，冲突时保留完整名称，提示可查原名和路径。干净 Git 状态不常显，没有异常 Git 项时不占用整列。展开、筛选不删除或重写工作区数据，清理确认与活动任务保护保留。
### 视觉与边界
统一页面标题和边距；长名称可换行，窄屏使用现有列表形态。不引入额外持久化或伪造最近使用排序。

## LauncherToolsRoute / LauncherProcessMonitorPanel / LauncherProjectMaintenancePanel

### 功能与适用范围
Launcher 的诊断与维护恢复入口，Agent 不可用时仍可使用。
### 使用方式
复用现有 `VTabs`、`VStateSurface` 和只读 query refetch。诊断实例状态与项目列表共用 `instanceRuntimeState`，后台和窗口分别展示真实观测；查询失败标明未知并可重试，已有 PID 仅作为证据保留。高级诊断由页签控制，不再添加同名折叠。窄屏保留状态与关键详情。
维护清单加载、失败或不完整时只呈现一处状态，失败提供重试，不展示零值指标或旧预览操作。只有清单成功时显示清理范围与预览；执行继续校验原计划、档位、活动任务与原生权限。计划标识不常显。
### 视觉与边界
沿用统一 Launcher 标题、边距和辅助文字，删除页首重复解释；必要的清理影响和操作确认保留。无后台数据协议或权限扩大。

## LauncherAssistantWorkspaceRoute

### 功能
默认展示常驻助理的原生对话；待办与提醒、任务进度、偏好和外观由 Agent 工具处理，浏览器保留并排工作区。
### 适用范围
仅 Launcher 控制面，固定常驻助理身份。模型连接、启动、更新、诊断和维护保留设置入口，以便 Agent 不可用时恢复。
### 使用方式
`?panel=` 的缺省、未知值以及旧的 `overview`、`dispatches` 值进入对话。旧待办、偏好、设置链接给出一次可关闭的只读查询按钮，由用户明确点击后发送；访问 URL 不自动发送。发送沿用原请求 UUID 与未知结果读回，保留当前草稿和附件。旧电脑链接打开同一对话内的授权卡，不替换 transcript。默认 Workbench 的原 HTTP 面板保留，不受 Launcher 收敛影响。

任务进度通过 Agent 的有界派遣查询和原回执工具读取，不在标题栏或输入框旁展示任务编号列表。待审批记录继续通过对话中的完整预览处理。电脑卡沿用 Launcher-scoped transport，只有当前原生 observe 请求且轮次未停止时自动出现。窗口列表只在本机选择；请求 id 随本次明确授权提交，过期、取消或身份变化拒绝授权。授权只建立窗口许可，不自动生成聊天消息或重新执行工具；后续由用户在原生对话中继续。恢复现有授权时显示暂停、接手和结束控件，不重复列举窗口。所有写入经固定 native identity 和封闭 IPC verbs，不接收 renderer 自报 Agent/Session。

### LauncherAssistantWelcome
仅在原生会话确认为空、无活动轮次/排队/授权/未知发送时显示欢迎内容。复用 `VButton` 的建议卡只填充既有草稿，不自动发送，不创建新会话，不替换 transcript。普通会话、工具执行中、已发送历史和未知状态不覆盖。桌面与窄屏为输入框保留底部空间，长标题可换行。

## LauncherAssistantRoute

### 功能
Launcher 自己拥有的个人助理浮窗，复用现有收起形象、原生消息列表与输入框，连接独立原生会话宿主。
对话中的用户名称沿用普通聊天的名称规则，用户头像继续使用当前账户资源；助理头像取固定原生助理的配置头像，并复用消息列表的头像展示。头像版本变化时读取新资源，加载或失败时不沿用其他身份或旧版本的图片；失败沿用外观图片重试入口。旧宿主没有该能力时保留默认头像。
### 适用范围
仅 `/launcher-assistant` 和 main 核验的专用窗口；首轮独立运行验收，不把原项目内助理当代理。

Launcher 聊天复用 `ConversationView` 的发送、停止和继续控件。运行时停止只绑定当前原生 Turn；隐藏、收起和关闭视图均不停止任务。继续控件仅在原生终态、分支和 ledger 快照允许时出现；已有草稿或排队消息时不出现。响应未确认时保留原请求标识，原生重新校验身份与快照，不用普通聊天发送替代继续操作。
### 使用方式
复用 DesktopPetCharacter、desktop-pet 样式和 LazyConversationView，展开态用 VDenseOpsPage；隐藏窗口不取消会话或派遣。消息请求 ID 在未知结果时保持不变，显式重试核对原生接受结果。通过 role-scoped IPC 读取状态、详情与回执，不给 renderer 后端凭据、端口或任意 URL。ConversationView 的可选 runtimeApi 只替换配置与标注的数据访问及查询 key，普通工作台默认行为不变。
### 非职责
不实现第二套 transcript、任务调度或 LLM 调用；不持有远程任务凭据；不把原生 succeeded 等同于业务验收通过。
### 视觉与状态
展开聊天始终以 `--vui-surface-panel` 提供不透明的浅色/深色窗口底色，由 Launcher route 样式明确持有，不依赖 VUI 默认透明背景与工具类的加载顺序；自定义壁纸只叠加 background-image，透明图片、未加载或清除图片均保留该底色。原有圆角不变，收起形象仍使用透明根节点。
聊天标题栏使用文本 VButton「打开 Launcher」，托盘提供同名入口；默认只显示助理，首次打开由 main 原生目录选择器选择现有项目，并复用项目管理窗口。renderer 不传入路径，打开入口不启动模型。
会话的 `lastTurnError` 直接交给 ConversationView 已有错误面板，展示原生失败摘要和可展开诊断；清除或更新均跟随会话读回，不增加错误分类、自动重试或另一份错误状态。
操作者名称和头像预设通过同一 status 的可选 `operatorProfile` 两字段投影传给 ConversationView 已有用户显示参数；同一终态刷新会自动读回，缺损时沿用普通显示默认值，不把用户名称混作助理名。原始只读配置不返回 bio、偏好、头像文件路径或凭据；不增加 writer、独立缓存或轮询。
status 明确声明 `operatorAssetsVersion: 1` 时，展开且可见的聊天通过固定 kind 的 `operatorAsset` IPC 独立读取头像和背景；旧宿主不读资源。图片只接收受限 MIME、大小和严格 base64 的封闭响应，renderer 不接收路径、任意 URL，不回退 HTTP。头像复用 ConversationView 的 `userAvatarImageUrl`；仅 Launcher 自定义头像用户行恢复普通会话头像的双列几何，无自定义图仍沿用 compact 布局，助理头像不变。背景仅在展开根设置既有 `--workbench-theme-background-image`，复用工作台背景合成与 soft 18% / standard 44% / strong 60% 可读性遮罩 token；收起形象保持透明。原生终态与既有配置刷新共用去重边界，收起时只标记资源失效，重开读取当前选择；删除图片或取消选择恢复默认。资源失败在聊天旁复用 VStateSurface/VButton 提示与重试，保留聊天、身份和发送能力，无独立设置 writer 或 raw 图片缓存。展开可见时复用现有状态轮询读取不含图片内容的外观变更标记，仅对应标记改变时重读该图片；旧宿主沿用原有刷新行为。
可读性渐变沿用 `tokens.css` 的同一公式，在 Launcher 自定义背景根重新绑定，让依赖的局部遮罩变量在同一节点解析，避免继承已失效的根级渐变导致整组背景丢失；通用主题 token 不变。
沿用已存在的浮窗形象与聊天布局，形象、名称、状态提示和标题显示读取 Launcher status 的 settings 偏好；明确的原生终态会按 session/turn 去重刷新，收起聊天也生效，不要求用户手动刷新。重新展开、窗口恢复可见与显式刷新仍可重读。自身会话在可见时启动读一次，以原生活动、已受理轮次、队列或待确认原请求维持观察；任务收口后停止轮询，隐藏后停止 UI 轮询。审批与派遣面板继续只在展开时读取。VUI 控件覆盖加载、连接错误、保留输入后的重试、收起和隐藏；没有实现的管理动作不显示可点击占位按钮。发送确认绑定原生 turnId，旧 ready 和旧终态不能结束新请求的等待；未知发送/继续只按原 requestId 回读原生接受证据，不重发、不换 ID、不把 queue ID 当 turnId。清理输入仅作用于仍等于原提交快照的草稿，新草稿保持。未确认输入与原 requestId 留在窗口内存缓存，组件卸载不清除；长期续租仍归宿主。
原生审批只读取当前助理会话的 pending 请求，复用 ChatToolApprovalDialog、toolApprovalPreview 与 VButton；只提供同意本次、拒绝及失败后重读，不显示会话级授权、永久授权或操作窗口委托。审批失败保留原请求，窗口隐藏和卸载不取消原生任务。 旧提醒交接重新授权复用此卡，完整展示来源身份、原操作和同步编号、当前快照摘要及原授权 head，并说明旧进程权限与发送者停止尚未证明、已开始或未知写入不重放；字段不完整或无效时禁用同意和快捷键。
派遣目标任务的待审批复用同一审批卡，一次只呈现一条，助理自身审批优先，避免快捷键同时处理多个请求。卡片标明项目、Agent、派遣、任务和审批 ID，按需读取受限原生预览并展示完整原始参数及含默认值的执行参数。完整预览和绑定版本核对通过时只提供一次批准或拒绝；预览失败、过大或身份不匹配时保留摘要并禁止批准，仅在回执版本有效时允许拒绝，目标再次核对实时任务、审批和版本。预览只存在于可见窗口内存，不写回执；决议失败时显示结果未确认并重新查询，关闭或重启 Launcher 不创建新任务。
忙碌时认可原生显式 queued ACK，校验 clientSubmissionId 与原请求 ID 一致后清空输入，保留原生队列引用，queue ID 不作 turnId。首个旧 ready 不解除等待；读取到对应 queuedTurns 后由原生 queued/starting 状态控制轮询，paused/blocked 显示原状态并在会话空闲时停读。复用原生提交读回 helper，以 canonical message/activeTask 的 clientSubmissionId 与真实 turnId 确认入场；已观察到的队列项移除且没有入场证据时只显示已移除，不宣称成功，不自动重发，不增加队列调度或管理按钮。
附件选择、粘贴和拖放复用 ConversationView 的图片与文档入口；宿主声明附件能力后启用，上传失败保留输入并允许重试。历史附件在消息可见时按需读取，受限缓存不改变原生会话的存储权威；生成图片也只通过当前助理会话读取。可写派遣的审批展示项目、Agent、权限和完整用户原话；摘要缺失或无效时不能同意。
### 实现落点
`routes/desktopPet/LauncherAssistantRoute.tsx`、`api/launcherAssistant.ts`。排队与派遣回执面板的几何、边框和提示色由同一 `DesktopAssistantRoute.styles.ts` 样式 owner 提供，Launcher 入口作为明确消费者登记，不在页面内新增视觉工具类。
### 反冗余
同一 ConversationView、DesktopPetCharacter 和 VUI 元素；迁移验收阶段保留旧入口，全部迁移和数据验收结束后退役旧产品实现。

## HumanAttentionNotifier

### 功能
主工作台的“双通道人工注意”触发链：轮询个人助理 overview 的 attention 列表（复用既有 query key 与 5s 节奏，不新建后端路径），发现 `kind` 为 knowledge_review/anomaly/affair_reminder 且当日未通知过的新条目 id，即调用壳层桥 `notifyHumanAttention(payload)`——助理悬浮窗开着时由壳层把通知投递进助理窗口，没开时壳层发 Windows 系统通知；收到壳层 `onHumanAttentionOpened` 打开回调时按 targetUrl（或 kind 默认路由）在工作台内导航。
### 适用范围
仅 AppShell 主工作台层挂载一次；可见通知卡归浮动助理窗（HumanAttentionNoticeStack），本组件不渲染任何界面。浮动助理窗不进 AppShell，不会双重触发。
### 使用方式
`<HumanAttentionNotifier />` 渲染为 null。去重 id 按本地日（localStorage `vibelution.human-attention.notified.v1`，day key 为本地日期，上限 400 条）持久化，页面刷新不重弹；桥不存在（非桌面环境）时静默跳过且不标记 id。payload 字段与壳层契约为 `id/kind/severity/title/body?/targetUrl?`；打开回调按 targetUrl 优先、否则用最近通知过的 id→kind 映射落到默认路由（knowledge_review→`/memory/knowledge`，anomaly→`/teams?researchView=workflow`，affair_reminder→`/personal-assistant`）。
### 非职责
不创建 attention 数据（后端 overview 权威）、不做可见 UI、不改普通会话通知链（chatDesktopNotifications 保持独立）、不聚焦或移动窗口（壳层职责）。
### 视觉与状态
无界面；桥调用失败静默（at-most-once 语义优先）。
### 实现落点
`routes/personalAssistant/HumanAttentionNotifier.tsx`、纯逻辑 `routes/personalAssistant/humanAttentionNotifications.ts`。
### 反冗余
复用 `queryKeys.personalAssistantOverview`、`fetchPersonalAssistantOverview`、`globalThis.vibelutionLauncher` 桥读取模式与既有桌面桥订阅骨架，不新建第二条 overview 请求或第二套桥发现。

## HumanAttentionNoticeStack

### 功能
助理浮动窗内的“人工注意”通知卡堆叠：监听壳层经 preload 暴露的投递订阅（`onHumanAttentionOpened`，通道 `launcher:human-attention-opened`），把完整 payload 渲染为窗口内通知卡——标题 + 正文（两行截断）+ severity（critical/high/medium/info，info 为完成类好消息专用低平档：无警示着色、CheckCircle2 图标）边框与图标着色 + 分类角标；点击卡片按 targetUrl（或 kind 默认路由）窗内导航并关卡，右上角可手动关闭，12s 自动消失、hover 暂停计时，最多堆叠 3 张（超出丢最旧，同 id 重复投递刷新为一张置顶）。
### 适用范围
浮动助理窗内挂载（收起与展开两态都覆盖，fixed 定位浮于舞台/聊天窗之上；退役的独立助理窗口栈曾是其唯一挂载点，组件与卡片协议保留待常驻助理窗沿用）。裸 `{ id, targetUrl? }` 打开事件不建卡、直接窗内导航。主工作台不挂载本组件。
### 使用方式
`<HumanAttentionNoticeStack onBeforeNavigate={...} />`；收起态点击定位前先经 onBeforeNavigate 展开窗口（失败仍继续导航）。组件用 VNativeButton 承载卡片主体（可聚焦、可回车），VIconButton 承载关闭；导航用窗内 react-router `navigate`，不可达目标（无 targetUrl 且 kind 未知）不动作。
### 非职责
不触发通知（触发链归 HumanAttentionNotifier）、不与系统通知竞争（壳层决定通道）、不持有 attention 数据副本、不写后端。
### 视觉与状态
severity 用 `--state-error`/`--state-warning` 与 `--vui-border-subtle`/`--vui-surface-panel` 的 color-mix 令牌着色（对齐 VStateSurface error/unavailable 口径）；info 档不着警示色，落默认中性卡面；桥缺失时渲染 null；hover 暂停与自动消失遵循 prefers-reduced-motion（过渡禁用）。文案 zh/en 双语。
### 实现落点
`routes/desktopPet/HumanAttentionNoticeStack.tsx`、`routes/desktopPet/HumanAttentionNoticeStack.styles.ts`、`design/route-css/desktop-pet.tailwind.css`（@source 登记）。
### 反冗余
复用 humanAttentionNotifications 的桥发现/解析/target 解析与 VUI 原语（VNativeButton/VIconButton），不新建弹窗体系；与 VDialog 的模态确认（session-tab-close-confirm）职责不同，本卡是非模态瞬时通知。

## PersonalAssistantComputerPanel

### 功能
在个人助理右栏提供单窗口授权、暂停与继续、人工接管与交回、具体操作确认和结束重选。
### 适用范围
个人助理工作台右栏、窄屏电脑操作 VDialog 和 Launcher 个人助理的电脑操作入口可复用。普通聊天和 Companion 不挂载。
### 使用方式
`<PersonalAssistantComputerPanel active onCollapse={...} />` 默认使用工作台传输；Launcher 注入其专用 transport，缓存按宿主隔离。组合 VButton、VIconButton、VCheckbox、VSurface 与 VStateSurface。打开页或手动刷新才读取窗口列表，普通状态一秒轮询且隐藏时停止。用户选定窗口、勾选画面许可后提交授权。顶部保留收起、暂停或继续、交给我或交回助理；结束撤销授权后重新选择。

对话中的 `presentation="conversation"` 使用紧凑授权卡：本机列出窗口供用户明确选择，可更换或暂不允许；确认文字包含选中窗口、画面交给当前助理模型以及敏感动作仍需确认，点击一次“允许读取并操作”才授权。仅该次用户授权成功触发 `onGranted`，被动查询不会触发。授权后显示窗口状态和暂停、继续、接管、交回、结束；结束成功关闭该卡，失败保留错误。待确认操作仍展示原目标和完整文本，沿用原确认服务。
### 非职责
不读取截图、不发送鼠标键盘输入、不持有消息或执行历史；不修改原生聊天语义，不以 UI 状态替代服务端授权与确认。
### 视觉与状态
授权前列出应用名和窗口标题，明确画面交给当前助理模型，并固定提交、发送、删除前确认。授权后展示唯一窗口、服务端状态和待确认动作、目标、完整输入；确认与取消分别提交 approved。失窗、结束和错误使用后端状态与原因，不伪造进度。mutation 失败保留原因与原状态，加载、不可用、空窗口和刷新失败均独立显示。长标题与输入换行，面板内容滚动，顶部控制与底部边界说明保持可见。
### 实现落点
`routes/personalAssistant/PersonalAssistantComputerPanel.tsx` 与 `.styles.ts`；transport 为 `api/personalAssistantComputer.ts` 或 `api/launcherAssistantComputer.ts`，DTO 为 `api/types/personalAssistantComputer.ts`。
### 反冗余
复用 VUI 控件、React Query 缓存和现有 VSplitWorkspace 的 personalAssistant 宽度记忆；不引入截图预览、第二套控制状态或额外布局持久化。

Launcher appearance control reuses the existing document theme/storage helper and
same-origin events; no theme panel or competing persistence is added. A governed
image upload opens the owned native chooser and applies the selected resource,
while current avatar/background consumers and native ConversationView remain
the only image presentation. Cancel/timeout is not success; image content and
source paths are not model results. Source-page acceptance covers settled light/
dark views, persistence, same-origin synchronization and existing image states.

### 桌宠悬停提示

浮动桌宠的状态、关闭与聊天提示默认隐藏；鼠标进入桌宠区域或键盘焦点进入时显示，无悬停的触屏保持可操作。脚下不显示角色署名小字，署名保留为非显示元数据；点击桌宠打开 Launcher 的行为不变。


## LauncherAssistantBrowserWorkspace

### 功能
Launcher 的单一助理工作区默认完整显示原生对话，需要网页时在右侧展开原生视图；会话始终只挂载一次。

### 适用范围
统一导航的「对话」使用同一工作区。旧 `?panel=browser` 深链仅作为展开网页面板的兼容请求，左栏仍选中对话。

### 使用方式
复用 `VSplitWorkspace` 和 `WORKBENCH_LAYOUT_IDS.launcherAssistantBrowser` 保存对话宽度。桌面和窄屏初始均收起网页；点击对话右上「打开网页」或收到原生 Agent 的展示事件时展开。窄屏仅在网页已展开后提供对话/网页切换。网页提供最多四个标签、地址导航、历史、刷新、接手与交还；接手等待宿主确认期间显示 pending。空页提供地址输入及哔哩哔哩入口。加载、失败和不可用均有可见状态；收起后对话占满宽度，恢复时保留标签、网页状态、原会话和输入草稿。深链与原生事件只展开同一个面板，不导航到第二个会话页面。

### 边界与实现
网页仅由 `window.vibelutionLauncherBrowser` 所属原生视图呈现；占位元素按内容区坐标报告边界，隐藏、滚动、调整尺寸和卸载时同步更新。地址仅接受不含凭据且不超过 8192 字符的 http(s)，地址栏保留完整查询与片段。`routes/desktopPet/LauncherAssistantBrowserWorkspace.tsx` 组合 `LauncherAssistantRoute`、`VButton`、`VInput` 与布局 recipe；`api/launcherAssistantBrowser.ts` 校验宿主状态。

### 反冗余
复用原生 Session、Launcher 导航与共享布局记忆；不使用 iframe、模拟网页或单独的 transcript。

网页恢复入口使用带地球图标的文字按钮「网页」，无障碍名称为「打开网页」。Launcher 对话标题沿用统一页面字号，助理工具名称用可读动作呈现；原始工具身份和执行证据仍保留在展开详情，不改变 transcript 或审批参数。
