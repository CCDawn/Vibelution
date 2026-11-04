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

待处理/进行中/已结束选项统计当前身份已加载记录。执行成功、失败、超时、取消、停止及清理未完成均进入已结束，绑定了终态回执的派遣记录在同步失败后仍归已结束并保留状态未确认提示。其余状态未确认的记录保留在待处理，并可按本地引用交宿主重新核验。首次默认首个非空桶，用户切换后保留选择。任务刷新保留原卡片，身份或可见性丢失关闭详情并停止后续清理请求。

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

行内清理 VButton 使用紧凑图标，并保留完整的无障碍名称和 tooltip，避免挤压窄栏中的任务标题与负责人。详情中的操作保留文字。

卡片显示任务名称、负责人、状态及独立的清理 VButton，详情行与清理按钮为相邻按钮。点击详情行在居中 VDialog 查看详情，移动端先关闭原导航。点击单项清理立即核验并执行，无需打开详情或确认。已知活动任务不提供行内清理。状态未确认的单项操作显示“移除记录”，tooltip 为“核验后仅移除本地记录，保留源任务和文件”，发送 `localOnly: true` 由宿主核验本地记录移除资格。清理已完成始终保留入口，有未读取的团队分页时也可点击。单项与批量共用忙碌状态，防止并发重复请求。

## LauncherAssistantTaskDetail

### 功能

查看单项任务的原生进展、结果和引用。

### 适用范围

仅 Launcher 已绑定身份的任务，不承载普通会话或全平台列表。

### 使用方式

仅 Launcher 卡片选择时显示；组合现有 VDialog/VChip/VButton，正文宽度最多560px、窄屏两侧留白，保持原聊天与草稿在后方挂载。

### 视觉与状态

显示名称、Agent、当前状态、项目与更新时间、公开进展/结果/错误，引用编号和步骤等放在“引用信息”。关闭、右上角关闭与 Esc 保留草稿并恢复可见焦点。详情清理按钮和行内按钮走同一条直接清理链路，已知活动任务与冲突记录禁用。状态未确认时详情也使用“移除记录”及相同 tooltip，实际资格与终态由宿主判定。

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

展示清理进行状态、实际释放字节、保留原因及逐项失败结果，提供一键重试。

### 适用范围

用于 Launcher 任务卡的单项清理和当前助理全部已结束事项的批量清理。批量先重读派遣记录、完整遍历团队运行 cursor，覆盖未加载页和未显示的记录，再提交终态候选和可定位的待同步关联。批量目标均使用常规清理范围，状态未确认的目标也不发送 `localOnly`。宿主逐项复核实际状态，给仍在执行或来源未确认的任务返回原因。

### 使用方式

组合现有 `VDialog` 与 `VButton`。用户一次点击后，内部调用 `previewTaskCleanup`，立即携带宿主 fingerprint 调用 `executeTaskCleanup`。弹窗只反馈进行状态和结果，执行期间禁用关闭。结果提供关闭与重试清理，重试只针对未完成引用，并重新执行宿主核验。

直接清理每批 2 条关联，核验后立即执行，再继续下一批，覆盖全部候选及团队别名。传输层复用有界、五分钟有效、单次消费的内存计划关联原生 fingerprint。身份、可见性变化或卸载通过 AbortSignal 停止后续分页与清理批次。重复或无效 cursor 显示错误并允许重试。未获确认的批次保留失败原因，释放字节累计宿主已确认的净变化。

团队同一 run 的 sourceRefs 去重后全部传给 host。待同步团队记录可省略未知的 teamId、flowId、runId，由 host 根据本地关联解析。host 判断独占文件、共享会话和团队资源保留边界。界面刷新权威列表，partial / blocked 保留结果及重试入口。

独占工作区含未提交改动、未合入代码、来源不明的忽略文件、锁定或不安全链接时，预览阻断整项删除，保留任务卡片及重试入口；不凭缓存目录名强删。明确共享的项目源码与其他任务引用的工作区可保留后删除本项独占记录。字节统计按同一文件范围的实际净变化计算，扣除新增的最小防重复记录，不把共享数据库的可复用空间或 Git 对象算成已经释放。

### 视觉与状态

收集任务、核验并清理、执行成功、全部受阻与部分失败均有文字状态。单项说明随范围展示，状态未确认记录明确保留源任务和文件。结果显示实际释放字节、逐项保留原因及宿主具体错误，源资源保留项显示“源任务和文件”，失败提供重试清理。当前助理身份改变、身份未确认或窗口不可见时关闭反馈，旧异步回复不能恢复状态。

### 实现落点

`routes/desktopPet/assistantTasks/LauncherTaskCleanupDialog.tsx`、`assistantTaskCleanup.ts` 与 `api/launcherAssistantTaskCleanup.ts`。

### 反冗余

复用 VDialog 的 Radix 焦点和关闭行为。内部核验计划和执行结果均由宿主提供。
