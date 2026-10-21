# 意图对齐模块设计

> **定位**：为口语需求建立「结构化 → 澄清 → 确认 → 持久化 → 供任务规划消费」的通用意图对齐底座。
> **状态**：设计定稿，待实施。
> **基线**：分支 `codex/intent-alignment-module`（= main@71eb491f7）；文中 file:line 锚点均基于该分支实读。

## 0. 需求基线与平级关系

四项定案（不可改）：

1. **通用底座**：覆盖普通 1:1 会话（BRT）与临时组队/开发团队规划师前置层（开发团队模板的规划师角色见 `core/web/services/team/dev_task_board.py:43` `PLANNER_ROLE = "规划师"`）。
2. **结构化工件 + 确认 + 持久化**：职责链为 口语需求 → 结构化（目标/边界/约束/验收）→ 歧义提问（只提会改变实现走向的问题）→ 对话内确认卡确认 → 持久化为需求工件 → 作为任务规划正式输入。
3. **歧义触发、清晰直通**：意图与范围清楚时零提问直通规划。
4. **对话内确认卡**：聊天流内问题卡，回答自然留在会话历史。

**与任务规划的平级关系**：本模块与 TaskManager（`core/orchestration/task_planner.py:341`）+ TASK_CHECKLIST 章节（`core/prompt_manager/sections.py:251`，priority 20）平级；新章节 `INTENT_ALIGNMENT` 的 priority 取 19，位于 RUNTIME_GOAL(18)（`sections.py:187`）与 TASK_CHECKLIST(20)（`sections.py:266`）之间。

**总原则：语义归模型、确定性归规则。** 歧义判定、问题组稿、答案语义归并由主 agent 在 turn 内按 INTENT_ALIGNMENT 章节协议完成；工件维护、回执解析、packet 刷新与注入由规则层（worker 意图对齐 gate 与工具 handler）确定性完成。规则层不短路 turn、不代替模型产出 assistant 内容。

---

## 1. 现状与空白

### 1.1 任务规划的平级先例

- TaskManager：单例 + `workspace/memory/tasks.json` 持久化（`task_planner.py:341`、`task_planner.py:346-367`）；`task_create` 是「整清单覆盖重建」模型（`task_planner.py:699-703`）。
- TASK_CHECKLIST 章节：工厂在 `sections.py:251`（priority 20），compute 内转调 `get_task_manager` 拉激活清单（`sections.py:254-260`）——「章节在 prompt_manager、状态在 orchestration」的既有先例。
- 章节优先级序列：RUNTIME_GOAL(18)（`sections.py:187`）、USER_PROFILE(19)（`sections.py:241`）、TASK_CHECKLIST(20)（`sections.py:266`）。

### 1.2 BRT 现状：两句散规则，无机制

普通 1:1 会话的意图对齐现状仅是 `core/web/services/prompt_template_service.py:76-77` 的两句内嵌指令（不带着高影响猜测写入/删除/发布/重启；一组简短问题澄清）。无结构、无强制、无记忆——主 agent 每轮其实都在自判，但无状态、无审计、无累积。本模块要把它升级为机制。

### 1.3 turn 执行链路（接线依据）

普通 1:1 会话一轮消息的实际执行链（均已实读）：

1. 提交与准入：`core/web/services/session/submit.py:1299` `submit_session_message`（claim scope 见 `submit.py:1-6`：只做 validate/open turn/journal 标记/首快照/调度）；turn 准入锁 `core/web/services/session/admission.py:63`。
2. 排队调度：`core/web/services/session/schedule.py:111` → `schedule.py:164`。
3. worker 执行：`core/web/services/session/worker.py:1140` → `worker.py:1174` `_run_session_turn_impl`（解析 agent 实例、pin 模型、准备 workspace）。
4. continuation loop：`worker.py:2590` 附近；`worker.py:2617` 取 prompt；`worker.py:2838-2843` 每轮重绑 guidance。
5. 单 turn 执行：`worker.py:2845` → `core/orchestration/turn_runner.py:353` `run_existing_agent_single_turn`（`prepare_agent_turn` `turn_runner.py:216`）→ `agent.run_single_turn`（`turn_runner.py:311`）→ `_run_orchestrated_turn`（`agent.py:2952`）。
6. 系统提示词组装：`core/prompt_manager/prompt_manager.py:393` `build()`。

### 1.4 群聊 caseState 反例：单轮重算、零积累

`build_team_case_state`（`core/web/services/team_case_orchestrator.py:24-81`，docstring `:33` 自述「per-round case state」）由 `core/web/services/chat_room_service.py:1942` 每轮调用：`knownFacts` 只装当轮 topic（`team_case_orchestrator.py:68`）；`missingFacts` 由正则对当轮 topic 重算（`:187` 起）；history 仅用于 caseId 计数（`:62`、`:289-291`）。上一轮问过什么、用户答过什么完全不进入下一轮状态——同一问题可被无限重复追问。这是新机制必须避免的形态，也是「状态合并可以归规则、语义判定必须归模型」双向教训的来源。

### 1.5 消息面前置事实（确认卡依据）

- 普通会话消息是 `UserConversationMessage | AssistantConversationTurn` 二元联合，assistant 侧结构化数据全部走 `turnItems`（`web/src/api/types/chat.ts:782`、`chat.ts:774-780`）；`SessionTurnItem` 六类，`ToolCallTurnItem.input?: string` 携带工具入参（`chat.ts:680-686`、`chat.ts:647-659`）。
- todo 清单卡片先例：`todo_write` 的 journaled tool-call arguments → journal → `turnItems` 投影 → 前端纯派生渲染，卡片不落盘不回写（`web/src/components/vui/designs/product/conversation.md:53-102`）。
- SSE 事件族六种（`chat.ts:1389-1394`）；journal 事件常量 `assistant_item_committed`（`core/chat/turn_journal.py:31`）；session 投影层负责 turnItems 组装/合并（`core/web/services/session/projection.py:1422-1424`）。
- 用户消息入口 `POST /sessions/{session_id}/messages`（`core/web/routes/sessions.py:950-956`）；`SessionMessagePayload` 已支持 `content`、`references: list[dict]`（`sessions.py:256-268`）；`references` 的 `kind` 是开放 string（`chat.ts:708-730`，`:711`），已有 `kind: "message"` 引用语义（`chat.ts:726-729`）；忙时排队 `queueIfBusy` 已覆盖（`chat.ts:797-826`）。
- 群聊 `messageKind: "user_clarification"` 是展示分类标签（服务端由 case 状态派生，`chat_room_service.py:4954-4971`；类型 `chat.ts:1512`），前端全量检索仅类型定义一处、零消费；群聊消息已有结构化 payload 先例（`chat.ts:1515`、`chat.ts:1477-1499`）。

### 1.6 团队组队链路现状

组队入口 `core/web/routes/teams.py:170` 直接以 `payload.topic` 原文调 `create_ephemeral_team`（`core/web/services/team/ephemeral_team_service.py:31`；`team_purpose` 与首个 dev task 的 `description` 均为 topic 原文，`ephemeral_team_service.py:68`、`:74-79`）；四角色模板（规划师 + 两名开发 + 评审员）见 `core/web/services/team_template_service.py:344-373`。

### 1.7 空白总结

无结构化需求工件（需求只存在于对话文本）；无跨轮问答台账（澄清无积累，同 1.4 反例）；无确认证据（用户「确认过什么」无可对账记录）；无 prompt 章节承载对齐状态；无确认卡消息契约与前端组件；组队输入是 topic 原文而非已确认工件。

---

## 2. 总体架构

### 2.1 架构图

```text
用户消息（P0 打字 / P1 卡片回执 references[kind="intent_alignment"]）
   │
   ▼
submit_session_message（准入 / Journal 标记 / 首快照 —— 全部保持不变）
   │ schedule
   ▼
worker 意图对齐 gate（worker.py:1174 _run_session_turn_impl 内、
                      continuation loop 之前；纯确定性，fail-open）
   ├─ 加载会话工件与问题台账（无工件则跳过，零开销）
   ├─ P1：解析确认回执 → 已答问题标 answered、存答案原文（不做语义归并）
   ├─ 规则预筛：clear 快路径信号 / 疑似分叉信号 → 写入 packet（提示与审计）
   ├─ 组装 IntentAlignmentPacket 并注入 PromptManager
   │        （set_intent_alignment_packet，镜像 set_runtime_goal_packet）
   └─ 任何异常 → fail-open 直通原链路（零行为差异路径）
   │
   ▼
agent turn（_run_orchestrated_turn → prompt_manager.build）
   ├─ INTENT_ALIGNMENT 章节渲染 packet（packet 为 None 或已对齐时章节零 token）
   └─ 主 agent 按章节协议自判（语义判定归模型）
        ├─ 直通：无未决分叉 → 正常推进规划/执行
        └─ 提问：正文文本提出问题 + 调用 intent_alignment_card 工具
             ├─ handler 生成 cardId；revision = 发卡时工件版本号
             ├─ journal 落 tool-call turnItem（payload = IntentAlignmentCardPayload）
             └─ 转调 store.record_question_asked ×N + store.request_confirmation(cardId)
   │
   ▼
用户回答
   ├─ P0：打字回答（卡片在前端折叠为工具行）
   │     └─ 本 turn：agent 读对话史 → 调 intent_alignment_merge 语义归并
   └─ P1：确认卡组件提交 → 普通用户消息
            （content 人类可读 + references 挂 IntentAlignmentReply 回执）
         └─ 下一 turn：gate 确定性标 answered 存原文
            → agent 调 intent_alignment_merge 语义归并
   │
   ▼
confirmed 需求工件（版本链落盘 memory/intent_alignment/<sessionId>.json）
   │ take_confirmed / get_current 只读快照
   ▼
RUNTIME_GOAL（goal/验收汇入）· TaskManager（task_create 输入）
· 开发团队规划师（拆板前置输入，P2）
```

### 2.2 职责分层

| 层 | 承担者 | 职责 | 禁止 |
| --- | --- | --- | --- |
| 语义层 | 主 agent（turn 内，按 INTENT_ALIGNMENT 章节协议） | 歧义判定（要不要问、问什么）、问题组稿、答案语义归并、确认语义判定 | —— |
| 确定性层 | worker 意图对齐 gate + intent_alignment_card / intent_alignment_merge 工具 handler | 回执解析、已答标注与原文留存、packet 刷新与注入、台账/版本/状态机维护、journal turnItem 落记 | 短路 turn；代替模型产出 assistant 内容；做语义判定 |

依据：规则层组不出高质量问题（分叉判定需要代码与项目上下文）；gate 代笔 assistant 内容会动摇「Journal 是模型产出 transcript 权威」；与判定形态选型（§4.1）一致。

### 2.3 关键时序（示例）

- **Turn 1**：用户提出口语需求 → gate 无工件、packet 为空 → agent 自判为歧义 → 调 `intent_alignment_merge` 落四要素初稿（推断内容进 assumptions，source=inferred）→ 调 `intent_alignment_card` 发卡（台账登记、工件 pending_confirmation）→ 正文文本同步提出同样问题，turn 正常收束。
- **Turn 2**：用户回答（P0 打字 / P1 卡片回执）→ gate 刷新（P1 先确定性标 answered 存原文）→ agent 读对话史与章节，调 `intent_alignment_merge` 归并答案生成新版本 → 无剩余分叉时随归并落确认判定（approved），工件 confirmed → agent 推进规划。
- **Turn 3+**：gate 加载 confirmed 工件 → packet status=aligned → 章节渲染已确认需求摘要（或空态零 token）→ 规划与执行照常。

---

## 3. 工件契约与服务核心

### 3.1 模块位置与命名

新建单文件模块 `core/orchestration/intent_alignment.py`，对外入口 `get_intent_alignment_store()` 单例与 `reset_intent_alignment_store()` 测试复位，与 `task_planner.py` 的 `get_task_manager`/`reset_task_manager`（`task_planner.py:855`、`:894`）一一对应。

理由：

