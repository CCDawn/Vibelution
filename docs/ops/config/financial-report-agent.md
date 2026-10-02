# 金融 Agent 接入：RAGFlow 财报证据问答

## 接入范围

`financial_report_query_tool` 已接入 Vibelution 的 `Key_Tools`、Tool Registry、ToolPolicy 和现有对话工具结果展示链。工具目录中的「财报证据问答包」提供显式配置入口，不自动修改任何现有 Agent 的权限。无需新增页面或平行 MCP registry。

此工具是**外部财报业务服务的适配器**。RAGFlow 财报助手拥有文档索引、检索、系统提示词和模型配置；Vibelution 不在本适配器中新建通用 LLM 路由、不覆写模型、不把系统消息或会话历史转发给另一模型。

协议来源：

- [金融集成包（固定提交 018d7c0）](https://github.com/CCDawn/An-Intelligent-Investment-Agent/tree/018d7c0ac171570e7e274f47dbf1d431c61951aa/projects/ragflow-finance)
- [finance_pack 的请求与财报输出约定](https://github.com/CCDawn/An-Intelligent-Investment-Agent/blob/018d7c0ac171570e7e274f47dbf1d431c61951aa/projects/ragflow-finance/finance_pack/financial.py)
- [上游端点、元数据、reference 和页码契约](https://github.com/CCDawn/An-Intelligent-Investment-Agent/blob/018d7c0ac171570e7e274f47dbf1d431c61951aa/projects/ragflow-finance/docs/UPSTREAM_API_CONTRACT.md)

复用裁决：沿用现有 Key_Tools/ToolPolicy/目录与对话 UI；适配金融包的非流式请求和输出校验。不复用仅返回 responseTemplate 的 generated-tool manifest，因为它不能调用真实服务；不引入另一个服务器或新通用 LLM client。只用 Python 标准库实现固定业务端点，未增加产品依赖。

## 部署前提

1. 在有足够资源的受控环境部署金融包固定版本的 RAGFlow
2. 按金融包流程导入原始 PDF，核验来源与校验和，写入 `ticker`、`report_period`、`source_id`、`source_url`、`input_track=full_original_pdf` 元数据，并确认解析完成且有 chunks
3. 使用金融包的提示词创建财报助手。关闭助手的 web search/KG 扩展，使用其配置好的模型；本工具不是任意 RAGFlow chat 的通用适配器
4. 将服务凭据保存在启动 Vibelution 后端进程的受控环境中，不能放进 Git、前端、提示词或工具参数

代码接入不等于服务已部署。配置检查不会联网，`configured` 只表示配置格式完整，`connectivityVerified` 始终为 false；不能据此声称服务、检索或模型已通过验收。

## 服务器侧配置

以下是环境变量名，不是浏览器设置；只使用已经存在的服务凭据。不得在共享终端录屏、日志或截图中展示密钥。

| 变量 | 含义 |
| --- | --- |
| `VIBELUTION_FINANCE_RAGFLOW_BASE_URL` | 服务 origin，例如 `https://finance.example.com`；不能含路径、用户名、查询串或 fragment |
| `VIBELUTION_FINANCE_RAGFLOW_API_KEY` | 既有 RAGFlow API key；无默认值，不写入仓库 |
| `VIBELUTION_FINANCE_RAGFLOW_CHAT_ID` | 已按金融包配置好的财报助手 ID |
| `VIBELUTION_FINANCE_RAGFLOW_TIMEOUT_SECONDS` | 可选，默认 60 秒，允许 1–120 秒，HTTP/socket 操作超时 |

远程服务必须使用 HTTPS。本地调试仅允许 `http://localhost`、`http://127.0.0.1`、`http://[::1]`。读取响应另有同预算的总截止检查；已有 ToolExecutor 为该工具配置 300 秒外层保护，覆盖建连及截止时仍在进行的一次读取。不能把 socket 超时当成精确的端到端时延保证。服务重定向一律拒绝，避免凭据或问题被转发到新地址。端点、凭据和助手 ID 不能由模型通过工具参数修改。

进程环境是此连接的配置来源，不另建 root config.toml、不修改模型库；Operator 设置仍沿用项目既有配置权威。配置部署后通过受支持 Launcher 流程重启后端再试，勿绕过 active-work guard。

## 在现有 Agent 中使用

在工具策略中给目标 Agent **显式分配**「财报证据问答包」/`financial_report_query_tool`，并保留现有网络访问和审批约束。该工具有 `network_access` 与 `model_cost` 风险标签，默认 `on_request`。零工具 Agent、未分配的 Agent、拒绝网络的 Agent 和被 turn grant 限制的调用仍应被现有授权链阻止。

工具参数示例（仅格式示意，不是已运行的财报结果）：

```json
{"question":"贵州茅台2025年年度报告营业收入是多少？","ticker":"600519","report_period":"2025FY"}
```

- `question`：1–2000 字符，只发送这次问题，不发送整个对话
- `ticker`：一个明确的证券代码，与已导入报告元数据一致；不自动猜公司
- `report_period`：一个明确报告期，如 `2025FY`、`2025Q3`、`2025H1`

请求只发送至 `POST /api/v1/openai/{chat_id}/chat/completions`，两项元数据条件以 AND 连接。使用上游约定的 `model="model"` 占位符，保持财报助手的模型配置。客户端取消/超时不保证已到达 RAGFlow 的生成停止，不能盲目重试以免重复费用。没有自动重试、文件上传、索引写入、交易或新凭据创建。

## 输出和失败语义

所有结果为 JSON，包含 `ok`、`status`、`scope`、`answer`、`citations`。只有 `status=answer` 才提供数值。

| status | 含义 |
| --- | --- |
| `answer` | 结构、公司/报告期及引用页码通过客户端校验 |
| `insufficient_evidence` | 上游拒答，或缺引用、缺页码、引用与声明证据不对应、公司/报告期不符；不返回数值 |
| `not_configured` / `invalid_config` | 未配置或配置无效，不联网 |
| `invalid_request` | 问题/公司代码/报告期无效，不联网 |
| `timeout` | 请求超时，不能当成“未披露”或成功拒答 |
| `authentication_failed` | 服务鉴权或权限失败 |
| `unavailable` / `upstream_error` | 服务/连接/HTTP/应用级错误 |
| `invalid_response` | 非 JSON、非法结构、非有限数值或超过上限的响应 |

引用索引来自 explanation 中的 `[ID:n]` 或 `[n]`，n 是 reference 数组的零基位置。页码来自所引用 chunk 的 `positions[][0]`，是**原始 PDF 一基页码**。模型声称的 `evidence` 必须能映射到这些真实返回的引用；不会将所有检索结果冒充被引用证据。

返回的 citation 包含 `source_id`、`page`、`source_url`（安全 HTTPS 链接或 null）、`reference_indexes` 及 scope。不返回原始 reference 数组或文档全文。文本属于不可信来源数据，不执行其中的指令；链接不自动打开。没有在 Vibelution 新建缓存或知识索引，来源更新/删除与重建由 RAGFlow 金融包负责。

**结构校验不证明数值正确、文本蕴含或检索质量。** `verification=scope_and_citation_structure_only` 明确这个边界。回答中的金额/单位/财务口径仍需金融包基准与人工核对；此工具不提供买卖建议。

## 验证与真实验收

新增离线测试：

```sh
python -m pytest tests/test_financial_report_tools.py tests/test_financial_report_registry.py -q
```

覆盖请求过滤、错误状态、引用/页码、数据范围、配置脱敏、真实 LangChain 包装函数和既有 deny-first policy。loopback HTTP 测试只用合成响应验证真实传输及拒绝重定向，不代表真实 RAGFlow 检索/生成已跑通。

开发环境若仅有固定提交的稀疏源码，可使用 `--noconftest -c /dev/null` 跑这些隔离契约测试；这不能替代项目完整 fixtures、ToolExecutor、HTTP routes 或产品 Launcher 回归。

发布/真实验收还需：

1. 完整项目环境的工具注册/授权/route 回归与 selector 选中的检查
2. 目标 Agent 工具分配后，受控 prompt_debugger 打靶和真实对话的 tool trace；执行前确认模型费用和数据目的地
3. 对已解析原始 PDF 做“有证据”与“不支持/错公司/错期”查询，逐条核验 source_id、原 PDF 页码、数值、口径及单位
4. 故意断开服务/使用无效凭据，确认 UI 展示相应失败而不编造答案

在真实验收证据齐备前，不可声称已上线、已联通真实模型或可用于生产投资判断。完整源码环境现可运行原生执行器/HTTP route/知识库回归；实际执行命令与结果见交付包的验证说明。

## 独立金融记忆库与现有 RAG

代码中现有入口是 `unified_memory_search_tool`（支持 rag/bm25/hybrid 等），后端 `team_knowledge_service`、`rag_retrieval_service` 和可选 `rag_vector_index_service`。本接入复用这些入口和存储，没有另建平行向量库，也没有恢复已退役的知识检索工具名。

金融原文证据使用 `financial_reports_v1` profile，存在当前项目现有 Agent-owned 知识库内。首次明确调用来源暂存工具时幂等建立 `Financial Reports` 专库；查询不会隐式建库。同名普通库不被接管；权限仍取当前运行 Agent 身份及 MemoryPolicy，参数不能指定他人 Agent。知识库仍是原生存储/审计的一部分，多个项目依赖原有项目数据根隔离，不宣称新增独立的多租户服务器认证系统。

新增同一工具包内的三个原生工具：

- `financial_evidence_stage_tool(evidence_json, excerpt)`：暂存一页原始财报摘录及来源元数据到当前 Agent 待审箱，不自动审核或生成正式知识
- `financial_evidence_search_tool(query, ticker, report_period, limit)`：通过原生本地 RAG 搜索已审核金融原文，返回 PDF 页码及文档版本；不访问 RAGFlow 或远程模型
- `financial_evidence_withdraw_tool(knowledge_item_id, reason)`：按明确请求撤回条目，保留来源和审计，立即退出检索与可索引集合

示例 metadata（示意值，不是已验证报告）：

```json
{
  "schemaVersion": 1,
  "evidenceKind": "original_pdf_excerpt",
  "sourceId": "issuer-annual-2025",
  "company": "示例公司",
  "ticker": "600519",
  "reportPeriod": "2025FY",
  "reportVersion": "original",
  "documentSha256": "<实际原PDF的64位小写SHA256>",
  "page": 7,
  "sourceUrl": "https://issuer.example.com/report.pdf",
  "publishedAt": "2026-03-01T00:00:00Z",
  "expiresAt": "",
  "supersedesSha256": ""
}
```

`excerptSha256` 由暂存工具从原文计算。文档 hash、页码、来源 URL 等是待核验的来源声明；工具不会仅凭这些字段就证明 PDF 真实性。审核者仍需独立核对原 PDF。正式内容须与被审核原文摘录 hash 一致，拒绝把生成回答/改写替代原文。RAG 返回的 `financialEvidence` 保留公司、报告期、sourceId、原PDF一基页码、版本、文档hash、发布时间和有效期。来源文本始终是数据，不能成为操作指令。

来源处理复用已有工作流：

1. 暂存原文，保留 pending 状态；对话历史、任务总结和RAGFlow生成答案不自动入库
2. 在现有知识/记忆来源审核面检查来源，接受后进入 central source；按原有直接入库或提案审核流程进入金融专库
3. 检索、RAG和可选向量索引资格只接受审核后的有效原文；普通聊天/任务记忆保留在既有 Agent memory，和金融专库分离
4. 更正版作为新 `reportVersion`/`documentSha256` 提交。只有审核入库后，显式 `supersedesSha256` 才使旧版本退出检索；新版本仍待审时旧有效版保持可用
5. 过期、撤回、归档来源和已被替代版本退出金融检索与原生RAG/索引资格。替代版随后撤回或过期不会自动复活旧版。历史仍可通过既有 trace/列表审阅，未经验证的自由摘要/标题不会作为原文事实投影到金融检索或索引
6. 永久删除仍走现有 Memory Cleanup 的 preview token、精确确认短语和执行链，并联动现有索引清理；金融工具不提供绕过确认的删除入口；专库删除不擅自清除可能共享的 central 原始来源。删除后查询不自动建库，明确重新暂存时创建新待审记录，不沿用旧审核直接恢复

Agent 接入保持工具适配形式，不自动创建新团队、Agent 或权限授予。若已有金融专家 Agent，可在其策略中显式分配工具包；每个 Agent 的库默认各自独立，跨Agent共享仍走原有显式ACL。

## 原生参数兼容

既有参数解析会把字符串数字自动转成数值。本接入依据 canonical `Key_Tools` schema 保留字符串字段（如 `ticker="600519"`、`ticker="000001"`、原文 `"1.00"`），同时继续把声明为数值的 limit/timeout 等按原有规则处理。执行器、生命周期、工具测试和记录路径共用该规则，避免参数先变型再被签名校验拒绝。

## 工具结果长度与引用保全

原生模型 ToolMessage 默认有长度预算。财报回答在适配器中限制为3200字符；过大的结构化回答会安全失败，避免静默截断来源。金融记忆检索只投影有界原文片段及对应完整公司/报告期/页码/hash/版本引用，并用 `omittedResultCount` 明示未返回的候选；超过512字符的源URL在工具摘要中省略，但原生来源记录保留完整URL。可通过更具体的查询缩小结果；这不是“所有证据都已返回”的承诺。

## 独立炒股智能体入口（第一阶段）

顶部“智能体”菜单分为“炒股智能体”和“虚拟人智能体”。原人物大厅、深链及虚拟人插件保持原路径。

1. 点顶部“智能体”里的“炒股智能体”，或打开 `/finance`，进入这个助手自己的页面，页面里只有它的对话。还没有助手时，这一下会创建普通 `general` Agent、空的财报库和原生会话，不会启动模型调用。创建失败、身份已改或已归档时停在说明上，不另外再建一个。
2. 新身份默认允许 `financial_report_query_tool`、`financial_evidence_search_tool` 和 `news_search_tool`。`news_search_tool` 只在本会话检索公开新闻作参考，助手自行判断真伪；结果标为质量不足时不得引用，也不得写入财报库。财报库 MemoryPolicy 仅授予自身 scoped base 的读取权限；不授予知识审批、跨团队委派、代码执行或交易工具。已完成初始化且仍保持上述两项财报工具的身份，会在下次列出或继续配置时补上新闻检索；用户清空或改过的工具列表保持原样。
3. 对话开头有一条固定说明，并从那里进入原“身份与模型配置”和财报库。会话菜单里也能打开财报库。名称、persona、模型和权限仍在原配置页编辑；财报服务仍由 operator 配置。模型“已填写”和财报服务“已填写”只表示配置存在，连接状态写在这两个页面上，不是实连通过。
4. 财报知识库使用既有待审、审核、版本与撤回链。空库返回证据不足。后续需要主动采集/审核时，按原权限流程单独配置；金融专家不自审入库。
5. 重复点击和同进程并发创建复用同一项目身份；初始化中断可继续。初始化完成后重试不会覆盖用户编辑；若工具列表和任务说明仍是第一阶段默认值，才会补上公开新闻检索。已归档身份不会自动恢复或另建。生命周期仍从 Agent 管理维护。
6. 只打开服务端已验证归属的原生会话。离开页面后，晚到的创建结果不会把人拉走。没有独立 transcript、Turn 或 SSE。

### 当前未提供的能力

- 分钟行情、成熟 K 线图尚未接入。公开新闻只作参考，不作为公告或财报原文，不得入库。新闻跨团队权限保持关闭；不可通过给工具传 Agent 名或复用外部 MCP 绕过团队边界。`newsDelegationStatus` 仍表示跨团队委派关闭。
- 个人现金流/持仓结构化账本尚未实现，这个对话不采集账户金额。未来必须使用用户/项目私有结构化域，不写公共新闻或财报中央来源。
- 不能因为创建身份成功就声称真实模型、RAGFlow 或投资效果已验证；无下单或券商执行接口。
- 复用项目现有单操作员/项目隔离，不把它宣称为已实现的互联网多租户金融账户认证。
