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
聊天为主体，可调整、可收起的概览侧栏；加载、错误与身份冲突用 VStateSurface；窄屏可收起概览。
### 实现落点
`routes/PersonalAssistantRoute.tsx`、`routes/personalAssistant/*`。
### 反冗余
复用 ChatCodingRoute 与 VSplitWorkspace，不创建消息列表或第二套设计系统。

## DesktopAssistantRoute

### 功能
在透明原生窗口显示大肥鲸，点击展开聊天与平台概览，返回同一个工作台会话。
### 适用范围
仅原生验证的 `/desktop-assistant`；旧 `/desktop-pet` 与虚拟人页面独立保留。
### 使用方式
先用 `getDesktopAssistantContext` 核实 role/mode，再验证助理 Agent/Session 绑定。`setDesktopPetExpanded` 申请固定安全尺寸。展开使用 VSplitWorkspace 与 `WORKBENCH_LAYOUT_IDS.desktopAssistant`。关闭只关闭窗口。`openConversationFromPet(sessionId)` 返回唯一同源的原工作台（主或分支），工作台按固定 source 接入并再次校验绑定。
### 非职责
不以 URL marker 证明原生身份，不停止会话，不修改桌宠偏好或洛天依。
### 视觉与状态
默认复用 WhaleRigCharacter，按钮为 VButton/VIconButton；顶部可拖动、按钮可操作；旧壳与身份错误明确提示。折叠状态复用 `/api/pet/activity` 的平台活动投影及既有动画映射，显示运行、待审批、失败等实际状态；读取中与读取失败有独立文案，不伪造空闲状态。
### 实现落点
`routes/desktopPet/DesktopAssistantRoute.tsx`、既有鲸鱼 renderer 与原生桌面 API。
### 反冗余
复用鲸鱼 renderer、窗口尺寸桥和聊天宿主，不另建渲染器或消息存储。

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
VStateSurface 表达加载与失败；空列表用简短文案；共享状态标签与语义 token。
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
