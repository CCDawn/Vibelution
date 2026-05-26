# 监督进化开发指导文档

## 定位

监督进化线负责回答一个核心问题：某次候选修改是否真的比当前 baseline 更值得保留。

这条线不是自动发布系统，也不是直接改写 runtime 的开关。它的职责是运行可回放评测、生成决策记录、维护 proposal 生命周期，并把 PROMOTE、HOLD、ROLLBACK 这些结论解释清楚。

结合 Agent Harness 论文综述，监督进化线应优先吸收三类机制：

- WildClawBench 风格的 hybrid verification：不要只看最终回答，要综合最终状态、工具副作用、轨迹、日志和语义判断。
- STT-Arena / AgentGym-RL 风格的可执行动态 case：评测要覆盖多轮、工具状态变化、不可完成任务、重规划和 post-adaptation verification。
- Shepherd / OpenClaw-RL 风格的 trace-driven decision：decision record 要能追溯到运行证据和 next-state signal，而不是只有一个分数。

监督线是 Vibelution 的 `V_ref` / frozen evaluator 主要承载者。对话线和无监督进化线产生的任何候选增量，最终都必须回到这里验收。

## 当前事实

- 监督进化已有 CLI 与 Web 两条入口。
- Web `/evolution` 已能启动监督运行、观察 active run、订阅 SSE，并执行 proposal action。
- `supervised_dry_run` bundle 已包含事务开账/关账探针。
- HOLD 后 observing proposal 已有默认观察预算，超预算后进入 expired 终态。
- active advisory baseline 仍然只是建议基线，不等于 runtime 已经改写。
- 当前记忆显示，历史监督记录多数仍停在 HOLD，说明候选与 baseline 的差异信号还不够强。
- 最新规划要求监督运行登记为 `WorkRun(supervised_evolution_run)`，并通过 resource lease 与 chat/self-evolution 协调。

## 当前实现快照（2026-05-26）

### 已落地机制

- `core/evaluation/supervised_evolution.py` 已按同一 bundle、同一 case、同一 scenario/mode/timeout 分别运行 baseline 与 candidate，并把每个 role 的 harness report 写入 `workspace/supervised_evolution/sessions/<session_id>/`。
- 每轮监督运行都会写 `workspace/supervised_evolution/decisions/<session_id>.json`，记录 `baseline_runs`、`candidate_runs`、`baseline_summary`、`candidate_summary`、`case_summaries`、`gates`、`decision`、`reason`、`score_delta`、`policy_action`。
- 当前 hybrid verification 是“部分结构化”：case 级已有 `difference_summary`、`difference_metrics`、`difference_reasons`，覆盖 validation、wall clock、guarded tools、new logs、restart miss、transaction issue、LLM failure。
- 当前 gate 顺序为 infrastructure、legality、safety、survival、cost，并在 PROMOTE 前追加 Gym promotion gate；LLM provider transport failure 会进入 `INCONCLUSIVE`，并跳过后续合法性/安全/生存/成本判断。
- `core/evaluation/dataset_registry.py` 已有 dataset 准入元数据：`review_required`、`source_track`、`allowed_downstream_uses`、`holdout_allowed`、`raw_chat_direct_training_allowed`、`usability_status`、`usability_reason`。
- `core/evaluation/supervised_intake.py` 已成为监督准入契约层，统一描述 reviewed chat、generated case 和 self-evolution candidate 的 downstream use、holdout/raw-chat 禁止项与 candidate-only 边界。
- `chat_reviewed_multiturn` 已被标记为 dialogue 来源、review required、非 holdout、禁止 raw chat direct training，允许 downstream use 为 `supervised_evaluation`、`gym_candidate_case`、`future_training_export`；物化 bundle 时只接受 `positive` review row。
- `chat_reviewed_multiturn` 物化时会保留 row 自带 `dataset_ref`，包括 `session_id`、`source_log_path`、`raw_excerpt_path` 和 `turn_range` 等来源证据；这些字段会进入 `intake_provenance`，并继续传播到 decision record、policy case evidence 和 proposal。
- `generated_cases` 已被标记为 generated 来源、非 holdout、禁止 raw chat direct training，允许 downstream use 为 `supervised_evaluation`、`gym_candidate_case`、`regression_observation`；每条 case 要求 provenance，且 `_validate_generated_case_provenance` 和 `_build_generated_case` 都禁止自动进入 `holdout`。
- `core/evaluation/supervised_intake.py` 已定义监督 case 类型集合：`static`、`dynamic_replanning`、`impossible_task`、`reviewed_chat`、`generated_case`。
- `core/evaluation/dataset_registry.py` 已能从 JSONL row 物化 dynamic/impossible case：`dynamic_replanning` 必须带 `provenance` 与 `expected_final_state`，`impossible_task` 必须带 `provenance` 与 `expected_infeasible_outcome`，并保留 `dynamic_events`。
- `CaseDecisionSummary` 已新增 `case_type` 与 `intake_provenance`，会把 generated provenance、review/approval、dataset split、allowed downstream uses、intake boundary、expected final state、expected infeasible outcome、dynamic events 和最小 expected outcome verification 带入 decision record；selection policy 的 case evidence 与 proposal 也会保留这些字段。
- self-evolution candidate pool 已写入 `supervised_intake_boundary`，并强制 `review_state=pending`、`candidate_only=true`、`supervised_required=true`、`auto_apply=false`，同时阻断 `accepted_baseline`、`selection_policy`、`runtime_prompt_override` 和 skill registry 直接写入。
- `core/evaluation/selection_policy.py` 会按 decision 写 policy 记录、audit log、observation/rejection/rollback pool、lineage index 和 proposal 文件；`INCONCLUSIVE` 只审计，不写候选观察池或回滚池。
- supervised selection policy proposal、case evidence 与 `accepted_baselines.json` 已显式写入 `supervised_decision`、`policy_action`、`proposal_status`、`runtime_effect=not_applied`、`agent_consumption=advisory` 和 `supervision_boundary.scope=supervised_frozen_evaluator`；PROMOTE 更新的是监督侧 frozen evaluator / policy artifact，不代表 runtime prompt、模型配置或线上行为已生效。
- `core/evaluation/supervised_workbench.py` 与 `core/evaluation/supervised_dashboard.py` 已能读取 Gym proposal lifecycle，并展示 `runtime_effect` 与 `agent_consumption`；active advisory baseline 仍只是 advisory。
- `core/web/services/evolution_service.py` 已区分 `manual_review` 与 `auto`：自动审查模式会锁定手工 proposal governance action、手工 proposal 编辑和删除。
- `core/web/services/supervised_control_service.py` 已为普通监督运行提供 active run、pause/resume/terminate、SSE event tail、`evaluation` lease 检查、dataset materialization 和 proposal action。
- `core/web/services/supervised_worktree_evolution_service.py` 已将工作树式监督闭环登记为 `supervised_worktree_evolution_run`，使用 `evaluation` + `worktree_write` leases；默认 `executionMode=simulation`，真实 LLM 路径需要 `confirmRealLlmCost=true`。

