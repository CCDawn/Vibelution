# Launcher 个人助理的外部 Agent 联系

Vibelution MCP 的 `list_project_agents` 在 `contacts` 中列出 Launcher 个人助理的服务身份。联系人不计入 `agents` 数量。Codex 或其他支持 MCP stdio 的 Agent 在本机登记后，可以在同一 MCP 连接上与助理交换消息。

## 登记连接

从 Launcher 实际使用的个人助理 profile 登记一个外部连接。以本机 Codex 为例，在 Vibelution 工作目录使用项目的 Python 运行：

```powershell
& .\.venv\Scripts\python.exe .\scripts\project_agent_tool.py assistant-peer-enroll --profile-root "<Launcher assistant profile>" --peer-id codex-local --platform codex
```

将返回的 `bindingPath` 传给 MCP stdio 的 `--assistant-peer-binding "<bindingPath>"` 参数。若该连接只需与助理通信，同时使用 `--assistant-peer-only`，便可独立接入现有项目网关。每个受信任的连接使用单独的登记。绑定文件留在 Launcher profile 内，模型只看到联系人、收件箱和消息回执。连接撤销命令：

```powershell
& .\.venv\Scripts\python.exe .\scripts\project_agent_tool.py assistant-peer-revoke --profile-root "<Launcher assistant profile>" --peer-id codex-local
```

## 交换消息

- 外部 Agent 通过 `launcher_assistant_contact` 的 `describe` 确认配对，`send` 发起请求，`inbox` 读取收到的请求和答复。
- 个人助理通过 `personal_assistant_action_tool` 的 `peer_contacts` 动作发现已配对连接，也可以主动 `send` 或读取 `inbox`。
- 两端用原 `request_id` 查询 `receipt`，由收件方 `reply`，原发送方领取答复后 `ack`。同一个配对内，两种方向共用请求编号；重试时沿用请求编号及原文。
- `queued` 表示消息已持久化，`reply_ready` 表示回复可领取，`acknowledged` 表示原发送端已确认领取。外部消息不提供操作者授权。收件靠消费者读取，投递本身不会启动新的模型调用。
- 单个配对保留最多 64 条请求及其回执，领取后仍保留原记录，用于核对和阻止重复投递。达到上限时，新请求会返回容量错误。
