# 进化工作台

## SupervisedConversationWorkspace

### 功能

将真实 Agent 对话作为监督进化与自进化的主视图。顶部提供两类进化切换、阶段与 Agent 选择、新建和证据；左栏分组展示真实运行，以及所选运行的来源或目标、阶段进度。

### 适用范围

统一进化实时工作区。两个原有入口选择各自初始类型，进入后可直接切换。运行历史和评测库继续使用原有列表详情布局。

### 使用方式

`EvolutionRoute` 传入真实来源、阶段状态、`conversation`、`setup`、`footer` 和 `evidenceTabs`；壳组件管理导航与证据面板的展开状态。

- 桌面顶部一行，目标高度 48px；窄屏两行，目标高度 88px。
- 顶栏切换保留每类进化最后查看的运行；运行列表的显式选择不会被活动运行刷新覆盖。
- 运行导航保留进行中、待审批、未知状态和当前选中记录；已结束记录进入默认收起的“历史记录（数量）”。展开后按时间显示最近 5 条，其余通过原有历史入口访问；不删除记录，不折叠当前选中项。
- 阶段和 Agent 使用同一个选择入口；查看历史阶段后可返回当前阶段。
- 桌面左栏宽 248px，可收起；窄屏通过顶栏导航按钮打开左侧抽屉。阶段入口与顶栏共用选择回调及可用性，不创建另一套运行状态。
- 桌面导航开合通过共享 `paneVisibilityPersistence` 按 `WORKBENCH_LAYOUT_IDS.evolution` / `run-navigation` 记忆；窄屏弹窗状态独立，关闭弹窗不覆盖桌面偏好。
- 对话在本工作区内左对齐，最大正文宽度 1120px；调整只作用于本工作区，不改变普通会话页。
- 证据默认关闭，桌面使用 `VSplitWorkspace` 侧栏，窄屏使用 `VDialog`。
- 新建打开评估来源选择；取消恢复原先草稿。运行记录中的来源保持只读。
- 历史和运行配置在左栏直接访问；更多菜单保留评测库、完整会话及左栏收起时的备用入口。

### 数据与状态

对话继续使用 `SupervisedAgentConversationPanel` 的原生 Session 查询、合并和实时轮询。非空 Session 消息优先于工作流摘要。只显示 API 已返回的来源信息、文件变更和评分，不生成样例、伪造补丁或评分依据。

监督历史通过现有工作树摘要列表与详情 API 获取，成员、会话、来源与审批来自同一运行详情。阶段与 Agent 选择按运行保存，阅读位置复用原生 Session 的滚动记忆。两个工作区快照提供左栏状态；完整评估目录只在监督类型下获取，隐藏类型不另建对话轮询。

审批紧凑栏复用 `SupervisedApprovalDecisionPanel` 和服务端 `actionStates`。批准、已提交、激活中和已生效是不同状态；确认时再次检查动作是否仍然可用。

### 实现落点与反冗余

实现位于 `web/src/routes/SupervisedConversationWorkspace.tsx`。复用 VUI 按钮、菜单、弹窗、分页与分栏组件；不增加 renderer 或第二套会话实现。布局宽度使用 `WORKBENCH_LAYOUT_IDS.evolution` 的共享 pane persistence。

## SelfEvolutionConversationWorkspace

### 功能

在统一工作台中查看自进化的原生 Agent 会话、候选改动、验证与版本证据，并执行服务端支持的用户审查和恢复动作。

### 适用范围

自主自动闭环、只读观察及已有自进化工作树运行。自主运行只能枚举快照返回的当前与最近记录；观察运行没有历史列表接口，不能用事务记录代替运行历史。

### 使用方式

`EvolutionRoute` 传入选中的运行种类及对应数据，组件复用 `SupervisedConversationWorkspace` 壳。主区按真实阶段 Session ID 加载只读原生会话；没有会话时呈现明确空态。目标、1 轮预算与阶段放左栏，改动、验证和版本证据按需打开。

新建区保留自动闭环与只读观察配置。后端当前自动闭环仅支持 1 轮预算，UI 显示固定值。审批、拒绝、清理重试及观察终止绑定所选运行，确认时核对最新状态。自主闭环没有停止 API，不添加虚假停止按钮。原配置及事务历史通过详情入口访问。

### 数据与状态

会话复用 `fetchSessionDetailWindow`、`mergeSessionDetailMessageWindow` 与 `ChatReadOnlySessionWorkspace`，不把阶段总结转换成 transcript。阶段映射复用自主闭环及工作树的既有契约。完整自进化详情复用 `EvolutionSelfTrackBoundary`，两类业务动作及运行锁仍由原服务端实现。

### 实现落点与反冗余

实现位于 `web/src/routes/SelfEvolutionConversationWorkspace.tsx`，视觉样式放相邻 `.styles.ts`。使用现有 VUI 控件、统一工作区壳和共享会话组件；不增加 renderer 或对话状态权威。

## EvolutionSupervisedLiveSetupPanel

### 功能

在一次新建操作内搜索、选择评估集或评测包，检查来源信息和样本数，然后启动监督进化。

### 适用范围

监督进化新建与按上轮配置重新准备。运行中的来源详情由只读弹窗呈现。

### 使用方式

Route 提供合并的 `sourceOptions` 和受控草稿字段。桌面左侧来源列表、右侧详情；窄屏纵向布局，启动与取消按钮固定在面板底部。

样本数允许留空表示全部，或输入不超过已知总数的正整数；评测包固定使用其案例数。高级设置保留审批方式与心智模式。提交必须同时通过来源、输入校验、后端运行锁和控制状态检查。

### 实现落点与反冗余

实现位于 `web/src/routes/EvolutionSupervisedLiveSetupPanel.tsx`，复用 VUI 表单和按钮。组件不创建运行、不请求模型、不另建评估集目录；这些职责仍由 Route 和现有后端 API 承担。