1. **包级路由支持**：`core/orchestration/README.md:3` 明示「新逻辑优先扩这里的模块，不要在 agent.py 再堆业务」。意图对齐是编排层能力（输出直接喂 RUNTIME_GOAL 与任务规划）。
2. **不触犯 DO_NOT_CREATE 裁决**：`README.md:43` 禁止的是新增第二套单轮 coordinator（四项必要条件对照 `README.md:57-64`）。本模块不进单轮调用链、不编排 message assembly / LLM adapter / TurnOutcomeController / ToolLifecycleBridge（现有链路对照 `README.md:47-55`）、不写回任何 `agent._private` 字段；它是被动数据服务，与 owner 表中 `runtime_goal.py`（`README.md:21`）、`task_planner.py` 同类。按 `README.md:66`「只允许继续把单一职责切片进现有 owner」的精神，以「单一职责新 owner」进 owner 表。本包不得反向 import `agent.py`（`README.md:5`）。
3. **平级关系成立**：数据流上 `intent_alignment`（需求工件）是 `runtime_goal`（目标包）与 `task_planner`（任务清单）的上游；模块间只通过快照读取交接（§3.8），无反向依赖。
4. **备选否决**：放 `core/prompt_manager/`（该层职责是章节工厂与 Prompt 组装，`sections.py:2-6`；持久状态不应藏进 prompt 层，TASK_CHECKLIST 本身就是「章节在 prompt_manager、状态在 orchestration」先例）；放 `core/web/services/`（非 web 的自进化/监督入口也要可用）；扩展 TaskManager 加字段（tasks.json 是无版本整清单覆盖模型，`task_planner.py:699-703`，塞版本链破坏其简洁契约）。

### 3.2 状态机与版本语义

「版本链（version chain）+ 当前指针」模型：每个版本是一次不可变快照（带 contentHash）；`status` 是当前版本的属性；`superseded` 是旧版本的冻结终态。

```text
draft ──发确认卡──▶ pending_confirmation ──用户确认──▶ confirmed ──规划入口采纳──▶ consumed
  ▲                                            │                          │
  └──── 新版本 supersede 旧版本 ◀───────────────┴──────────────────────────┘
（任意非终态版本都可被新版本 supersede；superseded/consumed 是「该版本」的终态，工件链可继续生长）
```

| 从 | 到 | 触发 | 约束 |
| --- | --- | --- | --- |
| draft | pending_confirmation | `request_confirmation`（发卡，由 intent_alignment_card handler 调用） | 四要素（goal/boundaries/constraints/acceptance）非空；绑定 cardId 与发卡 turnId。发卡前 agent 应先经 intent_alignment_merge 落当前最佳理解的四要素初稿，推断内容以 assumptions（source=inferred）显式标注，待澄清问题对准这些未验证假设 |
| pending_confirmation | confirmed | 用户确认（decision=approved），由 agent 语义判定后经 intent_alignment_merge 落判定 | 记录 decision turnId 与确认摘要 |
| pending_confirmation | superseded | 用户要求修改（decision=revision_requested） | 自动创建新版本（status=draft）继承已答内容；`supersedes` 双向链 |
| pending_confirmation | superseded | 用户拒绝（decision=rejected） | 不自动开新版本（用户明确放弃），链终止 |
| confirmed | superseded | 确认后需求变更 | 同 revision 路径 |
| confirmed | consumed | 首个规划入口 `take_confirmed` 采纳 | 后续消费方只登记 `consumedBy`，不改状态 |
| consumed | superseded | 采纳后需求再变更 | 链内开新 draft；旧 taskId 关联保留在版本上供审计 |
| draft | superseded | 结构化重写前需废弃 | 允许，罕见路径 |

决策词继承 problem_understanding 的 `HUMAN_GATE_DECISIONS`（`core/web/services/team_workflow/research_runtime/problem_understanding_artifact_writer.py:21-23` 的 `{"pending", "approved", "revision_requested", "rejected"}`）：approved→confirmed、revision_requested→superseded+新 draft、rejected→superseded 终止。不新增第五个状态。

**为什么版本不可变而不是原地更新**：被确认过的版本若被原地改写，确认行为失去锚点；仓内已有「append 一次不可变工件 + 精确重放幂等」可维护先例（`problem_understanding_artifact_writer.py:347` docstring「append one immutable canonical artifact, idempotently」；底层 `put_workflow_artifact` 在 `core/web/services/team_workflow/research_runtime/workflow_artifact_store.py:212-252`，同 identity 重放同 hash 幂等、不同 hash 抛冲突）。但 problem_understanding 是「按 attempt 追加独立工件」，没有链内 supersede；本模块的澄清是同一工件的连续修订，链模型更贴切（差异表见附录 A）。

### 3.3 存储方案：每会话一文件 + 文件内版本链

| 选项 | 形态 | 结论 |
| --- | --- | --- |
| A. 单例单文件（照抄 tasks.json：`memory/intent_alignment.json`） | 全部会话一个 JSON；与 TaskManager 模式最像（`task_planner.py:348`、`:353`） | 否决：多会话争用同一把文件锁（`core/infrastructure/file_lock.py:51` 锁粒度=单文件）；文件随会话数无界增长；单文件损坏殃及所有会话 |
| **B. 每会话一文件 + 文件内版本链（采用）** | `memory/intent_alignment/<sessionId>.json`，内含版本数组 + 当前指针 + 消费登记 | 会话天然隔离、锁粒度=会话；损坏爆炸半径=单会话；路径解析复用 `developer_sandbox.formal_workspace_path`（先例 `task_planner.py:265`，函数本体 `core/infrastructure/developer_sandbox.py:361-374`） |
| C. 独立 append-only 工件库（照抄 workflow_artifact_store） | 按 kind 追加 JSONL | 否决：该库身份域是 team/workflowRun（`put_workflow_artifact` 强制 workflowRunId，`workflow_artifact_store.py:226-227`），1:1 会话没有 workflow run，身份错配；但其 hash+幂等+冲突语义被 B 吸收 |
| D. 复用 Session/Journal/ConversationStore | 工件作为会话消息或 Journal 记录 | 否决：红线违规——Session Journal 是 Turn/transcript 唯一权威，派生的需求状态不得写进 transcript |

**与会话的绑定基数**：每会话单活跃工件 + 版本链历史；`origin.createdAt` 区分同会话先后工件链。跨会话查询按目录扫描，v1 无此需求（开放问题 §7.2-1）。

### 3.4 多轮澄清累积语义：问答台账并入版本，不做每轮重算

要避免的反例即 §1.4 的 caseState。本模块的累积契约：

1. **问题有稳定 id 与生命周期**。每提出一个问题，`record_question_asked` 分配 `questionId` 并置 `status=asked`，记录提问内容、为什么它改变实现走向（`whyItMatters`）、拟影响字段（`appliesTo`）与提问 turnId。
2. **回答触发显式合并，产生新版本**。`record_answer` 把答案文本 + 来源 turnId 写入该问题的 `answer`，置 `status=answered`，并按调用方给出的 `merge` 指令（改哪些四要素/assumptions 字段）生成新版本；新版本的 `changes` 逐条记录 `{field, from, to, questionId}`。**回答永不静默覆盖**——没有 merge 指令的答案只留在台账（问题已答、原文留存），不进结构化四要素。这正是 gate 回执落账（无 merge 指令路径）与 agent 语义归并（带 merge 指令路径）的分界。
3. **累积不变式**：任意时刻，当前版本 = 对所有已答问题的结构化汇总；剩余待问集合 = `asked ∧ 未 answered ∧ 未 withdrawn`。判定与组稿读的是累积状态（`open_questions`），不是从原始对话历史重新推断——这是与 caseState 反例的本质区别。
4. **撤销留痕**：`withdrawn` 的问题保留在台账（记录撤销原因）；被后续回答推翻的 assumption 置 `status=invalidated` 而非删除。
5. **版本提交原子**：一轮中途崩溃不产生半合并版本，恢复后从最后已提交版本继续——借鉴 langgraph checkpoint 的「失败写不更新 checkpoint、恢复只应用已提交写入」契约思想（本地缓存参考 langchain-ai/langgraph `libs/langgraph/tests/test_pregel.py:891` 起的 `test_pending_writes_resume`；只借版本/恢复契约，不引引擎）。

### 3.5 服务接口与 agent 工具面

#### 3.5.1 store 内部 API（伪签名，非实现）

所有方法挂在 `IntentAlignmentStore` 单例上；snapshot 一律深拷贝只读投影——「单存储源、投影非第二存储」，对齐 TaskManager 的 Plan 投影测试思想（`tests/test_task_planner.py:74` `test_current_plan_is_projection_not_second_storage`）。

```text
get_intent_alignment_store(project_root: str | None = None) -> IntentAlignmentStore
    # 单例 + project_root 校验，模式对齐 get_task_manager（task_planner.py:855-891）
reset_intent_alignment_store() -> None
    # 测试复位，对齐 reset_task_manager（task_planner.py:894-899）

class IntentAlignmentStore:
    # ── 工件生命周期 ──
    open_or_load(session_id: str, *, origin: OriginInfo) -> ArtifactRef
    record_structured(artifact_id, *, goal, boundaries, constraints, acceptance,
                      assumptions) -> VersionInfo
    request_confirmation(artifact_id, *, card_id: str, turn_ref: TurnRef) -> VersionInfo
        # draft → pending_confirmation；四要素齐备才允许
    submit_confirmation_decision(artifact_id, *, decision: str, turn_ref: TurnRef,
                                 note: str = "") -> VersionInfo
        # decision ∈ approved|revision_requested|rejected（词表继承
        # problem_understanding_artifact_writer.py:21-23）

    # ── 澄清台账 ──
    record_question_asked(artifact_id, *, question: str, why_it_matters: str,
                          applies_to: str) -> str   # 返回 questionId
    record_answer(artifact_id, question_id: str, *, answer_text: str,
                  turn_ref: TurnRef, merge: list[FieldUpdate]) -> VersionInfo | None
        # merge 为空：只落台账（gate 回执路径）；merge 非空：生成新版本（agent 归并路径）
    withdraw_question(artifact_id, question_id: str, *, reason: str) -> None

    # ── 读取与交接（消费方与 packet 组装调用） ──
    get_current(session_id: str) -> IntentSnapshot | None
    get_version(session_id: str, version: int) -> IntentSnapshot | None
    take_confirmed(session_id: str, *, consumer: str, ref: str = "") -> IntentSnapshot | None
        # confirmed→consumed（首次）；后续 consumer 只登记 consumedBy；无 confirmed 返回 None 不抛错
    open_questions(session_id: str) -> list[QuestionView]   # 累积待问集合（§3.4 不变式）
```

`TurnRef = {sessionId, turnId, messageId?}`：只作为引用记录，不回写 Session/Journal。

prompt 投影统一走 `IntentAlignmentPacket`（§4.2），由 worker 意图对齐 gate 组装后经 `PromptManager.set_intent_alignment_packet` 注入；store 不再单独提供 markdown 渲染入口（快照读取 API 即 packet 组装的全部输入）。

#### 3.5.2 agent 工具面（P0 即全量提供）

主 agent 与工件的所有写入都经工具族完成；两个工具即 store 写路径的 agent 面。

