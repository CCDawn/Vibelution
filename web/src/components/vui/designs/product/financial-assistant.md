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
本地金融专家的桌面 A 股研究与独立模拟账户。参考 TradingAgents-CN v3.0 社区版的研究、筛选、自选、报告、记忆、技能、学习与模拟交易信息架构；独立实现，不复制受限前后端源码。真实券商交易与 Pro 专属交易系统不属于这个页面。

### 使用方式
复用 `VSplitWorkspace`、`VStateSurface`、`VSkeleton`、`VInput`、`VSelect`、`VTabs`、`VButton`、`VChip`、`VIconButton`、`VSurface` 与 `VRouteLinkButton`。桌面三栏可拖动、折叠，宽度只经 `WORKBENCH_LAYOUT_IDS.finance` 与共享 pane persistence 保存。不做手机版和手机弹窗；1280px 与 1920px 桌面窗口均需验收。Finance 样式来源显式登记在 shell Tailwind 入口；路由代码分块加载与入口初始化均使用同一 frame，避免冷启动闪过通用壳。金融页面隐藏泛化聊天 starter 与模型、权限等技术设置，配置入口保留在左栏新研究按钮旁；原生工具授权入口仍完整保留。
GET 无自动创建；菜单或 `/finance` 这一下才会 POST。POST 幂等且并发串行。
只打开服务端验证 Agent/Session 绑定后返回的 sessionId，经 `useChatRouteSelection.openSession`。
离开入口后，晚到的结果不导航。已归档或身份已改不另建。
公开新闻复用既有 `news_search_tool`，只在本会话作参考；助手判断真伪，不写入财报库，不开启跨团队委派。
原生 `financial_market_snapshot_tool` 允许金融助手在追问中读取公开报价与日/周/月 K 线。研究过程只展示原生 tool call 名称与状态，不另建工具结果流。旧助手仅在服务端投影 `marketToolStatus=upgrade_available` 时展示 `VButton`「启用行情查询」；点击才调用既有幂等 POST，默认策略可升级，禁网、黑名单与自定义工具策略保持原样。写入中或原生研究运行/停止中按钮禁用；失败复用操作错误面，成功刷新助手查询缓存。GET 与页面读取不修改权限。

### 研究记录与输入
研究记录由 `querySessions` 按金融 Agent 查询并核对绑定。历史深链先读取轻量会话元数据，拒绝其他 Agent、已归档及 Companion 身份；不把普通会话套上金融身份。新研究走原生 `createChatSession`，同步 ref 防双击，未知结果重试沿用幂等键，晚到结果经当前路由 CAS 不抢页面。
股票身份来自行情搜索或用户选中的有效自选，历史研究通过原始用户问题恢复股票上下文，不从资料标题推断。分析日期、报告期、研究范围和深度写入实际请求。“开始研究”先写入原生 composer，只有相同草稿已提交到 React 状态且身份一致时才触发原生提交；已有消息时新建原生 Session。不直接调用消息写入 API。Session Journal、SSE、消息流、停止和 HTML 导出仍归原生会话；侧栏投影真实 busy/stopping、工具调用和待授权状态，不模拟多 Agent、阶段或百分比。

### 行情与报告
`FinanceStockOverview` 展示 Tencent 公共报价、来源与时间，保留元、手单位和延迟提示；数值不可用显示缺值，不估算。`FinanceStockChart` 使用真实前复权 OHLC、成交量和 MA5/20，支持日/周/月、悬停与方向键；前复权缺失时保留报价并显示 K 线错误，不把未复权数据错标为前复权。
`FinanceResearchReport` 只投影已完成原生 Turn 的 `final_answer`，不把思考、工具返回或未完成内容变成报告。摘要、章节和引用都来自实际回答，Markdown 导出仅导出该回答。报告章节使用 `VTabs`，正文复用原生 Markdown renderer；股票上下文不匹配时显示空态。相同 PDF 的不同页分别保留。`FinanceResearchHistory` 只读原生研究记录，提供关键词、状态筛选与分页。
自选只保存金融 Agent 范围内的有效股票身份，不保存行情、报告、transcript 或第二套会话状态。

