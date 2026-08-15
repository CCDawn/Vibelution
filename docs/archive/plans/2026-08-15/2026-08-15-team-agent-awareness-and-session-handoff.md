# 团队 Agent 感知、点对点消息与会话交接

> **状态**：已完成并归档。历史实施计划，**不覆盖** `AGENTS.md`、`docs/standards/`、[ADR 0002](../../../adr/0002-agent-collaboration-session-addressing.md)。
> **日期**：2026-08-15
> **分级**：`STANDARD_TASK`
> **复用结论**：`REFERENCE_ONLY`（不引入 A2A / Matrix / CrewAI / AG2）
> **工作区**：`.worktrees/team-agent-awareness-plan` · 分支 `codex/team-agent-awareness-plan`
> **Claim**：`claim-7592aeb8ab32`（方案）· `claim-ce49b75d4d56` / `claim-f437e4598a33`（实现）

按 [ADR 0005](../../../adr/0005-docs-authority-and-archive-policy.md) 归档，不得升格为日常规范。

---

## 1. 已锁定结果

用户确认「按推荐」。可观察结果：

1. 同队 Agent 在 Runtime Context 里看到**本队精简花名册**（存在、身份、职责、可寻址会话）。
2. 用现有 `agent_message_tool` 给指定队友发**点对点**消息；必须带 `target_session`。
3. 该消息在**团队页「成员通信」**可见；正文只在目标会话。
4. 第一期**不做** Agent 全员广播。用户广播与关联群聊保持原样。
5. 有团队绑定的会话，在会话身份上显示 **「团队」标签**；悬停/焦点用 tooltip 显示绑定团队名称；**点击跳到该团队工作台**（与现有「打开团队」同一路由）。

### 非目标

- 不引入 A2A SDK、Matrix、CrewAI、AG2、OpenAgents。
- 不改 ADR 0002：不按 `agentId` 隐式落到默认直聊；inbox 不做第二正文。
- 不重做群聊 round / 团队任务。
- 不把点对点混进「团队广播」列表。
- 不把个人 Agent 入队后改成 `team_private`（会从聊天列表消失）。
- 不为每个成员再造第二条「团队专用会话」。
- 不新开第二套 chip / 按钮设计；团队标签视觉仍是短标，跳转复用已有 `teamWorkspaceRoute`。

### 完成证据（功能）

- Prompt 含本队花名册，不含外队；无队则为 `TeamRoster: none`。
- 同队 + 有效 `target_session` → 投递成功；外队 / 无队 → 仍 `cross_agent_policy_required`。
- 无 `target_session` → 仍 `target_session_required`。
- 团队页能看到发件人 / 收件人 / 摘要 / 时间，并跳到目标会话。
- 广播列表不混入点对点。
- 有绑定的会话在页签和会话列表行显示「团队」标签；悬停可见团队名；点击进入 `teamWorkspaceRoute(teamId)`；无绑定不显示。

---

## 2. 外部调研（只参考）

