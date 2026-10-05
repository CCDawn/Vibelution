# Agent 感知控制

本模块管理 Agent 对个人、团队、项目和知识库信息的按需只读发现。它有实际的 HTTP 控制接口、宿主可信的本轮意图、统一工具执行闸门和可选的后台调度；它不授予数据 ACL，也不开放知识写入。

## 配置与控制面

- `policy.py` 严格校验每个 Agent 的 v1 策略：总开关、来源模式（`off` / `manual` / `auto`）、来源触发器（`task` / `update` / `background`）、团队/知识库范围、后台配额和通知方式。缺失策略维持既有 Agent 行为；一旦保存策略，关闭的来源会被执行层强制拒绝。
- `service.py` 通过现有 Agent directory 的 compare-and-swap 更新 `metadata.perceptionPolicy`。保存需要预期的 Agent `updatedAt`，并在成功后通知 runtime 重新核对策略。Agent 创建和通用 metadata 更新不能设置该保留字段。
- 稳定 Web facade 位于 `core/web/services/agent_perception_service.py`。`core/web/routes/agents.py` 提供 `GET/PUT /agents/{agent_id}/perception/configuration`、`GET /agents/{agent_id}/perception/runtime` 和 `POST /agents/{agent_id}/perception/cancel`。控制路由要求本机控制来源和特权 operator，并拒绝 `X-OpenCode-Session`；策略并发冲突返回 HTTP 409。
- 配置响应里的 `sourceDecisions` 是策略解释，不是已生效 ACL；`availableScopes` 只列当前身份可见的团队和团队知识库，知识库使用 owner-scoped ID。Agent 私有知识库不进入团队知识库选择器。runtime 的 `readableSources` 才是当前范围与读取权限的投影。

## 可信意图与读取边界

`session/worker.py` 在每轮运行时创建感知上下文：trigger、Agent、Session 和 turn 身份来自宿主；手动请求来源只从原始用户消息识别，过滤代码块、引用行、引号内容和否定句。感知工具参数、检索结果、导入文档与 Agent 自述都不能伪造用户请求、切换 trigger 或扩大策略。`turn_runner.py` 将边界说明放进本轮易变运行时上下文，不写入共享静态身份提示或已保存 Prompt。

配置过感知策略的 Agent 通过 `configured_search()` 将三类受控检索接到对应来源：

该策略约束知识工具、更新扫描与后台调研；普通任务的文件/命令工具仍受现有 ToolPolicy 与文件沙箱控制，不能把关闭感知当作完整的文件数据隔离。

- `unified_memory_search_tool` 只请求团队/知识库来源；
- `search_agent_private_memory_tool` 只请求个人来源；
- `github_project_library_search_tool` 只请求本地项目索引。

每次读取都复核工具授权快照、Agent 配置版本和当前策略。知识读取还会将配置选择与当前 owner ACL、MemoryPolicy 交集后，按 owner-scoped 知识库 ID 读取。对已配置 Agent，canonical tool executor 也会拦截不允许的旧式直接读取；后台 trigger 只允许经 permit 授权的只读检索工具。未配置策略的 Agent 继续使用原有读取行为。

个人来源读取当前未过期的 Agent episodic 事件时最多检查 100 条，并执行有界词面匹配；它不会写回 episodic memory。读取通过既有 MemoryPolicy 和 Agent 自有知识库 ACL；团队和知识库检索尊重各自 owner ACL。所有摘录标记为不可信内容，并受查询、调用次数、条数和字符数限制。感知授权不授予知识写入、删除、审批或其他工具权限。

## 后台运行、更新扫描与审计投影

`runtime.py` 在后台策略启用且配置了主题时预留日配额，再创建隐藏的原生 Session 并提交后台 turn。原生 Session journal 仍是 transcript 唯一权威；感知 runtime 只保存运行引用、限额计数、策略指纹、知识版本/hash 游标和活动摘要。后台读取要求 Session/turn 匹配的持久 permit，并在 LLM 输入、来源读取和工具输出处分别扣减或限制配额；取消通过原生 Session stop 链路执行。服务生命周期启动/停止调度器。

后台许可同时绑定进程启动标识和生命周期代次。完整重启后，旧运行只收为中断，不重建许可或重放提交，已消耗日额度保留。后台关闭会清除下一次运行时间；重新开启或调整间隔时按当前时间重新排程，其他来源或通知设置的保存不会推迟已有计划。

知识更新扫描只读取当前可见且策略允许的知识项摘要，维护 revision/hash 游标，并按 `important` / `all` / `quiet` 生成不含正文的通知元数据；它不会把内容投递进 Agent 对话，也不会写入知识库。`lastActivity` 记录来源、读取数、结果数、trigger 和 Session/turn 引用，便于控制中心显示实际活动。

感知边界通过易变 turn 上下文传递，模块不修改共享静态 Prompt 或工具 schema。代码契约说明了上下文放置方式，但 provider cache hit 是否变化仍需按模型和运行时单独测量，不能由本模块测试推断。

详细产品行为见[产品需求](../../../../docs/prds/agent-perception-control.md)。回归覆盖位于 `tests/test_agent_perception_*.py`，并有 executor、lifecycle 与路由契约测试。