### 桌面研究交互补充
沿用已确认的 TradingAgents-CN 单股详情方向和现有三栏布局，使用现有 VUI 控件扩展。图表以 `VTabs` 切换 MA、BOLL、MACD、RSI 及 30/60/全部已加载 K 线，`VIconButton` 向前/向后平移；SVG 只负责金融图形与命中，拖动和 Shift+方向键平移，方向键选择 K 线并播报真实日期/OHLC。指标基于完整已加载数据计算后再裁剪；样本不足显示缺值，不补造历史。股票/周期改变后重置窗口。
报告摘要只保留实际结论文字；纯财务表格直接保留列与单位，完整报告不重复压平摘要。工具“部分结果/备用来源/数据不可用”等语义沿原生字段投影，用警示图标和文字同时说明，不画成普通成功。
报告中心关键词通过原生 `querySessions(q)` 搜索全部本助手研究正文，输入加载、失败重试、空结果与同条件分页保留在原列表。最近研究不受关键词影响。原生 API 没有报告结果筛选契约，结果状态选择器明确只过滤已加载列表，不能把空闲阶段标成已完成。

### 财报资料
资料栏使用已绑定的 Agent-owned 财报库，所有条目、trace、source body 请求携带同一 agentId 和 knowledgeBaseId。仅显示有效条目；原文来源另核对 sourceArtifactIds、库归属、PDF 类型、生命周期与过期时间。公司、代码、报告期、版本、页码及链接只来自 sourceRef.financialEvidence，不解析自由标题当事实。无元数据就不显示对应字段，无有效原文就不展示摘录。
摘录使用 React 纯文本；外链只允许无认证信息的 HTTP/HTTPS，打开新窗口使用 noopener。点击报告引用时按有效 sourceRef URL 和 PDF 页码匹配本库来源，定位原文与 `#page=N` 链接；未匹配时明确告知，不把无关资料当引用。最多读取20条有效条目的 trace。

## 对话说明与连接状态

### 功能
正式工作台不设重复产品标题栏，三栏直接接在应用导航下；三栏宽度以当前容器为上限，右栏和报告列表约束最小内容宽度，长文本换行或截断单行标题。行情区域单独显示来源与报价时点。配置与财报管理链接留在对应栏位，避免与原对话说明重复。其他金融会话入口仍可用 `FinancialAssistantChatNote`；普通会话不增加说明。模型未配置时给简短状态，已填写不等于连接已验证。会话原有 HTML 导出保留。

### 适用范围
只在该助手自己的会话、配置和财报库出现。普通会话、其他 Agent 和虚拟人会话不出现。

### 使用方式
复用 `VStateSurface` 与 `VRouteLinkButton`。列表查询失败时说明不出现，不挡住对话。

### 非职责与反冗余
`FinanceResearchFrame`、`FinanceResearchWorkspace` 与 `FinanceReportLibrary` 共用 `FinanceRoute.styles`，保持加载、工作台与资料栏一致。`FinanceGeneralResearch` 复用知识中心的表单几何，`FinanceWatchlistTable` 与筛选页共用市场表格样式；所有共享消费者在 `vuiImportBoundary` 中逐项登记，不另建重复映射。
不新增 VUI primitive、第二套身份/配置存储、聊天组件、transcript 或 SSE；金融阶段协调复用原生后台任务与生命周期，不另建调度系统。
金融建议与工具沿原生 Agent 权限。股票查询、真实行情与 K 线通过独立只读域 API 校验；模拟账户另用 Agent-owned 账本与明确的虚拟资金接口，不能连接券商或真实资金。

## FinanceGeneralResearch / FinanceTaskCenter

### 功能与使用
通用主题研究使用现有 `VTextarea`、`VInput`、`VSelect` 和 `VButton`，支持行业、政策和投资主题。五级深度写入实际请求；创建独立原生 Session 后，经已提交的原生 composer 启动，没有第二套消息流。主题报告使用原生完成答案，打开历史主题时不套用股票匹配过滤。
任务页组合 `VSurface`、`VChip` 与 `VButton`，展示已加载原生记录的运行、完成、停止、失败和待继续状态；计数对应当前已加载记录，分页继续读取原生索引。空会话占位不算研究任务。

## FinanceMarketExplorer / FinanceWatchlistTable

### 功能与使用
股票筛选使用 `VInput`、`VSelect`、`VButton`、`VDenseTable` 和 `VStateSurface`。结构化条件只作用于已取得的真实股票池，结果明确给来源覆盖数、抓取时点和完整性。自然语言选股只生成原生研究草稿；未运行模型时不显示 AI 选股结果。来源不提供行情日期或市值单位时保留空值并说明，不能把抓取日期当成交日期。
新闻、公告和财务指标使用 `VSurface` 与原文外链，逐项保留来源、发布日或报告期，三块分别呈现错误、缺值与重试。公开数据不冒充已审核 PDF 财报证据。
自选组合既有身份偏好与批量 Tencent 报价，按实际数值排序。单只查询失败保留该行和错误；数字保留元、手和百分比单位，不从股票名称生成数值。
表格只在自身容器横向滚动，各页在中栏纵向滚动；左、右栏继续受共享桌面 pane 约束。

