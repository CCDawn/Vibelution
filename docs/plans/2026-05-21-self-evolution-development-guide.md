# 无监督进化开发指导文档

## 定位

无监督进化线负责让 Vibelution 在没有人类逐步评价每个候选的情况下，进行一轮受控、自证据驱动、自我约束的改进尝试。

它不是自由改写系统，也不是监督进化的替代品。它的职责是读取当前目标、工作区现场、最近事务、监督建议和运行证据，决定是否启动一轮 bounded self-evolution，并在运行后留下可诊断、可回滚、可删除的事务证据。

结合 Agent Harness 论文综述，无监督进化线应优先吸收三类机制：

- EvolveR 风格的经验闭环：在线经验经过清洗、去重、整合、蒸馏后进入策略/原则仓库，再反哺后续候选生成。
- AgentEvolver 风格的 self-questioning / self-navigating / self-attributing：系统自己发现弱点、复用历史成功轨迹，并把成功或失败归因到步骤、工具、prompt、文件或决策点。
- SAGE / E-SPL 风格的候选池：可进化的不只是一段 diff，还可以是 skill candidate、prompt candidate、proposal candidate，但这些都只是候选，必须回到监督线验收。

## 当前事实

- Web 自进化页已有 start 按钮、运行状态、历史组、批量删除和 stale run 解锁逻辑。
- `self_evolution_control_service` 已能处理 stale queued/paused/running 快照。
- 自进化启动会检查 active supervised run，避免和监督运行冲突。
- 自进化历史删除以 txnIds 为唯一入口，审计尾迹同步清理。
- 预览和 run prompt 已包含目标、建议基线、工作区快照、最近事务和 fitness。
- 这条线仍以 helper/control/service 层为主，不应随意改共享 workbench 入口。
- 最新规划要求自进化运行登记为 `WorkRun(self_evolution_run)`，并通过 resource lease 与 chat/supervised 协调。

## 职责边界

无监督进化线负责：

- 自进化 run 的 start、pause、resume、stop、stale unlock。
- 启动前现场摘要：goal、worktree、recent transactions、fitness、advisory baseline。
- 自进化事务历史和 audit 证据。
- 自进化运行与监督 active run 的互斥。
- 自进化结果的可诊断性、可回滚性、可删除性。
- 运行失败或停止后的用户可见恢复说明。
- 生成候选 case、候选策略、候选 skill、候选 prompt 和候选 proposal，但不直接宣布生效。

无监督进化线不负责：

- 监督决策的 PROMOTE/HOLD/ROLLBACK 判定。
- 对话消息展示、工具调用卡片、聊天停止按钮 UI。
- LLM provider/profile 的配置安全。
- 直接修改冻结评测集或监督 policy。
- 绕过 risky write transaction gate。
- 自己改写 accepted baseline 或 selection policy。

## 共享底座边界

无监督进化线必须遵守横向计划：[WorkRun Substrate And Chat Case Loop Implementation Plan](./2026-05-21-workrun-substrate-and-chat-case-loop.md)。

统一边界：

- 每次自进化运行登记为 `WorkRun(self_evolution_run)`。
- 自进化运行的 `active` 与 `latest` 只在 `self_evolution_run` kind 下生效，不应吞掉 chat 或 supervised 的状态。
- 自进化默认申请 `evolution_transaction`、`worktree_write`、`memory_write` 等严格 lease；只有 lease policy 允许时才能与其他 run 并行。
- 自进化可以生成候选 case、候选策略、候选修改，但不能直接写入冻结验收标准或 accepted baseline。
- 自进化成功经验必须作为 proposal、dataset candidate、generated case、skill candidate 或 prompt candidate 回到监督线验收。
- 自进化运行必须留下 evidence tail、transaction id、rollback hook 和 provenance。

无监督线向共享底座提供：

- `self_evolution_run` 的 lifecycle snapshot、event tail、事务证据和 rollback/handoff 信息。
- 候选增量的来源、provenance、事务 ID 和是否可回滚。
- 失败 run 的诊断标签、触发阶段、工具轨迹和可恢复说明。

## 论文启发到工程机制

- EvolveR：把经验做成闭环，在线交互 -> 离线蒸馏 -> principle repository -> candidate generation；重点是去重、整合和质量控制。
- AgentEvolver：让系统主动提出新问题、主动复用历史成功路径、主动给出归因，而不是只等人类告诉它哪里坏了。
- SAGE：把 skill library 作为可成长资产；新 skill 不是直接上线，而是带着适用条件、收益和失败案例进入 candidate pool。
- E-SPL：prompt evolution 可以做，但必须和 RL / evaluation 解耦为候选探索；它不适合作为当前阶段的直接自修改机制。
- MAESTRO：长期可引入 model/skill routing，但目前优先级低于 run evidence 和 candidate governance。
- Orchard：环境/执行基座要可复用、可扩展，尤其适合把真实 worktree、GUI 或 web environment 纳入统一执行面。

