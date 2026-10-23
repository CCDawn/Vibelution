# Personal assistant

## DesktopAssistantReturnNotice

### 功能
主工作台接收桌面助理的固定 source 返回事件；只读核实会话归属后打开已有页面。
### 适用范围
AppShell 中唯一桌面助理返回订阅；普通桌宠和其他会话通知保留原来的接入。
### 使用方式
事件只包含合法 Session ID。GET 助理身份后，canonical Session 回个人助理，其他 Session 用现有普通聊天 opener。失败显示 VDialog 可重试。请求 epoch、AbortSignal、当前位置与卸载保护阻止旧结果抢导航。
### 非职责
不创建智能体、不接受事件里的自由 pathname、不读取 transcript。
### 视觉与状态
成功无额外界面；失败使用 VDialog 与 VButton，关闭和重试均可操作。
### 实现落点
`routes/personalAssistant/DesktopAssistantReturnNotice.tsx`。
### 反冗余
复用原生事件、API 身份投影和已有路由写入者。

## PersonalAssistantRoute

### 功能
独立个人助理入口，提供原生聊天、平台管理概览与单窗口电脑操作；桌面模式沿用同一个 Agent、Session 与记忆。
### 适用范围
仅 `/personal-assistant`，与炒股智能体、虚拟人入口并列；普通会话与虚拟人保留原有页面。
### 使用方式
组合 VSplitWorkspace、VButton 与 PersonalAssistantOverview。`WORKBENCH_LAYOUT_IDS.personalAssistant` 持有概览宽度记忆。首次访问幂等创建或恢复助理；身份与原生 Session detail 的 agentId/directSessionId 均一致后才挂载 ChatCodingRoute。桌面按钮先检查原生能力，打开助理窗口并保留工作台任务。

通知深链 `?panel=dispatches` 打开派遣，`?panel=affairs&item=<URL 编码的 itemId>` 打开事务并定位条目。每次路由导航（含相同 URL 再次导航）均恢复已收起的右栏并切换目标 tab；窄屏打开对应 VDialog。Route 保存本次定位的消费结果，切换 tab 或关闭再手动打开 dialog 导致事务组件重挂载时不重复定位；缺失提示仍保留，新导航 key 重新处理。普通重渲染与轮询不改变用户选择的 tab 或收起状态。
### 非职责
不持有 transcript、composer、记忆副本或执行进度；原生 Session/SSE 与审批持有权威。
### 视觉与状态
聊天为主体，右栏用 VTabs 切换平台概览与电脑操作，沿用可调整与可收起侧栏；加载、错误与身份冲突用 VStateSurface；窄屏顶栏分别打开概览和电脑操作 VDialog，收起后入口保留。页面根节点在横向 VWorkbenchFrame 中占满可用宽度并参与伸展，避免按内容宽度缩成左侧窄列。
### 实现落点
`routes/PersonalAssistantRoute.tsx`、`routes/personalAssistant/*`。
### 反冗余
复用 ChatCodingRoute 与 VSplitWorkspace，不创建消息列表或第二套设计系统。

## DesktopAssistantRoute

### 功能
唯一的原生浮动个人助理窗口：收起态以助理身体常驻桌面并聚合平台会话状态，点击身体或「聊一聊」展开内嵌原生聊天与平台概览。桌宠与个人助理是同一个存在（同一 Agent、同一原生 Session），大肥鲸与小洛只是该助理的可选外观。

### 适用范围
仅原生验证的 `/desktop-assistant`；旧 `/desktop-pet` 是重定向别名（旧壳与书签兼容），不再有独立页面。不适用于普通 `/chat`、Companion 人物会话正文或第二套 transcript；这些仍由原生 Session、Journal 与 SSE 拥有。无 3D 引擎、模型导入或市场：小洛 Cubism Live2D 与大肥鲸 Anime2.5DRig 分层 WebGL 骨骼是仅有的两个外观 renderer。