### 仍存在的实现缺口

- `score_breakdown` 已成为 case-level decision schema v1，并从现有 harness metrics 派生 `final_state_score`、`side_effect_score`、`trace_score`、`safety_score`、`semantic_score`、`overall_score`；dynamic/impossible case 若在 harness `evolution_summary` 中提供实际 `final_state` 或 `infeasible_outcome`，会额外写入 `expected_outcome_score` 并让 semantic score 反映 expected outcome 核验。后续若接入语义裁判，必须保持旧字段兼容。
- `failure_taxonomy` 已从 `difference_reasons`、LLM failure category 和 expected outcome verification 派生，覆盖事务、restart、LLM failure、状态回归/改善、成本噪声、dynamic/impossible schema 风险、actual evidence missing 与 expected outcome mismatch。stale-state execution 和真正的动态 benchmark 判分仍需后续扩展。
- `evidence_paths` 已进入 case summary、policy case evidence、proposal 和 Web case diagnostics，当前统一引用 role report、worktree、新 conversation/debug 文件；`intake_provenance` 已补上 case 来源和准入边界，但 Gym trace/diff/log artifact map 仍可继续补强。
- 动态 case 与不可完成 case 已有 dataset schema、最小监督 run 记录路径、expected outcome verification decision path 和 harness fixture marker 提取；内置 dry-run bundle 已包含 `dynamic_replanning_fixture` 与 `impossible_task_fixture`，可分别产出 `final_state` / `infeasible_outcome` 作为监督核验证据。现有 fixture 仍是轻量可回放探针，还不是完整 STT-Arena 风格动态执行器。
- PROMOTE 与 accepted baseline 的边界已写入 selection policy 产物和 Web/API 可读字段；后续仍需在更多 UI 文案里持续避免把 supervised baseline registry 说成 runtime baseline。
- `proposal_action` 目前有审计、policy/proposal 记录和 `supervised_proposal_action.*` runtime scene lifecycle event；如果后续要和共享底座完全对齐，仍可补独立 `WorkRun(proposal_action)`。

## 职责边界

监督进化线负责：