## FinancePaperTrading

### 功能与使用
使用 `VSurface`、`VMetricStrip`、`VDenseTable`、`VInput`、`VSelect` 和 `VButton` 展示虚拟资金、持仓、费用、订单记录和月度复盘。GET 未开账户不建文件，用户明确点击才开设固定100万元模拟资金。下单只传股票、方向、数量、理由和幂等标识，价格由服务端腾讯来源决定；按钮同步防双击，未知结果重试沿用同一标识。
模拟 A 股买入整手、余额、持仓和北京时间自然日 T+1 由服务端检查，页面明确其模拟规则。报价时间、旧价估值和缺值可见，不能把获取时间当新报价。复盘只按真实账本汇总，不生成没有历史持仓估值依据的净值曲线。AI 复盘只在点击后准备包含实际账本的原生草稿。

## FinanceKnowledgeCenter

### 功能与使用
使用 `VSurface`、`VButton`、`VInput`、`VTextarea` 与 `VStateSurface` 组合研究记忆、技能与学习中心。偏好明确保存到同一金融 Agent 的原生 personal memory，原生运行时仍负责加载；GET 不写入。保存与移除只由用户点击，成功后使同一 Agent 查询失效并读回；关闭个人记忆时禁止保存。
私有资料只读取同一 Agent/actor 的原生详情，正文用 React 纯文本；未绑定的其他 Agent 数据不显示。技能展示原生已安装库，选取后使用原生 slash command；原生提交时再次解析文件并记录实际版本，不另建技能执行器。技能与记忆文本不覆盖工具和数据权限。
学习中心提供独立编写的五课、八项实践指南与校验题。当前股票练习进入实际原生 composer；课程正文只在选择后显示，切换课程重置答案反馈。

## FinanceAnalystTeam / FinanceAnalystTeamInspector / FinancePortfolioResearch

### 功能与使用
分析员协作使用 `VSurface`、`VInput`、`VSelect`、`VChip`、`VButton` 和原生 Markdown renderer。行情、基本面、新闻在各自的原生 Agent/Session 执行，再由独立乐观与审慎分析员检查，最后由主助手汇总。页面只投影原生 Turn 的真实状态和完成答案；运行引用绑定 Session、Turn 和 submission，停止只停止该 Turn。配置漂移、会话归属变化与未知提交都给实际原因，不补造百分比或报告。原始分析员会话通过原生 chat 页面打开。
明确提交基础分析并确认接受后，服务端通过原生持久后台任务继续推进；离开页面不暂停后续阶段。页面轮询等候和运行中的协调记录，阻断原因通过 `VStateSurface` 呈现，不自动重发。完成状态要求精确汇总 Turn 的最终回答；旧记录无协调状态时保留原有兼容路径。汇总失败、停止或缺回答不显示为仍在汇总。
分析卡片按桌面中栏可用宽度自动分列，使用一条完整的 grid template，避免其他延迟路由的基础 grid 样式覆盖断点。`FinanceAnalystTeamInspector` 复用 `VChip`、`VStateSurface` 和 `VButton`，跟随当前选中的研究轮次，显示股票、日期、实际已保存的分析引用与服务端协调状态；归档前的主助手旧标题不混入本轮进度。完整 Turn 引用和已完成协调同时存在时才显示完成，查看汇总跳转该轮次的精确 Session。
已接受的 Turn 在对话读取中或读取失败时显示对应读取状态，进度计数暂留空，不回退为未提交或 0/5。刷新同时重新读取该轮次的精确对话，不能因此重新发送分析。
组合研究使用 `VSurface`、`VMetricStrip`、`VDenseTable` 与 `VButton`，复用当前助手的模拟账本。持仓权重、现金和集中度按实际账本与报价计算；收益相关性仅来自共同日期的真实 K 线，样本不足保留缺值。点击股票回到已有单股页，AI 研究只准备包含账本和来源的原生草稿。

## FinanceSessionMenu / useFinanceSessionLifecycle

### 功能与使用
最近研究、报告和任务列表复用 `VDropdownMenu`、`VIconButton` 与 `VConfirmDialog`，提供原生归档、恢复和删除。运行中记录提示先停止；删除使用标准确认，成功才更新缓存与原生 tombstone。当前记录移除后只选择已验证的同助手存活研究，异步响应不能抢夺用户后续导航。
报告中心以 `VTabs` 切换活动记录与原生归档列表，后者核对同一 Agent 并保留分页、空态、失败重试。已归档直达研究显示恢复或新建操作，保留金融助手身份，不另建归档或删除存储。
