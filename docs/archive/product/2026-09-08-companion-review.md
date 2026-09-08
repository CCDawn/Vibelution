# 虚拟人整体审查与新增需求记录（2026-09-08）

Status: REVIEW_RECORDED / NEW_REQUIREMENTS_PENDING_ALIGNMENT

本文件是用户要求保存的一次性审查快照，不是新实施授权，也不覆盖现行规范或已确认的产品契约。审查基线为本地 main `d566b83d6309d695a26892ddca4e1bd2ff50a908`；后续开发应复核变化。

## 1. 结论与范围

Companion 专属入口及适配层复用原生会话权威的方向合理。当前高价值工作是消除机械表达规则、缩短进入聊天的等待、接通既有偏好与记忆能力、提升人物资料和对话的连续性，而不是继续增加状态卡或另建会话/记忆引擎。

边界沿用 [AGENTS.md](../../../AGENTS.md) 与 [开发标准](../../standards/development-standard.md)：只在 Companion 插件、适配层、专属 UI 投影改造。普通 Session admission、Journal、worker、persist、projection、SSE、ConversationStore 和普通 composer 语义不得因虚拟人需求改变；mailbox 不是第二份 transcript。普通链路如有缺陷，应拆成独立任务。

本次未修改产品代码、未发送新测试消息、未运行新模型生成、未执行生命周期操作，也未 push 或发布。纯文档交付无需构建或运行态刷新。

## 2. 已观察的运行状态与证据边界

- 通过 `scripts/desktop_debug.py` 发现 Electron CDP，并按 `main-workbench` 角色识别窗口，检查人物大厅、专属聊天、今天和记忆页签。
- 当时 health 中 backend head 与 frontend builtFromCommit 均为上述基线；backend dirty=true，不是纯净发布证明。
- 样本人物为洛天依（`agent-20260828-105328-220581`），专属会话为 `session-20260828-105328-032467`。桌面视口为 1426 × 923 CSS px，立绘加载成功，三栏无横向溢出。
- 历史完整加载后没有残留“正在输入”；原生文件 input 为 display:none、尺寸为零。观察到的正常页面请求没有目标 404/500 或 pageerror。
- 最初一次手动诊断 fetch 未带 control token 返回 403；补用产品正常 bootstrap 后请求成功。这不是产品请求错误，token 未记录。
- 冷打开约 22.6 秒输入框才出现，当时历史仍在加载，随后加载完整。一次正常鉴权的并发 GET 样本：companion-activity 为 17644ms / 200 / 456 字符，companions 为 20728ms / 200 / 43491 字符。仅是单次样本，不是 P95，也尚未证明具体耗时根因。
- 没有新发消息，因此不能据此声称 V2 新生成、用户插话、取消恢复和跨人物实时隔离已通过本次端到端验收。检查后已恢复用户原普通会话页面。
- 当时截图存于系统 Temp，仅为临时视觉佐证，不作为仓库内永久验收附件；以上记录不依赖该文件持续存在。

## 3. 发现与高价值改进

### R1：旧机械提问规则仍参与 V2 表达

证据：[interaction_expression.py](../../../core/agent_plugins/virtual_human_life/interaction_expression.py) 208–214 行使用 `ordinal % 3 == 0` 控制 questionBudget/followup；dialogue_context.py 315–325 行实际传入 turnOrdinal；prompt pack 同时加载 11 与 13，旧表达指令仍参与。test_virtual_human_life_expression.py 89–103 行固化八轮中只提问两至三次。

[companion_preferences.py](../../../core/agent_plugins/virtual_human_life/companion_preferences.py) 176–195 行将 normal/high 都映射为允许提问。独立纯函数检查得到 low=false、normal=true、high=true，前六轮 questionBudget 为 `[0,0,1,0,0,1]`。

建议：退役按轮次取模的旧执行规则和相应测试，让已确认的 V2 决策依据语境及偏好发挥作用；不再添加第三层控制。不把取消机械提问节奏等同于取消资源预算或允许无休止追问。

### R2：聊天进入路径等待重列表，耗时根因待定位

证据：[CompanionChatRouteGate.tsx](../../../web/src/routes/companions/CompanionChatRouteGate.tsx) 的身份校验等待完整人物列表；[agent_plugin_service.py](../../../core/web/services/agent_plugin_service.py) 的活动收集逐人物查询 Session，并读 Journal snapshot 找终态；完整列表另调用 service.snapshot。运行样本见 §2。