### 使用方式
先用 `getDesktopAssistantContext` 核实 role/mode，再验证助理 Agent/Session 绑定。`setDesktopPetExpanded` 申请固定安全尺寸（收起 300×330 / 展开 400×530，并限制在屏幕工作区内）。收起态身体为 `DesktopPetCharacter`，外观跟随 `vibelution.desktop-pet.preferences.v1` 的 characterId（默认大肥鲸，可切小洛）；4px 移动阈值区分单击与拖动，拖动经 Electron IPC（desktopPetWindowDrag）移动窗口并沿用位置持久化。工具栏提供状态提示、助理设置（状态/标题隐私/完成提示/空闲文案，保存失败明确提示仅本次有效）、外观切换与关闭个人助理。展开态仅内嵌同一 `ChatCodingRoute` 原生会话；聊天代码局部按需加载，读取服务端原生初始消息窗口完成身份验证后，复用同一 `queryKeys.session` 缓存，不能用乐观会话壳替代服务端身份校验。聊天头部的收起与「关闭聊天」均通过原生尺寸桥返回桌面形象，不关闭原生窗口或停止会话；尺寸调整失败保留聊天并显示错误。会话跳转只调用 `openConversationFromPet(sessionId)`，必须得到主进程 `opened: true`，失败保留当前窗口并提示。supportedModes 门（"pet"|"assistant"）对旧壳保持兼容，Electron 的 desktopPetWindowUrl 把两种模式请求都收敛到 `/desktop-assistant`。

### 非职责
不以 URL marker 证明原生身份，不停止会话，不保存消息、不判断 Turn 权威、不创建 Companion mailbox，也不修改普通 Session admission、worker、projection 或 composer；不显示用户消息、工具参数、审批 payload 或模型推理正文。

### 视觉与状态
紧凑聊天头部仅保留身份、返回工作台与关闭聊天。正文取消头像列缩进，保留原生作者/时间与消息操作；输入区使用 48px 起始文本框，模型、权限、上下文和发送控件复用原组件，在窄尺寸下换行而非裁掉权限或模型名。所有紧凑规则均限定在 `data-assistant-chat="compact"` 下，不改变工作台或普通会话的呈现。

窗口透明、无边框、置顶；收起态复用桌宠舞台（toolbar / HUD / character stage），状态、关闭与设置入口收拢在身体周围的紧凑舞台内。状态优先级由后端投影固定为 `approval > error > running > completed > idle`；异常仅最近五分钟占用聚合提醒优先级，待审批不超时隐藏；完成仅由成功结果触发且受偏好开关控制。两个 renderer 只消费活动投影，不持有会话；显示模型加载与失败状态，不静默切回旧 PNG，保留各自作者标注。`prefers-reduced-motion` 下停止全部非必要动画；标签页隐藏时停止渲染，卸载时释放模型资源。本机集成不代表已获公开发布许可，详见 `web/live2d/README.md`。旧壳与身份错误明确提示；读取中与读取失败有独立文案，不伪造空闲状态。

### 实现落点
`routes/desktopPet/DesktopAssistantRoute.tsx`、`routes/desktopPet/DesktopPetCharacter.tsx`、`routes/desktopPet/WhaleRigCharacter.tsx`、`design/route-css/desktop-pet.tailwind.css`、既有原生桌面 API（窗口拖拽、尺寸桥、会话返回）。

### 反冗余
复用桌宠角色 renderer、IPC 拖拽桥、窗口尺寸桥与聊天宿主，不另建渲染器、消息存储或第二套设计系统；HUD 是该浮动窗口的领域组合，不对外导出通用组件。

## PersonalAssistantOverview

### 功能
展示后端平台计数、智能体、会话状态及需要关注的事项。
### 适用范围
个人助理工作台与桌面展开视图的只读概览。
### 使用方式
`onOpenSession(sessionId)` 由消费者导航；桌面用原生桥返回工作台，`desktop` 隐藏管理页链接。五秒读取正式 overview API，VIconButton 可刷新。
### 非职责
不伪造进度、不执行管理命令、不自行判定任务完成。
### 视觉与状态
VStateSurface 表达加载与失败；空列表用简短文案；共享状态标签与语义 token。统计卡片按侧栏可用宽度自动分列，中文标签保持单行，覆盖桌面展开窗口的最小侧栏宽度。
### 实现落点
`routes/personalAssistant/PersonalAssistantOverview.tsx`。
### 反冗余
复用已有 Agents、Aux、Memory、Tools、Teams、Knowledge、Config、Logs 管理页；桌面桥只支持 Session 返回，因此桌面保留会话快捷返回，不在悬浮窗内导航这些管理页面。

