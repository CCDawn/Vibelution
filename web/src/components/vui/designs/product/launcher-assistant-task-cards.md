# Launcher 个人助理任务卡

用户已批准 agent-cards-v10。仅修改 Launcher 左栏任务与详情，不改变普通会话、Agent 目录或其他分支。

## LauncherAssistantTaskCards

### 功能

单一身份绑定 provider 复用现有原生派遣与团队运行查询、分页、可见性和轮询保护。桌面左栏和移动导航共享同一组读取与清理状态，不建立第二任务 store，不将任务伪装成 Agent 或 Session。

### 适用范围

仅 Launcher 的身份绑定任务工作区，不用于普通 Agent 会话。

### 使用方式

LauncherShell 持有 provider；LauncherTaskNavigationSlot 在原 LauncherNavigation 唯一任务入口之后挂载自有 portal host，显示 LauncherAssistantTaskSidebar；导航源码保持原样。WorkspaceRoute 保持原聊天和草稿挂载，只从当前助理身份的 reviewRequest 接收显式只读核对请求。旧 panel=tasks 书签进入相同工作区，列表直接在左栏呈现。

### 视觉与状态

卡片原样复用当前 AgentConversationDirectory.styles 的 agentRow/agentAvatar/agentCopy/agentTitle/agentMeta/agentStatusSlot 展示 recipe：36px 方圆角头像、约62px两行结构、右侧运行或关注指示。此处是用户指定复用边界，普通目录源文件和普通会话行为零改动；不借用旧 DirectSessionIndexItem 的错误/提示条。

卡片只显示可读任务名称、负责 Agent 与当前状态。状态不把同步失败误报执行失败，执行已结束不代表业务验收。团队来源未报告当前 Agent 时如实显示团队，详情说明未提供负责人。缺少历史标题时按可信负责人和任务种类标识，不展示“未命名任务”或数字后缀，不从 prompt、源码、结果正文猜标题。

待处理/进行中/已结束选项仅统计当前身份已加载记录；首次默认首个非空桶，用户切换后保留选择。任务刷新保留原卡片；身份或可见性丢失关闭详情并使清理失效。主导航、设置、项目与分支、网页、附件、聊天保持原有功能。

### 实现落点与反冗余

routes/desktopPet/assistantTasks/ 下 provider、context、sidebar、detail 与原 projection/cleanup；AgentConversationDirectory.styles 是卡片几何唯一来源，不复制 token 或引入 renderer。

## LauncherAssistantTaskSidebar

### 功能

显示当前身份的任务列表、分类与必要操作。

### 适用范围

Launcher 原左栏及其移动导航。

### 使用方式

组合 VButton、VTabs、VSkeleton 和现有 Agent 卡片 recipe。桌面与移动导航两个真实消费者从同一 provider 读取模型；不独立发起 API 查询。

### 视觉与交互

卡片无摘要、编号、项目、时间或行内展开。点击完整行在居中 VDialog 查看详情；移动端先关闭原导航。清理已完成始终保留入口，未加载或不可清理时禁用；刷新为有名称的图标按钮。

## LauncherAssistantTaskDetail

### 功能

查看单项任务的原生进展、结果和引用。

### 适用范围

仅 Launcher 已绑定身份的任务，不承载普通会话或全平台列表。

### 使用方式

仅 Launcher 卡片选择时显示；组合现有 VDialog/VChip/VButton，正文宽度最多560px、窄屏两侧留白，保持原聊天与草稿在后方挂载。

### 视觉与状态

显示名称、Agent、当前状态、项目与更新时间、公开进展/结果/错误；引用编号和步骤等放在“引用信息”。关闭、右上角关闭与Esc保留草稿并恢复可见焦点；原生终态可删除，运行/未知来源不可删，部分清理可重新预览后重试。所有删除继续走既有宿主 preview/fingerprint/execute 流程，UI不隐藏任务冒充清理。

## LauncherTaskNavigationSlot

### 功能

把任务侧栏接入原 Launcher 导航位置，避免更改共享导航控制器或重画外壳。

### 适用范围

仅 LauncherShell 的桌面和移动导航包装层；不用于平台普通对话栏。

### 使用方式

局部 ref 内通过现有 launcherAssistantPanelPath("tasks") 定位唯一入口，useLayoutEffect 添加任务自有 host，React createPortal 保留上下文。仅 host 就绪后用 scoped Tailwind selector 隐藏旧入口；匹配失败保留原导航。卸载只移除自有 host，无全局 MutationObserver、事件总线或源组件修改。移动端先关闭导航，再由全局 provider 保持居中详情；关闭后焦点回到可见导航按钮。

### 验证

真实 LauncherNavigation 的 StrictMode 挂载、语言/路由重渲染、重复/缺失锚点与卸载验收不得产生双 host 或丢失既有设置、分支、返回桌面功能。

## LauncherTaskCleanupDialog

### 功能

把真实预览范围、预估字节、保留原因与永久删除确认放在同一条可复核流程中，并展示执行后的实际字节和失败结果。

### 适用范围

仅用于上述 Launcher 任务卡的单项删除和当前已加载成功执行任务的批量清理；不做归档复制、本地隐藏或全平台清理。

### 使用方式

组合现有 `VDialog` 与 `VButton`。打开后先调用 `previewTaskCleanup`；只有预览返回可清理条目后才启用「永久删除」。用户确认后才携带预览 fingerprint 调用 `executeTaskCleanup`。取消不执行删除；失败重试必须重新预览，再由用户确认。

每批最多 32 条关联，按已预览的顺序串行执行，不截断团队别名。超过 512 条关联时明确要求减少范围或逐项删除。传输层以最多 16 条、五分钟有效、单次消费的内存计划关联各批原生 fingerprint；身份或可见性变化通过 AbortSignal 停止后续批次。未获确认的批次显示未确认错误，释放字节仅累计权威已确认结果，不宣称未确认批次成功。

团队同一 run 的所有已加载 sourceRefs 一并传给 host。host 负责判断独占文件、共享会话和团队资源保留边界；团队原生 Agent / flow / run 会话保留并显示原因。界面只刷新权威列表，不自行隐藏卡片，partial / blocked 仍由权威记录保留。

独占工作区含未提交改动、未合入代码、来源不明的忽略文件、锁定或不安全链接时，预览阻断整项删除，保留任务卡片及重试入口；不凭缓存目录名强删。明确共享的项目源码与其他任务引用的工作区可保留后删除本项独占记录。字节统计按同一文件范围的实际净变化计算，扣除新增的最小防重复记录，不把共享数据库的可复用空间或 Git 对象算成已经释放。

### 视觉与状态

预览加载、预览失败、全部受阻、执行中、执行成功与部分失败均有文字状态。结果显示实际释放字节、逐项保留原因和失败；部分失败提供「重新预览后重试」。当前助理身份改变、身份未确认或窗口不可见时使预览失效，旧异步回复不能恢复确认权。危险按钮使用 VUI danger variant。

### 实现落点

`routes/desktopPet/assistantTasks/LauncherTaskCleanupDialog.tsx`、`assistantTaskCleanup.ts` 与 `api/launcherAssistantTaskCleanup.ts`。

### 反冗余

复用 VDialog 的 Radix 焦点和关闭行为，不手写浮层；预览不是本地删档计划，execute 结果不能由 UI 推测。