建议：先给鉴权、人物身份、活动和 snapshot 读取分别计时，定位真实耗时；再评估轻身份校验与重详情拆开、复用现有索引。现在不能把循环读取直接认定为全部 20 秒的根因，也不应未经定位先加缓存或改原生 Session。

### R3：已规划偏好、记忆与修复体验尚未完整闭环

对照 [虚拟人 PRD](../../prds/2026-08-27-virtual-human-life-plugin.md) Task 41–43：

- 已有手动偏好保存/删除，这是用户明确操作，不是绕过确认；缺少自然聊天提出建议后 pending → accepted / rejected / expired 的确认闭环。
- 缺少 Companion 按当前话题选取少量有效、纠错后的原生 episodic memory 并关联来源的专用接线。service.py 的 `_dialogue_v2_allowed_source_keys` 当前仅提供 open-loop 和当天 Life Event；这不意味着普通 Agent 没有记忆能力。
- 会话头部有主动联系设置，尚未完整承载 PRD 中说话主动性、提问主动性和偏好建议三组配置。

建议：复用 CompanionPreferenceManager、既有确认机制和原生记忆；不增加第二套偏好库、向量库或摘要模型。

### R4：技术文案与存在状态削弱拟人感

正式页面可见 `bright`、`home`、“心跳在线”，人物介绍还展示“只把实际发生且有结果的活动当作经历”等内部行为规则。

- [affect.py](../../../core/agent_plugins/virtual_human_life/affect.py) 输出 low/bright/calm，而 [companionPresentation.ts](../../../web/src/routes/companions/companionPresentation.ts) 的心情映射缺少 bright/low。
- 输入框仍为“描述下一步要做什么...”，Companion 没有专属 placeholder 覆盖。
- CompanionConversationHeader / CompanionPersonRail 只根据 lifePaused 显示在线，未完整表达 sleep、busy 或状态新鲜度。
- formatLifeTime 使用浏览器时区，而 formatCompanionLocalTime 使用人物时区；异地显示有不一致风险，当前同上海样本未复现。

建议：只在 Companion 展示层使用自然中文、头像/轻量状态和对话型输入提示；人物简介与内部 Prompt 分开。在线状态应有事实依据，不能把进程心跳当人物可交流。普通 composer 文案保持原样。

### R5：既有生活档案缺少顺畅补全入口

当前人物 LifeProfile 显示“未建立 / 等待生活草案”；[CompanionLifeWorldCard.tsx](../../../web/src/routes/companions/CompanionLifeWorldCard.tsx) 199–207 行 missing 分支只有去 Agent 设置的文字，没有直接操作入口。

建议：串起城市 → 身份 → 学校/单位 → 作息 → 物品与资产确认流程，复用现有结构化档案。结论是当前人物未配置、入口不顺，不是这些能力完全没开发。不得自动编造已确认的生活事实。

### R6：跨次主动聊天的新鲜度与误解修复需补齐

历史中 9 月 5 日、9 月 8 日重复出现早餐、阅读项目、忙了吗、午饭等主题；这是历史体验证据，不能据此声称当前每次生成都重复。

[delivery_runtime.py](../../../core/agent_plugins/virtual_human_life/delivery_runtime.py) 264–274 行的 disclosedTopicKeys 仅在当前 burst 内，缺少跨 burst 的经历披露与成功送达关联。意图分类已有 correction/support/end/ack/help/small_talk，但未完整闭合误解、不耐烦的修复路径。单次 burst 限制自我披露主题本身不判为缺陷。

建议：优先新经历、未完话题、真实约定；只在成功送达后登记已披露，失败不消耗新鲜度，用户追问仍可再次谈及。同一次纠错不能被当作关系惩罚。

## 4. 外部调研与复用裁决

本轮复用刚完成的源码调研；没有安装、执行或复制外部代码。以下是审查当时的固定快照，不保证上游未来不变。

