# Product — Agent perception management

## AgentPerceptionPanel

### 功能
在 Agent 中心为单个 Agent 配置可查询来源、触发条件、后台调研边界和通知方式，并查看服务端记录的运行事实。

### 适用范围
- **适用**：选择 Agent 后的“感知管理”面板。
- **不适用**：知识库 ACL、工具授权、知识写入、审批、个人记忆保存与记忆内容管理；这些权限继续由各自 owner 管理。

### 使用方式
- 由 Agent 中心的 `AgentPerceptionPane` 负责按 Agent 查询策略和运行事实、提交带 Agent ID 的保存/取消请求；`AgentPerceptionPanel` 只呈现当前 Agent 的数据与草稿。
- 面板入口固定为“感知设置 / 运行记录”，默认进入感知设置。切换 Agent 时回到设置页，避免把上一 Agent 的运行记录误认成当前设置。
- 桌面端使用共享可调 pane 显示运行摘要；窄屏堆叠显示设置/记录和摘要，不增加独立的宽度持久化机制。

### 结构
- 来源范围按该 Agent 有界个人 episodic memory 与正式私有知识库、指定团队、共享知识库、本地成熟项目索引分组；团队和共享知识库选项来自服务端授权过滤后的配置响应。
- 每个来源独立设置关闭、按需查询或自动感知，并配置任务、知识更新和后台计划触发器。
- 后台调研单独展示启用状态、间隔、每日次数、每次调用与输入/输出上限及用户主题；每个 Agent 保持单任务并发。
- 通知策略支持仅重要、全部和静音投递。静音不关闭知识更新扫描。通知列表只呈现更新元数据；未投递字段表示待处理的新更新，不代表静音状态或真实外部送达回执。关联原生 Session 时提供会话入口。
- 面板固定展示“感知设置 / 运行记录”两个入口，默认打开设置；运行记录页展示实际执行、来源读取和知识更新通知。
- 宽屏将当前运行状态与最近实际读取摘要固定在右侧，设置和记录共用左侧内容区；窄屏纵向堆叠，导航仍位于内容上方。右侧 pane 使用 `WORKBENCH_LAYOUT_IDS.agentPerception` 和共享 pane 宽度记忆。
- 运行区分当前可用来源和执行记录：`readableSources` 只反映策略与当前权限，实际读取依据 `lastActivity` 或运行中的 `activeRun.sources`。本地项目索引通知用 `local-project-governance` 标识并显示为“本地成熟项目索引”，普通知识库仍按已有授权名称映射。

### 组合方式
页面只组合现有 VUI 产品 API：`VSection`、`VSettingsGroupCard`、`VSettingsRow`、`VCheckbox`、`VSwitch`、`VNativeSelect`、`VInput`、`VButton`、`VChip`、`VStateSurface`、`VTabs` 和 `VSplitWorkspace`。不在业务路由直接使用 renderer，也不新增并行控件。

`AgentPerceptionPanel` 属于 `routes/agentPerception` 的页面组合，没有新增 `components/vui` 独立导出组件。来源授权、草稿和原生 Session 运行记录由所属页面提供；通过面板交互测试、Agent 选择/草稿测试以及正式实例的设置/运行记录与桌面/窄屏验收覆盖，不列入独立组件静态预览目录。

来源卡片在宽屏采用双列，窄屏回到单列；列表、长主题、Agent ID 和运行 ID 均允许收缩或换行。配置加载、策略未保存、策略修订冲突、校验失败、运行加载失败和无读取记录分别呈现，不用演示值填补正式数据。修订冲突时保留本地草稿、暂停保存，并提供显式加载最新策略操作。

### 信任边界
- 保存配置只改变 Agent 感知策略，不增加 ACL 或工具能力，也不改变 episodic memory 保存权限。
- 未保存策略时延续既有行为；显式保存关闭后阻止后续感知读取，不清除已经进入会话的内容。
- 运行事实不得从策略决策或当前可读数量推断。通知只显示服务端提供的元数据，不把正文或摘要伪装成通知内容。

### 反冗余
- 继续使用 Agent 中心现有 pane、设置行和表单 primitives；不另建通用 perception 表单库。
- 后台研究的预算与来源边界由策略 DTO 持有，页面不保存第二份持久状态。
