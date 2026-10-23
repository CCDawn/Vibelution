# 个人助理 API 文档与操作入口

`tools/personal_assistant_tools.py` 每次验证唯一助理和原生直属 Session，随后调用本包。
工具名及实际授权仍由 canonical tool registry、ToolPolicy 和原生执行授权决定。

| 文件 | 所有权 |
| --- | --- |
| `api.py` | GET-only 回环网关：注册端点与固定已审路径交集、私密子路径拒绝、禁跟随重定向、固定错误回执、令牌进程内持有 |
| `catalog.py` | 从运行时 OpenAPI 导航所有注册 API，按 operationId 描述用途、参数、请求/响应 schema 及可执行入口 |

## 先发现，再操作

`personal_assistant_platform_api_tool(path="catalog", query="agents", offset=0, limit=20)`
搜索全部注册 API；tag 可过滤领域，total 和 truncated 指明是否还有下一页。
`path="describe", operation_id=<目录中的真实 operationId>` 返回该操作的参数及引用的 schema。
描述来自实际注册的 OpenAPI，不维护第二份接口参数表；schema 最多 32 个组件、48,000 字符，
超出时明确标记。没有适配器的 API 仍会出现在文档中，标为 operator_only；出现于目录不授予执行权限。

普通写操作使用 `personal_assistant_action_tool(action=..., parameters=<对象>)`，
先 action=index，再 action=describe、parameters={"action":"具体操作"} 查询准确 schema。
参数直接传对象，避免嵌套 JSON 字符串。外层每次核验唯一个人助理及原生直属 Session；
工具必须显式授予，原生 ToolPolicy 保留最终执行权。

| 操作 | 参数与行为 |
| --- | --- |
| agent_create | display_name、request_id，可选 model_id、mission。默认沿用助理对话模型，创建仅有消息协作权限的普通 Agent；不授予命令或文件权限。 |
| agent_update | agent_id、updates 对象。字段用 API camelCase；仅名称、模型、提示词、人物/任务档案、推理与压缩设置。局部档案更新保留其他字段，默认使用当前配置版本进行并发检查。 |
| agent_avatar | agent_id、avatar_image_path，或 reset_to_default=true；先 avatar_options 取得现有图片。 |
| settings_catalog / settings_update | 查看可用设置及现值，随后 updates=[{section,key,value}]。支持应用显示名、头像预设、偏好、语言、普通界面设置与现有壁纸；显示名和简介可清空恢复默认。整批校验后事务写入并读回核验。 |
| model_options / model_add | 精简目录始终包含助理 currentModel（providerId、upstreamId）；可 query 搜索、model_id 精确查询、offset/limit 分页（默认20，最多30）。随后 provider_id、upstream_id，可选 model_key、label。在已配置 Provider 增加模型，不接受凭据、网络地址或 Provider 修改。 |
| team_status | run_id，可选 team_id、wait_seconds（0–30）。省略团队 ID 时从自己的创建回执定位，数字形式也必须匹配自己的原始 ID。只读取自有团队原生状态、Session/Turn 引用及最终团队产物，不打开任意参与者会话正文。 |

扩展动作由 `pa_assistant_actions.py`、`pa_config_actions.py`、`pa_workspace_actions.py` 各自的
`contracts()` 生成准确 schema，汇总进同一 index/describe。每项声明 `governed`；为 true 时直接使用
`personal_assistant_manage_tool(action=<同名动作>, arguments_json=<parameters 的 JSON>)`，原生审批仍绑定完整参数。
不存在任意 HTTP 写网关；适配器只复用 owning native service 或精确配置事务。API catalog 中的原始 HTTP schema
用于理解服务接口，调用适配器必须使用 action describe 的参数，不能把整个 publicConfig/rawToml 交给模型。