| 项目与固定版本 | 有价值的部分 | 裁决 |
| --- | --- | --- |
| [SillyTavern vectors](https://github.com/SillyTavern/SillyTavern/blob/8172dcd0ee672d3cd9a5e5f7af134f91a45cd2b8/public/scripts/extensions/vectors/index.js)，AGPL-3.0 | 保护近期消息、少量相关召回；表情资源切换 | REFERENCE_ONLY；借设计、不复制 AGPL 代码、不新增向量库。protect=5、insert=3、score_threshold=0.25 仅为上游样本，不照搬为产品阈值 |
| [Pipecat context summarization](https://github.com/pipecat-ai/pipecat/blob/1f8a513dd79c31f54bbd5b197fa26aefe242deca/src/pipecat/utils/context/llm_context_summarization.py)，BSD-2-Clause | 保留近期上下文及未完成工具调用 | 参考上下文边界；不新建摘要模型、不改普通上下文 |
| [AIRI](https://github.com/moeru-ai/airi/tree/9a4e1da5a17c98af1bc7e1bebed2c4ab5022e1af)，MIT（调研子 agent 核验） | 表达、播放取消的局部设计 | 语音后置；Memory/Alaya 的在研内容不作为成熟记忆引擎引入 |
| [LiveKit Agents](https://github.com/livekit/agents/tree/e62b5bb76ee1f60d1b6b1b72146240ba0e935ba0)，Apache-2.0（调研子 agent 核验） | interruption / false-interruption | 未来语音参考，不替换当前文字 mailbox |
| [AstrBot Private Companion](https://github.com/menglimi/astrbot_plugin_private_companion) | 关系、回复温度、互动动态 | 保留用户已取得作者代码复用许可的事实。本次 repo/raw 为 404、API 为 403 限流，源码需重新核验；不能推断授权失效或项目删除。优先复用本地已适配切片 |

## 5. 建议顺序及后续验收

1. 清理旧机械表达规则，同时定位加载耗时；分别验证表达选择和页面进入耗时，不用一项结果冒充另一项。
2. Companion 文案、人物状态真实性与生活档案补全入口。
3. 偏好建议确认、相关记忆、误解修复及跨次披露去重；尽量复用已有权威模块。
4. 少量表情资产作为视觉增强。语音、Live2D、新记忆引擎暂后置。

以上是审查建议，不是已完成的修复。后续实施必须有 Companion-only 身份门、普通会话核心零差异检查及相关普通 Session 回归；前端遵循 VUI 并做类型、路由与交互验证。新生成、插话、终态和恢复仍需要授权范围内的真实场景证据。

## 6. 用户新增要求：待对齐，尚未实施

原始要求记录：未及时回应虚拟人的消息，虚拟人心情会变差；发送内容与关系维度挂钩，关系越好越亲密；不回复或说反感的话也应影响表现。

现有可复用能力：[relationship_events.py](../../../core/agent_plugins/virtual_human_life/relationship_events.py) 的关系事件账本、亲密度/信任与阶段投影；affect.py 的来源化情绪与恢复；[conversation_continuity.py](../../../core/agent_plugins/virtual_human_life/conversation_continuity.py) 的未回复降速；interaction_expression.py 的关系上限与心情调制。当前未证明“未回复降速”已会产生情绪事件，不能宣称新增需求已完成。

需要本轮对齐的分歧：

- 从何时计时、哪些消息期待回应、多久算未及时回复；实际送达不等于已读。
- 短期失落与长期亲密度/信任变化怎样区别；忙碌、睡眠、免打扰以及未送达怎样处理；关系变化怎样恢复。
- “不喜欢这个称呼/话题”等边界反馈，与“不想继续来往”、侮辱/持续敌意如何区分。
- 亲密表达与已认可的昵称、玩笑、自我披露怎样关联，而不把关系分数当成无限升级表达的许可。

既有 PRD 约束仍有效：心情与熟悉度影响表达；正常纠错/单次误解不惩罚关系；非用户来源的坏心情不能归责用户；不得用关系或记忆施压。新增规则若改变这些约束，必须先明确对齐，不静默覆盖。

本快照不固定任何未确认的时长、扣分值、长期衰减或恢复算法。用户校准后再更新现行产品契约并实施。

### 用户后续校准：真实时间与心理习惯

用户进一步要求“越真实越好，符合人的交流和心理习惯”，并明确纠正为“模拟真实的时间”。方向已确认：时间体验应与真实时间流逝相符，不以消息轮数或心跳执行次数冒充经过时间。

此前对话中提出的“累计 4 小时后轻微失落”仅为助手待确认建议，用户没有批准统一 4 小时阈值。作息、消息期待、已有约定、人物差异如何共同决定变化，以及离线恢复是否重建状态但不补发过期催促，仍需形成具体建议后对齐。

用户明确要求同步派遣子 agent 调研相关情绪回答方案；该调研为只读源码与许可核验，不授权直接导入框架或实现未确认行为。

## 7. 情绪回答专项调研补充

专项只读子 agent 已返回证据。以下更新 §4 的可获取性状态；不把新增设计建议当成已批准行为。

### AstrBot Private Companion：可获取性已重新核验

固定版本 `85cc366ee6e1ccf08b357e8b9e396c3abb842ff4` 已可读取。子 agent 核验提交日期为 2026-08-28、最近推送为 2026-09-07；API license=null，固定树没有 LICENSE。保留用户明确声明已获作者代码复用许可，不能把没有公开许可证说成用户授权失效；后续可在该授权范围内选择切片适配，不能据此宣称它是 MIT/Apache 或可任意再授权。本轮没有复制实现代码。

- [interaction_dynamics.py](https://github.com/menglimi/astrbot_plugin_private_companion/blob/85cc366ee6e1ccf08b357e8b9e396c3abb842ff4/domains/affect/interaction_dynamics.py#L25-L122)：主 agent 已独立读取。情绪负荷按真实 elapsed time 指数衰减；受伤事件强化负向情绪，安慰等事件可以逐步恢复，正向表达逐级升温。可适配的是时间投影与渐变思路，不照搬 3600/7200 秒参数或增加第二份情绪真源。
- [emotion_event_contract.py](https://github.com/menglimi/astrbot_plugin_private_companion/blob/85cc366ee6e1ccf08b357e8b9e396c3abb842ff4/domains/affect/emotion_event_contract.py#L12-L27)：主 agent 已独立读取。区分 neutral、hurt、boundary、boundary_violation，保留时间、来源和去重身份。普通偏好拒绝不能直接等同于受伤事件；本地 affect.py 当前按事件 kind 中的“拒绝/conflict”触发负向，只证明转换函数语义，不证明当前普通边界反馈一定误入该分支。
- [relationship_policy.py](https://github.com/menglimi/astrbot_plugin_private_companion/blob/85cc366ee6e1ccf08b357e8b9e396c3abb842ff4/relationship_policy.py#L190-L280)：子 agent 核验关系阶段迟滞与语气、称呼、续话提示；[表达投影](https://github.com/menglimi/astrbot_plugin_private_companion/blob/85cc366ee6e1ccf08b357e8b9e396c3abb842ff4/companion_interaction_expression.py#L394-L451)区分 contact_boundary；不整套引入上游阶段系统。
- [余波测试](https://github.com/menglimi/astrbot_plugin_private_companion/blob/85cc366ee6e1ccf08b357e8b9e396c3abb842ff4/tests/test_emotion_e5_interaction_dynamics.py#L98-L153)覆盖渐变恢复、无到期骤变及单事件升温幅度，可参考测试场景；本轮未执行上游测试。

### Generative Agents：作息与时间参考，不替换底座

子 agent 核验版本 `fe05a71d3e4ed7d10bf68aa4eda6dd995ec070f4`、Apache-2.0，提交日期 2023-08-11、最近推送 2024-08-05。

[plan.py](https://github.com/joonspk-research/generative_agents/blob/fe05a71d3e4ed7d10bf68aa4eda6dd995ec070f4/reverie/backend_server/persona/cognitive_modules/plan.py#L23-L106)根据 lifestyle 安排起床及日程，[长期规划](https://github.com/joonspk-research/generative_agents/blob/fe05a71d3e4ed7d10bf68aa4eda6dd995ec070f4/reverie/backend_server/persona/cognitive_modules/plan.py#L461-L513)依赖模拟当前时间。只参考人物日程如何影响当前行为；模拟时钟并不等于真实墙钟，不能照搬对话循环次数作为时间，也不引入老旧模拟环境或额外关系摘要模型。

### 综合裁决与待对齐重点

优先改造现有 Companion 情绪账本、关系投影和表达适配；外部最值得借的是 AstrBot 的事件分类、时间衰减及渐进表达切片。两候选均未提供已验证的“双方期待/约定回复窗口”完整机制，不能据上游参数宣称存在通用的人类回复时限。

建议让关系决定亲密表达范围、情绪决定当下语气、真实时间与作息决定等待和恢复。单次没回复、长期减少互动、明确拒绝来往、普通称呼/话题边界分别处理；昵称与亲密表达仍尊重已有偏好。当前低心情主要被投影为 brief/slow/关闭幽默，接入更多事件前需避免把所有情绪都变成冷淡短句。

验收建议（未执行）：相同真实时间点不因心跳次数不同产生不同结果；睡眠/已知忙碌与明确约定分别检查；无送达证据不累计等待；一次连续消息不逐气泡叠加失落；正常边界反馈不降低关系；恢复无需强制道歉；同一状态重算不重复入账；Companion-only 身份门及普通链路零差异。具体事件、参数和恢复行为仍待产品对齐，不直接实施。