```text
intent_alignment_card(
    intent_summary: str,                      # 当前理解的意图（卡片头部一句话）
    questions: list[{
        question_id?: str,                    # 重问沿用已有台账 id；缺省由台账分配
        question: str, why_it_matters: str, applies_to: str,
        input_mode: "single_choice" | "multi_choice" | "free_text" | "choice_or_text",
        options?: list[{option_id, label, hint?}], required: bool, placeholder?: str
    }],
    artifacts?: list[{artifact_id, version, title}],
) -> {cardId, revision}
    # handler（确定性）：
    #   1. 生成 cardId（§3.9）；revision = 发卡时工件版本号；
    #   2. 组装 IntentAlignmentCardPayload：模型原始入参（intent_summary/questions/
    #      artifacts）经 tool_call turnItem.input 落 journal（toolName=
    #      "intent_alignment_card"，todo_write 同构）；完整 payload（含 handler 生成的
    #      cardId/revision/台账分配的最终 questionId）随工具 result 侧入 journal；
    #   3. 转调 store.record_question_asked ×N + store.request_confirmation(card_id)；
    #   4. 刷新 PromptManager 内 packet（供同 turn 后续 continuation 轮次可见）。

intent_alignment_merge(
    answers?: list[{
        question_id: str, answer_text: str,
        merge?: list[FieldUpdate]             # 该答案折算进哪些四要素/assumptions 字段
    }],
    structured?: {goal?, boundaries?, constraints?, acceptance?, assumptions?},
    confirmation?: {decision: "approved" | "revision_requested" | "rejected", note?},
) -> {artifactId, version, status}
    # handler（确定性）转调 store.record_answer / record_structured /
    # submit_confirmation_decision；首次写入时 open_or_load 创建 v1(draft)；
    # 写后同样刷新 packet。语义判断（答案是什么、折算到哪、用户是否确认）全部由
    # 主 agent 在入参中给出——handler 只落账。
```

> 实现修订（T4）：工具执行机制下 turnItem.input 只承载模型原始入参（intent_summary/questions/artifacts）；handler 组装的完整 §5.2 payload（含 cardId/revision/最终 questionId）随工具结果（result 侧）入 journal，前端从 input+output 拼装或直接读 result.payload。

约束：`intent_alignment_card` 的前置条件是工件已有四要素初稿（agent 先 merge 再发卡）；不满足时 handler 返回错误，agent 可先补 merge。正文文本与卡片问题必须一致（P0 前端折叠卡片为工具行，正文是用户可见的提问本体）。

### 3.6 数据契约

`memory/intent_alignment/<sessionId>.json` 的完整形状（schema 示例，非实现代码）：

```json
{
  "schemaVersion": 1,
  "sessionId": "sess_...",
  "origin": {
    "mode": "chat | team_planning",
    "roomId": "",
    "sourceTextDigest": "sha256:...",
    "createdAt": "ISO-8601"
  },
  "currentVersion": 3,
  "versions": [
    {
      "version": 3,
      "status": "confirmed",
      "contentHash": "sha256:...",
      "supersedes": 2,
      "goal": { "text": "……" },
      "boundaries": ["不做……", "范围限于……"],
      "constraints": ["必须……", "技术栈限定……"],
      "acceptance": [
        { "criterion": "可验证的验收标准", "verifiable": true }
      ],
      "assumptions": [
        { "id": "a1", "text": "……",
          "source": "user_statement | inferred",
          "status": "open | validated | invalidated" }
      ],
      "openQuestions": [
        { "id": "q2", "question": "……", "whyItMatters": "该答案决定 X 走 A 还是 B",
          "appliesTo": "goal | boundaries | constraints | acceptance | assumptions",
          "status": "asked | answered | withdrawn",
          "askedAtTurn": "turn_...", "askedInCard": "",
          "answer": { "text": "……", "turnId": "turn_...", "answeredAt": "ISO-8601" } }
      ],
      "changes": [
        { "field": "constraints[+]", "from": null, "to": "必须……",
          "reason": "answer to q2" }
      ],
      "confirmation": {
        "cardId": "card_...", "issuedAtTurn": "turn_...",
        "decision": "approved | revision_requested | rejected | pending",
        "decidedAtTurn": "turn_...", "decidedAt": "ISO-8601",
        "confirmedDigest": "用户确认时看到的四要素摘要 hash"
      },
      "createdAt": "ISO-8601"
    }
  ],
  "consumedBy": [
    { "consumer": "task_manager | team_planner | runtime_goal",
      "consumedAt": "ISO-8601", "ref": "tasks.json 或 board task 的引用" }
  ],
  "updatedAt": "ISO-8601"
}
```

要点：

- `versions[]` **只追加不改写**；`contentHash` 为该版本内容字段的规范化 sha256，算法对齐 `canonical_sha256`（`core/web/services/team_workflow/research_runtime/human_gate_artifacts.py:13`，使用先例 `problem_understanding_artifact_writer.py:381`）。`supersededBy` 由后继版本写入索引侧（新版本的 `supersedes`），旧版本本身冻结。
- `confirmedDigest` 把「用户看到并确认的内容」与版本内容绑定：确认后若内容被质疑，可对账确认时摘要 hash 与当前版本 hash。
- `openQuestions` 随版本快照化：每版本记录当时的问题台账状态，天然形成逐版本审计（§3.4 累积语义的落地形态）。
- 文件级 `currentVersion` 指针 + `consumedBy` 登记是仅有的两个文件级可变字段；其余全部只追加。

### 3.7 存储与并发

- **路径解析**：`_intent_alignment_store_path(session_id)` 模块级函数，供测试 monkeypatch（对齐 `_tasks_json_path` 的设计意图，`task_planner.py:258-259` 注释明示「测试会 monkeypatch 这个函数」）。实现路径 = `developer_sandbox.formal_workspace_path(project_root, "memory", "intent_alignment", f"{session_id}.json")`（`developer_sandbox.py:361-374`）。另提供 `_INTENT_STORAGE_OVERRIDE` ContextVar + `intent_storage_override(workspace_root)` contextmanager（对齐 `task_planner.py:21`、`:235-241`）供集成测试整目录隔离。
- **写入（原子 + 锁）**：使用 `core/infrastructure/atomic_io.py:86` 的 `atomic_write_json(path, payload, strict_replace=True)`——内部已持 `cross_process_file_lock`（`atomic_io.py:57`），按 `<target>.lock` sidecar 串行化跨线程/跨进程写（锁约定 `file_lock.py:51`；锁语义 `file_lock.py:64-107`：per-target、同线程可重入、超时抛 `TimeoutError`）。`strict_replace=True` 必须开（`atomic_io.py:46-51`：默认会退化成就地写入，严格 all-or-nothing 语义的调用方必须让阻塞以错误暴露）；版本链文件绝不允许截断态。进程内再叠一层 `threading.Lock` 串行化「读-改-写」区间（模式对照 `runtime_task_registry.py:371` 的显式组合）。
- **读-改-写对账**：版本追加是「锁内读文件 → 校验 baseVersion == 文件 currentVersion → 追加 → 原子替换」。baseVersion 不匹配抛版本冲突，对齐 `put_workflow_artifact` 对「同 identity 不同 contentHash」抛 `WorkflowArtifactConflictError` 的语义（`workflow_artifact_store.py:243-252`）——冲突显式失败，绝不静默覆盖。
- **每会话一把锁**：`<sessionId>.json` 分文件即分会话分锁：同会话并发写串行化，跨会话零争用。
- **损坏容错**：加载时解析失败/结构非法 → 返回空库并保留损坏文件副本（`<sessionId>.json.corrupt-<ts>`）供人工恢复，不静默重建覆盖——比 TaskManager 的「异常即静默回空」（`task_planner.py:383-387`）更保守，因为本文件含用户确认记录，属审计证据。

### 3.8 交接接口（confirmed 工件如何被消费）

只定义接口与字段映射方向，不设计消费方内部。约定消费不删除、不回写工件，只登记 `consumedBy`。

- **→ RUNTIME_GOAL**：目标包构建处读取 `take_confirmed`/`get_current` 快照，`goal.text` 作为 `RuntimeGoalPacket.goal` 的优先来源、`acceptance` 汇入 `completion_standard`（RuntimeGoalPacket 字段面 `core/orchestration/runtime_goal.py:225-241`；构建入口 `build_runtime_goal_packet` `runtime_goal.py:292-297`）。本模块只保证快照可读与 `contentHash` 可校验，不改 runtime_goal.py 包结构。
- **→ TaskManager（1:1 会话规划）**：`take_confirmed(session_id, consumer="task_manager", ref=<tasks 引用>)`；TaskManager 侧以 `goal.text` 作为 `task_create` 的 goal 输入、`acceptance` 作为清单条目拆解与完成判据来源（`task_create` 签名 `task_planner.py:699`）。工件与任务由 `consumedBy[].ref` 与任务侧 metadata 各记一笔（双向可追溯，单向依赖，通过快照 dict 交接）。
- **→ 开发团队规划师（临时组队前置层）**：同一接口 `take_confirmed(session_id, consumer="team_planner")`。confirmed 工件作为规划师拆板输入的正式前置（组队链路改道设计见 §8.1 P2）。
- **→ 个人助理（只读引用）**：按 `artifactId（sessionId 工件）+ version + contentHash` 三元组经 `get_version` 引用读取，用于跨任务汇报中的「已确认需求」引用；**不提供任何写接口**（划界依据见 §6.4）。

### 3.9 标识映射（cardId / revision / questionId）

三级标识分工，全部可精确映射回台账：

| 标识 | 生成者 | 语义 |
| --- | --- | --- |
| `cardId` | `intent_alignment_card` 工具 handler 在发卡时生成 | 标识一次发卡；同会话内唯一；卡片随 journal append-only 不可变，需要改问时发新卡（新 cardId） |
| `revision` | handler 取发卡时的工件版本号 | 标记该卡针对哪一版需求工件提问；回执携带同一 revision 供对账 |
| `questionId` | packet/工件问题台账分配（`record_question_asked`） | 台账稳定 id，跨卡稳定；同一问题在新卡中重问时沿用原 id（工具入参可携带，缺省由台账分配） |

`IntentAlignmentReply` 回执按 `cardId + revision + questionId` 精确映射回台账；映射不到的条目原样留档，由主 agent 在 turn 内判定处置。前端「已作废」派生按会话时间线上的后发卡判断（见 §5.4）。

---

## 4. 判定机制与 INTENT_ALIGNMENT 章节

### 4.1 判定形态：规则预筛（确定性）+ 主 agent turn 内自判（语义）

方案对比（候选形态曾有三）：

| 维度 | prompt 内嵌协议，主 agent 自判自问 | 独立轻量 LLM 判定调用（每消息 +1 次串行调用） | **规则预筛 + 主 agent 自判（采用）** |
| --- | --- | --- | --- |
| 额外 LLM 调用 | 0 | 每条消息 +1 | 0（规则零调用） |
| 串行延迟 | 0 | clear 路径也被拖慢一整个 RTT | 多数 0；规则预筛为本地计算 |
| 判定信息集 | 完整（全部章节 + 对话史 + 代码面上下文） | 精简（弱信息集下系统性过问或漏问） | 语义判定仍在主 agent，信息集完整 |
| 判定/执行一致性 | 单一主体 | 双模型分歧风险（判定器说无歧义、主 agent 仍追问） | 单一主体；规则只提供信号不裁决 |
| 常驻 token 成本 | 协议文本约 150-300 token 进章节 | 判定 prompt 每消息 500-1500 token + 协议文本 | 同左第一列（aligned 时空态零 token） |
| 状态记忆 | 需外部台账 | 同左且双读接线更重 | 台账由工件层承担（§3.4） |

采用形态：**规则预筛负责确定性部分**（识别「明确祈使句 + 明确对象」的 clear 快路径信号、检测疑似分叉信号、解析确认回执、维护 packet），**主 agent 在 turn 内依 INTENT_ALIGNMENT 章节承载的协议与状态做语义判定**（要不要问、问什么、答案折算到哪）。决定性论据：

1. 成本结构：给所有轮次（含 clear 多数路径）加一次串行 LLM 延迟，与「零提问直通」的体验目标背反。
2. 信息集：判定「歧义是否改变实现走向」本质需要代码与项目上下文（「改一下登录」是否分叉取决于登录实现现状），独立判定调用拿不到。
3. 机制缺口在结构不在判断力：现状 BRT 规则（`prompt_template_service.py:76-77`）的问题是「无结构、无强制、无记忆」；升级为机制 = 结构化章节 + 持久台账 + 组装留痕，而不是换一个判定者。
4. 群聊反例的双向教训（§1.4）：纯规则判定会退化为单轮重算、重复追问；规则完全可以承担状态机合并这类确定性职责。

规则预筛的信号输出只是**提示与审计**（写入 packet 的 gate 段），判定权始终在主 agent；规则层不短路 turn。独立 LLM 判定调用不进本模块任何一期；如未来团队前置层需要廉价前置判定，另行评估，不占用 BRT turn 主路径。