## PersonalAssistantState

### 功能
阻断尚未验证身份的聊天，并显示可恢复的状态。
### 适用范围
工作台与桌面聊天挂载前的加载、错误、空状态、身份冲突。
### 使用方式
传入 `usePersonalAssistant` 状态；错误可重试，URL 冲突可返回助理自己的会话。
### 非职责
不渲染消息、不决定会话权限。
### 视觉与状态
加载显示骨架；错误保留原因；操作使用 VButton。
### 实现落点
`routes/personalAssistant/PersonalAssistantState.tsx`。
### 反冗余
复用 VStateSurface，不新增 alert、button 或 loading 控件。

## PersonalAssistantSettings

工作台角色栏的“助理设置”与桌面窗口设置区的“名称、外观与模型”共用此对话框。
`children` 插槽保留宿主已有的显示偏好控件。工作台和桌面均通过 `usePetPreferences`
读取后端偏好、保存局部修改并同步窗口；本机缓存仅作离线回退，后端保存失败须提示。

### 功能
个人助理的设置弹层：改名、默认外观（大肥鲸/小洛，纯外观偏好，同一 Agent/会话）与对话模型选择；全部以后端设置 API 为权威。
### 适用范围
`/personal-assistant` 工作台头部的「助理设置」入口（打开 VDialog）；桌面浮动窗继续使用自己的紧凑 HUD，不复用本弹层。不承担模型库管理、Provider 配置或偏好外的任何 Agent 治理。
### 使用方式
`<PersonalAssistantSettings open onOpenChange />`。打开时才读取 `GET /personal-assistant/settings`（本地 query key 复用 `personal-assistant` 前缀便于统一失效）。名称行 VInput + 保存按钮（草稿未变时禁用）；外观行 VStringSelect（dafeiyu/xiaoluo，选中即保存）；模型行 VStringSelect（选项来自后端白名单 choices，坏通道/缺 API Key 的选项禁用并在标签中说明），选择即 `PATCH /personal-assistant/settings/model`。成功与失败经 role=status 行内反馈；改名成功后失效助理投影与设置缓存。文案 zh/en 双语。
### 非职责
不创建/恢复助理（创建仍由页面访问语义负责）、不直接写 Agent 目录、不管理模型库或 Provider、不持久化到 localStorage（偏好持久化归桌面偏好层的后端权威链路）。
### 视觉与状态
VDialog size=sm + 纵向表单行；读取中 VStateSurface loading 骨架，读取失败 error + 重试；保存中按钮 isPending；空模型列表显示引导文案，不伪造可选项。
### 实现落点
`routes/personalAssistant/PersonalAssistantSettings.tsx`（组合 VDialog/VInput/VStringSelect/VButton/VStateSurface）。
### 反冗余
复用 VUI 表单原语与既有 settings API，不新建第二套选择器；模型白名单与治理全部在后端 choices，前端不另建模型清单。

## HumanAttentionNotifier

