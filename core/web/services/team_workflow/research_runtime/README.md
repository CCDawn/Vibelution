# `research_runtime` — Workflow Ledger 正式运行时（T3–T5 集成收口）

本目录实现科研工作流**正式运行时**：命令受理 → LangGraph interrupt/resume →
Adapter 执行 → Domain read-back → Receipt → Handoff → 下一节点 Readiness 的完整链路。
挑战杯规划规范不进入 GitHub，本地副本见桌面 `挑战杯/03-工程合同/`；仓内实现合同以本 README、Workflow Ledger 代码与对应测试为准。

## 职责边界

- **唯一写模型**：`core/research/workflow/ledger/`（SQLite Workflow Ledger）。LangGraph
  checkpoint 只保存控制位置；领域 Store 保存业务事实；本目录不写第二状态机。
- **唯一命令入口**：`WorkflowCommandService`（`command_service.py`）。
- **唯一可执行性判定**：`readiness/NodeReadinessService`，命令受理与自动推进共用。
- **Adapter 契约**：`action_registry.py` + `adapters/domain_adapters.py`；真实接线走
  `real_domain_ports.py`。
- **运行时组装**：`runtime_factory.py`（composition root）——Ledger + coordinator +
  readiness + real ports/context + graph/adapter worker 一次性组装。

### 执行、业务结果与工作流进度

| 事实 | 唯一来源 | 派生规则 |
| --- | --- | --- |
| Session / Turn 执行状态 | 原生 Session Journal | 按任务绑定的 sessionId + turnId 读取；当前 Session phase、其他 Turn 和业务状态不得覆盖 |
| 任务业务结果 | 领域任务 Store 与任务关联的持久产物 | Turn 终结后核验关联产物；有正文不等于有产物，写回后的执行失败不抹除已有产物 |
| 模型调用证据 | Model Invocation Receipt Registry | 由现有持久 Outbox 投递；Session 快照只能作为投影，不回写 Registry |
| 工作流进度 | Workflow Ledger | 任务结果、正式回执和产物 read-back/verify 全部满足后才提交节点成功 |

回执等待只挂起原 adapter action 的完成处理，保留原任务、Turn 和预算 reservation。
投递未完成时重排完成处理，不消耗模型重试额度；投递缺失或失败时阻塞工作流，
不伪造 Session 失败。匹配回执到达后只唤醒仍为最新且未取消的原节点尝试，
继续校验与提交，不新建任务或调用模型。工作流 anchor 的 closure 表达工作流关闭原因，
不得覆盖其 rootSession/scopedSessions 的执行状态。
此恢复只适用于保存了完成游标的新等待记录；旧版本已终结的失败尝试不自动重开。

### Readiness 来源约束

- 执行检查按显式 nodeId 解析阶段，复用预算准入的额度规则（包括 operator 扩容）和用量计算；
  budget receipt 查询同时限定 runId 与 stageId，不依赖 JSON 字段顺序或其他阶段的消耗。
- 指定 runId 的题目检查只读取该运行冻结快照；未指定运行的历史查询不参与执行检查。
- 产物检查只使用 canonical scoped loader；归属失配或缺失不再从宽松的列表读取中恢复。

### Agent 配置与绑定权威

- `Team.members` 只保存 `role -> agentId`，是团队成员关系的唯一来源。
- `AgentInstance` 是 model、Prompt、ToolPolicy、permission、Persona、TaskProfile、
  memory 等 Agent 配置的唯一 SSOT；本运行时只能读取，不能通过 bootstrap、
  repair、reconcile、Canvas 或 `workflowDefaults` 回写覆盖。
- Team-scoped `workflowDefaults` 由 `Team.members` 实时派生，不是第二份持久配置；
  历史残留值不得覆盖 Team 成员关系。
- stage/node override 只允许在本次执行中选择 `agentId`，不得携带或覆盖 Agent 配置。
- Run/Turn 中的 binding、model、Prompt/system segments、history、ToolPolicy 与权限
  仅是创建时冻结的不可变历史快照，用于复现和审计，不是回写来源。
- Canvas 仅投影 Team 成员。Canvas 保存不能反向修改 `Team.members` 或 Agent 配置。
- Run 的节点绑定只能读取该节点的冻结记录。缺失/空 Agent 保持 unbound，由 readiness 阻塞；
  不从当前 Team 或其他节点补全，不制造 `heal:*` 快照。更换执行者必须经过正式绑定变更。
- 运行证据图只读该 Run `artifactSummary.refs` 绑定的最新已物化图回执，并经现有 scoped
  artifact loader 与 SHA256 校验后展示。内容失配不得回退旧回执、同项目历史图或团队证据。
  团队 ClaimEvidence envelope 只交由研究台账解析；不作为运行图的输入。


## 核心流程

### 手动暂停与恢复调度

正式 `/research/workflow-runs/{run_id}/commands` 接受 `pause_run` 与 `resume_run`，
沿用 team、server operator 角色、`expectedRunVersion`、幂等键与原有命令回执；
这是兼容新增输入枚举和 command offers，不改变已有请求或回执字段。
`pause_run` 只接受已经产生节点尝试的 `running` / `waiting_human` Run，
不启动 `created` Run。`resume_run` 保留同一个 Run、节点尝试、Session 和 Turn；
仍有待决人工任务时恢复到 `waiting_human`，否则回到 `running`。

