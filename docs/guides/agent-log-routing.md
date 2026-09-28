# Agent 日志路由

**读者：** 工作台内 Agent 和外置开发 Agent。两边读同一份 JSON，没有两套路径。

**入口：** `scripts/agent_log_context.py`。工作台内调用 `conversation_log_inspect_tool` 且不传 `log_path`，输出相同。

---

## 1. 命令

```powershell
.\.venv\Scripts\python.exe scripts\agent_log_context.py --project "<ROOT>"
.\.venv\Scripts\python.exe scripts\agent_log_context.py --project "<ROOT>" --session-id "<ID>" --turn-id "<TID>"
```

指定某一次运行现场时加 `--scene-id "<sceneId>"`。深读某一个已经被点名的文件时，同一命令或工具再传 `log_path`。

## 2. 只读 firstRead

返回 JSON 里先看 `firstRead`。它有且只有四段：

| 段 | 字段 | 怎么用 |
| --- | --- | --- |
| 结论 | `conclusion` | 一句话：要不要动手，主问题是什么 |
| 证据路径 | `evidencePaths` | 先看 `ref`。入口会补上 `absolutePath` 和 `exists`。有 `warning` 就不要整篇读 |
| 下一步 | `nextStep` | 唯一允许的下一步 |
| 不要做 | `doNotDo` | 停在这些动作之外 |

`nextStep` 说停止，或结论是没有进行中的问题：不要打开原始日志。

`diagnostic_entrypoint.first_read` 仍是场景包里的文件名（通常是 `summary.json`），不是这四段。不要从它开始读。

要看某一轮会话时才加 `--session-id`。之后只读 `session.diagnosis.nextMinimalAction`，不要展开 journal。

## 3. 路径

活跃日志根在 `activePaths`。迁移之后不在 git checkout 里。不要猜 `logs/`，也不要跑存储迁移。

场景包里的 `summary.json` 会带同一形状的 `agent_brief.first_read`。绝对路径以入口 JSON 的 `evidencePaths.absolutePath` 为准。

## 4. 不要做

- 未跑入口就 grep，或整篇读取超过 8MB 的 stdout
- 打开 `evidencePaths` 里没有的文件
- 把 `diagnose_session_turn.py` 当成另一套流程
- 为内置 Agent 和外置 Agent 各写一套日志路径

## 相关

- [loop.md](loop.md) §3
- [conversation-flow-map.md](../agents/conversation-flow-map.md)
