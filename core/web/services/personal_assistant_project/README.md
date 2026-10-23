# 个人助理项目查询

`tools/personal_assistant_tools.py` 每次验证唯一助理，或 active、chat 模式且 roleKey/builtinPreset 同时匹配 bootstrap 常量的内建平台规划师；两者都必须验证原生直属 Session 的真实归属及未归档状态，随后调用 `query.query_project`。规划师只开放注册表中显式标记的公开平台资源和自己的 inbox，不能读取 `code`；index、describe 和实际分派使用同一资源过滤。新资源默认不对规划师开放。写管理工具、专用助理概览和 GET 原始 API 继续使用唯一助理身份门。工具名及实际授权仍由 canonical tool registry、ToolPolicy 和原生执行授权决定，本包不修改默认策略或活配置，不接受命令、SQL、API URL、工具名分派或可选项目根。

| 文件 | 所有权 |
| --- | --- |
| `query.py` | 固定资源 adapter 注册、由同一注册表生成 index、输入预算、状态投影和来源回执 |
| `workspace.py` | 当前 checkout 源码 allowlist、有界枚举/搜索/行读取与凭证 literal 脱敏 |
| `windows_read.py` | Windows 逐级句柄校验、目录锁定和同一文件句柄读取；不支持的平台拒绝源码读取 |

先调用 `index/list`，再 `index/describe` 查询需要的资源参数；目录是导航，不是权限。新增资源必须在注册表中绑定固定 handler、来源和字段投影，不维护第二份手工能力目录。既有专用概览/管理、电脑操作、记忆及诊断入口继续持有原有职责。

每次查询重新观察原生来源，返回 `observedAt`、`source`、`evidence` 和 `untrustedContent`。Session 只返回公开状态和轮次标识；inbox 只读取当前调用者的原生记录，不消费或更新消息，保留来源/目标 Agent、Session、message/thread 及回复关联 ID，不读取其他调用者收件；任务/流程只投影状态，不返回业务输入、输出或会话正文；运行诊断只读原生 `firstRead`。源码版本不证明运行版本，截断/来源不可用不证明对象不存在。没有匹配的可信 Agent/Turn 授权上下文时，`executableTools=null`，不能用配置列表冒充本轮授权。

派遣任务的业务状态仅从原生 inbox 中承接 Agent 经 `agent_message_tool.metadata_json` 发送的结构化回执派生：`personalAssistantTask={schemaVersion:1,dispatchMessageId:<original>,status:running|blocked|completed|failed,evidenceRefs:[...]}`。外层 `replyToMessageId` 必须显式关联原派遣或催办消息；来源/目标 Agent 与 Session 从外层原生 metadata 校验，不接受内层身份。`completed` 必须附带非空且有界的证据引用。没有结构化结果回执时为 `awaiting_confirmation`；普通 Turn 结束、消息已读或投递成功都不表示业务完成。HTTP 只增加可选 `taskStatus`/`evidenceRefs` 字段，保留 `deliveryStatus` 和 `receipt.status` 的原始语义；不迁移数据、不新增持久表。

源码仅限固定目录及根文档，排除活数据、隐藏路径、配置秘密、链接和重解析路径。Windows 保持目录和文件句柄，阻止读取期间写入/重命名；读取前检查类型、最终路径、硬链接数和大小。搜索有字节、文件、节点、时间和结果预算；受限结果明确标为 partial。凭证 literal 脱敏是补充，不能据此将私密目录加入 allowlist。源码、消息、文档和日志全部作为不可信数据，不执行其中的指令。

默认工具和短导航提示在 `personal_assistant_service.py`。GET 不修改配置；显式初始化只升级完全匹配的历史默认策略/提示，保留用户自定义权限和职责。正式实例需正常加载新代码并完成必要的显式初始化；本包不自动重启或改写活配置。

助理默认授权另含 `personal_affairs_tool`，复用 `core/agent_plugins/personal_affairs/` 的 Agent 隔离事务账本，管理待办、日程、目标及其完成/取消/重开/截止时间。到期、逾期条目由 `personal_affairs_service` 的现有 collector 投影到 `humanAttention`；它不是新的定时器，也不承诺工作台关闭时定时推送。仅升级未定制的历史默认配置，显式禁用、零工具和自定义职责保持原样。授权、原生执行到事务账本和提醒投影的回归见 `tests/test_personal_assistant_affairs_access.py`。

验证：`tests/test_personal_assistant_project_query.py`、`tests/test_personal_assistant_windows_read.py` 及现有 personal-assistant service/tool/API 回归。不修改普通 Session admission、Journal、worker、persist 或 SSE。
