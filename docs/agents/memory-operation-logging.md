# 记忆操作日志

个人记忆和正式知识继续使用现有运行场景日志；正式知识的持久化审计仍由 owner 下的 `knowledge/audit.jsonl` 维护。

## 实现与职责

- `core/logging/memory_events.py`：记忆日志写入及受控工具终态补充，复用 runtime-scene、调用追踪和日志管线指标。
- `core/infrastructure/tool_executor.py`：在既有跨线程上下文复制前绑定真实调用 ID；仅供记忆日志关联，执行结束恢复，不修改权限或业务参数。
- `tools/episodic_memory_tools.py`：记录追加、作废和替换的成功、拒绝及失败，带当前 Agent、Session、Turn、工具调用和记忆标识。
- `tools/team_knowledge_tools.py`：补齐提前拒绝、参数错误和失败返回的终态，保留已有成功和治理事件。
- Agent directory 与 Team Knowledge 的既有事件写入者使用同一失败告警；它们继续保有原来的组件、事件名称和持久化职责。
- 底层运行场景记录器的写入失败告警也仅保留异常类型，防止安全元数据在外层脱敏后又经内层异常消息泄露。

## 记录内容

工具终态是 `memory.tool.execution.succeeded`、`blocked` 或 `failed`。正式知识已有成功事件，因此只补充拒绝和失败；个人记忆成功终态补足会话与条目关联。

日志只带工具名、可用的 Agent / Session / Turn / toolCallId、知识库或条目标识、受控原因码与耗时。标识有字符和长度限制；不记录查询正文、记忆正文、附件、自由文本理由、参数全集或异常消息。工具名与签名、权限校验、业务结果和数据存储不变。

新增工具终态使用 `info` 记录，业务拒绝和失败由事件名及 `outcome` 明确区分；关闭周期性刷新，并避开 warning 的同步诊断投影。因此它们不在请求路径触发完整运行场景包刷新，仍写入同一事件流。日志存储异常仍发出独立 warning。

## 日志写入失败

日志写入抛出异常时，发出 `memory.event.write_failed` 的标准 warning，包含原事件名、Agent / Session 和异常类型；不会复制异常消息。既有日志管线的 `operational:writer_failed` 计数同时递增，不依赖日志写入，不递归调用运行场景记录器。

告警处理器或指标本身失败也不重试记忆写入、不改变已完成的业务结果。未开启运行场景时，沿用现有 `no_runtime_scene` 语义；此机制不把日志变成事务性数据库，也不承诺日志存储不可用时仍能完整落盘。

验证入口：`tests/test_memory_event_audit.py`、既有个人记忆及正式知识工具回归；运行落盘证据写入任务独立场景。
