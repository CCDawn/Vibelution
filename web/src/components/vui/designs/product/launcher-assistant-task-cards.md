# Launcher 个人助理任务卡

已批准的任务卡方案；复用现有 VUI primitive，不新增按钮、卡片或对话框 renderer。

## LauncherAssistantTaskCards

### 功能

在个人助理任务窗口展示当前已加载的派遣任务与已登记团队运行，帮助用户知道谁在处理什么、最新进展及哪些任务需要自己处理。原生执行成功只表示执行已结束，仍待业务验收。

### 适用范围

仅用于 Launcher 个人助理的身份绑定任务视图。普通 Agent 会话、Session transcript、团队执行控制和全平台任务统计由各自 owner 负责。

### 使用方式

`LauncherAssistantTaskCards` 接收 `lang`、`onReview`、`onApproval`。它复用 `VSurface`、`VChip`、`VButton`、`VStateSurface`、`VSkeleton`，由现有 `LauncherAssistantWorkspaceRoute` 的 `VDialog` 承载。

卡片按「需要你处理 / 进行中 / 已结束」分组，可用 VButton 折叠；分组数只代表当前已加载记录。组内按真实更新时间、创建时间倒序排列；无时间记录稳定排在末尾，不用读取时间冒充任务更新时间。

首屏包含短标题、负责人 Agent 名或团队名、项目名、当前状态、两行摘要或失败原因和更新时间。名称缺失时用对应 Agent、团队或项目身份编号标识；身份或时间也缺失时显示「未提供」。未命名任务显示「未命名任务 · 短编号」；不从 prompt、源码或回执正文推断标题。长摘要可展开；完整任务编号、创建时间、团队当前步骤、步骤数和尝试次数放在详情。来源提供当前 Agent 名时也在首屏显示，缺失时不推断。

### 视觉与状态

复用 `vui-fg-*`、`vui-border-subtle` 与现有卡片 surface token。首次无内容读取使用 skeleton；已有卡片刷新时只显示轻量文字，不替换卡片。通信失败显示「状态同步失败」，引用未绑定显示「身份未确认」，不会误报为执行失败。失败、待授权、待输入和未确认放在需要处理组；成功执行待验收与已停止放在已结束组。

所有卡片均提供删除入口，只有来源可用、身份绑定且已确认原生终态时启用。工具栏「清理已完成」仅包括当前已加载且原生 `succeeded` 的派遣任务及 `completed` 的团队运行；确认页说明业务验收仍未完成。

宿主仅在用户确认清理并核验终态后设置 `cleanupPending: true`。此类任务显示「清理未完成，可重试」，进入需要处理组并提供「重试清理」；即使后台读取原生回执返回 TASK_NOT_FOUND，仍可用保留的 project/nativeTaskId 引用重新向宿主预览。批量清理亦包含这些已确认但未完成的清理记录。缺失、字符串标记、无绑定引用或冲突观测不会开启恢复权限。

### 实现落点

`routes/desktopPet/assistantTasks/LauncherAssistantTaskCards.tsx` 与同目录 projection / metadata / cleanup 模块。普通会话、LauncherAssistantRoute 不参与此组合。

### 反冗余

复用现有卡片组件，不建立第二套任务 store；查询缓存只持有服务端事实和展示信息，折叠状态只属于本次窗口。

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