### 4.2 IntentAlignmentPacket（prompt 投影 schema）

规则预筛与主 agent 自判共用同一产物结构；对 prompt 层它是只读渲染输入，对存储层它是工件快照的确定性投影（由 worker gate 组装，§4.4）。

```text
IntentAlignmentPacket（伪 schema，非实现代码）
  schemaVersion: 1
  status: "aligned" | "clarifying"
  confirmedRequirements:        # 已确认需求（只保留影响实现走向的条目，≤5）
    - point: string             # 一句话结论，如"目标浏览器仅 Chrome ≥ 120"
      settledAt: roundRef
      evidence: string          # 用户原话短引用（≤80 字符）
  openQuestions:                # 待澄清问题（status=clarifying 时非空）
    - id: string                # 即台账 questionId（§3.9）
      question: string
      impactFork: string        # 不问则实现怎么分叉（一句话）
      options: [string]         # 建议选项（可空，≤3）
      askedAt: roundRef | null  # 尚未问过为 null
  clarifyHistory:               # 已问已答（append-only，渲染时只取最近 3 条）
    - questionId: string
      question: string
      answer: string            # 用户答复要点
      settledAs: string         # 折算成的 confirmedRequirement point
  gate:                         # 规则预筛结论（提示与审计，非裁决）
    action: "proceed" | "ask"   # 信号命中时给出 ask 倾向；仅参考
    confidence: 0.0-1.0
    decidedBy: "rules"          # 规则预筛；主 agent 的最终决策体现为其行为
    reason: string              # 如"命中缺失量纲信号，交由本轮自判"
  budget:
    questionsAskedThisSession: int   # 防追问循环
    maxQuestionsPerTurn: 3           # 对齐 BRT 现规则"一组简短问题"语义（prompt_template_service.py:77）
```

packet 字段与工件的映射：`confirmedRequirements` ← 当前版本四要素中已确认要点；`openQuestions` ← 台账 `asked ∧ 未 answered ∧ 未 withdrawn`；`clarifyHistory` ← 台账已答条目；`gate` ← 规则预筛对当前消息的信号输出；`budget` ← 会话级提问预算。packet 是派生投影，store 是唯一权威。

### 4.3 零提问直通判据

gate.action = proceed 需全部满足（判据 1-4 由主 agent 在 turn 内核，判据 5 由规则预筛核）：

1. **目标可执行**：消息（或 confirmedRequirements）能推出「动作动词 + 作用对象 + 期望产出」。
2. **无未决问题**：openQuestions 为空，或全部已有 answer。
3. **不落高影响动作类**：本轮不涉及写入/删除/发布/重启/长期自动化/远端同步等需要用户闸门的动作（语义对齐 `prompt_template_service.py:77` 与 `:80` 的高风险闸门清单）。
4. **范围边界可推导**：改动面/输出面能从消息或已确认条目直接推出，不需要在多个互斥解读中选边。
5. **规则预筛未命中分叉信号**：多义指代（「它/这个」无就近唯一先行词）、缺失量纲（「优化一下」无指标）、互斥约束并存（「既要全量又要增量」）等信号任一命中时，规则层不得给出 proceed 倾向，必须交主 agent 自判。

### 4.4 注入机制

- `BuildContext`（`core/prompt_manager/types.py:108-115`）新增 `intent_alignment_packet: Any = None` 字段，与 `runtime_goal_packet` 并列。
- `PromptManager` 提供 `set_intent_alignment_packet(packet)` / `get_intent_alignment_packet()`，写入 `self._build_context` 并 `self._section_cache.invalidate("INTENT_ALIGNMENT")`——逐行镜像 `set_runtime_goal_packet`（`core/prompt_manager/prompt_manager.py:996-1000`）。
- INTENT_ALIGNMENT 章节的 compute 从 ctx 读 packet 渲染（同 `make_runtime_goal_section` 从 ctx 读 packet 的写法，`sections.py:172-181`）。
- **packet 更新的两个时点**：
  1. **turn 前（规则，确定性）**：worker 意图对齐 gate 内——加载工件快照、（P1）解析确认回执落台账、运行规则预筛、组装 packet 并注入。gate 取到已解析 agent 的 PromptManager 注入；异常 fail-open 直通（packet 不注入，章节空态）。
  2. **turn 中（工具 handler，确定性）**：`intent_alignment_card` / `intent_alignment_merge` 写后刷新 PromptManager 内 packet，供同 turn 后续 continuation 轮次的提示词构建反映最新状态。语义归并不发生在 prompt 层——prompt 层只持投影，单一权威在 store。
- **防重复追问的呈现规则**：clarifyHistory 渲染最近 3 条为一句式结论（「已确认：X」），已答问题同时折算进 confirmedRequirements；章节协议明文禁止对 clarifyHistory 中已 settle 的 questionId 再次提问。

### 4.5 INTENT_ALIGNMENT 章节设计

#### 4.5.1 章节元信息

| 属性 | 取值 | 依据 |
| --- | --- | --- |
| name | `INTENT_ALIGNMENT` | 新增，全库无冲突（已检索 core/config/tests/docs） |
| priority | 19 | 介于 RUNTIME_GOAL(18)（`sections.py:187`）与 TASK_CHECKLIST(20)（`sections.py:266`）之间；USER_PROFILE 已占 19（`sections.py:241`），并列由排序规则消解（§4.6） |
| cache_break | True | 内容随澄清进展逐轮变化，动态章节（同 RUNTIME_GOAL/TASK_CHECKLIST，`sections.py:186`/`:265`） |
| cache_prefix | False | 内容跨轮不字节稳定，不得进缓存前缀（对比 USER_PROFILE 静态画像才允许 `cache_prefix=True`，`sections.py:239-240` 及注释） |
| required | False | 可被显式 exclude（进 protected floor 保障默认在场，排除语义同 SESSION_FILE_REFERENCES，`tests/test_prompt_manager.py:1070-1078` 验证的模式） |
| capability_requirements | 不设 | 见 4.5.4 |
| TTL | 不进 TTL 注册表 | `_DYNAMIC_SECTION_TTL_SECONDS` 明确排除会话/任务状态类章节（`core/prompt_manager/builder.py:40-44` 注释把 RUNTIME_GOAL、TASK_CHECKLIST 等列为不收录对象），本章节同族 |

#### 4.5.2 章节内容结构

packet 为 None 或 status=aligned 且无 openQuestions 时 compute 返回 None → 章节零 token，直通规划（「零提问直通」在 prompt 侧零成本）。

status=clarifying 时的渲染形态（示例文本，非实现代码）：

```text
## 意图对齐
- 状态: 存在会改变实现走向的未决分叉，先澄清再规划/执行。
- 已确认需求:
  - 目标浏览器仅 Chrome ≥ 120（第 3 轮，用户："不用管 Safari"）
  - 只改前端展示层，不动接口契约（第 2 轮，用户："后端别动"）
- 待澄清问题（最多 3 个，一次问完，不拆成多轮问卷）:
  1. "表格数据超过一屏时要分页还是虚拟滚动？"——不问则布局与数据层实现直接分叉；建议: 分页 / 虚拟滚动 / 你定
- 澄清历史（已问已答，禁止重复追问）:
  - 已确认: 改动范围仅 web/src/table（第 1 轮问"改哪部分"）
- 判定依据: 规则预筛命中"缺失量纲"信号，交由本轮自判（confidence 0.7）
```

协议规则（写进章节文本本身，替代 `prompt_template_service.py:76-77` 的两句散规则；该模板处的散规则在章节落地后改为指向/让位，避免双源漂移，改动时机归实现期任务 T3）：

- 只在「歧义会改变实现走向」时提问；影响面仅是措辞、风格、等价路径选择时不问，直接选并说明。
- 提问必须一次成组（≤3 个）、每个问题附 impactFork 一句话；不得把提问拆成连续多轮问卷。
- 决定提问时：先以 `intent_alignment_merge` 落当前最佳理解的四要素初稿（推断内容进 assumptions），再调用 `intent_alignment_card` 发卡，同时以正文文本提出同样的问题（正文是用户可见的提问本体）。
- 收到用户回答（无论打字还是卡片回执）后，先以 `intent_alignment_merge` 归并答案与结构化更新，再继续推进；全部对齐且用户确认时随归并落 approved 判定。
- 已在澄清历史中 settle 的问题禁止重问；用户答复先折算成已确认需求再进入规划。
- 意图清楚时直接推进规划与执行，不为常规步骤索要确认（继承 `prompt_template_service.py:76` 语义）。

#### 4.5.3 与 RUNTIME_GOAL / TASK_CHECKLIST 的边界

| 章节 | 职责 | 证据锚点 |
| --- | --- | --- |
| RUNTIME_GOAL | 本轮目标包：目标、来源、能力边界、完成标准（「目标是什么、被允许做什么」） | `sections.py:169-190` |
| INTENT_ALIGNMENT | 需求理解状态：已确认需求 + 待澄清问题 + 问答记忆（「理解到什么程度、还差什么」） | 本设计 |
| TASK_CHECKLIST | 任务分解与执行清单（「怎么做、做到哪」） | `sections.py:251-268` |

互斥规则：INTENT_ALIGNMENT 不渲染任务条目、步骤或状态勾选（TASK_CHECKLIST 的内容）；不渲染能力边界与完成标准（RUNTIME_GOAL packet 的内容）。对齐完成进入规划后，本章节退化为一条「已确认需求」摘要或直接为空，把版面让给 TASK_CHECKLIST。三者形成「目标 → 理解 → 计划」递进，priority 18/19/20 与此一致。

#### 4.5.4 能力门：不新增 capability 位

- 机制事实：章节声明 `capability_requirements` 后，v2 组装路径下 `PromptSectionResolver` 对缺失能力直接 BLOCK（`core/prompt_manager/assembly_resolver.py:124-141`）；现有运行时投影只产生 `code_context`/`git_workflow` 两个额外能力位（`core/prompt_manager/provider_adapters.py:202-221`，packet 为 None 时也只回这对默认值 `:211-212`）。
- 若新增 `intent_alignment` 能力位：必须同时扩展 `runtime_goal_capabilities` 投影、runtime goal packet 字段与 turn 接线（`agent.py:2706-2711` 的 `_runtime_goal_prompt_capabilities`），且 packet 缺席路径下新位永远缺席 → 章节在无 packet 的会话被静默 BLOCK，出现「接线完备才可见」的隐式依赖；legacy 路径（`assembly_context is None`，`builder.py:191`）根本不执行能力裁决，两路行为分叉。
- 参照系：平级模块 TASK_CHECKLIST 无 capability_requirements（`sections.py:262-268`）——能力位预留给「重且可选」的章节（CODEBASE_MAP `sections.py:301`、GIT_RULES `sections.py:335`）。
- 结论：INTENT_ALIGNMENT 轻量（空态零 token）、应全场景在场、由「内容存在性」自然门控（packet None → compute None → 章节消失），**不新增能力位、不声明 capability_requirements**。

### 4.6 注册集（最终定案）

注册机制的既定事实（注册集决策的全部依据）：

- `build()` 的 `include=None` 走 config `default_components`（Pydantic 默认列表非空，`config/models.py:2075-2078`）；未列章节的正文不渲染，只在「其他可选」索引出现名字（`core/prompt_manager/builder.py:263-305`）。TASK_CHECKLIST 自身就不在默认 build 正文里。
- 唯一能在 operator 显式列表缺项时仍补回的机制是 `_PROTECTED_FLOOR_SECTIONS`：floor 在 include 过滤后运行（`prompt_manager.py:561-577` 的 `_apply_protected_floor`），对 `include` 参数同样生效（测试 `tests/test_prompt_manager.py:564-569`）。
- 渲染位置由 `_PREFERRED_SECTION_ORDER` 先决：`_order_sections`（`prompt_manager.py:579-585`）排序键是 `(order_map 命中索引, priority, name)`，不在 order_map 里的章节排在所有已列章节之后。

最终注册集（七条）：