## 关键文件

核心服务：

- `core/evaluation/self_evolution_workbench.py`
- `core/web/services/self_evolution_control_service.py`
- `core/web/routes/evolution.py`
- `core/runtime_manager/evolution_store.py`
- `core/runtime_manager/daemon.py`

共享治理：

- `core/infrastructure/evolution_governor.py`
- `core/infrastructure/git_memory.py`
- `core/infrastructure/tool_executor.py`
- `core/gym/advisory.py`
- `core/runtime_manager/work_run_store.py`，如共享底座已引入
- `core/runtime_manager/work_run_leases.py`，如共享 lease policy 已引入

前端：

- `web/src/routes/EvolutionRoute.tsx`
- `web/src/routes/EvolutionRoute.module.css`
- `web/src/api/client.ts`
- `web/src/api/types.ts`
- `web/src/store/shellStore.ts`
- `web/src/i18n/dictionary.ts`

工件：

- `workspace/evolution/audit.jsonl`
- `workspace/evolution/proposals`
- `workspace/gym/proposals`
- `workspace/supervised_evolution/policy`
- `.runtime`，如当前 runtime manager 使用该目录

测试：

- `tests/test_self_evolution_control_service.py`
- `tests/test_web_app.py`
- `tests/test_runtime_manager.py`
- `tests/test_evolution_governor.py`
- `tests/test_git_memory.py`
- `tests/test_tool_executor.py`
- `tests/test_work_run_store.py`
- `tests/test_work_run_leases.py`

## 开发原则

1. 先看现场，再决定是否开跑。
   如果 worktree 已脏、监督运行 active、stale run 未收口、最近事务失败，先解释和收口，不直接开新 run。

2. 自进化必须 bounded。
   每轮要有目标、预算、停止条件、事务边界和可见结果。

3. 自进化不能自改评判标准。
   可以参考 active advisory baseline，但不能直接改写监督 policy 或冻结验收逻辑。

4. 高风险写入必须走事务。
   `core/`、`tools/`、`config/`、`workspace/prompts/` 等路径必须由 risky write gate 保护。

5. 失败也是证据。
   失败 run 要写清楚原因、阶段、工具、路径、是否可恢复，而不是只留一个 failed 状态。

6. 经验要先入仓，再出候选。
   在线发现的策略、失误、修复和启发先写入 experience repository，再决定是否生成 prompt candidate、skill candidate 或 proposal candidate。

7. 自问自答要面向弱点。
   self-questioning 应直接围绕最近失败、重复错误和未覆盖 case，而不是泛泛地产生新点子。

8. 归因要细到步骤和证据。
   self-attributing 需要把成功/失败拆到 tool、prompt、文件、阶段和外部状态变化，供后续诊断和复用。

## 优先任务

### 任务 1：稳定启动前现场检查

目标：用户点开始前，能看清楚这一轮是否适合启动。

重点检查：

- active supervised run 是否阻止 self-evolution start。
- stale queued/paused/running 是否能自动收口或给出解释。
- worktree snapshot 是否展示 dirty files、branch、recent transactions。
- advisory baseline 是否明确标注“参考，不是开关”。
- 最近失败是否能转成诊断输入，而不是只展示一个 failed 状态。

建议测试：

```powershell
pytest tests/test_self_evolution_control_service.py -k "start or stale or supervised" -v
pytest tests/test_web_app.py -k "self_evolution or active_supervised" -v
```

### 任务 2：稳定运行控制

目标：start/pause/resume/stop 不互相污染，停止不会留下假 active 状态。

重点检查：

- runtime manager store 是否隔离测试和真实 `.runtime`。
- queued/paused/running/stopping 之间的状态迁移。
- stop 后 worker 是否真正停止。
- 重新加载页面时是否修复缺内存 worker 的持久化状态。
- run 结束后是否留下完整 evidence tail 和 transaction context。

建议测试：

```powershell
pytest tests/test_self_evolution_control_service.py -v
pytest tests/test_runtime_manager.py -k "evolution or daemon" -v
```

### 任务 3：稳定事务历史

目标：自进化运行产生的事务和 audit 可以被用户理解、删除、回看。

重点检查：

- 删除入口是否只接受 txnIds。
- 删除 history 时，相关 audit jsonl 也同步清理。
- active/running/stopping 事务是否禁止删除。
- UI 是否把事务组、审计尾迹、运行状态对应起来。
- provenance、rollback hook 和恢复说明是否可见。

