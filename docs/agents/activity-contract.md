# Session、AgentRun 与 WorkRun 活动契约

同一业务事实必须得到同一解释；不同领域保留各自的生命周期。词汇由后端定义，`scripts/generate_activity_contract.py` 生成前端投影与 Electron 通知契约，消费端不得复制状态词表或自行拼接 fallback。

## 权威与边界

| 事实 | 权威 / 写入者 | 读取与派生 | 刷新 | 迁移收尾 |
| --- | --- | --- | --- | --- |
| Session 执行与 Turn 结果 | 原生 worker / Turn Journal；`core/chat/session_activity.py` 定义解释契约 | `resolve_session_activity` / `resolveSessionActivity` 与共享 policy | 已接受的 detail / SSE、同 Turn 的终态身份和 ledger 水位 | 不改 Journal 格式；消费端不再用历史结果推断当前执行 |
| AgentRun 生命周期、阶段、原因 | `agent_run_store.py`；`agent_run_status.py` 规范化 | `status/currentPhase/terminalReason/rawStatus`，历史和时间线分别展示 | 记录明确结果或读取历史快照时解码 | 删除未发布的重复 `executionStatus/activityPhase`，不读取它们作为替代权威 |
| 异构 WorkRun 生命周期保护 | 各 kind 原有写入者；`work_run_status.py` 定义解释与保护 | Store、lease、admission、恢复与诊断读取共享策略 | 原有快照与 active index 更新 | Store 删除重复词表；不扩大关闭扫描 kind，不批量改写历史 |
| 展示词汇 | 后端领域 labels / phaseLabels / reasonLabels | 生成的 `activityContract.ts` 与领域展示函数 | 生成检查、标签覆盖测试 | 未知值显示未知，原值只作诊断 |

## 相互独立的含义

| 状态事实 | 执行所有权 | 活跃输出 | 新轮次 / 输入 | 删除 / 归档 |
| --- | --- | --- | --- | --- |
| `ready/idle`，无结果 | 无 | 无 | 可发新消息，仍受原生 admission 校验 | 可以 |
| `queued/running` | 保留 | 排队 / 执行中 | 输入进入后续队列 | 阻止 |
| `stopping` | 保留 | 不声明正在输出 | 等待停止确认 | 阻止 |
| `paused` | 保留 | 暂停 | 遵循后续队列语义；不提供同轮恢复入口 | 阻止 |
| `needs_continue/paused_limit` | 本轮已释放 | 无 | 继续会开启同 Session 的新 Turn | 可以 |
| 已完成 / 失败 / 停止 / 取消 | 无 | 无 | 可发新消息 | 可以 |
| 缺失 / 未知 | 不能证明存在 | 不能证明正在输出 | 不可据此推断接纳许可，原生 admission 仍校验 | 保守阻止 |

`execution`、`phase`、`outcome`、`reason` 分别表示执行、活动、结果和原因。`thinking/tooling/...` 属于活动；`completed` 是成功结果；停止结果为 `stopped`，`terminalReason` 保留用户或强制停止的原因。`ready` 本身不能产生成功通知。

Session 的 `status/currentPhase` 是原生当前控制面；`lastTurnStatus` 和 `terminalReason` 是历史结果事实，`childStatus` 是子会话投影。它们是独立事实字段。只有领域解析器可以解码它们；缺失阶段不得用 status 填造，历史 running 不得复活 idle，旧成功不得覆盖新执行。明确 live 状态或新 owner 优先；匹配 `lastTurnTerminalTurnId` 的终态 receipt 才能释放延迟清理的旧 owner。原生 `terminalReason` 与旧终态展示值冲突时，保持原生结果回执的优先级，不凭词义猜测哪个属于更新的 Turn。

WorkRun 的 `status → currentPhase → phase → runtimeStatus` 是异构快照的唯一解码边界；显式未知 status 不得被低优先字段洗白。缺失、未知和 `blocked` 等未证明结束的值保护关闭；`finishedAt/endedAt` 证明释放，不证明成功。恢复工作需要明确执行证据，不能把安全阻塞当成运行证据。