1. **`create_default_sections` 注册**（floor 前提）：新工厂 `make_intent_alignment_section(ctx)` 放 `sections.py`（与 `make_task_checklist_section` 相邻），在 `create_default_sections`（`sections.py:719`）的内置动态章节段、`make_task_checklist_section()` 调用（`sections.py:766`）之后追加注册。不走 `prompt_manager.py:337-341` 那条显式注册路径（RUNTIME_GOAL/SPEC_DIGEST/MEMORY 在此注册是历史原因拿不到 build_context；`create_default_sections` 已接收 `build_context` 形参 `sections.py:725`，PromptManager 传入的就是 `self._build_context`，`prompt_manager.py:332`）。
2. **进 `_PROTECTED_FLOOR_SECTIONS`**（`prompt_manager.py:195-210` 追加）：**在场唯一保证**——default_components 未列时仍默认在场；operator 显式 `exclude=["INTENT_ALIGNMENT"]` 时让位，这是期望的开关面（floor 语义已被 SESSION_FILE_REFERENCES 测试固化，`tests/test_prompt_manager.py:1070-1078`）。
3. **进 `_PREFERRED_SECTION_ORDER`**（`prompt_manager.py:229-251`）：插在 `"RUNTIME_GOAL"` 与 `"USER_PROFILE"` 之间——决定实际渲染位置（RUNTIME_GOAL 之后、TASK_CHECKLIST 之前）；name 字典序 INTENT_ALIGNMENT < USER_PROFILE 与该位置一致，priority=19 并列由 `(order_map, priority, name)` 排序键消解，无歧义。
4. **不进 `_FALLBACK_DEFAULT_SECTIONS`**（`prompt_manager.py:211-228`）：floor 已覆盖 config 异常场景，fallback 冗余；也因此无需同步 `tests/test_prompt_manager.py:1462-1483` 的 fallback 全量断言。
5. **不改 `config/models.py` 的 `default_components` 默认值**：项目惯例是 default_components 描述「配置口径的默认拼装集」，代码级常驻保障交给 protected floor（RUNTIME_GOAL/USER_PROFILE 等常驻章节均不在默认列表）；不新增 operator 必须理解的新开关，operator 想关掉用显式 exclude。
6. **不设 capability_requirements**（§4.5.4）。
7. **实现期同步既有断言**：grep tests 中对 `_PROTECTED_FLOOR_SECTIONS` 的既有断言并同步更新（追加新成员会影响对 floor 集合内容的精确断言）。

---

## 5. 消息契约与确认链

### 5.1 通道选型

**普通会话（主场景）：卡片走 tool_call turnItem 通道；群聊（后续可选）：走 messagePayload 扩展；两者共用同一 payload schema。**

- 普通会话：意图对齐问题卡由 `intent_alignment_card` 工具以 `tool_call` turnItem（`toolName: "intent_alignment_card"`，input 为 IntentAlignmentCardPayload 的 JSON 字符串）随 assistant turn 持久化。完全复刻 `ConversationTodoChecklist` 已验证链路（`designs/product/conversation.md:53-102`）：journal 唯一事实源 → `turnItems` 投影 → 前端纯派生渲染，不落盘、不回写、不开第二 SSE 通道。
- 群聊（后续可选）：走 `ChatRoomMessage.messagePayload` 新 `kind: "intent_alignment_card"`（结构先例 `chat.ts:1477-1499`）；`messageKind` 分类标签照旧由 `_case_message_metadata` 派生（`chat_room_service.py:4954-4971`），互不占用。
- 否决项：扩展 `user_clarification` 消息族——它是「这条发言是澄清性质」的展示分类且前端零消费（§1.5），扩展是给死通道加重量；新增独立消息 kind——直接触碰普通会话消息联合核心（`chat.ts:782`），需改 admission/journal 回放/分支/导出全链路，红线只豁免「消息契约扩展」而非「核心消息模型变更」，且换不来 turnItem 方案没有的能力。

### 5.2 payload schema

TS 类型草案（前端侧，`web/src/api/types/chat.ts` 追加；`schemaVersion` 对齐 challenge meeting 惯例 `chat.ts:1478`）：

```ts
/** 意图对齐确认卡 payload。普通会话：模型入参经 intent_alignment_card 工具调用的
 *  turnItem.input，handler 组装的完整 payload（含 cardId/revision/最终 questionIds）
 *  经工具 result 侧；前端从 input+output 拼装或直接读 result.payload。
 *  群聊随 messagePayload 传输。 */
export type IntentAlignmentCardPayload = {
  schemaVersion: 1;
  kind: "intent_alignment_card";
  cardId: string;              // 由 intent_alignment_card 工具 handler 在发卡时生成
  revision: number;            // 发卡时的工件版本号（handler 填写）；回执按
                               // cardId+revision+questionId 精确映射回台账
  intentSummary: string;       // 一句话：当前理解的意图（卡片头部）
  artifacts?: Array<{          // 关联工件（只读引用）
    artifactId: string;
    version: number;           // 工件整数版本号；展示格式留实现期（开放问题）
    title: string;
  }>;
  questions: IntentAlignmentQuestion[];
  status: "open" | "superseded"; // 发卡时恒为 "open"；answered/superseded 由前端派生（§5.4）
};

export type IntentAlignmentQuestion = {
  questionId: string;          // 台账稳定 id（§3.9）；同一问题在新卡中重问时沿用
  prompt: string;              // 问题文本
  inputMode: "single_choice" | "multi_choice" | "free_text" | "choice_or_text";
  options?: Array<{            // choice 系必有；free_text 可省
    optionId: string;
    label: string;
    hint?: string;             // 选项补充说明（次级文字）
  }>;
  allowCustomAnswer?: boolean; // choice_or_text 时为 true 的显式化
  required?: boolean;          // 默认 true；false 时可整题跳过
  placeholder?: string;        // 自由输入的水印文案 key 参数
};

export type IntentAlignmentReply = {
  schemaVersion: 1;
  kind: "intent_alignment_reply";
  cardId: string;
  revision: number;            // 回答针对的卡片 revision
  answers: Array<{
    questionId: string;
    selectedOptionIds?: string[];   // single 取 1 个；multi 取 n 个
    freeText?: string;              // 自由输入 / 自定义答案
    skipped?: boolean;              // required=false 且用户跳过
  }>;
  action: "confirm" | "dismiss";    // confirm=提交答案；dismiss=放弃本次对齐
};
```

JSON 示例（卡片，随 tool-call input 传输）：

```json
{
  "schemaVersion": 1,
  "kind": "intent_alignment_card",
  "cardId": "ia_8f3c2a",
  "revision": 3,
  "intentSummary": "为电商项目新增优惠券到期提醒：先做后端任务，再接消息推送",
  "artifacts": [
    { "artifactId": "plan_coupon_reminder", "version": 3, "title": "优惠券提醒任务计划" }
  ],
  "questions": [
    {
      "questionId": "q_scope",
      "prompt": "提醒渠道先做哪一个？",
      "inputMode": "single_choice",
      "options": [
        { "optionId": "o_sms", "label": "短信", "hint": "需供应商配置" },
        { "optionId": "o_push", "label": "App 推送" },
        { "optionId": "o_both", "label": "两个都要" }
      ],
      "required": true
    },
    {
      "questionId": "q_timing",
      "prompt": "提前多久提醒？（可多选）",
      "inputMode": "multi_choice",
      "options": [
        { "optionId": "o_1d", "label": "提前 1 天" },
        { "optionId": "o_3d", "label": "提前 3 天" },
        { "optionId": "o_7d", "label": "提前 7 天" }
      ]
    },
    {
      "questionId": "q_extra",
      "prompt": "还有其他要补充的约束吗？",
      "inputMode": "free_text",
      "required": false,
      "placeholder": "例如：仅提醒未使用券"
    }
  ],
  "status": "open"
}
```

约束：

- payload 尺寸上限建议 8 KB（与 tool-call input 的 journal 落盘成本对齐；问题数 ≤5、选项数 ≤6 由 `intent_alignment_card` 产出端约束，前端只做防御性截断渲染）。questions 数量的工具面硬上限为 5（超限 handler 直接拒绝，防滥用防线）；协议纪律仍为一次成组 ≤3（`maxQuestionsPerTurn`），硬上限只是兜底而非目标。
- `inputMode: "choice_or_text"` 是 `single_choice + allowCustomAnswer` 的语法糖，前端实现统一为「单选 + 其他（输入框）」。
- 卡片不可变：journal append-only；需要改问时发新卡（新 cardId、当时的 revision），旧卡由前端按 §5.4 派生标记。

### 5.3 用户回答路径：口语主通道 + 回执加速通道

**口语回答永远有效，卡片回执是加速通道而非唯一通道**——P0 路径即口语路径，P1 在其上叠加结构化回执。

1. **主通道（人类可读，权威）**：点选/输入后（或用户无视卡片直接打字），前端组装自然语言 `content`（如「意图对齐回答：提醒渠道=App 推送；提前时间=提前 1 天、提前 3 天；补充：仅提醒未使用券」）走既有 `POST /sessions/{session_id}/messages`（`sessions.py:950-956`）提交。回答自然留在会话历史（需求基线），进 transcript 供后续轮次与导出消费。
2. **辅通道（机器可读，P1 契约扩展）**：同一请求的 `references` 挂一条 `kind: "intent_alignment"` 的引用（开放 string kind 的向后兼容扩展，`chat.ts:711`），结构即 `IntentAlignmentReply`。worker 意图对齐 gate 按 `cardId + revision + questionId` 确定性解析回执、把已答问题标 answered 存答案原文（不依赖 LLM 解析文本，也不做语义归并——语义归并仍归主 agent 的 `intent_alignment_merge`）。
3. **UI 回执（呈现层）**：提交成功后前端把卡片渲染为「已回答」态（§5.4 派生），不新增消息、不新增 SSE 事件。

P0 与 P1 的差别只在辅通道与前端卡片呈现：P0 前端把卡片 turnItem 折叠为工具行（未知 toolName 按既有默认路径处理），用户打字回答，agent 下一 turn 语义归并；P1 前端渲染交互卡并随提交挂回执，gate 先确定性落账，agent 再语义归并。两条路径最终都经 `intent_alignment_merge` 收敛到同一工件。

- **放弃（dismiss）路径**：同样走普通用户消息——`content` 为「放弃此次意图对齐」，`references` 挂 `action: "dismiss"` 的 `IntentAlignmentReply`（P1）。放弃也进历史，保证 transcript 完整；agent 判定语义后经 merge 落 rejected 判定（链终止）。
- **修改（修订重发）路径**：由 assistant 侧驱动——agent 判定需要改问时再调 `intent_alignment_card` 发新卡；前端把旧卡标记「已作废（有新版本）」。用户侧「修改已提交的回答」= 直接再发一条新回答消息（P1 引用同一 `cardId`、`revision` 指向所答的卡），历史保留两份，不删不改（append-only）。

**不改 Session/Journal 核心语义的证明**：该路径零改动 admission、journal 事件集、SSE 事件族（`chat.ts:1389-1394`）、投影合并（`projection.py:1422-1424`）；`references` 的 kind 本就是开放枚举，新 kind 是数据契约的向后兼容扩展；卡片本体是普通 `tool_call` turnItem（`chat.ts:647-659`），旧链路按普通工具调用处理。对照组：若把「卡片交互回执」做成独立事件/独立消息类型，必须在 journal 与 SSE 各开一条新通道，直接违反「原生 Session Journal、worker 与 SSE 仍是唯一 Turn、transcript 和实时输出权威」红线。

### 5.4 卡片状态派生与兼容

仿 `deriveLatestTodoChecklist`（快照从 journal 回放的 turnItems 派生，`designs/product/conversation.md:59`；纯派生模型 `:95`）：新增 `conversationIntentAlignmentModel.ts`，`deriveIntentAlignmentCardState(turnItems, subsequentUserMessages)`：

