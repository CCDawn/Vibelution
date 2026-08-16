# Agent 日志路由（统一入口）

**读者：** 所有开发 Agent（Cursor、工作台内 Agent、脚本），无内外分叉。

**唯一入口：** `agent_log_context` — CLI 与 `conversation_log_inspect_tool` 共用同一 JSON 契约。

---

## 1. 命令

```powershell
# 项目根（Launcher 所在 checkout）
.\.venv\Scripts\python.exe scripts\agent_log_context.py --project "<ROOT>"

# 会话/轮次问题附加 session/turn
.\.venv\Scripts\python.exe scripts\agent_log_context.py --project "<ROOT>" --session-id "<ID>" --turn-id "<TID>"

# 指定 runtime scene
.\.venv\Scripts\python.exe scripts\agent_log_context.py --project "<ROOT>" --scene-id "<sceneId>"
```

工作台内 Agent：调用 **`conversation_log_inspect_tool`（无 `log_path`）**，输出与 CLI 相同。

深读某一文件或 scene 包：同一 tool / CLI 传 **`log_path`**（第二步，非默认）。

---

## 2. 读序（强制）

1. **`agent_log_context`** — 解析 `activePaths`、当前 scene、`agentBrief`
2. **`summary.json`** — 已在 (1) 摘要；需要细节再打开
3. **`resolvedEvidenceRefs.absolutePath`** — 优先于手工拼接 `evidence_refs`
4. **有 session/turn 时** — (1) 内 `session` 字段（journal + runtime 证据）
5. **仅当仍不够** — `log_path` 深读；禁止未做 (1) 就 grep 全仓或大 stdout

---

## 3. 路径 SSOT

| 项 | 权威 |
| --- | --- |
| 活跃 logs/runtime | `agent_log_context.activePaths`（来自 `vibelution_storage`） |
| 当前运行现场 | `.runtime/launcher/active-runtime-scene.json` → `currentScene` |
| 诊断首读 | `<scene>/summary.json` → `agent_brief` |
| Launcher 原始 stdout/stderr | `{activePaths.runtime}/launcher/`；大文件看 `launcherRuntime.largeLogs` 警告 |

不要使用 `logs/runtime_scenes/latest`（不存在）。不要硬编码 `<repo>/logs`。

---

## 4. 症状 → 下一步

| 症状 | 第一步 | 然后 |
| --- | --- | --- |
| 启动/Launcher/卡住 | `agent_log_context` | `raw/launcher-control.log` → timeline |
| API/后端 | `agent_log_context` | `raw/backend.api.log` |
| 浏览器/前端 | `agent_log_context` | `raw/browser.telemetry.log` |
| Agent/会话/工具 | `agent_log_context --session-id …` | 按 `session.diagnosis.evidenceRefs` |
| 深读 JSONL/scene 文件 | `conversation_log_inspect_tool(log_path=…)` | 窄范围 |

---

## 5. 禁止

- 未跑 `agent_log_context` 就猜测路径或读 8MB+ stdout 全文件
- 把 `diagnose_session_turn.py` 当独立流程（已并入 `agent_log_context`）
- 区分「外部 / 内部」两套日志路径

---

## 相关

- [loop.md](loop.md) §3
- [conversation-flow-map.md](../agents/conversation-flow-map.md)
- [launcher_runtime.md](../../core/web/services/launcher_runtime.md)
- [development-standard §8](../standards/development-standard.md)