| 领域 | 动作与验证方式 |
| --- | --- |
| 助理自身 | `assistant_settings`、`assistant_settings_update`、`assistant_model_set`：名称、外观、提示开关、空闲文案、已配置对话模型，写后读回。 |
| 对话偏好 | `dialogue_settings`、`dialogue_settings_update`：当前唯一助理的主动说话、提问与偏好建议方式；在原生 Agent 锁中读合并写，未指定项保留。 |
| 模型连接 | `provider_catalog`、`provider_add/update/remove/test/discover`、`provider_models`：连接目录只返回公开 origin、标识和状态；凭据留在服务端，同 origin 才可复用既有凭据。新密钥不得经模型文本提交。发现与连接测试不代表真实任务或生图完成。 |
| 模型配置 | `model_update/remove/default`：精确写入已固定模型，删除检查活动引用；默认目标为已有 profile、image2 或 git。Git 原生路径支持 v2 provider/model 与别名。image2 资格筛选不代替真实生图验证。 |
| 会话 | `workspace_list`、`session_get`、`session_parameters_get` 只投影公开标识和参数；`session_pin/unpin`、`session_reasoning_update`、`session_model_parameters_update`、`session_budget_update`、`session_archive/unarchive` 保留 native CAS/生命周期边界。不得选择操作者当前会话或改动助理自身会话。 |
| 团队与群聊 | `team_get`、`team_update`、`room_get`、`room_update`：按名称发现，再修改受限元数据；不返回消息、私有档案或路径，不改变成员权限。团队归档必须额外通过原生团队 admission 保护。 |

只接受已登记动作；新增 HTTP route 或新 schema 字段不会自动获得写权限。权限变更、电脑操作授权、审批决定、
purge、内部证据写回和私密正文不得借 API catalog 执行。未接入项仍明确标为 `operator_only/executable=false`，
不能把“已文档化”解释成“已接入”或“已实测”。

删除、权限和重启仍走 `personal_assistant_manage_tool` 原生审批。
该工具新增 `action="team_run"`：arguments_json 包含 name、goal、request_id，可选 template_id="dev-team"。
一次审批后复用内置四角色模板，创建规划师、两位开发者、评审员及团队，保存顺序原生工作流并启动。
不启用故障自动恢复、不授予自动合入或部署权限。返回 teamId、flowId、runId 和 status；
running 仅表示已启动，需以 team_status 核验终态。执行、记录和产物仍由原生工作流/Session 负责。

创建使用当前助理/直属 Session 与稳定 request_id 的持久幂等记录。同 key 不同输入拒绝；
未知或部分结果保留已知对象 ID 并要求核验，不通过更换 key 自动重建。
模型新增复用已有 key 时仅在上游模型相同的情况下返回 existing，不覆盖冲突。
普通更新不接受身份、工具/记忆权限、角色键、生命周期或任意 metadata，不能用它绕过审批。

## 边界

- **方法固定 GET**：没有方法参数；写侧管理继续走 `personal_assistant_manage_tool` 及其审批。
- **令牌不出进程**：执行器在进程内取 `core.web.control.get_control_token()` 并自行加
  `X-Vibelution-Control-Token` 头；模型侧永远见不到令牌。
- **只打注册端点**：目标路径必须匹配当前 OpenAPI 规范的 GET 集合（`ensure_web_routes_registered`
  幂等，启动早期调用会等待路由挂载）。目标固定为 `http://127.0.0.1:<port>`；path 只接受
  `/api/` 开头的具体路径，拒绝 URL、query、fragment、模板占位符、编码字符、反斜杠、空段、
  `.`/`..` 段和空白/控制字符，避免请求与服务端路由解码不一致。
- **动态路径逐项开放**：目前仅允许 `/api/sessions/{session_id}/llm-options`、
  `/api/sessions/{session_id}/budget-parameters` 两个配置 GET；调用时将 `{session_id}` 换成真实 ID，
  一个占位符只匹配一个完整段。其他动态详情不进入索引，新增路由不会自动扩大授权。