- dataset/bundle 选择与 materialization。
- baseline 与 candidate 的同条件比较。
- case 结果、gate、reason、score 的记录。
- hybrid verification：最终状态、工具副作用、轨迹、日志、安全行为和语义判断。
- Decision Record 的写入和回放。
- proposal 的 proposed/applied/active/rolled_back/superseded 生命周期。
- dashboard/workbench/Web 的监督数据读取。
- 观察预算、过期、拒绝、回滚的策略。
- 将 reviewed chat case、generated case、self-evolution proposal 纳入受控评测。

监督进化线不负责：

- 用户对话体验。
- Web Chat 的消息展示和停止语义。
- 自进化运行队列。
- 直接改写 runtime prompt、代码或模型配置。
- 自动把 PROMOTE 变成线上生效。
- 接收 raw chat transcript 作为正式评测样本。

## 共享底座边界

监督进化线必须遵守横向计划：[WorkRun Substrate And Chat Case Loop Implementation Plan](./2026-05-21-workrun-substrate-and-chat-case-loop.md)。

统一边界：

- 每次监督运行登记为 `WorkRun(supervised_evolution_run)`。
- 监督运行的 `active` 与 `latest` 只在 `supervised_evolution_run` kind 下生效，不应作为全局 active lock。
- 监督运行默认申请 `evaluation` lease；proposal action 需要单独申请 `policy_write` 等写资源。
- 监督线可以消费 `ReviewedChatCase` 和 `GeneratedCase`，但不能读取 raw chat 作为正式评测样本。
- 监督线是 `V_ref` / 冻结验收面的主要承载者；无监督进化和对话产生的候选增量必须回到这里验收。
- PROMOTE 是监督结论，不自动等于 runtime effect。

监督线向共享底座提供：

- `supervised_evolution_run` 的 lifecycle snapshot、event tail、decision/proposal 关联路径。
- dataset/bundle 的 review 边界提示，例如 `chat_reviewed_multiturn` 只代表人工审核后的多轮对话 case。
- 每个 case 的 verification artifacts：trace、final state、side effects、failure taxonomy、score breakdown。
- decision record 和 proposal action 的 provenance。

当前实现补充：

- 普通监督 run 使用 `runKind=supervised_evolution_run` 和 `leases=["evaluation"]`。
- 工作树式监督闭环使用 `runKind=supervised_worktree_evolution_run` 和 `leases=["evaluation", "worktree_write"]`。
- `manual_review` 允许人工治理 proposal；`auto` 锁定人工接纳、激活、回滚、编辑和删除。
- `simulation` 是工作树式监督闭环默认安全执行模式；`real` 必须显式确认真实 LLM 成本。

## 论文启发到工程机制

- WildClawBench：引入 hybrid verification，把最终状态、工具副作用、transcript、日志和语义判断合并成决策证据。
- STT-Arena：构建动态 case，覆盖 temporal change、spatial/context change、spatio-temporal conflict、impossible task、重规划失败和适配后未验证。
- AgentGym-RL：把多轮交互任务做成统一 case 结构，支持 horizon scaling，先从短任务到长任务逐步增加难度。
- Spreadsheet-RL：对有明确文件状态的任务，优先使用 start-goal state pair 和 oracle final-state comparison。
- Shepherd：监督决策应能回放 trace，未来支持 counterfactual replay 对比 baseline/candidate。
- OpenClaw-RL：用户反馈、工具输出、终端/GUI 状态可作为外部行为信号，但必须经过 review 或 case materialization 才能进入正式评测。
- E-SPL：prompt evolution 只适合作为 candidate 生成机制；是否采用必须由 frozen evaluator 判断。

## 关键文件

核心评测：

- `core/evaluation/supervised_evolution.py`
- `core/evaluation/supervised_cli.py`
- `core/evaluation/dataset_registry.py`
- `core/evaluation/bundles/supervised_evolution_dry_run_v1.json`

策略与生命周期：

- `core/evaluation/selection_policy.py`
- `core/evaluation/lineage.py`
- `core/gym/promotion.py`
- `core/gym/advisory.py`
- `core/gym/README.md`

工作台与 Web：

- `core/evaluation/supervised_workbench.py`
- `core/evaluation/supervised_dashboard.py`
- `core/web/services/supervised_control_service.py`
- `core/web/services/evolution_service.py`
- `core/web/routes/evolution.py`
- `web/src/routes/EvolutionRoute.tsx`
- `web/src/api/types.ts`
- `web/src/i18n/dictionary.ts`

共享运行底座，如已引入：

- `core/runtime_manager/work_run_store.py`
- `core/runtime_manager/work_run_leases.py`
- `core/web/services/runtime_service.py`

工件：