| 来源 | 借鉴 | 不引入 |
| --- | --- | --- |
| [A2A Agent Card](https://a2a-protocol.org/latest/specification/) | 公开卡 vs 扩展卡；`name` / `description` / `skills[]` / 已发布地址 | JSON-RPC 服务端 |
| [AG2 send_introductions](https://docs.ag2.ai/latest/docs/user-guide/advanced-concepts/groupchat/groupchat/) | 开场注入名字+描述；公开描述 ≠ 完整 system prompt | GroupChat 轮转引擎 |
| [CrewAI role/goal/backstory](https://docs.crewai.com/en/concepts/agents) | 本队边界 + 职能/目标/一句话背景 | Crew 运行时 |
| [AgentTeams](https://github.com/agentscope-ai/AgentTeams) | 人能看见同一条协作时间线 | Matrix / K8s |
| [OpenAgents](https://github.com/openagents-org/openagents) | 频道给人看 | 独立网络 SDK |
| IBM ACP | — | 仓库已 archive |

行业里两套模型，本项目已经分层，不要选错层：

| 开源常见做法 | 本项目已有面 | 本功能用哪面 |
| --- | --- | --- |
| 共享房间就是对话 | 关联群聊 + 团队任务 | 全员讨论 |
| 发布身份卡 + 发到明确地址 | 成员字段 + `directSessionId` + `agent_message_tool` | **点对点** |
| 人看总时间线 | 团队页目前只有用户广播 | **新增成员通信投影** |

---

## 3. 现状：三条通信面，一种成员会话

团队里的 Agent **没有**单独的「团队会话类型」要新发明。现有契约已经把「成员」解析成「该 Agent 的唯一直聊会话」。

### 3.1 一个 Agent 只有一个 `directSessionId`

- Agent 记录持有唯一 `directSessionId`。另一个 active Agent 占用同一会话会在写入前拒绝（`ops_residual._ensure_active_direct_session_available`）。
- 团队侧已有 `_active_member_session_ids`：遍历 active 成员，收集其 `directSessionId`。
- 关联群聊同步用这批 session id 当 `participant_session_ids`（`chat_room_links._ensure_team_chat_room_link`）。

### 3.2 直聊会话的两种可见性

| `conversationIndexKind` | 可见性 | 谁在用 | 聊天列表 |
| --- | --- | --- | --- |
| `personal_agent` | user visible | 普通/自定义团队拉进来的个人 Agent | 默认可见 |
| `team_agent` | `team_private` | 系统队（挑战杯、知识扩展等）ensure 出来的角色 Agent | **默认隐藏** |

分类逻辑在 `agent_conversation_index_classification`：`team_agent` 必须带 team 标记（`metadata.teamId` / 系统队 key / 系统 `createdBy`）。缺标记会变成 invalid。

系统队在缺会话时会 `ensure_agent_direct_session(..., conversation_index_kind=TEAM_AGENT)` 或 `create_chat_session`。自定义团队 **入队时不 ensure 会话**。

### 3.3 三条通信面（不要合并）

```text
用户广播     POST /teams/{id}/messages
             → Project Agent Bus（source=team）
             → 扇出到全体 active 成员直聊 / inbox
             → 团队页「团队广播」

团队任务     关联群聊 round
             → 参与者 = 成员 directSessionId
             → 团队页「团队任务」+ 打开群聊

点对点（本功能）
             agent_message_tool(target_session=成员 directSessionId)
             → 目标会话正文（SSOT）+ inbox 索引
             → 团队页「成员通信」（投影，无第二正文）
```

当前缺口：跨 Agent 的 `agent_message_tool` **默认拒绝**，只有科研组织边能过（`cross_agent_policy_required`）。本队点对点要做成 ADR 0002 §4 已预留的下一道授权门，不是新聊天系统。

### 3.4 自定义团队的会话缺口

`create_team` / `update_team` 只规范化成员身份并同步群聊。若成员没有 `directSessionId`：

- `_active_member_session_ids` 会跳过该成员；
- 群聊参与者不全；
- 花名册无法给出可寻址地址；
- 发送会被 ADR 正确硬挡（`session_not_found` / 无 session）。

这是「团队里的 Agent 会话如何解决」的核心：补 **入队/修复时 ensure**，而不是在发送时猜会话。

---

## 4. 会话与团队交接：锁定规则

「交接」= 把一条协作工作交到**某个队友已存在的可唤醒会话**，不是交到 Team 抽象，也不是再开一条平行会话。

### 4.1 寻址

1. 成员的可寻址会话 **就是** 其当前 `directSessionId`。
2. 花名册必须带上该 id；缺失则标 `unaddressable`，不得编造。
3. `agent_message_tool` 仍只接受显式 `target_session`。花名册提供地址，工具不推断。
4. 发送时校验：目标会话所有者 ∈ 发送者的同一 active team；否则 `cross_agent_policy_required`。
5. 科研组织路由保持优先；本队门是并列授权，不是替换。

### 4.2 何时创建 / 修复会话

| 时机 | 行为 |
| --- | --- |
| 系统队 ensure | 已有：缺则 `ensure_agent_direct_session` / `create_chat_session`，kind=`team_agent` |
| 自定义团队 入队 / 更新成员 | **新增**：对缺 `directSessionId` 的 active 成员调用 `ensure_agent_direct_session`，kind **保持**该 Agent 已有分类（默认 `personal_agent`） |
| Runtime Context / 花名册 | **只读**。禁止在拼 prompt 时建会话 |
| `agent_message_tool` 发送 | **不建会话**。无/无效 session → 硬挡（ADR 0002） |
| 离队 | 保留直聊会话；只从关联群聊摘掉参与者 |
| 归档团队 | 沿用现有级联；本功能不新开删除会话语义 |

入队 ensure 失败（会话碰撞、Agent 已归档）必须记团队事件，成员标 `unaddressable`，不得静默占用他人会话。

### 4.3 不改变会话身份

- 个人 Agent 加入自定义团队：**不**改成 `team_agent` / `team_private`。
- 系统队角色 Agent：继续 `team_agent` + 默认不进聊天列表。
- 团队页跳转一律用显式会话 URL（`?session=`）。`team_private` 不因此被提升进默认会话列表。

### 4.4 三种交接分别走哪条面

| 意图 | 走哪条 | 落点 |
| --- | --- | --- |
| 「问/交给某个队友」 | 点对点 `agent_message_tool` | 对方 `directSessionId` |
| 「全队讨论一个议题」 | 已有团队任务 / 关联群聊 | 群聊 round，不是直聊 |
| 「操作者通知全队」 | 已有团队广播 | 各成员直聊 + 广播时间线 |
| 「项目级换人/换地盘」 | 已有 Project Agent Territory / HandoffTargets | **不是**本队花名册；不要混进 TeamRoster |

### 4.5 花名册公开字段（对齐 Agent Card / Crew，仍用本项目已有数据）

公开（注入 prompt）：

- `displayName` / `agentName`
- `role` / `purpose`（1–2 行）
- `responsibilities`（最多数条短句，对应 Card `skills`）
- `agentId` / `agentCode`
- `directSessionId` 或 `unaddressable`
- `agentStatus`

详情工具才给：完整 persona、工具清单、运行状态。
不进公开卡：完整 Prompt、私有记忆、工作区内部。

### 4.6 会话上的团队绑定标签

用户要求：会话若有团队绑定，就要有标签声明绑定；鼠标悬停显示绑定的团队；**点击跳转该团队**。

**现有证据**

- 后端会话投影已有 `teamId` / `teamName`（`session/projection.py`），前端 `SessionSummary` **尚未声明**这两字段。
- 对话索引已有 `conversationTeamFor`：先读会话上的 team 字段，再按成员 `agentId` / `agentCode` 反查 active team。
- 聊天页签：`AgentSessionTabStrip`；列表行：`DirectSessionIndexItem`（已用 `VTooltip`）。
- 群聊的团队归属已在 `ChatStatusRail` 用「打开团队」，**不是**本标签。本标签只打在**直聊会话**身份上。

**绑定判定（有任一即显示）**

1. 会话投影带非空 `teamId` / `teamName`。
2. 会话所属 Agent 是某个 **active team** 的 active 成员（复用 `conversationTeamFor` / `_find_active_team_for_agent`）。
3. `experimentBinding.teamId` 非空（实验会话也算绑定到该团队）。

无上述信号则不显示。群聊房间、无 Agent 的 `user_chat` 不打此标签。

**交互**

| 项 | 锁定 |
| --- | --- |
| 出现位置 | 会话页签（`AgentSessionTabStrip`）+ 会话列表行（`DirectSessionIndexItem`） |
| 可见文案 | 短标签「团队」/ `Team`（页签密，不把团队全名写进标签） |
| 悬停/焦点 | `VTooltip`：团队显示名；有 `purpose` 可第二行；可附 `teamId` |
| 点击 | 跳到 `teamWorkspaceRoute(teamId)`，与 `ChatStatusRail` / `AgentTeamRelationsPanel` 的「打开团队」同一落点。不进 `panel=agents`，不另开通信面板深链 |
| 事件 | `stopPropagation`：点标签不得同时选中页签或打开该会话 |
| 无 `teamId` | 仍可显示标签 + tooltip 名称；**不可点**（`teamWorkspaceRoute` 空 id 会抛） |
| 无障碍 | 禁止只用原生 `title=`；控件对读屏为「打开团队：{name}」的 link，可键盘激活 |
| 组件 | 语义走现有 `VRouteLinkButton`（站内路由）；视觉保持短标签密度。`VChip` 文档写明不做可点击主操作，**不要**给 `VChip` 加 `onClick`。外裹 `VTooltip`。不新建 V* |

入队 ensure 会话后，投影应能读到绑定（成员关系或会话/Agent 上的 team 字段）。标签是投影，不单独存一份「标签状态」。

---

## 5. 实施方案

**推荐路径**：在现有 `team` + `agent_message_tool` + 团队页上长；会话权威继续是成员直聊。

### 影响面

| 切片 | 落点 | 保护边界 |
| --- | --- | --- |
| 花名册 | `team/team_membership.py`、`team_projection.py`；`agent_directory/projections.py` 的 `build_agent_runtime_context_block` | 不改项目级 HandoffTargets |
| 入队 ensure 会话 | `team/team_crud.py` 成员写入后；复用 `session_service.ensure_agent_direct_session` | 不在 context 热路径写会话；不改 kind |
| 同队授权 + 索引 | `tools/agent_message_tools.py`；`team/` 新切片；`routes/teams.py` 只加薄 GET | 不改 `POST /teams/{id}/messages` 广播语义 |
| 团队页 | `TeamCommunicationPanel.tsx` + 团队 API client + 现有 V* | 不新建设计体系；不把点对点写入群聊正文 |
| 会话团队标签 | `SessionSummary` 补 `teamId`/`teamName`；`AgentSessionTabStrip`；`DirectSessionIndexItem`；复用 `conversationTeamFor` + `teamWorkspaceRoute` | `VTooltip`+`VRouteLinkButton`；`stopPropagation`；不改群聊 StatusRail |

根 `main` 上已有无关脏文件与其它 claim（`agent.py` / `core/orchestration/*`、Agents 路由拆分、解耦计划）。**禁止**掺进那些文件。

### Critical Path

```text
Task 0: 入队/更新成员时 ensure 缺席的 directSessionId
- Owner: team_crud + session_service.ensure_agent_direct_session
- Dependency: 无
- Mode: SIMPLE
- Verification: 无会话成员入队后有 directSessionId；碰撞/归档失败可观测；kind 不变

Task 1: 本队精简花名册进入 Runtime Context
- Owner: team pack + agent_directory/projections.py
- Dependency: 可读 Task 0 的会话，但不依赖其合入才能设计
- Mode: SIMPLE
- Verification: 有队含地址或 unaddressable；无队 TeamRoster: none；外队不出现；拼 prompt 无写盘

Task 2: 同 active team 作为跨 Agent 授权门 + 团队投递索引
- Owner: agent_message_tools.py + team 新切片 + teams.py GET
- Dependency: 科研组织路由仍优先
- Mode: BDD_TDD（已有跨 Agent 拒绝测试必须继续对「非本队」成立）
- Verification: 同队投递成功；外队/无队 blocked 且 kernel 未调用；索引无正文副本

Task 3: 团队页成员通信时间线
- Owner: TeamCommunicationPanel + team API client
- Dependency: Task 2 list API
- Mode: SIMPLE
- Verification: 与广播分区；跳转 ?session=；tsc -b 绿

Task 4: 有绑定的直聊会话显示「团队」标签 + 悬停团队名 + 点击进团队
- Owner: chat 页签/列表（`AgentSessionTabStrip`、`DirectSessionIndexItem`）+ `SessionSummary` 类型
- Dependency: Task 0 之后投影更稳；可与 Task 3 并行
- Mode: SIMPLE
- Verification: 有绑定显示标签+tooltip；点击 href=`teamWorkspaceRoute(teamId)` 且不选中会话；无 teamId 不可点；无绑定不显示；群聊不打此标；tsc -b 与相关 layout/contract 绿
```

并行：Task 0 ∥ Task 1 ∥ Task 2 骨架 → Task 2 实现 → Task 3 ∥ Task 4。

### 风险决策

- 同队授权 = ADR 已预留 gate，不是放开任意跨 Agent。
- 发送时不建会话，避免「工具调用副作用创建隐藏会话」。
- 团队页只读索引，避免和会话正文漂移。
- 花名册截断，避免胀 prompt。
- `team_private` 会话用显式 URL 打开，不污染默认聊天列表。

### 验证命令（实施阶段）

- `tests/test_agent_message_session_addressing.py`
- `tests/test_multi_agent_conversations.py`（跨 Agent 拒绝仍在）
- `tests/test_team_service.py` / 成员会话 ensure 新用例
- `tests/test_agent_project_memory_updates.py` 或 runtime context 现有用例（花名册）
- `web/src/routes/teams/TeamCommunicationPanel.contract.test.ts`
- `web/src/routes/AgentSessionTabStrip.test.tsx`、`DirectSessionIndexItem.test.ts`
- `web/` 下 `npx tsc -b --pretty false`

日志：发送/拒绝带 `teamId`、source/target、`targetSessionId`、reason。

---

## 6. Deferred

- Agent 主动全员广播。
- 把点对点摘要镜像进关联群聊（会变成双可见面，另案）。
- A2A 对外暴露本队 Agent。
- 将个人入队成员改成 `team_private`。
- 在标签上直接写团队全名（页签过宽）。
- 标签深链到成员通信 / agents panel（第一期只到团队工作台首页）。

---

## 7. 权威与复用

- 协作寻址：[ADR 0002](../../../adr/0002-agent-collaboration-session-addressing.md)
- 领域词：Project Agent Bus / Team Broadcast / Agent Collaboration Message — [domain.md](../../../agents/domain.md)
- 会话热路径：[conversation-flow-map.md](../../../agents/conversation-flow-map.md) · [session/README.md](../../../../core/web/services/session/README.md)
- 团队：[team/README.md](../../../../core/web/services/team/README.md)
- 列表默认隐藏 `team_agent` / `team_private`：session README live directory 条

本文件不是第二套会话规范。实施时以 ADR 与模块 README 为准；本文件只锁定本功能的交接选择。