- `answered`：存在 `IntentAlignmentReply` 引用指向该 `cardId`（且 `revision` 匹配）的后续用户消息 → 卡片渲染为已回答态（展示所答内容摘要行）。派生只认回执（确定性）；口语回答后卡片可能停留 open 态，属可接受的呈现滞后——工件与章节状态是权威，前端呈现不是第二事实源，后续发新卡或对齐完成后自然收敛。
- `superseded`：会话时间线上出现后发的新卡 → 旧卡折叠为「已作废，见新版」一行。
- 派生只读不落盘；journal 仍是唯一事实源。

兼容：

- **旧客户端遇新卡**：`tool_call` turnItem 按既有默认路径折叠为工具调用行（toolName 不识别不崩溃——与 todo_write 落地时同构）。
- **旧历史消息在新客户端**：无 `intent_alignment_card` 工具调用的回合不渲染卡片。
- **旧客户端遇新 reference kind**：`kind` 为开放 string（`chat.ts:711`），主通道 `content` 人类可读文本自含全部语义，引用不渲染只是少元数据、不破会话。实现期需验证 composer/@ 引用 type-ahead（`web/src/components/conversation/conversationReferenceTypeahead.ts`）对未知 kind 的过滤行为（开放问题 §7.2-8）。
- **payload 版本演进**：`schemaVersion` 门槛（对齐 `chat.ts:1478` 惯例）；未知版本卡片降级为纯文本问题列表渲染（读 `intentSummary + questions[].prompt`），交互禁用并提示升级。

### 5.5 前端确认卡组件与登记

- **组件定位**：conversation product 组合组件 `ConversationIntentAlignmentCard`，放 `web/src/components/conversation/`（与 `ConversationTodoChecklist.tsx` 同层；不经 `vui/index.ts` 导出 `V*`——先例 `ConversationTodoChecklist` 亦不在 `web/src/components/vui/index.ts` 导出，但按红线登记 designs 专节与 INDEX，`web/src/components/vui/designs/INDEX.md:158`）。交互原子全部组合 VUI primitives：`VSurface/VPanel`（卡壳）、`VButton`（提交/放弃）、`VInput/VTextarea`（自由输入）、`VCheckbox`（多选）、`VChip`（选项/工件徽标）。
- **Props 草案**：

```ts
export type ConversationIntentAlignmentCardProps = {
  payload: IntentAlignmentCardPayload;        // 从 turnItem.input JSON.parse 派生
  cardState: "open" | "answered" | "superseded"; // deriveIntentAlignmentCardState 产物
  replySummary?: string;                      // answered 态的摘要行（派生模型给出）
  lang: "zh" | "en";
  onSubmit: (reply: IntentAlignmentReply, humanReadable: string) => void;
  onDismiss: () => void;                      // 组装 dismiss 回复后走 onSubmit 同一通道
  busy?: boolean;                             // 消息提交中（禁用交互）
};
```

`onSubmit` 的消费者（`ConversationView` 回合渲染区）负责组装 `content`（humanReadable）+ `references`（reply）→ 调既有会话发送 API → 失败走既有错误重试 UI。组件本身不发请求、不接触 API 层。

- **designs 专节**：实现时写入 `designs/product/conversation.md` 新增 `## ConversationIntentAlignmentCard`，并同步 INDEX.md「Product — conversation」表登记（格式对照 `_TEMPLATE.md` 与 ConversationTodoChecklist 专节）。专节要点：功能（结构化问题卡，点选/输入后以普通用户消息回答，已答/作废卡折叠为摘要行）；适用范围（直连会话时间线内含卡片工具调用快照的 assistant 回合；陪伴模式不渲染；无快照不渲染空卡；任务管理用 task_* 工具面）；场景表（open 活跃轮可交互 / answered 折叠摘要只读 / superseded 一行折叠 / 历史 fork 回放按派生态只读）；非职责（不落盘、不回写、不开第二 SSE 通道；不负责发送与重试；不渲染群聊卡片）；视觉与状态（卡壳 VSurface、题号 tabular-nums、选中 `--vui-selection-bg`、answered/superseded 行 `--fg-tertiary` 弱化）；实现落点（组件 + 派生模型源码路径、协议来源=intent_alignment_card 工具调用的 journaled tool-call arguments）。
- **renderer 扩展点**：无新增 renderer 需求——所需交互原子在 `web/src/components/vui/renderers/shadcn/` 已齐备；仅当实现期发现需要新原子（如 radio group）时按红线在 `renderers/shadcn` 扩展并同步 VUI 产品 API 与契约测试，本设计不预设。

### 5.6 i18n key 清单

域 `web/src/i18n/domains/dictionaryChat.ts`（命名对齐 `todoChecklist*` 惯例，`dictionaryChat.ts:181`、`:187`；en 同文件下半区，参照 `:410`、`:416`）：

| key | 用途 | 中文初稿 |
| --- | --- | --- |
| `intentAlignmentTitle` | 卡片标题 | 意图确认 |
| `intentAlignmentQuestionOf` | 题号「第 {n}/{total} 题」 | 第 {n}/{total} 题 |
| `intentAlignmentCustomAnswer` | 「其他」输入占位 | 其他（请输入） |
| `intentAlignmentSubmit` | 提交按钮 | 提交回答 |
| `intentAlignmentDismiss` | 放弃按钮 | 跳过此次确认 |
| `intentAlignmentRequiredHint` | 必答未答提示 | 请完成必答项 |
| `intentAlignmentAnsweredBadge` | 已回答徽标 | 已回答 |
| `intentAlignmentSupersededNote` | 作废提示 | 问题已更新，请查看新版 |
| `intentAlignmentArtifactsLabel` | 工件区标题 | 关联工件 |
| `intentAlignmentReplyPrefix` | 回答消息 content 前缀 | 意图对齐回答 |
| `intentAlignmentDismissContent` | 放弃消息 content | 放弃此次意图对齐 |

共 11 key，zh/en 双语。`dictionary.ts` 为共享热文件，实现期串行合入。

### 5.7 与群聊既有 clarify 投影的关系：共存（不统一）

- **保留** `messageKind: "user_clarification"` 原语义：群聊 case 状态的展示分类（`chat_room_service.py:4954-4971`），继续服务折叠/受众判断；不让它承载问题清单。
- **群聊确需确认卡时**（非本期必做）：走 `ChatRoomMessage.messagePayload` 新 `kind: "intent_alignment_card"`（结构先例 `chat.ts:1477-1499`），payload 复用 §5.2 同一 schema，前端复用 `ConversationIntentAlignmentCard` 渲染核心（以 `presentation` prop 区分直连/群聊宿主，同 ConversationTodoChecklist 的 `inline/panel` 先例）。群聊回答路径随房间消息发送机制另行设计（开放问题 §7.2-11）。
- **不统一的理由**：两个面的传输权威不同（直连 = Session journal/turnItems；群聊 = room timeline 投影，`chat.ts:1604-1615`），强行统一会要求其中一面开第二通道。统一的是 payload schema 与卡片组件，不是传输通道。

---

## 6. 红线合规声明

### 6.1 三核心身份层不动

本模块不读不写三核心规格（`core/prompt_manager/core_prompt_sources.py:30-49` 的 COMMON/SOUL/AGENTS，加载失败即抛 `CorePromptSourceError`，`core_prompt_sources.py:53-58`，fail-closed）。INTENT_ALIGNMENT 是新增动态章节，不触碰 core prompt 装配优先级与身份层内容。

### 6.2 Session / Journal / SSE 零行为改动

证据要点（逐条可验证）：

1. 用户回答走既有 `POST /sessions/{session_id}/messages`（`sessions.py:950-956`）；零新消息类型、零新 SSE 事件（`SessionStreamEvent` 事件族六种集合不变，`chat.ts:1389-1394` 对照断言）。
2. 卡片本体是普通 `tool_call` turnItem（`chat.ts:647-659`）；journal 唯一事实源（`assistant_item_committed`，`core/chat/turn_journal.py:31`）；投影复用既有合并逻辑（`core/web/services/session/projection.py:1422-1424`），零新通道。
3. `references` 的 `kind` 本是开放 string（`chat.ts:711`），`kind: "intent_alignment"` 是数据契约的向后兼容扩展；主通道 `content` 人类可读文本自含全部语义。
4. worker 意图对齐 gate 位于 `worker.py:1174` 执行期（continuation loop 之前），不改 submit 层（`submit.py:1-6` claim scope：validate/open turn/journal 标记/首快照/调度）、不动 turn 准入（`admission.py:63`）与 Journal 写入时序；gate fail-open、不短路 turn、不代替模型产出 assistant 内容——澄清提问是主 agent 的正常 assistant 正文，turn 收束走既有路径。
5. 需求工件落 workspace memory 目录（与 tasks.json 同域），不进 Session/Journal transcript；前端卡片纯派生渲染，不落盘、不回写。
6. 回归要求：普通会话 admission/journal/SSE 代码路径 diff 为零（除 `chat.ts` 类型契约追加与 turnItem 消费只读渲染外，无 `core/chat`、`core/web/services/session` 行为改动）；现有 session/prompt_manager 测试全绿。

### 6.3 VUI 两机器门

| 机器门 | 检查内容 | 本设计过门方式 |
| --- | --- | --- |
| `web/src/components/vui/vuiShadcnRouteContract.test.ts` | routes 下文件禁止 import `@heroui/react`、`renderers/shadcn/*`、`components/ui/*` | 卡片组件放 `components/conversation/`，只 import `@/components/vui` 的 `V*` 产品 API；routes/ConversationView 只消费卡片组件，不触 renderer |
| `web/src/components/vui/vuiComponentDesignContract.test.ts` | `vui/index.ts` 导出的每个 `V*` 必须在 `designs/INDEX.md` 有目录行且指向文件存在 `## Name` 标题 | 本组件不进 `vui/index.ts` 导出（同 ConversationTodoChecklist 先例，机器门不强制）；但按项目红线仍登记 designs 专节 + INDEX 行（§5.5）。若实现期决定以 `V*` 命名导出，该门自动生效，登记内容已备 |

### 6.4 与个人助理划界

`docs/plans/2026-10-18-platform-a2a-evolution-harness.md:36` 规定个人助理「维护用户意图与授权引用」是跨任务引用职责；本模块是任务级已确认需求工件的权威。个人助理只能按 `artifactId + version + contentHash` 三元组经 `get_version` 只读引用（§3.8），无任何写接口——引用可对账（hash）但不可被助理改写。

---

## 7. 开放问题

### 7.1 已定案关闭（含结论去向）

| 原问题 | 结论（落位章节） |
| --- | --- |
| priority 19 与 USER_PROFILE 并列的处理、`_PREFERRED_SECTION_ORDER` 是否需同步插入 | 注册集第 3 条：插在 RUNTIME_GOAL 与 USER_PROFILE 之间，排序键 `(order_map, priority, name)` 消解并列（§4.6） |
| operator config 的 `default_components` 同步问题 | 注册集第 5 条：不改默认值；floor 保障在场；显式 exclude 是唯一开关面——同步问题不存在（§4.6） |
| cardId 格式与确认卡的 turn 绑定细节 | 标识映射：handler 发卡时生成 cardId；revision=发卡时工件版本号；回执三元组映射（§3.9） |
| 主 agent 自判产出的回收契约 | `intent_alignment_card` / `intent_alignment_merge` 工具面即回收通道（§3.5.2、§4.4） |
| 用户直接打字回答（不经卡片）的关卡语义 | 口语回答永远有效（P0 路径即口语路径）；卡片回执是加速通道非唯一通道（§5.3） |
| 工件与会话的绑定基数 | 每会话单活跃工件 + 版本链历史（§3.3） |

### 7.2 保留（14 项）