- `workspace/supervised_evolution/decisions`
- `workspace/supervised_evolution/policy`
- `workspace/supervised_evolution/dashboard`
- `workspace/supervised_evolution/workbench_state.json`
- `workspace/gym/proposals`
- `workspace/gym/decisions`

测试：

- `tests/test_supervised_evolution.py`
- `tests/test_supervised_workbench.py`
- `tests/test_supervised_dashboard.py`
- `tests/test_dataset_registry.py`
- `tests/test_web_app.py`
- `tests/test_workbench.py`
- `tests/test_work_run_store.py`
- `tests/test_work_run_leases.py`

## 开发原则

1. 决策必须可回放。
   每次监督运行都要能从记录恢复出为什么 PROMOTE、HOLD 或 ROLLBACK。

2. PROMOTE 不等于生效。
   文案、API 字段和 dashboard 都必须区分 supervised decision、advisory baseline 和 runtime effect。

3. baseline 与 candidate 必须同条件比较。
   同一 bundle、同一 dataset limit、同一事务规则、同一禁止工具边界。

4. HOLD 必须有出口。
   observing 不能无限堆积，必须有预算、过期、终态和 lineage 表达。

5. Web 和 CLI 必须共享域逻辑。
   不允许 Web 另写一套监督决策或 proposal action 语义。

6. 评测要看状态，不只看文本。
   对文件、工具、代码、工作区任务，最终状态和副作用证据优先于语言解释。

7. 动态能力必须单独评测。
   需要区分 stale-state execution、误判动态触发、适配后未验证三类失败。

8. 监督线保护冻结标准。
   自进化、prompt evolution、skill evolution 只能产生候选，不能直接改写 `V_ref` 或 accepted baseline。

9. 接纳入口必须可追溯。
   reviewed chat case、generated case、self-evolution proposal 进入监督验收时，必须留下来源、review/provenance、允许用途和 evidence path。

10. 自动模式不能绕过治理。
    `auto` 可以生成候选、运行评测和整理建议，但不能替代人工 governance 直接 apply/activate/rollback/delete proposal。

## 三类输入进入监督验收的规则

### Reviewed Chat Case

准入路径：

1. Chat segment 进入 candidate queue。
2. 人工 review 后写入 positive/negative decision。
3. positive case 进入 `chat_reviewed_multiturn`。
4. dataset registry 将其物化为 `chat_reviewed_multiturn_v1` bundle。
5. 监督线只能从 materialized bundle 运行，不读取 raw chat transcript。

必须保持：

- `rawChatDirectTrainingAllowed=false`。
- `review_required=true`。
- `source_track=dialogue`。
- `holdout_allowed=false`，除非后续有独立 frozen holdout review 流程。
- downstream use 只允许 registry 明确列出的用途。
- `intake_boundary.contract=reviewed_chat_case`。
- bundle case 必须携带 positive review/approval 证据；pending/negative/discard/raw row 不得物化为正式监督 case。
- bundle case 必须保留审核后样本的 `dataset_ref`，至少能回溯到 `session_id`、`source_log_path`、`raw_excerpt_path` 或等价 evidence reference；监督 run 的 `intake_provenance`、policy evidence 和 proposal 不得丢失这条来源链。

测试锚点：

```powershell
pytest tests/test_chat_dataset_capture.py -v
pytest tests/test_dataset_registry.py -k "chat_reviewed or downstream" -v
pytest tests/test_supervised_evolution.py -k "materialized_reviewed_chat_case" -v
pytest tests/test_web_app.py -k "chat_review" -v
```

### Generated Case

准入路径：

1. Gym、trace diagnosis 或 harness gap 生成 candidate case。
2. 写入 `workspace/evaluation/datasets/generated_cases.jsonl`。
3. 每条 case 必须有 provenance：`source_trace_id`、`source_episode_id`、`source_harness_gap`、`generation_reason`、`creator_version`、`created_at`、`allowed_splits`。
4. `dataset_splits` 必须是 provenance `allowed_splits` 的子集。
5. 禁止自动进入 `holdout`。

必须保持：

- generated case 可以用于 observe/dev/regression 压力测试。
- generated case 不能无 review 晋升为 frozen holdout。
- generated case 的 provenance 要进入 bundle case，供 decision record 回放。
- `source_track=generated`、`holdout_allowed=false`、`raw_chat_direct_training_allowed=false`。
- `intake_boundary.contract=generated_case`。
- provenance、dataset split 和 downstream uses 必须进入 `intake_provenance`，供 selection policy proposal 回放。

测试锚点：

```powershell
pytest tests/test_dataset_registry.py -k "generated_cases or holdout or provenance" -v
```

