# 配置文档索引（Agent 配置入口）

> **给后续 Agent**：改配置前先读本索引，再只打开任务相关的专节。
> **活跃配置路径**：`%USERPROFILE%\Documents\Vibelution\config\config.toml`（权威）。
> 仓库根 `config.toml` / `config.example.toml` 仅为 legacy/template，**不得**当运行时真源。
> 决策：[ADR 0003](../../adr/0003-operator-config-lives-outside-repo.md)。
> 项目可变状态根与迁移：[ADR 0008](../../adr/0008-project-mutable-state-lives-outside-source-tree.md)。

## 怎么用

1. 看 [README](./README.md) 确认权威与禁止事项（1 分钟）。
2. 用下表跳到目标域。
3. 需要「能调 + 能缓存」时，**必须**打开 [04 协议/Wire/缓存](./04-llm-protocol-wire-cache.md) + [05 厂商菜谱](./05-llm-vendor-recipes.md)。
4. 改完用 [09 自检清单](./09-agent-checklist.md) 验收。

## 文档地图

| ID | 文档 | 何时读 |
| --- | --- | --- |
| 00 | [README](./README.md) | 任何配置任务 |
| 01 | [权威路径与加载](./01-authority-and-paths.md) | 找不到配置、多环境、env 覆盖 |
| 02 | [LLM Provider](./02-llm-provider.md) | 新增/改厂商、base_url、密钥、discovery |
| 03 | [模型与 Profile](./03-llm-model-and-profile.md) | 钉选模型默认值、Profile 引用、Agent 槽位 |
| 04 | [协议 / Wire / Prompt Cache](./04-llm-protocol-wire-cache.md) | 调用失败、缓存不命中、协议选型 |
| 05 | [厂商菜谱（OpenAI/DeepSeek/Anthropic/…）](./05-llm-vendor-recipes.md) | 按厂商抄正确片段 |
| 06 | [Agent / Evolution](./06-agent-evolution.md) | Agent 行为、进化、工具面 |
| 06a | [公共 Agent 预设](./public-agent-presets.md) | 全新部署的角色、虚拟人人物配置、模型回退与初始化 |
| 07 | [Launcher / Runtime / Workbench](./07-launcher-runtime-workbench.md) | 启动、窗口、运行时 |
| 08 | [Git / UI / User](./08-git-ui-user.md) | 提交文案模型、UI、用户资料 |
| 09 | [Agent 配置自检清单](./09-agent-checklist.md) | 交付前必过 |
| 10 | [挑战杯 Qwen Agent 路由](./10-qwen-challenge-cup-agent-routing.md) | 模型分层、性价比、角色选择依据 |

## 实现权威（代码）

| 主题 | 代码 / 模块文档 |
| --- | --- |
| 配置模型与校验 | `config/models.py` |
| Operator 配置路径 | `config/paths.py` |
| Project identity / data / runtime / logs / memory / cache | `vibelution_storage.py` |
| 旧路径迁移 | `core/infrastructure/storage_migration.py`、`scripts/migrate_project_storage.py` |
| Provider 注册合并 | `config/llm_provider_registry.py`、`config/providers.py` |
| 协议解析 | `core/llm/protocol_resolver.py`、`core/llm/protocols.py` |
| 协议运行时权威 | [core/llm/PROTOCOL.md](../../../core/llm/PROTOCOL.md) |
| Payload / 缓存注入 | `core/llm/payload_builder.py` |
| Wire 适配器 | `core/llm/wire/` |

## 按任务的最短路径

| 任务 | 打开顺序 |
| --- | --- |
| 新加 OpenAI 官方模型 | 02 → 03 → 05(OpenAI) → 09 |
| 新加 DeepSeek | 02 → 03 → 05(DeepSeek) → 04(缓存) → 09 |
| 新加 Claude | 02 → 03 → 05(Anthropic) → 04 → 09 |
| 修「能调但 cache 不命中」 | 04 → 05(对应厂商) → 09 |
| 修「unsupported_wire_protocol」 | 04 → 02(protocols) → [PROTOCOL.md](../../../core/llm/PROTOCOL.md) |
| 只改 Workbench 窗口 | 07 |
| 只改 git 提交模型 | 08 |
| 部署或调用 Vibelution MCP Agent 网关 | [MCP 受管 Agent 网关指南](../../agents/mcp-managed-agent-gateway.md) → 07（Launcher/Runtime） → 09（交付自检） |

## 配置根表（`config.toml`）

| 根节 | 文档 |
| --- | --- |
| `[llm]` | 02–05 |
| `[agent]` | 06 |
| `[evolution]` | 06 |
| `[launcher]` | 07 |
| `[runtime]` | 07 |
| `[workbench]` | 07 |
| `[git]` | 08 |
| `[ui]` | 08 |
| `[user_profile]` | 08 |
| `[research_workflow]` | 根节仅剩零散键：`auto_advance_policy_path` 及 auto-advance 策略文档读者已随 T8 自动推进机器退役（挑战杯封存后 ladder 从未激活）；保留的只有 kill switch 语义（`VIBELUTION_AUTO_ADVANCE_DISABLED` env + 挑战杯封存模式，见 `core/web/services/team_workflow/research_runtime/automation_policy_executor.py` 与 `archive_mode.py`）。历史模板 `auto-advance-policy.active.json`、部署脚本 `deploy_auto_advance_policy.py` 与影子转写 `shadow_to_g12_judgements.py` 均已删除；`Documents\Vibelution\config` 下的旧部署副本不再被运行时读取，可自行清理 |

## 业务服务连接

- [个人助理桌面 CUA 试验](desktop-cua.md)：独立 Notepad 窗口授权、固定驱动、原生审批与真实保存核验
- [金融 Agent / RAGFlow 财报证据问答](financial-report-agent.md)：服务器侧环境配置、显式工具授权、引用与失败语义
