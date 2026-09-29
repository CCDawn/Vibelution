# 监督进化工作区

## SupervisedConversationWorkspace

### 功能

将真实 Agent 对话作为监督进化主视图。顶部提供阶段与 Agent 选择、新建、证据和更多入口；左栏承载评估来源、样本数、阶段进度、历史和配置。

### 适用范围

监督进化实时工作区。运行历史和评测库继续使用原有列表详情布局。

### 使用方式

`EvolutionRoute` 传入真实来源、阶段状态、`conversation`、`setup`、`footer` 和 `evidenceTabs`；壳组件管理导航与证据面板的展开状态。

- 桌面顶部一行，目标高度 48px；窄屏两行，目标高度 88px。
- 阶段和 Agent 使用同一个选择入口；查看历史阶段后可返回当前阶段。
- 桌面左栏宽 248px，可收起；窄屏通过顶栏导航按钮打开左侧抽屉。阶段入口与顶栏共用选择回调及可用性，不创建另一套运行状态。
- 对话在本工作区内左对齐，最大正文宽度 1120px；调整只作用于本工作区，不改变普通会话页。
- 证据默认关闭，桌面使用 `VSplitWorkspace` 侧栏，窄屏使用 `VDialog`。
- 新建打开评估来源选择；取消恢复原先草稿。运行记录中的来源保持只读。
- 历史和运行配置在左栏直接访问；更多菜单保留评测库、完整会话及左栏收起时的备用入口。

### 数据与状态

对话继续使用 `SupervisedAgentConversationPanel` 的原生 Session 查询、合并和实时轮询。非空 Session 消息优先于工作流摘要。只显示 API 已返回的来源信息、文件变更和评分，不生成样例、伪造补丁或评分依据。

审批紧凑栏复用 `SupervisedApprovalDecisionPanel` 和服务端 `actionStates`。批准、已提交、激活中和已生效是不同状态；确认时再次检查动作是否仍然可用。

### 实现落点与反冗余

实现位于 `web/src/routes/SupervisedConversationWorkspace.tsx`。复用 VUI 按钮、菜单、弹窗、分页与分栏组件；不增加 renderer 或第二套会话实现。布局宽度使用 `WORKBENCH_LAYOUT_IDS.evolution` 的共享 pane persistence。

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