### Self-Evolution Proposal

准入路径：

1. self-evolution 只能产出 candidate change、candidate case 或 proposal。
2. 监督线用固定 bundle/dataset 对 baseline 与 candidate 做同条件评测。
3. decision record 写出 PROMOTE/HOLD/ROLLBACK/REJECT/INCONCLUSIVE 及 gate 证据。
4. selection policy 生成 proposal/advisory/observation/rejection/rollback 工件。
5. apply/activate/rollback 只能走 proposal lifecycle action，且 `manual_review` 模式下才允许人工治理动作。

必须保持：

- PROMOTE 是监督结论，不是 runtime 生效。
- `runtime_effect=not_applied` 与 `agent_consumption=advisory` 必须在 dashboard/workbench/Web 中可见。
- 无监督线不能直接改 policy、accepted baseline registry、frozen evaluator 或 runtime 配置。
- 监督侧 accepted baseline registry 属于 `V_ref`/frozen evaluator 工件，不是线上 runtime prompt。
- candidate pool 记录必须保持 `review_state=pending`、`supervised_required=true`、`candidate_only=true`、`auto_apply=false`。
- `supervised_intake_boundary.contract=self_evolution_candidate`，且 blocked downstream uses 必须包含 `accepted_baseline`、`selection_policy`、`runtime_prompt_override`。

测试锚点：

```powershell
pytest tests/test_supervised_evolution.py -k "decision or policy or INCONCLUSIVE" -v
pytest tests/test_supervised_workbench.py -k "promotion or lifecycle" -v
pytest tests/test_web_app.py -k "proposal or auto_review_mode" -v
```

## 优先任务

### P0-1：把 hybrid verification 固化为 decision schema（已完成 v1）

目标：把当前分散在 `difference_metrics`、gate metrics、run reports 里的证据固化成可回放 schema。

已完成：

- 在 `CaseDecisionSummary` 上新增正式 `score_breakdown`。
- 将 `difference_reasons` 升级或映射为 `failure_taxonomy`。
- 在 decision record 中补 `evidence_paths`，统一引用 role report、trace、diff、logs、proposal、Gym decision。
- 保留旧字段，保证 dashboard/workbench 对历史记录兼容。

仍可补强：

- `semantic_score` 当前从 final state 派生，尚未接入独立语义裁判。
- `evidence_paths` 当前覆盖 role report/worktree/conversation/debug 文件，尚未统一 Gym trace、diff artifact 和 runtime scene child log。

文件影响：

- `core/evaluation/supervised_evolution.py`
- `core/evaluation/selection_policy.py`
- `core/evaluation/supervised_dashboard.py`
- `core/web/services/evolution_service.py`
- `tests/test_supervised_evolution.py`
- `tests/test_supervised_dashboard.py`
- `tests/test_web_app.py`

风险：

- 历史 decision record 可能缺字段，读取层必须做默认值。
- score 名称一旦暴露给 Web，会成为事实 API，先保持小而稳定。

建议测试：

```powershell
pytest tests/test_supervised_evolution.py -k "case or score or decision or INCONCLUSIVE" -v
pytest tests/test_supervised_dashboard.py -k "artifact or decision" -v
pytest tests/test_web_app.py -k "proposal or evolution_routes_use_real_supervised_records" -v
```

### P0-2：锁定三类输入准入边界（已完成核心契约）

目标：reviewed chat case、generated case、self-evolution proposal 都能进入监督验收，但不能污染 `V_ref`。

已完成：

- 新增 `core/evaluation/supervised_intake.py`，集中定义 reviewed chat、generated case、self-evolution candidate 的准入 contract。
- `chat_reviewed_multiturn` 现在只物化 positive reviewed row，bundle dataset/case 都携带 intake boundary。
- reviewed chat 物化时优先保留 row 自带 `dataset_ref`，确保会话来源、source log、raw excerpt 和 turn range 进入 `intake_provenance`，并随 decision/policy/proposal 回放。
- `generated_cases` registry 会强制回填 generated 来源、非 holdout、禁止 raw-chat direct training 和 allowed downstream uses；bundle case 携带 provenance、source track 与 intake boundary。
- `CaseDecisionSummary`、selection policy case evidence 和 proposal 均携带 `intake_provenance`，可回放 case 来源和准入证据。
- self-evolution candidate pool 写入 `supervised_intake_boundary`，并继续强制 candidate-only/pending/supervised-required/no-auto-apply。
- Web supervised workbench dataset payload 透出 `intakeBoundary` 与 `formalSupervisedEvaluationAllowed`；proposal/detail 层的 `intakeProvenance` 展示仍留给 P0-3/P1-2 读取层统一。

