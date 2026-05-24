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

## 优先任务

### 任务 1：增强差异信号

目标：减少“baseline 和 candidate 看起来差不多”的 HOLD 堆积。

可做方向：

- 设计更能暴露行为差异的 case。
- 把 trace-driven diagnosis 纳入 candidate 对比。
- 增强每个 case 的 failure reason。
- 对工具序列、事务开关、停止语义给出更细粒度评分。
- 引入 final state、side effects、trace quality、safety behavior 的 score breakdown。

建议测试：

```powershell
pytest tests/test_supervised_evolution.py -k "case or score or decision" -v
pytest tests/test_dataset_registry.py -v
```

### 任务 2：统一监督事实源

目标：无论记录来自 `decisions/`、`policy/` 还是 gym proposal，都能被 dashboard、workbench 和 Web 稳定读取。

重点检查：

- 是否需要引入或补齐 `core/evaluation/supervised_artifacts.py`。
- policy-only 历史记录是否能回放。
- decision 记录里是否包含 proposal path、policy action、runtime effect。
- decision 记录里是否包含 verification artifacts 和 trace/provenance 路径。

建议测试：

```powershell
pytest tests/test_supervised_dashboard.py -v
pytest tests/test_supervised_workbench.py -v
pytest tests/test_web_app.py -k "evolution_routes_use_real_supervised_records or supervised_run" -v
```

### 任务 3：建立 hybrid verification 结构

目标：每个 case 的结果不再只是 pass/fail 或单一 score，而是包含可解释证据。

建议字段：

- `final_state_score`：最终状态是否满足目标。
- `side_effect_score`：是否产生不允许的副作用。
- `trace_score`：工具顺序、重试、停止、事务是否合理。
- `safety_score`：是否越权、泄露或绕过 gate。
- `semantic_score`：必要时由语义判断补充。
- `failure_taxonomy`：失败标签。
- `evidence_paths`：trace、日志、diff、artifact 路径。

建议测试：

```powershell
pytest tests/test_supervised_evolution.py -k "verification or score or artifact" -v
pytest tests/test_supervised_dashboard.py -k "artifact or decision" -v
```

### 任务 4：增加动态和不可完成 case

目标：让监督评测覆盖真实 agent 常见失败：环境变化、工具失败、用户改目标、任务不可行、适配后未验证。

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

### 任务 5：收紧 proposal action 语义

目标：apply、activate、rollback、delete 都有清晰前置条件和用户可见解释。

重点检查：

- active run 存在时 proposal action 是否锁定。
- active proposal 是否禁止删除。
- missing/proposed/applied/active/rolled_back 的按钮状态是否合理。
- Web 和 CLI 文案是否都说明 runtime effect。
- proposal action 是否作为独立 `WorkRun(proposal_action)` 或等价事件留下证据。

建议测试：

```powershell
pytest tests/test_web_app.py -k "supervised_run_action or proposal or delete" -v
pytest tests/test_supervised_workbench.py -k "promotion or lifecycle" -v
```

### 任务 6：稳定监督运行控制

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

### 任务 7：接入 reviewed chat case 和 generated case

目标：把对话线与无监督线产生的候选增量纳入监督评测，但保持冻结验收边界。

重点检查：

- `chat_reviewed_multiturn` 标记为 reviewed-only。
- `generated_cases` 必须带 provenance、generator、review status 和 allowed downstream uses。
- 默认不把 chat reviewed case 或 generated case 放入 frozen holdout。
- UI 明确展示数据来源和风险边界。

建议测试：

```powershell
pytest tests/test_dataset_registry.py -k "chat_reviewed or generated_cases or downstream" -v
pytest tests/test_web_app.py -k "dataset or chat_review or evolution_workbench" -v
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