- **固定已审路径**（`PUBLIC_GET_OPERATIONS`）：18 个静态路径及6个动态路径。
  原有头像选项、群聊 mode/purpose、runtime code-freshness、Launcher freshness/current-instance/
  workbench-window/startup/developer-mode 和 usage summary 保持可用；财务助理目录、股票 search/quotes/screen、
  团队知识库目录和研究来源/任务目录使用逐路径公共字段投影。动态除两个 Session 参数路径，还包括
  financial-preferences workspace、financial-portfolios research 和 financial-jobs schedules/batches。
  投影裁掉提案正文、ACL、记忆、instructions、rationale、terminalReason、日志、agentContext 和研究偏好派生 tags。
  tag 仅用于导航，不能自动授权新接口。
  runtime summary、diagnostics health、Session archive 及 Companion 聚合含会话派生内容，因此原始读取拒绝；
  需要公开信息时用 overview、workspace_list 或其他带身份和字段投影的适配器。
- **私密子路径拒绝**（`DENIED_PATH_TOKENS`，词级匹配）：路径段按 `-`/`_` 分词后命中
  messages/transcript/export/timeline/inbox/events 任一整词即拒绝（`member-messages` 拦、
  `messaging-status` 放），即使处于允许 tag 下；自身 inbox 读取继续走 project-query 包。
- **会话正文不开放**：`/api/sessions/{session_id}` 默认 `transcriptScope=all`，即使传入
  `transcriptScope=none` 也不允许通过网关；queued-turns、artifacts 等其他 Session 对象路径同样
  拒绝。chat-room 列表与详情会返回 rounds/messages，因此 `/api/chat-rooms` 和其动态详情均拒绝。
  `/api/agents`、`/api/agents/config-workspace` 也不通过原始网关读取，避免跨 Agent 档案与配置聚合泄露；
  名称与状态使用个人助理 overview 或 query 的公开投影。
  `/api/sessions`、`/api/sessions/query`、`/api/sessions/bootstrap` 与动态 `child-sessions` 的
  原始目录 DTO 会携带来自 lastPreview 的 taskSummary，搜索还可能返回 journal 正文 searchSnippets，
  因此也从调用和索引中移除。操作者活动会话 `/api/sessions/active` 同样拒绝。
  会话查询使用 `personal_assistant_query_tool` 的公开 `sessions` 投影；自身 inbox 也沿用该工具的
  身份边界。普通 Session 路由不作修改。
- **query 不做客户端校验**：主机与路径已由白名单固定，query 由服务端自行解析；网关原样透传，
  空值不追加 `?`。
- **响应即不可信数据**：每个回执带 `untrustedContent: true`；载荷超过
  `MAX_RESPONSE_CHARS` 截断并标记 `truncated`。

## 导航协议

`path="index"` 返回 tag 总览（含每个 tag 的端点数）；`path="index", tag="agents"` 列出该
tag 的端点（path+summary，封顶 `INDEX_ENDPOINTS_CAP`）；`path="/api/agents/avatar-options"` 直接 GET
（可选 `query` 传 urlencode 的分页/过滤参数）。回执统一
`{ok, status, observedAt, source, untrustedContent, ...}`。

## 验证

`tests/test_personal_assistant_platform_api.py`：白名单/拒绝规则、注册端点门、动态路径与私有详情隔离、目录正文泄漏拒绝、
索引形状、hostname/port 断言、本机临时 HTTP server 的带令牌 GET 往返、
注入假 urlopen 的取数与截断、HTTP 错误不读正文、真实跨 origin 重定向拒绝与令牌不转发。不修改普通 Session admission、Journal、
worker、persist 或 SSE。

新增契约测试：`test_personal_assistant_api_catalog.py`、`test_personal_assistant_actions.py`、
`test_personal_assistant_settings_actions.py`、`test_personal_assistant_team_actions.py`。
扩展覆盖 `test_personal_assistant_assistant_actions.py`、`test_personal_assistant_config_actions.py`、
`test_personal_assistant_workspace_actions.py` 与 `test_personal_assistant_platform_operations.py`。
隔离测试通过不表示真实模型或桌面通知验收通过；后者需记录实际工具调用、原生终态和业务写回证据。