后续仍可补强：

- UI 文案可以继续把 reviewed case / supervised pressure / future training export 分层讲得更直白。
- self-evolution candidate 当前是只读 pending source；是否进入正式 proposal action run 仍留给 P0-3 / proposal_action 工作。

文件影响：

- `core/evaluation/supervised_intake.py`
- `core/evaluation/chat_case_lifecycle.py`
- `core/evaluation/dataset_registry.py`
- `core/evaluation/self_evolution_candidate_pool.py`
- `core/evaluation/supervised_evolution.py`
- `core/evaluation/selection_policy.py`
- `core/web/services/evolution_service.py`
- `core/web/services/supervised_control_service.py`
- `tests/test_chat_dataset_capture.py`
- `tests/test_dataset_registry.py`
- `tests/test_supervised_evolution.py`
- `tests/test_self_evolution_candidate_pool.py`
- `tests/test_web_app.py`

风险：

- Web 文案容易把 reviewed chat case 说成 training data；必须坚持“reviewed case / supervised pressure / future training export”分层。
- generated case 的 split 和 provenance 校验如果过严，可能阻塞已有本地实验数据；错误信息要可修复。

建议测试：

```powershell
pytest tests/test_chat_dataset_capture.py -v
pytest tests/test_dataset_registry.py -k "chat_reviewed or generated_cases or downstream or holdout" -v
pytest tests/test_web_app.py -k "chat_review or dataset or auto_review_mode or proposal" -v
```

### P0-3：对齐 proposal lifecycle 与 frozen evaluator 边界

目标：让 PROMOTE、policy accepted baseline、Gym proposal、applied、active、runtime effect 的边界不再混淆。

当前状态：

- 已完成 policy proposal 明示边界：selection policy 写出的 proposal 会带 `supervised_decision`、`policy_action`、`proposal_status`、`runtime_effect=not_applied`、`agent_consumption=advisory` 和 `supervision_boundary`。
- 已完成 accepted baseline registry 明示边界：`accepted_baselines.json` 每条记录带 `scope=supervised_frozen_evaluator` 与 `supervision_boundary.accepted_baseline_registry_scope=supervised_policy_artifact`。
- 已完成 Web/API 读取边界：policy-only proposal 被 dashboard/evolution service 读取时会保留 proposal 内的 `runtime_effect` 与 `agent_consumption`。
- 已完成等价 runtime scene lifecycle event：apply/activate/rollback 成功会记录 `supervised_proposal_action.executed`，状态不允许时会记录 `supervised_proposal_action.blocked`。
- 尚未完成独立 `WorkRun(proposal_action)`；当前仍通过 audit log、policy record、proposal file 和 runtime scene lifecycle event 提供可回放证据。

重点检查：

- decision record / policy record / proposal 是否明确写出 `supervised_decision`、`policy_action`、`proposal_status`、`runtime_effect`、`agent_consumption`。
- PROMOTE 后 selection policy 对 accepted baseline registry 的更新是否持续被描述为监督侧 frozen evaluator 工件，而不是 runtime 改写。
- active proposal 是否仍禁止直接删除；applied/active/rolled_back/superseded/promoted 是否禁止编辑草稿。
- proposal action 后续是否需要从等价 lifecycle event 升级为独立 `WorkRun(proposal_action)`。

文件影响：

- `core/evaluation/selection_policy.py`
- `core/evaluation/supervised_workbench.py`
- `core/evaluation/supervised_dashboard.py`
- `core/web/services/evolution_service.py`
- `core/web/services/supervised_control_service.py`
- `tests/test_supervised_workbench.py`
- `tests/test_web_app.py`

风险：

- 如果把 accepted baseline registry 误写成 runtime baseline，会破坏 PROMOTE 边界。
- 如果 action 状态过度收紧，会阻塞必要的人工回滚；回滚必须始终保留可解释路径。

建议测试：

```powershell
pytest tests/test_supervised_workbench.py -k "promotion or lifecycle" -v
pytest tests/test_web_app.py -k "proposal or delete or action or auto_review_mode" -v
```

### P1-1：增加动态和不可完成 case

目标：让监督评测覆盖真实 agent 常见失败：环境变化、工具失败、用户改目标、任务不可行、适配后未验证。

当前状态：

