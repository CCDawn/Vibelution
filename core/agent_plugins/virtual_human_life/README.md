# `virtual_human_life` plugin pack

这是 Vibelution 第一方、按 `agentId` 显式绑定的虚拟人生活插件。未绑定或已禁用的 Agent 不创建生活数据，不注入 Prompt，不获得插件工具，也不会产生心跳或主动消息。

## 30 秒路由

| 需要修改 | 所有者 |
| --- | --- |
| manifest、能力、工具包和 Prompt Pack 元数据 | `manifest.py` |
| 绑定、生活状态、日程、活动、日记、Agent 生命周期 token 和领域编排 | `service.py` |
| 长期目标、项目、习惯、技能与完成事件推进 | `drives.py` |
| 情绪事件、余波恢复和表达档位 | `affect.py` |
| 关系事件、每日变化上限、阶段迟滞和自然回落 | `relationship_events.py` |
| 主动候选、未回复降速、未完话题和承诺 | `conversation_continuity.py` |
| 用户消息、已选主动消息与第二气泡的插件私有到达 FIFO | `mailbox.py` + `delivery_plan.py` + `delivery_runtime.py` + `service.py` |
| 夜间反思、记忆强化和来源校验 | `reflection.py` |
| 长期日历、周期事件、例外和冲突 | `calendar.py` |
| 昼夜节律与非医疗生活需要 | `rhythms.py` |
| 阅读、新闻、创作和练习兴趣投影 | `interests.py` |
| 熟悉地点、路线和重要物品 | `world_model.py` |
| 稳定 NPC 社会圈 | `social_circle.py` |
| 本地生活动态、日记和作品聚合 | `life_feed.py` |
| 有条件、可排序、可解释的表达规则 | `expression_policy.py` |
| 每轮真人化表达决定、意图优先级和追问预算 | `interaction_expression.py` |
| mailbox 意图 receipt 与时间/经历/计划 Prompt 投影 | `dialogue_context.py` |
| 可选语音/3D/Live2D provider 回退 | `embodiment.py` |
| 环境事实 supersession 与位置移动连续性 | `environment.py` |
| 因果存储路径、schema 和授权复用来源 receipt | `causal_contracts.py` |
| Agent 私有目录、原子 JSON/JSONL 读写和路径边界 | `storage.py` |
| 有界 Prompt Pack 文件列表和加载预算 | `prompt_pack.py` + `prompts/*.md` |
| Web/runtime facade、心跳 supervisor、receipt 恢复和 runtime-scene | `core/web/services/virtual_human_life_service.py` |
| 内部非用户 Session Turn | `core/web/services/session/proactive.py` |
| HTTP DTO 与薄路由 | `core/web/routes/agent_plugin*.py`、`core/web/routes/virtual_human_life*.py` |
| Agent 专用工具 | `tools/virtual_human_life_tools.py` |

## 不变量

- 计划不等于经历；只有带有效 outcome 的活动才能成为 Life Event、日记或长期记忆来源。
- 主动 Turn 不写 `user_message`；只有 assistant item 持久化并取得 receipt 后才计额度。
- `candidate/reserved/delivering` 使用稳定 token 和有效期；重启只按 receipt 对账或过期，不盲目重发。
- disable、archive、purge prepare 和 host stop 先使新工作失效，再取消插件拥有的主动 Turn。
- 工具可见性是 ToolPolicy 与 enabled binding 的交集；插件不能修改共享 ToolPolicy。
- 旧 `pet_info.json` 仅显式预览和导入，来源文件保留。
- 目标、项目、习惯和技能只由具有成功 outcome 的真实完成事件推进；计划、失败、取消、跳过和重复事件不推进。
- 心情和关系均从 Agent 私有事件账本投影；Prompt 只接收有界摘要，不接收原始互动备注。
- 主动消息先进入候选池，候选未出队不创建 Turn；未回复、重复主题、免打扰、忙碌和睡眠都有可解释抑制原因。
- 只有 Companion 模式把消息写入 `conversation/mailbox.json`；普通 Agent 继续直达原生 Session submit。mailbox 只保存待处理命令和租约，不保存 transcript、推理或工具轨迹；真正出队后才复用原生 Session Journal、worker 与 SSE。
- 用户消息、已选中的主动消息和最多一个第二气泡按同一 Session 的 `arrivalSequence` 严格 FIFO；用户可在人物回复期间继续入队，但不能并发启动第二个 Turn。第二气泡复用原生 assistant-only proactive admission 建立独立 Turn，用户新 generation 会取消尚未原生 admission 的旧气泡；DeliveryPlan 和 mailbox 都不保存 assistant 文本，也不成为第二份 transcript。
- 夜间反思只强化有来源的生活记忆；梦境与仅计划内容不能成为外部事实或自我历史。
- 环境事实保留来源和 supersession 历史；位置移动必须经过明确耗时后才能到达。
- 长期日历只提供跨日约束；每日 Schedule 仍是当天活动执行状态的唯一权威。
- 作息画像只由明确配置或重复可信经历改变；睡眠和忙碌不延迟用户实时消息。
- 偏好、习惯、技能、自我叙事和记忆纠错提案未经审核不得进入 Prompt；Persona 核心与 ToolPolicy 不可由提案改写。
- 兴趣只从可验证的成功 outcome 成长；NPC 不是 Agent，生活动态也不反向写入生活经历。
- 具身化 provider 和资产均为可选；没有授权资产或 provider 不健康时回退现有立绘，文本会话不受影响。
- 每轮表达决定只读取有界投影和插件 mailbox 的意图 receipt，不保存用户原文，不调用第二次 LLM，也不能放宽关系、权限或安全边界。

## 主测试

- `tests/test_virtual_human_life_plugin.py`
- `tests/test_virtual_human_session_proactive.py`
- `tests/test_virtual_human_life_api.py`
- `tests/test_virtual_human_life_tools.py`
- `tests/test_virtual_human_life_causality.py`
- `tests/test_virtual_human_life_reflection.py`
- `tests/test_virtual_human_life_long_horizon.py`
- `tests/test_virtual_human_life_continuity.py`
- `tests/test_virtual_human_life_mailbox.py`

产品契约见 [`docs/prds/2026-08-27-virtual-human-life-plugin.md`](../../../docs/prds/2026-08-27-virtual-human-life-plugin.md)。
