# `virtual_human_life` plugin pack

这是 Vibelution 第一方、按 `agentId` 显式绑定的虚拟人生活插件。未绑定或已禁用的 Agent 不创建生活数据，不注入 Prompt，不获得插件工具，也不会产生心跳或主动消息。

## 30 秒路由

| 需要修改 | 所有者 |
| --- | --- |
| manifest、能力、工具包和 Prompt Pack 元数据 | `manifest.py` |
| 绑定、生活状态、日程、活动、日记、Agent 生命周期 token 和领域编排 | `service.py` |
| 长期目标、项目、习惯、技能与完成事件推进 | `drives.py` |
| 人物自主预约下一次行动、到点原生唤醒、停机后重新规划 | `self_continuity.py` |
| 隐藏内部执行身份、原生 Session 配对与主人物当前授权交集 | `native_wakeup.py` |
| 情绪事件、余波恢复和表达档位 | `affect.py` |
| 关系事件、每日变化上限、阶段迟滞和自然回落 | `relationship_events.py` |
| 主动候选、未回复降速、未完话题和承诺 | `conversation_continuity.py` |
| 用户消息、已选主动消息与第二气泡的插件私有到达 FIFO | `mailbox.py` + `delivery_plan.py` + `delivery_runtime.py` + `service.py` |
| 夜间反思、记忆强化和来源校验 | `reflection.py` |
| 生活来源分类、原生工具回执核对与旧模拟记忆纠正 | `life_provenance.py` + `native_activity_evidence.py` + `memory_sources.py` |
| 长期日历、周期事件、例外和冲突 | `calendar.py` |
| 双方约定提议、确认、改约和结果闭环（同一日历账本） | `commitments.py` |
| 真实到达时间的重逢、成功事件与共同话题只读投影 | `reunion.py` |
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

- 计划不等于经历。计时器完成记录标为日程模拟，人物自行描述标为自述；只有已开始活动的必需工具在同一原生 Session/Turn 留下明确成功回执，才能成为可信行动、日记晋升或长期记忆来源。一份回执只能支持一次活动，插件仅保存有界回执 ID，不保存第二份工具正文。
- 旧模拟记忆仅在插件晋升回执、原生 private_note 的完整引用和模拟事件精确一致时，通过原生 supersession 退出召回；原正文与来源历史保留。纠正发生在 Companion 原生接收前，不能清除已经组装的旧 Turn。来源不明或混合引用的记忆不自动失效，界面不得称其已隔离。
- 默认独立生活与创作项目是持续目标，展示可信行动次数，不按日程条数累计百分比；用户自定义目标保留。
- 自我唤醒只保存一个有界未来命令及原生 receipt 引用，不保存第二份 transcript；执行复用同一人物的隐藏原生工作 Session 和 assistant-only proactive admission，工作记录只有该 Session Journal 持有，不复制陪伴聊天。人物可用既有 schedule tool 读取、替换和取消未来唤醒；初次启用会安排一次规划唤醒，后续时间由人物决定。自我唤醒独立于主动联系开关、次数和免打扰，不创建聊天 continuation burst；联系用户必须另走既有聊天门，每次原生工具仍受 ToolPolicy 限制。
- 关闭应用即停止生活与调度。重启时过期活动标记 skipped/unknown，不补造生活事件、日记或成长；过期/中断的唤醒改为一次未来的重新规划，未来有效计划保留。自我唤醒至少间隔一分钟、最多预约七天后、每天至多 24 次，忙碌或已到达的用户消息优先。
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
- 约定候选不入有效日历，后续用户 Turn 确认后才生效；改约未确认保留原约，到点只等待真实结果。新动作要求人物自身 direct Session 与当前用户 Turn，不允许管家代替用户确认。
- 重逢按 mailbox `createdAt` 而非出队/心跳时间计算；共同经历复用 open loop 内事件/Turn/日期引用，Prompt 定点读成功事件，不创建第二 transcript 或记忆库，也不推断用户在场或未回复惩罚。

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
- `tests/test_companion_commitments.py`
- `tests/test_companion_reunion.py`
- `tests/test_companion_lived_continuity.py`

产品契约见 [`docs/prds/2026-08-27-virtual-human-life-plugin.md`](../../../docs/prds/2026-08-27-virtual-human-life-plugin.md)。