暂停只阻止新的 graph / adapter 派发。在飞执行继续落账，已有完成游标和 live-turn
等待继续按原动作收口；完成回执仍按现有最长 5 秒重排窗口读取，不要求暂停期间即时唤醒。
真实失败仍进入既有 `blocked`，成功收口不自动解除暂停。暂停与后继提交并发时，
graph outbox 保留待恢复动作；恢复后复用 checkpoint，避免再次调用已完成的图步骤。
恢复事务只提前本 Run 中因 `run_paused` 重排且仍为 pending 的 graph / adapter 动作，
不清重试计数、不抢 leased 动作、不缩短其他退避；提交成功后才唤醒 worker。
界面复用 snapshot / node detail 的 command offers 与节点通用操作区。
只读投影沿用经 control token 验证的 server operator；有对应命令权限时才签发
`authorized`，缺少上下文或角色不足仍显示 operator 权限门。提交时独立重新鉴权，
快照签名、客户端身份头和 `requestedBy` 均不能赋予写权限。

取消收口读取同一 Ledger 的冻结执行身份；普通 Session 携带预期 Turn，
会议使用预期 room / round 与参与者身份，不能用普通 Turn 的终态补写代替会议停止。
创建入口在外部副作用前以 Ledger CAS 记录 `executionAdmission=creating`，
实际返回的 Session / meeting / fan-out 身份登记成功后才改为 `closed`。
取消清理在创建尚未确认结束时保持 pending，并继续停止已经登记的执行。
明确未准入的短暂繁忙仍按既有退避重试；硬崩溃或未知副作用不能伪装成清理完成，
保留未确认的 admission 供进一步核查，不自动清除标记或重放未知操作。

```text
Command transaction (WorkflowCommandService)
  -> graph_dispatch outbox (graph_dispatch_factory.py 唯一构造)
  -> Graph Worker (graph_dispatch_worker.py) invoke/resume
  -> PendingAction interrupt (challenge_cup_runtime.py)
  -> adapter_dispatch outbox
  -> Adapter Worker (adapter_dispatch_worker.py):
       read-back -> resolve binding -> reserve budget -> create task
       -> verify -> 一个 Ledger transaction (anchor/receipt/handoff)
       -> after-commit settle budget (RealDomainPorts.settle_budget)
  -> graph resume -> 下一节点 Readiness 重检 -> 自动推进或 blocked
```

## 关键文件

| 文件 | 职责 |
| --- | --- |
| `command_service.py` | 单命令入口；operator 授权（`_authorize_operator`）；fork_revision |
| `graph_dispatch_factory.py` | 唯一 graph_dispatch payload 构造（完整冻结字段） |
| `graph_dispatch_worker.py` | graph outbox 消费；自动后继 NodeReadiness 预检（writer 事务外） |
| `adapter_dispatch_worker.py` | adapter outbox 消费；verify 后 settle 预算 |
| `action_registry.py` | ActionAdapter 协议 + 精确 kind 注册表 |
| `adapters/domain_adapters.py` | agent/human/system adapter；全节点 kind 注册 |
| `real_domain_ports.py` | 生产 DomainPorts：binding 解析 / 预算 reserve+settle / 真实 task |
| `real_readiness_context.py` | 生产 DomainReadinessContext：冻结 input snapshot + 领域查询 |
| `runtime_factory.py` | composition root：`build_workflow_runtime(...)` |
| `hypothesis_first_chain.py` | 假说链命令/会议入口；公共导入保持在此 |
| `hypothesis_first_chain_store.py` | 假说链 JSONL 账本、scope lock、错误类型 |
| `hypothesis_first_chain_auto_advance.py` | 假说链自动推进/扫场入口；执行时绑定到 chain facade globals |

## T5 收口要点（P1 审查项）

- 自动推进的后继 attempt 进入 adapter **前**重新执行 NodeReadiness（`use_cache=False`）；
  不 ready 则 attempt 标 `blocked`、不建 adapter outbox。readiness 读 ledger 走 writer
  队列，因此预检必须在 **writer 事务外**的 `_precheck_readiness` 完成，避免死锁。
- attempt/handoff/run 状态转移由 `core/research/workflow/transitions.py` 冻结函数在
  repository 层强制校验（`repository._require_*_transition`）。
- `fork_revision` 与人工 `revise` 决策在同一 Ledger 事务内创建 child Run（parent lineage），
  并产出 child `graph_dispatch`；不再把 revise 压成 failed receipt。
- 高影响命令（pause/resume/cancel/rebind/extend_budget/resolve_human/fork_revision/reconcile）
  要求可信 server operator 上下文，并按命令执行角色授权。
- Adapter 用冻结 `RunAgentBindingSnapshot` 解析 agentId/roleKey（不再 `agent-{nodeId}` 伪造）；
  budget `reserve_budget` 返回值贯穿到 budget_receipt，commit 后 `settle_budget` 落 ledger。

## 测试

`tests/test_research_workflow_*` 覆盖 T1–T5 全链路；集成链测试：
`tests/test_research_workflow_integration_chain.py`（无 Fake：Command→Graph→Adapter→
read-back→Receipt→Handoff→下一节点 Readiness）。

驻留 runtime 的通用治理开关（默认行为之外的唯一 env 旁路）见
`tests/test_research_runtime_governance_switches.py`：
`VIBELUTION_AUTO_ADVANCE_DISABLED`（auto-advance 全链路 kill，含
closure sweep）与 `VIBELUTION_AWAITING_APPROVAL_REAPER`（reaper 关闭）。