1. **跨会话需求复用**：同一需求多会话续谈，v1 按「每会话独立工件、新会话重开新工件」处理；是否需要「需求库」升级，留待首版使用反馈。
2. **组聊/临时组队的工件 key**：群聊侧现有状态以 roomId 为键（`team_case_orchestrator.py:63`），本契约以 sessionId 为键；组队场景建议「房间主会话 sessionId 持有工件、`origin.roomId` 登记房间」，最终落点由团队链路接线（P2）与群聊回答路径设计对齐后定。
3. **consumed 后需求变更的粒度**：v1 允许 consumed→superseded（链内新 draft，taskId 审计保留）；若实践证明消费方需要显式失效信号，再补订阅/失效接口。
4. **rejected 后同会话重启**：用户拒绝当前对齐后同会话又提出新需求——v1 按「同一 sessionId 允许开新工件链」处理（store 以 sessionId→活跃工件单例 + 历史链列表，`origin.createdAt` 区分）。
5. **规则预筛的信号清单边界**：分叉信号（多义指代/缺失量纲/互斥约束）初版从简；误报率的观测与迭代机制（哪些指标进 runtime scene 事件）待定。
6. **config 校验器**：是否仿 `config/models.py:2567-2580` 为 INTENT_ALIGNMENT 增加 default_components 缺失告警（倾向不加：floor 已保障在场，告警只会在 operator 故意 exclude 时制造噪音）。
7. **章节空态策略**：aligned 且无 openQuestions 时渲染 None（本文推荐，零 token）还是一行「意图已对齐」锚点？需实现期用真实会话样本验证模型是否会在无章节痕迹时遗忘机制。
8. **composer 引用 type-ahead 对未知 kind 的行为**：`conversationReferenceTypeahead.ts` 的候选过滤是否会把 `kind: "intent_alignment"` 引用暴露进 @ 候选（不应暴露——它是回执不是用户可主动添加的引用）；实现期验证并在过滤白名单外处理。
9. **动作集扩展**：`action` 枚举是否需要 confirm/dismiss 以外的显式动作（如「让我直接改工件」跳转）；本期按两动作收口，扩展留枚举位。
10. **群聊卡片的回答路径**：房间消息与直连会话传输面不同，实现前需补群聊房间消息提交链路的设计核对（§5.7）。
11. **工件版本显示格式**：`artifacts[].version` 与 `revision` 已定为整数版本号，但卡片展示格式（裸数字 / `v3` 标签 / 是否带 contentHash 短缀）留前端实现期定稿。
12. **P0 澄清 turn 的 outcome 语义**：澄清 turn 是否需要独立的 outcome 分类标记（供统计/前端区分），还是完全靠工具调用 payload 区分；P0 前端折叠工具行、P1 靠 payload 渲染已够用，标记位是否另设留实现期评估。
13. **gate 的延迟与成本预算**：规则预筛零 LLM 调用，但 gate 的工件加载/文件锁开销与章节 token 常驻成本需要延迟上限约束与观测指标，进 P0 验收细化。
14. **团队前置的澄清载体**：P2 组队前澄清发生在哪个交互面（组队对话框 vs 发起会话）依赖前端输入；本设计只锁定「confirmed 工件 → team purpose/首任务」的映射契约。

---

## 8. 分期与实现任务拆解

### 8.1 分期

#### P0 — 纯后端全量（工件 + 工具族 + 章节 + gate；前端零改动）

范围：`IntentAlignmentStore`（工件存储与服务核心）、规则预筛与 packet 维护、`intent_alignment_card` / `intent_alignment_merge` 工具族、INTENT_ALIGNMENT 章节注册、worker 意图对齐 gate（确定性维护）。现有前端把卡片 turnItem 折叠为工具行；agent 的正文以文本提出同样的问题；用户打字回答；下一 turn 由 agent 调 `intent_alignment_merge` 语义归并。

不做：任何 `web/` 前端改动；团队链路；群聊链路。

验收标准：

1. 清晰路径零行为差异：现有 session/prompt_manager 测试全绿；新增回归断言「无工件/无信号时 gate 不改变 prompt 构造输入与 turn 输出结构」。
2. 歧义轮全链路：主 agent 经章节协议自判 → `intent_alignment_merge` 落四要素初稿 → `intent_alignment_card` 发卡（tool-call turnItem 落 journal、台账登记、工件 pending_confirmation）；澄清问题以普通 assistant 正文提出并正常收束（无新 turn 类型、无 Journal 准入变更、无 gate 短路分支）。
3. 打字回答归并：下一 turn agent 调 `intent_alignment_merge` 产生新版本；章节渲染反映已答（已答问题不再出现在待澄清区）。
4. confirmed 工件持久化：确认判定落盘；`take_confirmed` 可消费；后续 turn 的 build 产物包含意图对齐章节（对照 `tests/test_prompt_manager.py:382` 模式的包含性断言）。
5. fail-open：gate 与工具 handler 异常时直通原链路（专项测试）。

#### P1 — 确认卡前端 + reference 回执

范围：`ConversationIntentAlignmentCard` 组件与派生模型、`IntentAlignmentCardPayload` / `IntentAlignmentReply` 类型契约、designs 专节与 INDEX 登记、i18n key、`kind: "intent_alignment"` 回执；gate 增加确定性回执解析（标 answered 存原文），语义归并仍归 agent。

验收标准：

1. `vuiShadcnRouteContract.test.ts`、`vuiComponentDesignContract.test.ts` 通过；`npx tsc -b` 通过。
2. 确认卡交互闭环：三 inputMode 交互、必答校验、提交（content + references 组装）、放弃、修订重发（旧卡作废派生）；后端 P0 状态机不变，前端只做投影视图。
3. 回执链路：POST `/sessions/{id}/messages` 携带 `kind: "intent_alignment"` references 的持久化与回放一致（session detail / journal 重放后 transcript 一致）；gate 确定性落账、无结构化变更。
4. 双路径回归：口语回答（打字）与卡片回执都能推进工件；口语路径（P0 回归）不劣化。
5. 红线证据：§6.2 证据要点逐条成立（SSE 事件族对照断言、普通会话核心路径 diff 为零）。

#### P2 — 团队前置改道 + 群聊收编（可选）

范围与设计：

- **组队前置**：组队入口先过意图对齐——歧义则在发起方上下文（组队发起所在的 1:1 会话或组队对话框，载体见开放问题 §7.2-14）完成澄清对话产出 confirmed 工件；`team_purpose` ← 工件结构化渲染（goal + 边界 + 关键 constraints 紧凑文本）、首个 dev task 的 `description` ← 工件渲染 + 工件 id 引用、`subject` ← goal 单行摘要截断；映射逻辑收进 `ephemeral_team_service.py`（或其新前置函数），`routes/teams.py:170` 改传已确认工件引用；fail-open（判定服务不可用/超时 → 回退 topic 原文直通组队，组队永不被阻塞）；confirmed 工件经规划师系统提示词或任务 description 注入（章节机制的团队变体）。
- **四角色流水线影响**：不受影响——`_dev_team_template` 的 roles/chatRoom/canvas 定义（`team_template_service.py:344-373`）与 purpose 内容正交；planned 模式轮次推进与 `dev_task_board` 生命周期（`ephemeral_team_service.py:1-7` 模块 docstring）不因输入从 topic 原文变为工件渲染而改变；唯一行为差异是规划师拿到的首任务描述更结构化。
- **群聊 clarify 状态机**：P0/P1 完全不动 `team_case_orchestrator.py`（它是群聊轮次编排器：说话人收窄 `chat_room_service.py:1950`、演示域话术 `team_case_orchestrator.py:138-169`、`_infer_intent` `:172-184`、`_missing_facts_for_intent` `:187-197`、`_next_action` `:219-231`——与任务级需求工件权威不是同一抽象层，强收编会让通用底座背上演示域特化逻辑，且替换需大量演示域回归）。P2 列为可选收编：保留 case 状态机与说话人编排，只把信息充分性判定换成意图对齐规则预筛的群聊适配；前置条件是演示域回归护栏先行。

验收标准：

1. 组队前澄清产出 confirmed 工件，team_purpose 与首任务 description 为工件渲染而非 topic 原文（断言 `ephemeral_team_service` 输入映射）。
2. 判定服务不可用时组队回退现状路径（fail-open 专项测试）。
3. （若做收编）医疗问诊、企业 demo 两演示域的 case_state 裁决快照测试通过后才允许切换判定来源。

分期理由：BRT 覆盖面最大且 P0 纯后端即可用文本问答完整交付（口语路径即全功能路径），先闭合；确认卡前端依赖消息契约冻结与 VUI 红线流程，第二；团队前置依赖底座在 1:1 会话稳定，群聊收编带演示域回归风险，最后。

### 8.2 实现任务拆解

| 任务 | 文件面（owning surface） | 验收要点 | 定级 | 依赖 |
| --- | --- | --- | --- | --- |
| T1 工件存储与服务核心 | 新文件 `core/orchestration/intent_alignment.py`（store/状态机/存储并发/快照投影）；新测试 `tests/test_intent_alignment_artifact.py` | §9 表 A 十用例；fixture monkeypatch 路径函数隔离 tmp_path（模式 `tests/test_task_planner.py:15-22`）+ 单例复位；owner 表登记归 T9 | STANDARD_TASK | 无 |
| T2 规则预筛、回执解析与 packet 维护 | `core/orchestration/intent_alignment.py` 判定段（纯函数：clear 快路径信号、分叉信号清单、`IntentAlignmentReply` 回执解析、packet 组装）；测试 | §9 表 B 前置项：三类输入（clear 信号/分叉信号命中/回执样本）判定解析正确；回执落账走「无 merge 指令」路径（标 answered 存原文、无结构化变更）；保守不误标（规则不确定时保留 openQuestions） | STANDARD_TASK | T1 |
| T3 意图对齐章节注册 | `core/prompt_manager/sections.py`（工厂 + `create_default_sections` 注册）、`core/prompt_manager/prompt_manager.py`（`_PROTECTED_FLOOR_SECTIONS`、`_PREFERRED_SECTION_ORDER`、`set/get_intent_alignment_packet`、`BuildContext` 配合）、`core/prompt_manager/types.py`（ctx 字段）、`core/web/services/prompt_template_service.py:76-77`（散规则指向/让位）；`tests/test_prompt_manager.py` 增补 | 注册集七条落位（§4.6：floor 进、fallback 不进、默认列表不改、order_map 插 RUNTIME_GOAL 与 USER_PROFILE 之间、不设能力位）；grep 并同步 `_PROTECTED_FLOOR_SECTIONS` 既有断言；空态零 token；排序落位断言 | STANDARD_TASK | T1（快照读取 API） |
| T4 意图对齐工具族 | agent 工具注册面（`todo_write` 同族 journaled tool-call 注册点）+ `core/orchestration/intent_alignment.py` 工具 handler 段；测试 | `intent_alignment_card`：cardId 生成、revision=发卡时工件版本、turnItem 落 journal、`record_question_asked` ×N + `request_confirmation` 转调、四要素前置校验；`intent_alignment_merge`：`record_answer`/`record_structured`/`submit_confirmation_decision` 转调、写后 packet 刷新；正文与卡片一致性由章节协议约束（E2E 断言归 T5） | STANDARD_TASK | T1 |
| T5 BRT worker gate | `core/web/services/session/worker.py`（`_run_session_turn_impl` 内 gate 段，唯一写入点）；session 回归测试 | §8.1 P0 验收 1-5 全部；gate 只做确定性维护（P0：加载/预筛信号/packet 组装注入；P1 预留 T2 回执解析调用点），无短路分支、无 assistant 内容代笔；fail-open 专项；普通会话 Session/Journal 核心语义零差异证据（现有 session 测试全绿 + gate 段最小化 diff 审查） | HIGH_RISK（触及普通 Session turn 执行路径，须零差异证据） | T1/T2/T3/T4 |
| T6 确认卡前端（P1） | `web/src/components/conversation/ConversationIntentAlignmentCard.tsx`、`web/src/components/conversation/conversationIntentAlignmentModel.ts`、`web/src/api/types/chat.ts`（类型契约追加）、`web/src/components/vui/designs/product/conversation.md` + `INDEX.md`（登记）、`web/src/i18n/domains/dictionaryChat.ts`；组件/模型/契约测试 | §8.1 P1 验收 1-5；两机器门 + `tsc -b`；派生模型（解析/降级/answered/superseded）、发送组装（reply schema、dismiss）；`chat.ts` 与 `dictionaryChat.ts` 为共享热文件，串行合入 | STANDARD_TASK | T4/T5 + 消息契约冻结（本设计 §5.2 即契约） |
| T7 团队前置改道（P2） | `core/web/routes/teams.py:170` 附近、`core/web/services/team/ephemeral_team_service.py`（输入映射）；测试 | §8.1 P2 验收 1-2；fail-open 回退 | STANDARD_TASK | T1/T2 |
| T8 群聊收编（可选，P2） | `core/web/services/team_case_orchestrator.py`（`_missing_facts` 判定委托）、`core/web/services/chat_room_service.py` 相关消费行 | §8.1 P2 验收 3；演示域回归护栏先行 | STANDARD_TASK | T2（默认延后） |
| T9 文档路由 | `core/prompt_manager/README.md:49`（sections.py owner 行补新章节）、`core/orchestration/README.md`（owner 表补 `intent_alignment.py` 行）、`docs/guides/ownership.md:58`（Prompt owner 段核对补行） | 三处文档与代码一致 | FAST_PATCH | 随 T3/T5 合入前收口 |

