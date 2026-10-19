# 10 · 挑战杯 Qwen Agent 路由

> 配置核验日期：2026-09-08。以下六角色绑定已通过活跃实例 Agent API 写入并回读，新运行路由解析已核验；未进行付费模型调用或科研质量对照实验。

## 当前按功能分级的配置

全部使用已注册且 enabled 的 `dashscope_main` 模型。

| 角色 | Agent ID | dialogue 模型 | 用途 |
| --- | --- | --- | --- |
| 搜索 | `agent-20260722-220511-172658` | `qwen3.8-flash` | 高频检索规划、来源发现 |
| 提炼 | `agent-20260722-220511-556053` | `qwen3.7-plus` | 证据与限定条件提取 |
| 知识管理 | `agent-20260722-220511-967382` | `qwen3.7-plus` | 证据关系、知识治理 |
| 执行 | `agent-20260823-213449-655985` | `qwen3.7-plus` | 工具编排、产物登记 |
| 实验修订 | `agent-20260722-220513-235601` | `qwen3.7-plus` | 假说推理与日常修订 |
| 评估 | `agent-20260722-220514-082385` | `qwen3.8-max-0902` | 独立批判与评审 |

该分级把最高档模型留给评审，避免高频检索、提炼和日常修订全部使用 Max。注册可用和配置解析正确不代表已证明实际时延、成本或假说质量改善；这些结论仍需真实样本与调用回执。

## 配置权威与生效范围

- 角色的实际来源是 AgentDirectory 的 `llmBindings.dialogue.modelId`，修改应经 `PATCH /api/agents/{agent_id}`，携带当前 `expectedConfigRevision` 与 `expectedUpdatedAt`，避免覆盖并发配置。
- 新运行由 `resolve_catalog_model_routing_policy` 按服务端角色绑定解析模型，并冻结到 `inputSnapshot.modelRoutingPolicy`。全局 `research_broad/deep/review` Profile 不是此链的角色配置来源。
- 已有运行继续使用原冻结模型路由。本次回读确认 `run-d6359ff65c28` 的输入快照未改变；需要分级路由的后续运行应走正常新建与授权流程。
- 当前实现没有按难度自动升级模型的策略。表中的模型是实际默认绑定，不能将“困难时升级”描述成已实现功能。
- 模型标识按本机已启用配置记录，不推断厂商版本不可变性、价格或上下文能力。正式调用仍受现有模型策略、预算和回执要求约束。

2026-09-06 的配置事件显示六角色曾通过 `direct_patch` 连续从统一 Plus 改为统一 Max；事件没有操作者身份。2026-09-08 已按上表修正五个角色，评估保留原 Max 绑定。

## 第一阶段与第二阶段

第一阶段假说设计保留知识包接受、补证完成和假说评审收敛条件，不要求冻结实验模板。第二阶段启动会在冻结输入 `constraintSnapshot.phaseOneKnowledgePackage` 中携带已发布的第一阶段知识交接；仅该主研究运行检查模板基线。题号本身不决定阶段，继承输入的知识子运行也不被判为第二阶段主运行。

配置入口见 [03 · 模型钉选与 Profile](./03-llm-model-and-profile.md)、[05 · 厂商菜谱](./05-llm-vendor-recipes.md) 和 [09 · Agent 配置自检清单](./09-agent-checklist.md)。