建议测试：

```powershell
pytest tests/test_web_app.py -k "self_evolution.*delete or history" -v
pytest tests/test_self_evolution_control_service.py -k "history or delete" -v
```

### 任务 4：稳定自改边界

目标：无监督 agent 的修改不会绕过阶段 2 的事务治理。

重点检查：

- `open_evolution_transaction_tool` 是否在 risky write 前显式调用。
- `close_evolution_transaction_tool` 是否清理 active txn。
- `GitMemoryService.note_file_modified()` 是否只追踪 dirty state，不写后自动开账。
- cli 写入目标是否能被 `EvolutionGovernor` 解析。
- proposal candidate、skill candidate、prompt candidate 是否都留有 provenance，但不直接落盘为标准。

建议测试：

```powershell
pytest tests/test_tool_executor.py -k "evolution or risky or transaction" -v
pytest tests/test_evolution_governor.py -v
pytest tests/test_git_memory.py -k "evolution or transaction" -v
```

### 任务 5：把开放探索变成候选增量

目标：无监督进化可以发现新策略、新 case、新工具习惯，但只进入候选池，不直接污染核心标准。

重点检查：

- generated cases 是否有 provenance。
- 运行失败是否能变成诊断 case。
- 自进化成功经验是否只作为 proposal、dataset candidate、skill candidate 或 prompt candidate。
- 是否仍要回到监督线进行验收。
- experience repository 是否去重、聚合和保留质量分数。

建议测试：

```powershell
pytest tests/test_dataset_registry.py -k "generated_cases" -v
pytest tests/test_gym_collections.py -v
```

### 任务 6：建立经验仓库

目标：把可复用经验从一次性日志变成长期资产。

建议仓库内容：

- recurring failure patterns
- successful strategies
- candidate prompts
- candidate skills
- candidate proposals
- diagnostic cases
- tool-use heuristics

要求：

- 每条记录带 provenance、source run、source turn 或 transaction id。
- 经验条目应支持 dedupe、quality score 和 downstream use 标签。
- 经验仓库本身不能成为冻结标准。

建议测试：

```powershell
pytest tests/test_dataset_registry.py -k "generated_cases or review" -v
pytest tests/test_web_app.py -k "self_evolution or evolution_workbench" -v
```

## 与对话线的接口

无监督线可以读取：

- 用户当前目标。
- 最近对话上下文摘要。
- stop/continue 失败证据。
- runtime scene 和 conversation log。
- next-state signal 和 trace-driven failure pattern。

无监督线不能修改：

- Chat 消息结构。
- ConversationView 展示规则。
- 用户对话历史的原文内容。
- 对话线的 stop/continue UI 语义。
- reviewed chat case 的 review 边界。

## 与监督进化线的接口

无监督线可以读取：

- active advisory baseline 摘要。
- 最近 supervised decision。
- proposal lifecycle 状态。
- 是否存在 active supervised run。
- 最近失败 taxonomy 和弱点分布。
- 监督线反馈的可生成 case 缺口。

无监督线不能直接修改：

- `workspace/supervised_evolution/decisions`
- `workspace/supervised_evolution/policy`
- `core/evaluation/selection_policy.py`
- accepted baseline registry

任何自进化产出的“更好策略”都必须回到监督线验收，不能自己宣布生效。

## 验收清单

- 有 active supervised run 时，self-evolution start 被拒绝。
- stale self-evolution run 能收口或解释。
- start/pause/resume/stop 状态稳定。
- 历史删除以 txnId 为唯一入口。
- risky write 必须显式开账。
- 失败 run 有可读原因。
- 成功经验只进入候选增量，不直接改写标准。
- 经验仓库中能找到重复失败模式和重复成功策略。
- proposal / skill / prompt / generated case 都带 provenance 和 downstream use 标签。
- 无监督探索产物最终仍回到监督线验收。

## 推荐验证

```powershell
pytest tests/test_self_evolution_control_service.py -v
pytest tests/test_runtime_manager.py -k "evolution or daemon" -v
pytest tests/test_web_app.py -k "self_evolution or active_supervised" -v
pytest tests/test_tool_executor.py -k "evolution or risky or transaction" -v
pytest tests/test_evolution_governor.py -v
pytest tests/test_git_memory.py -k "evolution or transaction" -v
pytest tests/test_dataset_registry.py -k "generated_cases or review" -v
```

## 提交说明

无监督进化线提交建议使用：

- `feat(self-evolution): ...`
- `fix(self-evolution): ...`
- `refactor(self-evolution): ...`
- `test(self-evolution): ...`

不要把监督 selection policy、Chat UI、Config security 的无关改动混进无监督提交。