### 8.3 写域互不重叠核对

- `core/orchestration/intent_alignment.py`：T1 创建（store 段）→ T2 增判定段 → T4 增工具 handler 段，串行推进（依赖链 T1→T2/T4），不并行派遣，无同文件并发写。
- T3 独占 `core/prompt_manager/`（sections.py、prompt_manager.py、types.py）与 `prompt_template_service.py`；T5 独占 `worker.py` gate 段；无重叠。
- T6 独占 `web/src/components/conversation/` 新组件与派生模型；`chat.ts`、`dictionaryChat.ts` 为共享热文件，T6 内部串行、不合入其他任务的并行改动。
- T7 独占 `teams.py` + `ephemeral_team_service.py`；T8 独占 `team_case_orchestrator.py` + `chat_room_service.py` 相关行；T9 独占三处文档。

---

## 9. 测试策略总表

### 表 A — 服务核心（`tests/test_intent_alignment_artifact.py`；fixture 隔离模式 `tests/test_task_planner.py:15-22`）

| # | 用例（名称即断言意图） |
| --- | --- |
| A1 | `test_structured_draft_persists_and_reloads` —— v1 draft 落盘，新 store 实例重载可见（对齐 `tests/test_task_planner.py:25`） |
| A2 | `test_answer_creates_new_version_and_freezes_old` —— `record_answer(q2)` 产生 v2；v1 状态/内容/contentHash 不变，v2.changes 引用 q2 |
| A3 | `test_same_answer_replay_is_idempotent` —— 相同 questionId+answer+merge 重放不产生新版本（对齐 `workflow_artifact_store.py:243-250` 幂等语义） |
| A4 | `test_invalid_transitions_rejected` —— confirmed→draft 直接连边、对 superseded 版本 record_answer 均拒绝 |
| A5 | `test_confirmation_decision_paths` —— approved→confirmed；revision_requested→旧版本 superseded + 新 draft 继承已答内容；rejected→superseded 无后继 |
| A6 | `test_take_confirmed_first_consumer_transitions_then_registrations_only` —— 首次 take 使 confirmed→consumed，第二个 consumer 只追加 consumedBy |
| A7 | `test_concurrent_append_conflict_detected` —— 两个 store 实例持相同 baseVersion 追加，后写者收版本冲突，文件保持先写者完整版本链 |
| A8 | `test_corrupt_file_quarantined_not_rebuilt` —— 损坏文件改名隔离、store 返回空库，原内容不被覆盖 |
| A9 | `test_snapshot_is_projection_not_second_storage` —— get_current 返回深拷贝，改投影不影响落盘数据（对齐 `tests/test_task_planner.py:74`） |
| A10 | `test_open_questions_accumulate_across_rounds` —— 问 q1、答 q1、问 q2 后 open_questions 只含 q2；q1 答案已体现在当前版本四要素（反 caseState 断言，对照 `team_case_orchestrator.py:68`） |

### 表 B — 判定辅助、章节与组装（T2/T3；对照 `tests/test_prompt_manager.py` 与 `tests/test_prompt_assembly_contract.py` 断言模式）

| # | 用例 |
| --- | --- |
| B1 | 注册与空态（仿 `test_spec_digest_section_compute`，`tests/test_prompt_manager.py:1087-1101`）：`pm._sections.get("INTENT_ALIGNMENT")` 非空；packet 未注入时 compute 返回 None；注入 clarifying packet 后输出含「## 意图对齐」「待澄清问题」 |
| B2 | 排序位置（仿 `test_priority_order_in_output`，`tests/test_prompt_manager.py:1211-1224`）：`build(include=["RUNTIME_GOAL","INTENT_ALIGNMENT","USER_PROFILE","TASK_CHECKLIST"])`，断言「## 意图对齐」位于 RUNTIME_GOAL 内容之后、任务清单内容之前 |
| B3 | protected floor 存活（仿 `test_session_file_references_survives_default_include_via_protected_floor`，`tests/test_prompt_manager.py:1070-1078`）：默认 `build()` 注入 packet 后含「## 意图对齐」；`exclude=["INTENT_ALIGNMENT"]` 后不含 |
| B4 | 逐轮刷新（仿 `test_task_checklist_refreshes_between_builds`，`tests/test_prompt_manager.py:1125-1134`）：set packet v1 → build → set packet v2（含新已答问题）→ build，两次文本反映各自版本，旧问题不再出现在待澄清区 |
| B5 | 动态分区（仿 `test_config_awareness_priority_order` 的 static/dynamic 断言，`tests/test_prompt_manager.py:1233-1235`）：「## 意图对齐」落在 `split_sys_prompt_prefix` 的 dynamic_parts |
| B6 | floor 既有断言同步（注册集第 7 条）：grep tests 中 `_PROTECTED_FLOOR_SECTIONS` 相关精确断言并随注册同步更新；fallback 列表断言（`tests/test_prompt_manager.py:1462-1483`）不需改动（未进 fallback） |
| B7 | 组装契约与脱敏（仿 `tests/test_prompt_assembly_contract.py:141-162`）：非空 packet 构建后 manifest segments 含 key=INTENT_ALIGNMENT 且 `to_manifest_entry` 不泄漏问题正文/用户引用文本（沿用 `_assert_manifest_has_no_prompt_body`，`tests/test_prompt_assembly_contract.py:20-27`）；decision 不为 BLOCKED（对照 `assembly_resolver.py:124-141`） |
| B8 | 协议语义回归（新增）：构造含已 settle 问题的 packet，断言章节文本含「禁止重复追问」与已答结论，且该问题不在待澄清区 |
| B9 | 规则预筛与回执解析（T2）：clear 快路径信号识别、分叉信号命中交自判、`IntentAlignmentReply` 样本按三元组映射、回执落账无结构化变更、规则不确定时保守保留 |

### 表 C — 消息契约与前端（T6；三组）

| # | 组 | 用例 |
| --- | --- | --- |
| C1 | 机器门对照 | `vuiShadcnRouteContract.test.ts` 与 `vuiComponentDesignContract.test.ts` 通过（过门方式见 §6.3 表） |
| C2 | 单元/组件 | 派生模型：payload 解析（合法/截断/未知 schemaVersion 降级）、answered/superseded 派生（reference 匹配 cardId+revision、后发卡判断）、口语消息不误判；组件：三 inputMode 交互、必答校验、busy 禁用、answered/superseded 折叠渲染，zh/en 快照；发送组装：`onSubmit` 产出的 content/references 符合 reply schema，dismiss 路径同测 |
| C3 | 链路/契约 | 后端：POST `/sessions/{id}/messages` 携带 `kind: "intent_alignment"` references 的持久化与回放（session detail / journal 重放后 transcript 一致）；兼容回归：无卡片 turn 不渲染、未知 toolName 折叠为工具行、`SessionStreamEvent` 事件族六种集合不变（`chat.ts:1389-1394` 对照断言）；红线证据：普通会话 admission/journal/SSE 代码路径 diff 为零 |

### 表 D — worker gate 与链路（T5；对应 §8.1 P0/P1 验收）

| # | 用例 |
| --- | --- |
| D1 | 清晰路径零行为差异：无工件/无信号时 gate 不改变 prompt 构造输入与 turn 输出结构 |
| D2 | fail-open 专项：gate/工具 handler 异常直通原链路，消息接收不受影响 |
| D3 | 发卡链路：agent 提问 turn 的 tool-call turnItem 落 journal、台账登记、工件 pending_confirmation；澄清以普通 assistant 正文收束（无新 turn 类型/Journal 准入变更） |
| D4 | 回执落账（P1）：gate 确定性标 answered 存原文、无结构化变更；agent 后续 merge 产生新版本 |
| D5 | 双路径回归：打字回答与卡片回执均推进工件至 confirmed；口语路径（P0 回归）不劣化 |

---

## 附录 A：与 problem_understanding 契约的差异表

基准：`validate_problem_understanding` 的字段集（`problem_understanding_artifact_writer.py:24-26`：scope/subquestions/assumptions/known_unknowns/human_gate）与写入契约（`:338-400`）。

| 维度 | problem_understanding | intent_alignment（本模块） | 继承/新增及理由 |
| --- | --- | --- | --- |
| 身份域 | teamId/workflowRunId/nodeRunId/questionId 绑定工作流 Ledger（`:174-296` fail-closed 对账） | sessionId/turnId/taskId/roomId（会话与任务域） | **新增**：1:1 会话与临时组队没有 workflow run 身份；会话-任务关联是本域的天然主键 |
| scope（单字符串，`:80`） | 一段范围描述 | 拆为 `goal` + `boundaries` | **拆分新增**：目标要喂 RUNTIME_GOAL 的 goal 字段（`runtime_goal.py:229`），边界要参与能力与范围讨论；单字符串无法分向投递 |
| subquestions（静态唯一字符串数组，`:82`） | 待研究子问题清单 | `openQuestions`：带 id/status(asked/answered/withdrawn)/answer/appliesTo 的问题台账 | **继承并扩展**：多轮澄清需要问-答生命周期与合并去向，静态数组表达不了「问过什么、答了什么」 |
| assumptions（`:83`） | 字符串数组 | 对象数组：id/text/source(user_statement/inferred)/status(open/validated/invalidated) | **继承并扩展**：假设需要被后续回答证实或推翻的追踪，纯文本无法表达失效 |
| known_unknowns（`:83`） | 已知未知清单 | 并入 `openQuestions`（未提问的缺口以 status=asked 之前的状态存在于判定视野，落盘时机=提问时） | **合并**：known_unknowns 与 subquestions 在对话场景下是同一对象的两端（还没问的问题）；拆两个字段会造成双账本 |
| human_gate（`:59-78`，required 必须为 true，`:66-67`） | 决策 pending/approved/revision_requested/rejected | `confirmation`：cardId + decision（同词表）+ issuedAtTurn/decidedAtTurn + confirmedDigest | **继承决策词表**（`:21-23`），**新增**卡与 turn 绑定、确认摘要 hash——「用户在对话内确认」需要可对账的证据 |
| （无） | —— | `constraints`、`acceptance` | **新增**：任务规划需要约束（技术/资源/时间边界）与可验证验收标准作为 `task_create` 输入与完成判据（`task_planner.py:699` 的 goal 只有一根字符串，验收必须在工件层结构化） |
| （无） | —— | 版本链 + supersede/supersededBy + changes | **新增**：problem_understanding 按 attempt 追加独立不可变工件（`:347`），没有「同一工件连续修订」语义；澄清对话必须支持链内演进 |
| 不可变性 | 工件级：append-only，精确重放幂等（`workflow_artifact_store.py:243-252`） | 版本级：append-only 版本链 + 同幂等/冲突语义 | **继承机制**（contentHash 幂等、冲突显式抛错），粒度从工件细化到版本 |
| 输入冻结 | inputSnapshotHash 对账工作流输入快照（`:247-268`） | 不采用 Ledger 对账，以 `confirmedDigest` 绑定用户确认时看到的内容 | **差异化**：研究运行时必须对冻结的 workflow 输入负责；对话场景的权威是「用户确认过什么」，摘要对账即够 |
