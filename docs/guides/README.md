# Agent 开发路由（非用户手册）

**读者：仓库内 / 外部 coding Agent。**
**目标：最少 token 定位权威、落点、命令、禁止项。**
人类产品说明见根 `README.md`；**不要**用本目录给最终用户做产品教程。

## 加载顺序（强制）

| 序 | 文件 | 约行数 | 何时读 | 何时跳过 |
| --- | --- | --- | --- | --- |
| 0 | `AGENTS.md` | ~120 | 每任务；红线（含 §3.0 默认 BRT） | 永不跳过 |
| **0b** | **`ccdawn-brt` skill** | ~150 | 每次开发/修复/规划/会改代码或行为；声称最新前重读磁盘 `SKILL.md` | 纯只读问答且不改验证边界 |
| 1 | **本文件** | ~70 | 选子文档、查 token 预算 | 已明确只需 `route.md` 一行且不需 budget 表 |
| 2 | `route.md` | ~45 | 任务类型 → READ/EDIT/TEST | 续接同任务且 route 行未变 |
| 3 | `ownership.md` | ~90 | **写入前**定 owning surface | 只读审查、纯 docs、或 owner 已在 route 行闭合 |
| 4 | `loop.md` | ~95 | 分级 / 验证 / 完成报告 | 实现阶段中；FAST_PATCH 可只扫 §1+§3 |
| 5 | `playbook.md` | ~75 | 架构边界/红线速查仍不够时 | route+standards 已答清边界 |
| 6 | 下表「权威」列 | 不定 | 细则；**禁止**用 archive 当规则 | 子文档 + 模块 README 已足够 |

**默认规划门：** 未完成 0b 的 BRT 意图/分级/owner 选择前，不得广扫全仓、加载无关 process skill、或开始实现写入。`FAST_PATCH` 可 silent/micro，仍服从 BRT 最小门。

**Token 预算（guides 全目录）：** 若按序全读 §0–§5 约 **~600 行**；常态开发最小集 = `AGENTS.md` + `route.md` 一行 + `ownership.md` 命中段 + `loop.md` §1/§3/§6（约 **~250 行**）。

## 子文档

| 文件 | 内容 | 约行数 | 何时跳过 |
| --- | --- | --- | --- |
| [route.md](route.md) | 任务类型 → READ / EDIT / TEST / 禁止 | ~45 | 续接且任务类型/触面未变 |
| [ownership.md](ownership.md) | 路径 ownership | ~90 | 只读；或 owner 已由 route 唯一确定 |
| [loop.md](loop.md) | 分级、命令、完成报告模板 | ~95 | 未到验证/收束；FAST_PATCH 只看 §1+§3 |
| [agent-log-routing.md](agent-log-routing.md) | **统一日志入口** `agent_log_context` | ~55 | 非 Bug/回归/卡住/运行不一致 |
| [playbook.md](playbook.md) | 系统边界 + 红线速查 + SSOT | ~75 | standards § 已覆盖当前疑问 |
| [agent-dev-roi-backlog.md](agent-dev-roi-backlog.md) | **便利度 ROI 改造清单**（P0–P3） | ~100 | 非 ROI/便利度认领任务 |
| [button-selection.md](button-selection.md) | **按钮选型** V / VNative / 禁止裸 button | ~50 | 不改按钮/表单提交控件 |
| [install-windows.md](install-windows.md) | Windows 最终用户安装（人类） | ~55 | **Agent 开发一律跳过** |

**FE 路由索引：** [`web/src/routes/README.md`](../../web/src/routes/README.md)（非 Chat/Teams 30 秒表；~80 行）

## 权威（冲突时）

```text
用户当前要求
  → AGENTS.md
  → docs/standards/development-standard.md
  → docs/adr/* + 模块 README
  → docs/ops/config/* + core/llm/PROTOCOL.md
  → docs/guides/*（本目录：路由，不发明规则）
  → docs/archive/* · 外部 project memory（恢复投影；旧 .docs/project-memory 只读）
```

## 默认禁止

- 把 `docs/archive/**`、`docs/superpowers` 历史、过期 plan 当现行指令
- 用户可见 UI 非 VUI 交付
- 改仓库根 `config.toml` 当运行时已生效
- 无用户授权 remote push / force
- Windows 产品路径可见控制台 / `taskkill` 绕过 lifecycle

## 相关

| 主题 | 路径 |
| --- | --- |
| **Windows 最终用户安装**（人类，非 Agent 路由） | [install-windows.md](install-windows.md) |
| 配置 | `docs/ops/config/INDEX.md` |
| **全部 web services** | `core/web/services/README.md` |
| **便利度改造排期** | `docs/guides/agent-dev-roi-backlog.md` |
| **Launcher / Runtime 迷你索引** | `core/web/services/launcher_runtime.md` |
| **按钮选型** | `docs/guides/button-selection.md` |
| LLM 协议 | `core/llm/PROTOCOL.md` |
| 测试 | `tests/README.md` |
| VUI | `web/src/components/vui/README.md` |
| **前端 domain API** | `web/src/api/README.md` |
| Chat 链路 | `docs/agents/conversation-flow-map.md` |
| Worktree | `docs/agents/worktree-collaboration.md` |