## 消费与验收

- 输入控制使用 execution ownership；输出动画和 token 采样使用 output-active；删除、归档和清空历史使用 mutation protection。三者不能共用含义模糊的 busy 布尔值。
- 通知消费权威 detail 的结果与稳定 Turn 身份，SSE 和 query 使用同一去重入口。待继续、失败和用户停止不能报告成功；初次读历史和重访不补发。
- Companion 的完成身份和通知隔离保持在 Companion 边界；Queue、CLI、Group、工具和研究工作流保留各自领域状态。
- `activity_contract_cases.json` 与 `activity_policy_cases.json` 由 Python / TypeScript 共用；生成同步、标签覆盖、真实消费者和运行场景分别验证。
- 历史别名只在领域解析入口接受。运行时不批量覆写历史快照；没有新增存储格式、第二写入者或迁移等待窗口。

普通 Session 当前不提供保持同一活动 Turn 的执行暂停 / 恢复。本次迁移不新增该能力，也不把后续队列暂停或“继续新轮次”宣称为同轮恢复。

## 其他领域的权威与解释边界

| 领域 | 权威 | 消费契约 |
| --- | --- | --- |
| 原生通知 | `session_activity.py` 的 `SESSION_NOTIFICATION_CONTRACT` | 生成 `conversationNotificationContract.generated.ts`；传输只接受规范成功值，失败和待继续保留原因。`ready`、用户停止和未知值不产生完成提醒；`--check` 同时检查 web 与 Electron 生成文件。 |
| 后续输入队列 | `session/queued_turns.py` 的持久化记录和原生 admission | `queued/starting/paused/blocked` 描述输入项，队列暂停不等于当前 Turn 执行暂停。领取竞争保留原提交身份，用户停止形成的 hold 不由机器通知解除。 |
| Runtime 命令队列 | `command_queue.py` 的 inbox / processing / results 与 `commandId` | `accepted/completed/ok` 分别表示接收、结算和操作结果；取消、替代与执行失败分别展示。缺少结果证据保持未知，结果列表和结果事件采用同一解释。 |
| CLI Task / Terminal | task kernel 记录任务结果，terminal runtime 记录进程与交互能力 | reader 已发布的运行/终态不能被提交确认覆盖；`alive` 不等于允许输入。停止收尾仍可读输出，不能再输入、恢复或启动。 |
| Group | `chat_room_service.py` 写 room / round 和 append-only timeline | room `ready` 表示可接收新轮次，round `completed/partial/failed/stopped` 才是轮次结果。同轮终态吸收迟到的 `stopping`，不阻止新轮次启动。 |
| 工具调用 | Executor 的 transport / semantic / exitCode 与原生 Journal | 预提交 `ready` 是待执行。v3 的四值 status 描述传输生命周期；已取消调用以已结束传输加 `semanticStatus=cancelled` 保真，界面显示中立取消。实际 failed 不能被语义警告或取消展示覆盖。工具无结果、显式业务失败不能报告成功；聚合命令检查所有 operation，搜索无匹配不掩盖另一条命令失败。 |
| 正式研究工作流 | Ledger 的 `RunStatus`、`NodeAttemptStatus`、租约与已有 action offers | `paused` 是可恢复调度 hold，DTO、状态投影和展示必须接受。仅保留权威已授权的 retry / reconcile；`starting/dispatching` 在画布边界折叠为运行中，正式 Snapshot 保留原值。归档不自行证明成功，Campaign 阶段、决策和租约不冒充 Run 结果。 |

各领域的回归分别覆盖真实消费者、DTO 与顺序竞争；不通过批量改写历史记录来消除兼容拼写。领域测试通过和隔离实例 API / CDP 验收分别记录，均不代表运行过付费 CLI 任务或真实科研实验。