- 已完成最小 schema：bundle case 可携带 `case_type`，支持 `static`、`dynamic_replanning`、`impossible_task`、`reviewed_chat`、`generated_case`。
- 已完成最小 materialization：dynamic/impossible JSONL row 会校验 provenance 与 expected outcome，并写入 materialized bundle。
- 已完成最小 decision path：`CaseDecisionSummary`、policy case evidence 和 proposal 会保留 `case_type`、expected final/infeasible outcome、dynamic events、expected outcome verification、score breakdown、failure taxonomy 和 evidence paths。
- 已完成最小核验路径：dynamic case 从 harness `evolution_summary.final_state` / `post_adaptation_final_state` / `observed_final_state` 读取实际最终状态；impossible case 从 `evolution_summary.infeasible_outcome` / `observed_infeasible_outcome` 读取实际不可完成结果；核验采用 expected dict 子集匹配，缺证据或 mismatch 会进入 taxonomy 与 score breakdown。
- 已完成最小 harness fixture：`scripts/evolution_harness.py` 新增 `dynamic_replanning_fixture` 与 `impossible_task_fixture` scenario，要求 agent 在最终回复输出单行 JSON marker：`SUPERVISED_FINAL_STATE: {...}` 或 `SUPERVISED_INFEASIBLE_OUTCOME: {...}`；`infer_evolution_summary()` 会提取 marker 并写入顶层 `final_state` / `infeasible_outcome` 与 `supervised` 子对象，供监督 decision path 使用。
- 已完成内置 dry-run 接入：`supervised_evolution_dry_run_v1` 新增 dynamic/impossible fixture case，携带 provenance、expected outcome 和 dynamic events。
- 已完成门控对齐：`transaction`、`modify_rollback`、`full_evolution` 继续要求完整 open/close transaction；`dynamic_replanning_fixture` 与 `impossible_task_fixture` 是 marker-only 场景，不把缺少事务开关当成 legality failure，但仍受 commit 越界、运行状态和 expected outcome verification 约束。
- 已完成真实 smoke：真实 agent 对 dynamic/impossible fixture 的最终 `llm_response` 能输出 marker；harness 已从 conversation event、stdout 和 debug 三类来源提取 marker，避免只看 stdout/debug 导致误判。
- 尚未完成真实 STT-Arena 风格动态执行器；当前 fixture 只能提供稳定 outcome marker 与最小核验闭环，不能替代完整动态 benchmark。

建议 case 类型：

- 中途文件状态变化。
- 工具第一次失败，第二次可恢复。
- 用户追加约束导致原计划失效。
- 任务本身不可完成，需要明确报告不可行。
- 需要 stop 后 continue 才能恢复上下文。
- 需要执行后验证，而不是只给解释。

建议测试：

```powershell
pytest tests/test_dataset_registry.py -k "dynamic or generated_cases" -v
pytest tests/test_supervised_evolution.py -k "dynamic or impossible or replanning" -v
```

### P1-2：统一监督事实源

目标：无论记录来自 `decisions/`、`policy/`、Gym proposal 还是 worktree run，都能被 dashboard、workbench 和 Web 稳定读取。

当前状态：

- 已新增 `core/evaluation/supervised_artifacts.py` 作为监督事实源读取 helper，先统一 policy proposal artifact、project path 安全解析和 target key 生成。
- `supervised_dashboard.py` 已改用共享 helper 读取 policy-only proposal，避免 dashboard 独立维护一套 proposal path / target key 解析。
- Web `caseDiagnostics` 已改用共享 helper 生成，保留 `caseType`、expected final/infeasible outcome、dynamic events、score breakdown、failure taxonomy 和 evidence paths 的 API 形状不变。
- Web detail/preview 的只读 JSON artifact 加载已改用共享 helper，项目外路径、坏 JSON、非 object JSON 都不会进入 detail payload。
- `load_gym_promotion_lifecycle()` 已改用共享 JSON artifact loader 读取 Gym proposal，保持 missing/invalid lifecycle 语义，并阻止项目外 proposal 路径进入 proposal action 链。
- `load_gym_promotion_lifecycle()` 读取 decision record gates 时也已委托共享项目内 JSON object loader；项目外 decision record 不会再把 proposal path 注入 lifecycle。
- workbench/Web 仍有各自的 decision history、lifecycle 和 detail payload 组装逻辑；后续可继续把 decision record、policy record 与 worktree run artifact 聚合迁移到同一 helper。

重点检查：

- `core/evaluation/supervised_artifacts.py` 是否继续承载更多 decision/policy/worktree artifact 读取，而不是让 UI 层散读文件。
- Web/API 的 `caseDiagnostics` 是否只消费共享 helper 输出，不在路由服务里重新解释 case schema。
- Web/API 的 detail raw payload 是否只通过项目内 JSON object artifact loader 读取，避免路径逃逸或非 object payload 污染监督事实面。
- Gym proposal lifecycle 是否继续通过共享 artifact loader 区分 loaded/missing/invalid/unsafe，而不是在 workbench 内部散读 JSON。
- Gym proposal lifecycle 的 decision gates 是否只从项目内 decision record 读取，避免项目外 decision 文件注入 proposal path。
- policy-only 历史记录是否能回放。
- decision 记录里是否包含 proposal path、policy action、runtime effect。
- decision 记录里是否包含 verification artifacts 和 trace/provenance 路径。

