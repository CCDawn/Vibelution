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
`/finance` 是炒股智能体的桌面投研工作台。菜单进入、加载、失败与正式页面共用 `financial-assistant-workspace` 框架。左栏放股票搜索、自选、真实研究记录和报告中心；中间展示股票概况、K 线、研究设置、原生对话和报告；右栏展示真实执行过程与财报引用。还没有助手时，入口创建身份、空财报库和会话；打不开时在原布局内给原因和重试。

### 适用范围
本地项目单一金融专家，桌面端只读 A 股研究。参考 TradingAgents-CN v3.0 的股票详情、分析、报告和自选信息架构；不复制其受限前端源码，不宣称 Pro 工坊、自动交易或账户账本能力。

### 使用方式
复用 `VSplitWorkspace`、`VStateSurface`、`VSkeleton`、`VInput`、`VSelect`、`VTabs`、`VButton`、`VChip`、`VIconButton`、`VSurface` 与 `VRouteLinkButton`。桌面三栏可拖动、折叠，宽度只经 `WORKBENCH_LAYOUT_IDS.finance` 与共享 pane persistence 保存。不做手机版和手机弹窗；1280px 与 1920px 桌面窗口均需验收。Finance 样式来源显式登记在 shell Tailwind 入口；路由代码分块加载与入口初始化均使用同一 frame，避免冷启动闪过通用壳。金融页面隐藏泛化聊天 starter 与模型、权限等技术设置，配置入口保留在页头；原生工具授权入口仍完整保留。
GET 无自动创建；菜单或 `/finance` 这一下才会 POST。POST 幂等且并发串行。
只打开服务端验证 Agent/Session 绑定后返回的 sessionId，经 `useChatRouteSelection.openSession`。
离开入口后，晚到的结果不导航。已归档或身份已改不另建。
公开新闻复用既有 `news_search_tool`，只在本会话作参考；助手判断真伪，不写入财报库，不开启跨团队委派。

### 研究记录与输入
研究记录由 `querySessions` 按金融 Agent 查询并核对绑定。历史深链先读取轻量会话元数据，拒绝其他 Agent、已归档及 Companion 身份；不把普通会话套上金融身份。新研究走原生 `createChatSession`，同步 ref 防双击，未知结果重试沿用幂等键，晚到结果经当前路由 CAS 不抢页面。
股票身份来自行情搜索或用户选中的有效自选，历史研究通过原始用户问题恢复股票上下文，不从资料标题推断。分析日期、报告期、研究范围和深度写入实际请求。“开始研究”先写入原生 composer，只有相同草稿已提交到 React 状态且身份一致时才触发原生提交；已有消息时新建原生 Session。不直接调用消息写入 API。Session Journal、SSE、消息流、停止和 HTML 导出仍归原生会话；侧栏投影真实 busy/stopping、工具调用和待授权状态，不模拟多 Agent、阶段或百分比。

### 行情与报告
`FinanceStockOverview` 展示 Tencent 公共报价、来源与时间，保留元、手单位和延迟提示；数值不可用显示缺值，不估算。`FinanceStockChart` 使用真实前复权 OHLC、成交量和 MA5/20，支持日/周/月、悬停与方向键；前复权缺失时保留报价并显示 K 线错误，不把未复权数据错标为前复权。
`FinanceResearchReport` 只投影已完成原生 Turn 的 `final_answer`，不把思考、工具返回或未完成内容变成报告。摘要、章节和引用都来自实际回答，Markdown 导出仅导出该回答。报告章节使用 `VTabs`，正文复用原生 Markdown renderer；股票上下文不匹配时显示空态。相同 PDF 的不同页分别保留。`FinanceResearchHistory` 只读原生研究记录，提供关键词、状态筛选与分页。
自选只保存金融 Agent 范围内的有效股票身份，不保存行情、报告、transcript 或第二套会话状态。

### 财报资料
资料栏使用已绑定的 Agent-owned 财报库，所有条目、trace、source body 请求携带同一 agentId 和 knowledgeBaseId。仅显示有效条目；原文来源另核对 sourceArtifactIds、库归属、PDF 类型、生命周期与过期时间。公司、代码、报告期、版本、页码及链接只来自 sourceRef.financialEvidence，不解析自由标题当事实。无元数据就不显示对应字段，无有效原文就不展示摘录。
摘录使用 React 纯文本；外链只允许无认证信息的 HTTP/HTTPS，打开新窗口使用 noopener。点击报告引用时按有效 sourceRef URL 和 PDF 页码匹配本库来源，定位原文与 `#page=N` 链接；未匹配时明确告知，不把无关资料当引用。最多读取20条有效条目的 trace。

## 对话说明与连接状态

### 功能
正式工作台在页头说明只读 A 股研究，行情区域单独显示来源与报价时点。配置与财报管理链接留在对应栏位，避免与原对话说明重复。其他金融会话入口仍可用 `FinancialAssistantChatNote`；普通会话不增加说明。模型未配置时给简短状态，已填写不等于连接已验证。会话原有 HTML 导出保留。

### 适用范围
只在该助手自己的会话、配置和财报库出现。普通会话、其他 Agent 和虚拟人会话不出现。

### 使用方式
复用 `VStateSurface` 与 `VRouteLinkButton`。列表查询失败时说明不出现，不挡住对话。

### 非职责与反冗余
`FinanceResearchFrame`、`FinanceResearchWorkspace` 与 `FinanceReportLibrary` 共用 `FinanceRoute.styles`，保持加载、工作台与资料栏一致；三个消费者在 `vuiImportBoundary` 中逐项登记，不另建重复样式映射。
不新增 VUI primitive、第二套身份/配置存储、聊天组件、transcript、SSE 或后台调度。
金融建议与工具沿原生 Agent 权限。股票查询、真实行情与 K 线通过独立只读域 API 校验，不提供账户或订单接口。
