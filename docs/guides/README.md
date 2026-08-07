# Agent 开发路由（非用户手册）

**读者：仓库内 / 外部 coding Agent。**
**目标：最少 token 定位权威、落点、命令、禁止项。**
人类产品说明见根 `README.md`；**不要**用本目录给最终用户做产品教程。

## 加载顺序（强制）

| 序 | 文件 | 何时 |
| --- | --- | --- |
| 0 | `AGENTS.md` | 每任务；红线（含 §3.0 默认 BRT） |
| **0b** | **`ccdawn-brt` skill**（`~/.grok/skills/ccdawn-brt/SKILL.md` 或本机已安装路径） | **每次开发 / 修复 / 规划 / 会改代码或行为的任务：默认先读并执行路由**；用户无需 `/brt`；声称最新 skill 前重读磁盘 `SKILL.md` |
| 1 | **本文件** | 选子文档 |
| 2 | `route.md` | 任务类型 → 打开路径 |
| 3 | `ownership.md` | 写入前定 owning surface |
| 4 | `loop.md` | 分级 / 验证 / 完成字段 |
| 5 | `playbook.md` | 架构约束摘要（仍不够再下钻） |
| 6 | 下表「权威」列 | 细则；**禁止**用 archive 当规则 |

**默认规划门：** 未完成 0b 的 BRT 意图/分级/owner 选择前，不得广扫全仓、加载无关 process skill、或开始实现写入。`FAST_PATCH` 可 silent/micro，仍服从 BRT 最小门。

## 子文档

| 文件 | 内容 |
| --- | --- |
| [route.md](route.md) | 任务类型 → READ / EDIT / TEST / 禁止 |
| [ownership.md](ownership.md) | 路径 ownership |
| [loop.md](loop.md) | 分级、命令、完成报告模板 |
| [playbook.md](playbook.md) | 系统边界 + 红线速查 + SSOT |
| [agent-dev-roi-backlog.md](agent-dev-roi-backlog.md) | **便利度 ROI 改造清单**（P0–P3，可认领） |
| [button-selection.md](button-selection.md) | **按钮选型** V / VNative / 禁止裸 button |

## 权威（冲突时）

```text
用户当前要求
  → AGENTS.md
  → docs/standards/development-standard.md
  → docs/adr/* + 模块 README
  → docs/ops/config/* + core/llm/PROTOCOL.md
  → docs/guides/*（本目录：路由，不发明规则）
  → docs/archive/* · .docs/project-memory/*（只读状态/考古）
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
| **按钮选型** | `docs/guides/button-selection.md` |
| LLM 协议 | `core/llm/PROTOCOL.md` |
| 测试 | `tests/README.md` |
| VUI | `web/src/components/vui/README.md` |
| Chat 链路 | `docs/agents/conversation-flow-map.md` |
| Worktree | `docs/agents/worktree-collaboration.md` |
