# 智能体菜单与金融助手入口

## SpecialistAgentMenu

### 功能
替代顶栏原“虚拟人”直达按钮，向下显示“炒股智能体”和“虚拟人智能体”。

### 适用范围
桌面顶栏及移动导航共用；仅聚合入口，不改变人物大厅和会话链路。

### 使用方式
组合现有 `VDropdownMenu` + `VButton`，`side="bottom"`；`onNavigate` 交回壳层原导航与遥测。
pathname 决定当前项及按钮高亮。Radix 管理键盘、Esc、外点和焦点；路由变化关闭菜单。
原 `/companions` 和 Companion 深链保留。禁用 chat 域时菜单不可用。

## FinanceRoute

### 功能
`/finance` 是炒股智能体自己的投研工作台。菜单进入、加载、失败与正式对话共用 `financial-assistant-workspace` 框架。左栏放研究标的、报告期和真实研究记录，中间保留原生会话，右栏显示财报库资料。还没有助手时，入口创建身份、空财报库和会话；打不开时在原布局内给原因和重试。

### 适用范围
本地项目单一金融专家，第一阶段只读研究。不是行情终端、自动交易或个人账户账本。

### 使用方式
复用 `VSplitWorkspace`、`VStateSurface`、`VSkeleton`、`VInput`、`VButton`、`VDialog` 与 `VRouteLinkButton`。桌面三栏，800px 以下记录与标的放入弹窗，1200px 以下财报资料放入弹窗；保留键盘、Esc 和焦点返回。固定列宽，不另存布局尺寸。Finance 样式来源显式登记在 shell Tailwind 入口；路由代码分块加载与入口初始化均使用同一 frame，避免冷启动闪过通用壳。金融域布局 CSS 防止后台预加载的共享 utility 覆盖列宽，并仅校正金融弹窗的动画居中和窄屏边距；其他视觉样式沿用 Tailwind 与 VUI tokens。金融页面隐藏泛化聊天 starter，财报、事件与风险任务由标的栏填入原生草稿。
GET 无自动创建；菜单或 `/finance` 这一下才会 POST。POST 幂等且并发串行。
只打开服务端验证 Agent/Session 绑定后返回的 sessionId，经 `useChatRouteSelection.openSession`。
离开入口后，晚到的结果不导航。已归档或身份已改不另建。
公开新闻复用既有 `news_search_tool`，只在本会话作参考；助手判断真伪，不写入财报库，不开启跨团队委派。

### 研究记录与输入
研究记录由 `querySessions` 按金融 Agent 查询并核对绑定。历史深链先读取轻量会话元数据，拒绝其他 Agent、已归档及 Companion 身份；不把普通会话套上金融身份。新研究走原生 `createChatSession`，同步 ref 防双击，未知结果重试沿用幂等键，晚到结果经当前路由 CAS 不抢页面。
公司/代码与报告期是用户的研究输入，不从资料标题推断股票身份。财报、事件、风险仅通过金融范围的 Context 填入原生草稿并聚焦，不自动发送。Session Journal、SSE、消息流、停止和 HTML 导出仍归原生会话；状态栏只读投影真实 busy/stopping，不模拟阶段、暂停或恢复。

### 财报资料
资料栏使用已绑定的 Agent-owned 财报库，所有条目、trace、source body 请求携带同一 agentId 和 knowledgeBaseId。仅显示有效条目；原文来源另核对 sourceArtifactIds、库归属、PDF 类型、生命周期与过期时间。公司、代码、报告期、版本、页码及链接只来自 sourceRef.financialEvidence，不解析自由标题当事实。无元数据就不显示对应字段，无有效原文就不展示摘录。
摘录使用 React 纯文本；外链只允许无认证信息的 HTTP/HTTPS，打开新窗口使用 noopener。资料栏明确是库内资料，本报告的引用以原生回答为准；不把整个资料库假称本次引用。

## 对话说明与连接状态

### 功能
正式工作台在页头说明行情未接入，配置与财报管理链接留在对应栏位，避免与原对话说明重复。其他金融会话入口仍可用 `FinancialAssistantChatNote`；普通会话不增加说明。模型未配置时给简短状态，已填写不等于连接已验证。会话原有 HTML 导出保留。

### 适用范围
只在该助手自己的会话、配置和财报库出现。普通会话、其他 Agent 和虚拟人会话不出现。

### 使用方式
复用 `VStateSurface` 与 `VRouteLinkButton`。列表查询失败时说明不出现，不挡住对话。

### 非职责与反冗余
`FinanceResearchFrame`、`FinanceResearchWorkspace` 与 `FinanceReportLibrary` 共用 `FinanceRoute.styles`，保持加载、工作台与资料栏一致；三个消费者在 `vuiImportBoundary` 中逐项登记，不另建重复样式映射。
不新增 VUI primitive、第二套身份/配置存储、聊天组件、transcript、SSE 或后台调度。
金融建议与工具沿原生 Agent 权限；未来行情图仍需成熟图表库和独立来源验证。
