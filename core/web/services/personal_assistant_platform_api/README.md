# 个人助理平台 API 网关（只读）

`tools/personal_assistant_tools.py` 每次验证唯一助理和原生直属 Session，随后调用本包。
工具名及实际授权仍由 canonical tool registry、ToolPolicy 和原生执行授权决定。

| 文件 | 所有权 |
| --- | --- |
| `api.py` | GET-only 回环网关：OpenAPI 注册端点 + tag 白名单 + 私密子路径拒绝 + 响应截断 + 令牌进程内持有 |

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
- **tag 白名单**（`ALLOWED_TAGS`）：runtime/launcher/runtime-tasks/cli-agents/agents/sessions/
  chat-rooms/teams/team-workflows/knowledge/research/git/evolution/usage/diagnostics 等
  状态与管理面。排除 `memory`（Agent 私密记忆）、`external-agent`（MCP 协议面）、
  `user-content`/`files`（用户原始文档）、`logs`（原始日志走 project-query 包）、
  `config`（供应商凭据，脱敏未证明前不开）、`computer-use`（屏幕数据走授权的电脑工具）与无 tag 端点。
- **私密子路径拒绝**（`DENIED_PATH_TOKENS`，词级匹配）：路径段按 `-`/`_` 分词后命中
  messages/transcript/export/timeline/inbox/events 任一整词即拒绝（`member-messages` 拦、
  `messaging-status` 放），即使处于允许 tag 下；自身 inbox 读取继续走 project-query 包。
- **会话正文不开放**：`/api/sessions/{session_id}` 默认 `transcriptScope=all`，即使传入
  `transcriptScope=none` 也不允许通过网关；queued-turns、artifacts 等其他 Session 对象路径同样
  拒绝。chat-room 列表与详情会返回 rounds/messages，因此 `/api/chat-rooms` 和其动态详情均拒绝。
  `/api/sessions`、`/api/sessions/query`、`/api/sessions/bootstrap` 与动态 `child-sessions` 的
  原始目录 DTO 会携带来自 lastPreview 的 taskSummary，搜索还可能返回 journal 正文 searchSnippets，
  因此也从调用和索引中移除。仅返回 ID 的 `/api/sessions/active` 仍可调用。
  会话查询使用 `personal_assistant_query_tool` 的公开 `sessions` 投影；自身 inbox 也沿用该工具的
  身份边界。普通 Session 路由不作修改。
- **query 不做客户端校验**：主机与路径已由白名单固定，query 由服务端自行解析；网关原样透传，
  空值不追加 `?`。
- **响应即不可信数据**：每个回执带 `untrustedContent: true`；载荷超过
  `MAX_RESPONSE_CHARS` 截断并标记 `truncated`。

## 导航协议

`path="index"` 返回 tag 总览（含每个 tag 的端点数）；`path="index", tag="agents"` 列出该
tag 的端点（path+summary，封顶 `INDEX_ENDPOINTS_CAP`）；`path="/api/agents"` 直接 GET
（可选 `query` 传 urlencode 的分页/过滤参数）。回执统一
`{ok, status, observedAt, source, untrustedContent, ...}`。

## 验证

`tests/test_personal_assistant_platform_api.py`：白名单/拒绝规则、注册端点门、动态路径与私有详情隔离、目录正文泄漏拒绝、
索引形状、hostname/port 断言、本机临时 HTTP server 的带令牌 GET 往返、
注入假 urlopen 的取数与截断、HTTP 错误映射。不修改普通 Session admission、Journal、
worker、persist 或 SSE。