### 功能
主工作台的“双通道人工注意”触发链：轮询个人助理 overview 的 attention 列表（复用既有 query key 与 5s 节奏，不新建后端路径），发现 `kind` 为 knowledge_review/anomaly/affair_reminder 且当日未通知过的新条目 id，即调用壳层桥 `notifyHumanAttention(payload)`——助理悬浮窗开着时由壳层把通知投递进助理窗口，没开时壳层发 Windows 系统通知；收到壳层 `onHumanAttentionOpened` 打开回调时按 targetUrl（或 kind 默认路由）在工作台内导航。
### 适用范围
仅 AppShell 主工作台层挂载一次；可见通知卡归助理窗口（HumanAttentionNoticeStack），本组件不渲染任何界面。助理窗口自身不挂载（/desktop-assistant 不进 AppShell），不会双重触发。
### 使用方式
`<HumanAttentionNotifier />` 渲染为 null。去重 id 按本地日（localStorage `vibelution.human-attention.notified.v1`，day key 为本地日期，上限 400 条）持久化，页面刷新不重弹；桥不存在（非桌面环境）时静默跳过且不标记 id。payload 字段与壳层契约为 `id/kind/severity/title/body?/targetUrl?`；打开回调按 targetUrl 优先、否则用最近通知过的 id→kind 映射落到默认路由（knowledge_review→`/memory/knowledge`，anomaly→`/teams?researchView=workflow`，affair_reminder→`/personal-assistant`）。
### 非职责
不创建 attention 数据（后端 overview 权威）、不做可见 UI、不改普通会话通知链（chatDesktopNotifications 保持独立）、不聚焦或移动窗口（壳层职责）。
### 视觉与状态
无界面；桥调用失败静默（at-most-once 语义优先）。
### 实现落点
`routes/personalAssistant/HumanAttentionNotifier.tsx`、纯逻辑 `routes/personalAssistant/humanAttentionNotifications.ts`。
### 反冗余
复用 `queryKeys.personalAssistantOverview`、`fetchPersonalAssistantOverview`、`globalThis.vibelutionLauncher` 桥读取模式与 DesktopAssistantReturnNotice 的订阅骨架，不新建第二条 overview 请求或第二套桥发现。

## HumanAttentionNoticeStack

### 功能
助理浮动窗内的“人工注意”通知卡堆叠：监听壳层经 preload 暴露的投递订阅（`onHumanAttentionOpened`，通道 `launcher:human-attention-opened`），把完整 payload 渲染为窗口内通知卡——标题 + 正文（两行截断）+ severity（critical/high/medium/info，info 为完成类好消息专用低平档：无警示着色、CheckCircle2 图标）边框与图标着色 + 分类角标；点击卡片按 targetUrl（或 kind 默认路由）窗内导航并关卡，右上角可手动关闭，12s 自动消失、hover 暂停计时，最多堆叠 3 张（超出丢最旧，同 id 重复投递刷新为一张置顶）。
### 适用范围
仅 DesktopAssistantRoute（/desktop-assistant 浮动助理窗，收起与展开两态都覆盖，fixed 定位浮于舞台/聊天窗之上）。裸 `{ id, targetUrl? }` 打开事件不建卡、直接窗内导航。主工作台不挂载本组件。
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
仅个人助理工作台右栏与窄屏电脑操作 VDialog。普通聊天、Companion 和桌面浮动窗不挂载。
### 使用方式
`<PersonalAssistantComputerPanel active onCollapse={...} />`。组合 VButton、VIconButton、VCheckbox、VSurface 与 VStateSurface。打开页或手动刷新才读取窗口列表，普通状态一秒轮询且隐藏时停止。用户选定窗口、勾选画面许可后提交授权。顶部保留收起、暂停或继续、交给我或交回助理；结束撤销授权后重新选择。
### 非职责
不读取截图、不发送鼠标键盘输入、不持有消息或执行历史；不修改原生聊天语义，不以 UI 状态替代服务端授权与确认。
### 视觉与状态
授权前列出应用名和窗口标题，明确画面交给当前助理模型，并固定提交、发送、删除前确认。授权后展示唯一窗口、服务端状态和待确认动作、目标、完整输入；确认与取消分别提交 approved。失窗、结束和错误使用后端状态与原因，不伪造进度。mutation 失败保留原因与原状态，加载、不可用、空窗口和刷新失败均独立显示。长标题与输入换行，面板内容滚动，顶部控制与底部边界说明保持可见。
### 实现落点
`routes/personalAssistant/PersonalAssistantComputerPanel.tsx` 与 `.styles.ts`；transport 为 `api/personalAssistantComputer.ts`，DTO 为 `api/types/personalAssistantComputer.ts`。
### 反冗余
复用 VUI 控件、React Query 缓存和现有 VSplitWorkspace 的 personalAssistant 宽度记忆；不引入截图预览、第二套控制状态或额外布局持久化。