建议测试：

```powershell
pytest tests/test_supervised_dashboard.py -v
pytest tests/test_supervised_workbench.py -v
pytest tests/test_web_app.py -k "evolution_routes_use_real_supervised_records or supervised_run or proposal" -v
pytest tests/test_supervised_artifacts.py -v
```

### P1-3：稳定监督运行控制

目标：Web 启动、暂停、恢复、停止监督运行时，状态不会卡死或污染下一轮。

重点检查：

- 单 active run 锁只在 `supervised_evolution_run` kind 内生效。
- SSE event tail。
- pause/resume/terminate 结果。
- dataset limit 是否只写入独立 bundle，不污染默认 dry-run bundle。
- open/close evolution transaction 是否显式完成。
- `evaluation` lease 是否和 self-evolution/write lease 正确互斥或并行。

建议测试：

```powershell
pytest tests/test_web_app.py -k "start_supervised_run or active_supervised or pause_resume" -v
pytest tests/test_dataset_registry.py -k "supervised_bundle" -v
pytest tests/test_work_run_leases.py -v
```

### P2-1：扩展 case 生成与缺口反馈

目标：用监督结果反向提示 Gym/self-evolution 生成更有区分度的 case，但仍通过 review/provenance 进入 dataset。

重点检查：

- 从 recent decision 的 `failure_taxonomy` 聚合弱点分布。
- 生成新 case 时写入 `source_trace_id` 和 `source_harness_gap`。
- 默认写 observe/regression，不写 holdout。
- 提供人工 review 入口，再进入更高信任 split。

建议测试：

```powershell
pytest tests/test_dataset_registry.py -k "generated_cases or provenance" -v
pytest tests/test_supervised_evolution.py -k "taxonomy or generated" -v
```

## 与对话线的接口

监督线可以读取：

- `chat_reviewed_multiturn` 这类经人工审核的对话数据集。
- 对话线提供的最终用户接受样本。
- 工具调用和任务结果作为 case 元数据。
- next-state signal 的审核后摘要。
- 动态变化和重规划证据。

监督线不能要求对话线：

- 直接把未审核聊天历史变成评测集。
- 为了监督评测改变 Chat 的消息展示结构。
- 在对话页展示 PROMOTE 等同于 runtime 生效。
- 让用户反馈信号绕过 review 直接进入 frozen evaluator。

## 与无监督进化线的接口

监督线向无监督线提供：

- active advisory baseline 摘要。
- 最近 decision 结果。
- proposal lifecycle 状态。
- 当前是否有 active supervised run。
- 最近失败 taxonomy 和弱点分布。
- 可生成新 case 的缺口提示。

监督线不应允许：

- 无监督线在 active supervised run 期间启动冲突运行。
- 无监督线绕过 proposal action 直接改 policy 工件。
- 无监督线把 HOLD/OBSERVE 当成可直接应用的改进。
- 无监督线直接修改 frozen holdout、selection policy 或 accepted baseline registry。

## 验收清单

- 每次监督运行都有 decision record。
- dashboard/workbench/Web 都读同一套事实。
- PROMOTE、applied、active、runtime effect 清楚分层。
- observing proposal 有预算和终态。
- active run 期间动作锁定。
- proposal action 的结果可回放、可撤销。
- dataset limit 不污染默认 bundle。
- 每个 case 结果包含 score breakdown 或明确说明为何只有单一分数。
- 动态/不可完成 case 有独立失败标签。
- reviewed chat case 和 generated case 的来源、review 边界和 downstream use 可见。
- 自进化产物只能作为候选进入监督验收，不能直接修改冻结标准。

## 推荐验证

```powershell
pytest tests/test_dataset_registry.py -v
pytest tests/test_supervised_evolution.py -v
pytest tests/test_supervised_workbench.py -v
pytest tests/test_supervised_dashboard.py -v
pytest tests/test_web_app.py -k "evolution or supervised or dataset" -v
pytest tests/test_work_run_store.py tests/test_work_run_leases.py -v
```

## 提交说明

监督进化线提交建议使用：

- `feat(supervised): ...`
- `fix(supervised): ...`
- `refactor(supervised): ...`
- `test(supervised): ...`

不要把 Chat UI、Self Evolution run control、Config security 的改动混进监督提交。
