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
独立个人助理入口，提供原生聊天与平台管理概览；桌面模式沿用同一个 Agent、Session 与记忆。
### 适用范围
仅 `/personal-assistant`，与炒股智能体、虚拟人入口并列；普通会话与虚拟人保留原有页面。
### 使用方式
组合 VSplitWorkspace、VButton 与 PersonalAssistantOverview。`WORKBENCH_LAYOUT_IDS.personalAssistant` 持有概览宽度记忆。首次访问幂等创建或恢复助理；身份与原生 Session detail 的 agentId/directSessionId 均一致后才挂载 ChatCodingRoute。桌面按钮先检查原生能力，打开助理窗口并保留工作台任务。
### 非职责
不持有 transcript、composer、记忆副本或执行进度；原生 Session/SSE 与审批持有权威。
### 视觉与状态
聊天为主体，可调整、可收起的概览侧栏；加载、错误与身份冲突用 VStateSurface；窄屏可收起概览。页面根节点在横向 VWorkbenchFrame 中占满可用宽度并参与伸展，避免按内容宽度缩成左侧窄列。
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
先用 `getDesktopAssistantContext` 核实 role/mode，再验证助理 Agent/Session 绑定。`setDesktopPetExpanded` 申请固定安全尺寸（收起 300×330 / 展开 760×600）。收起态身体为 `DesktopPetCharacter`，外观跟随 `vibelution.desktop-pet.preferences.v1` 的 characterId（默认大肥鲸，可切小洛）；4px 移动阈值区分单击与拖动，拖动经 Electron IPC（desktopPetWindowDrag）移动窗口并沿用位置持久化。工具栏提供状态提示、助理设置（状态/标题隐私/完成提示/空闲文案，保存失败明确提示仅本次有效）、外观切换与关闭。展开态使用 `VSplitWorkspace` 与 `WORKBENCH_LAYOUT_IDS.desktopAssistant`：main 为 `ChatCodingRoute` 原生会话，aside 为实时对话列表（`/api/pet/activity` 轮询，活动 1s/空闲 3s）与 `PersonalAssistantOverview`。会话跳转只调用 `openConversationFromPet(sessionId)`，必须得到主进程 `opened: true`，失败保留列表并提示；标题隐私开关隐藏会话标题与智能体名。supportedModes 门（"pet"|"assistant"）对旧壳保持兼容，Electron 的 desktopPetWindowUrl 把两种模式请求都收敛到 `/desktop-assistant`。

### 非职责
不以 URL marker 证明原生身份，不停止会话，不保存消息、不判断 Turn 权威、不创建 Companion mailbox，也不修改普通 Session admission、worker、projection 或 composer；不显示用户消息、工具参数、审批 payload 或模型推理正文。

### 视觉与状态
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