## PersonalAssistantDialoguePreferences

### 功能
个人助理的对话偏好评议面板：三组对话设置（说话主动性 restrained/natural/talkative、提问主动性 few/natural/proactive、偏好建议模式 ask_first/manual_only）即时保存；待确认的偏好提案（verbosity/question_initiative/address/humor/proactive_contact）逐条「采纳/保留原样」，并展示最近已处理记录。全部数据以后端 Companion 插件 API 为权威，前端只映射受控枚举到行为词语，词语不落盘。
### 适用范围
`/personal-assistant` 工作台右侧 VTabs 的「对话偏好」标签（宽屏）与窄屏 VDialog 入口；窄屏不渲染侧栏时仍可从顶部操作条打开。不承担角色形象/模型切换（归 PersonalAssistantSettings）、不创建提案（提案只能由绑定直连会话内的结构化工具在真实用户回合产生）。
### 使用方式
`<PersonalAssistantDialoguePreferences agentId headerAction? />`。设置组每行 VStringSelect（选项为后端封闭枚举），选择即 PUT `dialogue-settings`，成功后失效设置 query；失败 role=alert 行内提示并保持服务端值。提案列表 GET `preference-proposals`（5s 轮询，与 overview 节奏一致），待确认行展示类型/建议值（枚举值映射为中文行为词，自由文本直显）+ 采纳/保留原样（互斥 pending，决策后同时失效提案与设置缓存）；已处理仅保留最近 6 条。读取失败 VStateSurface error + 重试。文案 zh/en 双语。
### 非职责
不写 Agent 目录、不绕过提案状态机直接改偏好情节记忆（采纳走后端 accept 及其回执）、不做提案的催办/通知（归双通道通知链）、不在组件内持久化任何本地缓存。
### 视觉与状态
面板结构对齐 PersonalAssistantOverview（pinned header + 滚动 content）；设置行卡片化（field 边框卡 + 标签 + 提示语）；提案行左文案右操作；空态复用 empty 图标+文案模式；保存/决策中按钮 isPending 且兄弟按钮禁用。
### 实现落点
`routes/personalAssistant/PersonalAssistantDialoguePreferences.tsx`（组合 VStringSelect/VButton/VStateSurface）+ 同名 `.styles.ts`；API 客户端 `api/virtualHumanLife.ts`，query key `virtualHumanDialogueSettings/virtualHumanPreferenceProposals`。
### 反冗余
复用 VUI 表单原语与 virtualHumanLife 既有客户端模式，不新建第二套 select/设置通道；提案候选值标签只在展示层映射，不在前端维护第二份偏好状态。

## PersonalAssistantAffairs

