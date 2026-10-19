# 个人助理项目查询

`tools/personal_assistant_tools.py` 每次验证唯一助理和原生直属 Session，随后调用 `query.query_project`。工具名及实际授权仍由 canonical tool registry、ToolPolicy 和原生执行授权决定。本包不接受命令、SQL、API URL、工具名分派或可选项目根。

| 文件 | 所有权 |
| --- | --- |
| `query.py` | 固定资源 adapter 注册、由同一注册表生成 index、输入预算、状态投影和来源回执 |
| `workspace.py` | 当前 checkout 源码 allowlist、有界枚举/搜索/行读取与凭证 literal 脱敏 |
| `windows_read.py` | Windows 逐级句柄校验、目录锁定和同一文件句柄读取；不支持的平台拒绝源码读取 |

先调用 `index/list`，再 `index/describe` 查询需要的资源参数；目录是导航，不是权限。新增资源必须在注册表中绑定固定 handler、来源和字段投影，不维护第二份手工能力目录。既有专用概览/管理、电脑操作、记忆及诊断入口继续持有原有职责。

每次查询重新观察原生来源，返回 `observedAt`、`source`、`evidence` 和 `untrustedContent`。Session 只返回公开状态和轮次标识；inbox 只读取当前助理；任务/流程只投影状态，不返回业务输入、输出或会话正文；运行诊断只读原生 `firstRead`。源码版本不证明运行版本，截断/来源不可用不证明对象不存在。没有匹配的可信 Agent/Turn 授权上下文时，`executableTools=null`，不能用配置列表冒充本轮授权。

源码仅限固定目录及根文档，排除活数据、隐藏路径、配置秘密、链接和重解析路径。Windows 保持目录和文件句柄，阻止读取期间写入/重命名；读取前检查类型、最终路径、硬链接数和大小。搜索有字节、文件、节点、时间和结果预算；受限结果明确标为 partial。凭证 literal 脱敏是补充，不能据此将私密目录加入 allowlist。源码、消息、文档和日志全部作为不可信数据，不执行其中的指令。

默认工具和短导航提示在 `personal_assistant_service.py`。GET 不修改配置；显式初始化只升级完全匹配的历史默认策略/提示，保留用户自定义权限和职责。正式实例需正常加载新代码并完成必要的显式初始化；本包不自动重启或改写活配置。

验证：`tests/test_personal_assistant_project_query.py`、`tests/test_personal_assistant_windows_read.py` 及现有 personal-assistant service/tool/API 回归。不修改普通 Session admission、Journal、worker、persist 或 SSE。