### 功能
个人助理的事务面板：一个账本三类事务（todo 待办 / schedule 日程 / goal 目标）。顶部 counts 徽标（进行中/已逾期/已完成）来自后端投影；新增行（类型 + 标题 + 可选截止时间）POST 账本；列表按后端排序（open 优先、逾期优先、截止升序）渲染，每行展示类型/截止状态徽标、本地化截止时间与备注。open 行可「完成/取消/设截止」，done/cancelled 行可「重新打开」；设截止在行内展开 datetime-local 编辑器，留空保存即清除截止。类型/状态筛选走查询参数，由 query key 变化驱动重新拉取。
### 适用范围
`/personal-assistant` 工作台右侧 VTabs 的「事务」标签（宽屏）与窄屏 VDialog 入口。不承担主动提醒推送（归 A2 提醒链）、不写 Agent 目录、不提供第二套与工具侧不同的状态机（一切状态迁移都走后端路由，前端只失效缓存）。
### 使用方式
`<PersonalAssistantAffairs agentId headerAction? focusItemId? focusRequestKey? focusRequestResult? onFocusRequestHandled? />`。列表 GET `personal-affairs/affairs`（5s 轮询，与偏好面板节奏一致，kind/status 筛选进 query key）；动作互斥 actingKey，动作后失效整个 personal-affairs 前缀缓存；读取失败 VStateSurface error + 重试；动作失败 role=alert 行内提示。截止时间展示用本地 locale，编辑往返用 datetime-local 值与 ISO 转换。文案 zh/en 双语。提醒导航以路由 key 为定位请求：清除当时的类型/状态筛选，待无筛选列表读取完成后聚焦并滚动至目标行；每次导航只定位一次，后续轮询和用户筛选不重置焦点。定位完成后通过回调把 found/missing 结果交给 Route，重挂载时用已消费结果恢复提示并跳过定位。条目不存在时在固定头部显示可见状态提示，列表仍可正常管理。
### 非职责
不解析自然语言建事务（对话中的结构化工具才是创建入口之一，面板只做手工补录与管理）、不做催办通知、不在前端持久化任何本地缓存或草稿。
### 视觉与状态
面板结构对齐 PersonalAssistantOverview/DialoguePreferences（pinned header + 滚动 content）；计数徽标横排、逾期计数用 error 色；新增表单与筛选行卡片化；事务行左文案右操作，行内截止编辑器以细分隔线展开；空态复用图标+文案模式并区分「无事务」与「筛选无结果」；动作中按钮 isPending 且兄弟按钮禁用。
### 实现落点
`routes/personalAssistant/PersonalAssistantAffairs.tsx`（组合 VStringSelect/VInput/VButton/VStateSurface）+ 同名 `.styles.ts`；API 客户端 `api/personalAffairs.ts`，DTO `api/types/personalAffairs.ts`，query key `personalAffairs`。
### 反冗余
复用 VUI 表单原语与 fetchJson 客户端模式，不新建第二套列表状态或乐观更新层；counts/dueState/排序全部信任后端投影，前端不重复计算。

## PersonalAssistantDispatches

### 功能
个人助理的派遣跟踪面板：聚合展示助理派给其他智能体的任务与回执状态。「派出」列表每行展示目标智能体名、摘要、发出时间、投递状态徽标（pending=待对方接收 / consumed=对方已接收 / revoked=已撤销）、业务状态和回执数。业务状态区分等待结果、进行中、遇到阻塞、收到回复但结果待确认、对方报告完成、对方报告失败和已取消；投递或已读不代表完成。行内可展开查看全部回执（来源/摘要/时间/已读状态/明确报告的任务状态及证据引用）；「收到的回执（未配对）」列出尚未与派出任务配对的回执，空时整段隐藏。
### 适用范围
`/personal-assistant` 工作台右侧 VTabs 的「派遣」标签（宽屏）与窄屏 VDialog 入口。只读跟踪；派遣的创建入口是对话中的结构化工具，不归本面板。
### 使用方式
`<PersonalAssistantDispatches agentId headerAction? />`。列表 GET `/api/personal-assistant/dispatches?limit=50`（5s 轮询，与事务面板节奏一致，隐藏时停止）；类型与 query key 内联在 `api/personalAssistantDispatches.ts`，不改 `api/queryKeys.ts`。读取失败 VStateSurface error + 重试；空态显示「还没有派遣记录」加一句对话引导。回执展开是纯组件本地 state，不进缓存。文案 zh/en 双语。
### 非职责
不创建/重发/撤回派遣、不修改 deliveryStatus 或回执已读状态（后端投递链权威）、不持有消息 transcript、不做催办通知（归双通道通知链）。
### 视觉与状态
面板结构对齐 PersonalAssistantAffairs（pinned header + 滚动 content）；行卡片化，状态/回执数徽标复用事务面板徽标样式（pending 用主前景色突出）；回执以细分隔线在行内展开，与未配对回执共用同一紧凑行样式；时间显示沿用事务面板的本地 locale 格式；空态复用图标+文案+引导模式。
### 实现落点
`routes/personalAssistant/PersonalAssistantDispatches.tsx` + 同名 `.styles.ts`；API 客户端 `api/personalAssistantDispatches.ts`。
### 反冗余
复用 VUI 原语（VButton/VStateSurface）、fetchJson 客户端与事务面板的列表/徽标模式，不新建第二套轮询、badge 组件或消息存储；投递状态与回执配对全部信任后端投影，前端不重复计算。
