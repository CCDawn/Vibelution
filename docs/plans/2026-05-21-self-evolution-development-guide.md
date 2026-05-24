# 无监督进化开发指导文档

本轮接手日期：2026-05-24

## 定位

无监督进化线负责让 Vibelution 在没有人类逐步评价每个候选的情况下，进行一轮受控、自证据驱动、自我约束的改进尝试。

它不是自由改写系统，也不是监督进化的替代品。它的职责是读取当前目标、工作区现场、最近事务、监督建议和运行证据，决定是否启动一轮 bounded self-evolution，并在运行后留下可诊断、可回滚、可删除、可回到监督线验收的证据链。

当前阶段的核心目标：

- 对齐无监督进化的运行控制、事务边界和证据链。
- 把成功经验先收敛为 experience / candidate，而不是直接宣布 runtime 标准改变。
- 把 skill / prompt / proposal / generated case 全部纳入候选池语义。
- 明确所有候选最终必须回到监督线验收，不能自改 accepted baseline、selection policy 或冻结评测面。

## 当前实现事实

### 运行控制

- `core/web/services/self_evolution_control_service.py` 已经实现网页自进化的 start、pause、resume、stop、rollback、handoff 和 SSE 事件流。
- 自进化 run snapshot 带 `runKind=self_evolution_run`、`leases=[evolution_transaction, worktree_write, memory_write]`、`runtimeManagerControl.ownerPid`、`rollback` 和 `artifacts`。
- live runtime-manager 模式下，自进化控制会通过 `submit_command()` 转交 runtime manager；非 live 模式保留本地 executor 兜底。
- start/resume 会拒绝写入型 chat turn、active supervised run、active supervised worktree run，以及 lease policy 判定出的资源冲突。
- queued / running / paused / stopping 都属于 locked status；done / failed / cancelled 属于 final status。
- stale / orphaned self run 会通过 `ownerPid` 与当前 runtime-manager pid 对齐；owner 不匹配或 active index 丢失时会自动改写为 `cancelled` 并清空 active index。
- 工作台关闭前会通过 runtime shutdown / daemon close path 收口 active self / supervised evolution run，避免留下假 active。

### WorkRun 与 lease

- `core/runtime_manager/work_run_store.py` 已经提供共享 `WorkRunStore`，按 `runKind` 持久化 active/latest snapshot，并把 lifecycle 变化写入 runtime scene。
- `core/runtime_manager/evolution_store.py` 已经通过 legacy facade 复用 `WorkRunStore`；当前 self/supervised 仍使用 legacy kind `self` / `supervised` 路径，但语义上对应 `self_evolution_run` / `supervised_evolution_run`。
- `core/runtime_manager/work_run_leases.py` 已经定义初始 lease policy：
  - `readonly_chat` 不阻塞 supervised/self。
  - `self_evolution_run` 默认占用 `evolution_transaction`、`worktree_write`、`memory_write`。
  - `supervised_evolution_run` 默认占用 `evaluation`。
  - `supervised_worktree_evolution_run` 占用 `evaluation` 和 `worktree_write`。
  - write / evaluation / evolution_transaction 之间按冲突矩阵互斥。
- `core/web/services/session_service.py` 已把 chat turn 注册为 `WorkRun(chat_turn)`，并用 `infer_chat_turn_leases()` 区分 readonly 与 write intent。
- `core/web/services/runtime_service.py` 已在 runtime summary 中暴露 `workRuns.active/latest`，覆盖 chat、self、supervised、supervised worktree。

### 事务边界

- `core/infrastructure/git_memory.py` 负责 `open_evolution_transaction()` / `close_evolution_transaction()`，事务写入 `EvolutionTransaction`，并发布 `EVOLUTION_TXN_OPENED` / `EVOLUTION_TXN_CLOSED`。
- `tools.git_tools.open_evolution_transaction_tool()` 会设置 session active txn；`close_evolution_transaction_tool()` 会清空 active txn。
- validation 事件不会自动关闭 active txn；事务必须显式 close。
- `GitMemoryService.note_file_modified()` 只追踪 dirty state 和 attention，不会因为修改 risky path 自动开账。
- `core/infrastructure/evolution_governor.py` 对 risky write 做运行时拦截：
  - 没有 active txn 时，写入 `core/`、`tools/`、`config/`、`workspace/prompts/`、`agent.py` 会被拒绝。
  - 有 active txn 时，只允许写入 `config.evolution.allowed_target_dirs`。
  - mutation blocked / recorded、txn opened / closed、validation completed 会进入 `workspace/evolution/audit.jsonl`。
- `core/infrastructure/tool_executor.py` 在工具执行前调用 governor，并在工具执行后记录 mutation result。

### 证据链与回滚

- `self_evolution_control_service` 在启动前通过 `_capture_preflight_state()` 记录 git base rev、dirty files、backup dir 和 manifest path。
- run 结束后通过 `_finalize_rollback_manifest()` 生成 rollback manifest；可安全回滚时前端状态为 `rollback.status=available`。
- 自动回滚会先检测进化后文件是否又被修改；冲突时阻断并要求 handoff 给会话 agent。
- runtime scene 已记录：
  - `self_evolution_run.preflight.captured`
  - `self_evolution_run.state.changed`
  - `self_evolution_run.turn.started`
  - `self_evolution_run.turn.completed`
  - `self_evolution_run.failed`
  - runtime-manager command succeeded / failed
- `WorkRunStore` 也记录 `work_run.snapshot.persisted` / rejected / deleted，用于统一 active/latest 生命周期证据。
- `core/evaluation/self_evolution_workbench.py` 已把 goal、active advisory baseline、worktree snapshot、recent transactions 和 fitness 写入 preview / run prompt。

### 候选与监督边界

- `generated_cases` 已作为 dataset registry 里的 generated dataset 存在；`core/evaluation/dataset_registry.py` 要求 generated case provenance，并阻止自动进入 holdout。
- `core/gym/generated_cases.py` 写入 generated case 时要求 provenance，且拒绝 `dataset_splits` 包含 `holdout`。
- `chat_reviewed_multiturn` 已带 `review_required`、`source_track`、`allowed_downstream_uses`、`raw_chat_direct_training_allowed=false` 等元数据。
- `docs/plans/2026-05-21-workrun-substrate-and-chat-case-loop.md` 已把 raw chat -> candidate -> review -> reviewed case -> dataset/bundle 定为共享边界。
- `core/evaluation/self_evolution_experience_repository.py` 已提供第一版 terminal experience repository：自进化终态 run 会写入 `workspace/self_evolution/experience/experience.jsonl`，并用 `self_terminal:<runId>` 去重。
- 目前还没有正式的 skill candidate / prompt candidate / proposal candidate 池存储层；experience record 也还没有被 P2/P3 机制消费。

## 当前文档与实现差距

1. WorkRun 底座不再只是“最新规划”。
   `WorkRunStore`、chat turn registration、runtime summary `workRuns`、resource lease policy 已部分落地；文档需要把它们写成当前事实，并保留 legacy `self` / `supervised` facade 仍存在的现实。

2. 事务和 risky write 边界已经比旧文档更具体。
   现在必须写清楚：risky write 没有 active txn 会被 tool executor 前置拦截；active txn 仍受 allowed target dirs 限制；validation 不会自动 close txn。

3. 证据链已经包含 runtime scene 和 rollback manifest。
   旧文档只说 evidence tail / rollback hook，未准确写出 preflight、child log、WorkRun lifecycle、ownerPid stale 收口和 rollback conflict handoff。

4. generated cases 已有部分监督边界；experience repository 已落地第一版，但仍只是候选来源。
   文档需要继续强调：experience record 不自动生效，不写 accepted baseline / selection policy，也还未接入 P2/P3 候选池消费。

5. skill / prompt / proposal candidate 池还缺统一契约。
   当前只有 generated case 和 chat reviewed case 有较明确的 registry / review 边界；skill candidate、prompt candidate、proposal candidate 还需要 schema、provenance、dedupe、quality score 和 supervised handoff。

6. self-questioning / self-navigating / self-attributing 还只是目标机制。
   现有实现能提供 worktree、fitness、recent transactions、runtime scene 和 tool trace，但还没有把三种机制固化为 bounded steps 和候选输出。

## 不可突破边界

- 无监督进化必须 bounded：每轮必须有目标、预算、停止条件、事务边界和可见结果。
- 不能自改评判标准：不得直接修改冻结评测集、accepted baseline、selection policy、supervised policy 或 holdout。
- 不能直接写入 accepted baseline 或 selection policy。
- risky write 必须走事务，并且事务内仍必须遵守 allowed target dirs。
- 成功经验只能先进入 experience repository / candidate pool，再回到监督线验收。
- generated case 默认不能进入 holdout；必须带 provenance 和 allowed splits。
- raw chat 不能直接变成训练/评测压力；必须经过 review。
- 自进化可以生成候选、证据和 handoff，但不能自己宣布候选生效。

## 产物分级

| 产物 | 当前允许落点 | 是否可直接生效 | 必须回到监督线验收 | 备注 |
|---|---|---:|---:|---|
| runtime scene event | `logs/runtime_scenes/` | 否 | 否 | 证据，不是策略。 |
| WorkRun snapshot | `.runtime/runtime-manager/...` | 否 | 否 | 运行状态，不是评判标准。 |
| audit record | `workspace/evolution/audit.jsonl` | 否 | 否 | 事务证据。 |
| rollback manifest | `workspace/web_self_evolution/<runId>/rollback_manifest.json` | 否 | 否 | 只用于恢复/交接。 |
| experience record | `workspace/self_evolution/experience/experience.jsonl` | 否 | 视 downstream use 而定 | 终态 run 第一版已写入；只作为候选来源。 |
| generated case | `workspace/evaluation/datasets/generated_cases.jsonl` | 否 | 是 | 已要求 provenance，不能自动 holdout。 |
| reviewed chat case | `chat_reviewed_multiturn` 数据集 | 否 | 是 | 必须 review 后进入 supervised/Gym。 |
| proposal candidate | 待建候选池或 `workspace/gym/proposals` | 否 | 是 | 不能直接写 accepted baseline。 |
| skill candidate | 待建候选池 | 否 | 是 | 只能作为候选 skill，不能自动安装/启用。 |
| prompt candidate | 待建候选池 | 否 | 是 | 不能直接覆盖 runtime prompt 或 accepted prompt。 |
| accepted baseline | 监督线 accepted registry | 是 | 已验收后 | 无监督线不得直接写。 |
| selection policy | 监督线 policy 文件/代码 | 是 | 已验收后 | 无监督线不得直接写。 |

## EvolveR 式经验闭环

目标：把一次性运行经验变成可审计、可去重、可候选化、但不直接生效的长期资产。

建议闭环：

1. Online experience capture
   - 来源：runtime scene、WorkRun snapshot、audit、tool trace、rollback manifest、recent transactions、fitness。
   - 输出：原始 experience record，只保存摘要、稳定 ID、路径引用和结果，不保存秘密、完整 prompt 或大段工具输出。

2. Cleaning and dedupe
   - 合并重复失败模式、重复成功策略和同一 root cause 的多条运行记录。
   - 以 `source_run_id`、`txn_id`、`event_code`、`tool_name`、`target_paths`、`failure_signature` 做去重锚点。

3. Integration
   - 把经验归类为 failure pattern、successful strategy、tool-use heuristic、diagnostic case、candidate prompt、candidate skill、candidate proposal。
   - 每条记录带 `quality_score`、`confidence`、`downstream_use` 和 `supervised_required=true/false`。

4. Distillation
   - 只把高质量经验蒸馏为 candidate。
   - distillation 产物仍是候选，不能直接改写 runtime prompt、skill library 或 policy。

5. Candidate generation
   - 生成 prompt candidate、skill candidate、proposal candidate、generated case。
   - 生成时必须携带 provenance：source run、source turn、txn id、runtime scene refs、audit refs、原因和限制。

6. Supervised validation
   - 候选回到监督线进入 proposal / dataset / review lifecycle。
   - 通过监督线验收后，才允许进入 accepted baseline、policy 或正式 skill/prompt registry。

## AgentEvolver 三机制工程化

### self-questioning

目的：从最近失败、重复错误、空白 case 和低 fitness 中主动提出 bounded 问题。

输入：

- 最近 failed / cancelled self run。
- `EvolutionGovernor.build_fitness_summary()`。
- runtime scene timeline/lifecycle。
- generated case 缺口和 chat review feedback。

输出：

- question candidate，不直接改代码。
- diagnostic case candidate。
- proposal candidate。

约束：

- 每轮最多生成少量问题，问题必须绑定 source evidence。
- 问题必须指向可验证行为，不生成泛泛愿望。

### self-navigating

目的：复用历史成功路径，减少重复漂移。

输入：

- successful transactions。
- validated tool sequence。
- previous rollback-free run。
- project memory lane 和 relevant plan docs。

输出：

- navigation hint / strategy candidate。
- tool-use heuristic candidate。

约束：

- 只能推荐路径，不能绕过 WorkRun lease、txn gate 或测试。
- 不允许因为历史成功就跳过当前现场检查。

### self-attributing

目的：把成功或失败归因到步骤、工具、prompt、文件、阶段和外部状态变化。

输入：

- tool trace。
- WorkRun state changes。
- audit mutation records。
- validation completed events。
- rollback touched files / conflicts。

输出：

- attribution record。
- failure pattern candidate。
- candidate quality score。

约束：

- 归因必须指向证据引用，不写无证据结论。
- attribution 只支持候选排序和诊断，不直接成为 selection policy。

## 可执行优先计划

### P0：对齐当前文档和实现边界

状态：本轮文档更新完成。

文件影响：

- `docs/plans/2026-05-21-self-evolution-development-guide.md`
- `.docs/project-memory/lanes/self-evolution-loop.json`
- `.docs/project-memory/*`
- `PROJECT_MEMORY.html`

风险：

- 文档把未落地机制写成已实现，会误导后续 agent。

测试锚点：

```powershell
git diff --check -- docs/plans/2026-05-21-self-evolution-development-guide.md
```

### P1：建立 experience repository

状态：第一版已落地。终态 self-evolution run 会生成摘要化 experience record，写入 `workspace/self_evolution/experience/experience.jsonl`，并记录 `self_evolution_run.experience_recorded` / `self_evolution_run.experience_record_failed` runtime scene 事件。该记录仍只是候选来源，不自动进入 accepted baseline、selection policy、runtime prompt 或正式 skill registry。

目标：把自进化运行经验从日志尾迹变成结构化候选来源。

已落地文件影响：

- 新增 `core/evaluation/self_evolution_experience_repository.py`
- 新增 `workspace/self_evolution/experience/experience.jsonl`
- 新增 `workspace/self_evolution/experience/index.json`
- 更新 `core/web/services/self_evolution_control_service.py`
- 新增 `tests/test_self_evolution_experience_repository.py`
- 更新 `tests/test_self_evolution_control_service.py`

最小 schema：

```json
{
  "experience_id": "exp_...",
  "kind": "failure_pattern | successful_strategy | tool_heuristic | diagnostic_case | prompt_candidate | skill_candidate | proposal_candidate",
  "source_run_id": "web-self-...",
  "source_turn": 1,
  "txn_id": "txn-...",
  "runtime_scene_refs": [],
  "audit_refs": [],
  "summary": "...",
  "evidence": {"status": "failed", "tool_name": "..."},
  "quality_score": 0.0,
  "confidence": 0.0,
  "dedupe_key": "...",
  "downstream_use": ["self_questioning", "supervised_candidate"],
  "supervised_required": true,
  "created_at": "..."
}
```

风险：

- 记录过多会噪声化；必须摘要化、去重、保留路径引用。
- 不能记录秘密、完整 prompt、大段工具输出或完整文件内容。

测试锚点：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_self_evolution_experience_repository.py -v
.\.venv\Scripts\python.exe -m pytest tests/test_self_evolution_control_service.py -k "experience or self_evolution_run" -v
```

### P2：把 self-questioning / self-navigating / self-attributing 固化为 bounded step

目标：每轮自进化结束后生成结构化问题、路径建议和归因，而不是自由展开。

建议文件影响：

- 新增 `core/evaluation/self_evolution_reflection.py`
- 更新 `core/evaluation/self_evolution_workbench.py`
- 更新 `core/web/services/self_evolution_control_service.py`
- 新增 `tests/test_self_evolution_reflection.py`

风险：

- 三机制如果直接喂回 prompt，容易形成无限循环。
- 归因若没有证据引用，会变成叙事污染。

测试锚点：

```powershell
pytest tests/test_self_evolution_reflection.py -v
pytest tests/test_self_evolution_control_service.py -k "failed or completed or runtime_scene" -v
```

### P3：建立 skill / prompt / proposal candidate 池

目标：无监督线可以产出候选，但不能自动安装、启用或 accepted。

建议文件影响：

- 新增 `core/evaluation/self_evolution_candidate_pool.py`
- 新增 `workspace/self_evolution/candidates/skill_candidates.jsonl`
- 新增 `workspace/self_evolution/candidates/prompt_candidates.jsonl`
- 新增 `workspace/self_evolution/candidates/proposal_candidates.jsonl`
- 更新 `core/gym/generated_cases.py`
- 更新 `core/evaluation/dataset_registry.py`
- 新增 `tests/test_self_evolution_candidate_pool.py`
- 更新 `tests/test_dataset_registry.py`

候选通用字段：

- `candidate_id`
- `candidate_type`
- `source_experience_id`
- `source_run_id`
- `txn_id`
- `provenance`
- `review_state=pending`
- `allowed_downstream_uses`
- `blocked_downstream_uses`
- `supervised_required=true`

风险：

- skill candidate 不能直接写入实际 skills 目录。
- prompt candidate 不能直接覆盖 runtime prompt。
- proposal candidate 不能直接写 accepted baseline 或 selection policy。

测试锚点：

```powershell
pytest tests/test_self_evolution_candidate_pool.py -v
pytest tests/test_dataset_registry.py -k "generated_cases or provenance or holdout" -v
```

### P4：把候选回流监督线

目标：成功经验和候选进入监督线 review / proposal / dataset lifecycle。

建议文件影响：

- 更新 `core/web/services/supervised_control_service.py`
- 更新 `core/web/services/evolution_service.py`
- 更新 `core/evaluation/dataset_registry.py`
- 更新 `web/src/routes/EvolutionRoute.tsx`
- 更新 `web/src/api/types.ts`
- 更新 `tests/test_web_app.py`
- 更新 `tests/test_dataset_registry.py`

风险：

- UI 文案必须明确“candidate / pending / reviewed / accepted”的区别。
- 不能把自进化成功 run 等同于监督验收通过。

测试锚点：

```powershell
pytest tests/test_web_app.py -k "self_evolution or supervised or candidate" -v
pytest tests/test_dataset_registry.py -k "generated_cases or chat_reviewed or downstream" -v
```

### P5：强化运行关闭和证据审计

目标：关闭、停止、失败、回滚冲突都可从日志包重建。

建议文件影响：

- 更新 `core/web/services/self_evolution_control_service.py`
- 更新 `core/runtime_manager/work_run_store.py`
- 更新 `core/web/services/runtime_service.py`
- 更新 `tests/test_self_evolution_control_service.py`
- 更新 `tests/test_web_app.py`
- 更新 `tests/test_work_run_store.py`

风险：

- lifecycle 日志过密会噪声化。
- duplicate snapshot 不能反复进入 lifecycle。

测试锚点：

```powershell
pytest tests/test_self_evolution_control_service.py -k "stale or orphaned or rollback or shutdown" -v
pytest tests/test_web_app.py -k "work_run or runtime_scene or shutdown" -v
pytest tests/test_work_run_store.py -v
```

## 与对话线的接口

无监督线可以读取：

- 当前用户目标。
- 最近对话上下文摘要。
- stop / continue 失败证据。
- runtime scene 和 conversation log。
- next-state signal 和 trace-driven failure pattern。
- reviewed chat case 的汇总信号。

无监督线不能修改：

- Chat 消息结构。
- ConversationView 展示规则。
- 用户对话历史原文。
- 对话线 stop / continue UI 语义。
- raw chat -> reviewed case 的 review 边界。

chat 进入进化压力的唯一路径：

```text
Raw Chat Segment -> Candidate -> Human/Review Decision -> ReviewedChatCase -> Dataset/Bundle
```

## 与监督进化线的接口

无监督线可以读取：

- active advisory baseline 摘要。
- 最近 supervised decision。
- proposal lifecycle 状态。
- 是否存在 active supervised run。
- 最近失败 taxonomy 和弱点分布。
- 监督线反馈的可生成 case 缺口。

无监督线可以提交候选：

- generated case candidate。
- proposal candidate。
- prompt candidate。
- skill candidate。
- diagnostic case candidate。

无监督线不能直接修改：

- `workspace/supervised_evolution/decisions`
- `workspace/supervised_evolution/policy`
- `core/evaluation/selection_policy.py`
- accepted baseline registry
- frozen holdout

任何自进化产出的“更好策略”都必须回到监督线验收，不能自己宣布生效。

## 关键文件

核心服务：

- `core/evaluation/self_evolution_workbench.py`
- `core/web/services/self_evolution_control_service.py`
- `core/web/routes/evolution.py`
- `core/runtime_manager/evolution_store.py`
- `core/runtime_manager/work_run_store.py`
- `core/runtime_manager/work_run_leases.py`
- `core/runtime_manager/daemon.py`

共享治理：

- `core/infrastructure/evolution_governor.py`
- `core/infrastructure/git_memory.py`
- `core/infrastructure/tool_executor.py`
- `core/gym/advisory.py`
- `core/gym/generated_cases.py`
- `core/evaluation/dataset_registry.py`
- `core/evaluation/chat_case_lifecycle.py`

前端：

- `web/src/routes/EvolutionRoute.tsx`
- `web/src/routes/EvolutionRoute.module.css`
- `web/src/api/client.ts`
- `web/src/api/types.ts`
- `web/src/store/shellStore.ts`
- `web/src/i18n/dictionary.ts`

工件：

- `workspace/evolution/audit.jsonl`
- `workspace/web_self_evolution/<runId>/rollback_manifest.json`
- `workspace/evaluation/datasets/generated_cases.jsonl`
- `workspace/evaluation/datasets/chat_reviewed_multiturn.jsonl`
- `workspace/gym/proposals`
- `.runtime/runtime-manager/evolution`
- `.runtime/runtime-manager/work_runs`
- `workspace/self_evolution/experience`
- 待建：`workspace/self_evolution/candidates`

测试：

- `tests/test_self_evolution_control_service.py`
- `tests/test_runtime_manager.py`
- `tests/test_work_run_store.py`
- `tests/test_work_run_leases.py`
- `tests/test_evolution_governor.py`
- `tests/test_git_memory.py`
- `tests/test_tool_executor.py`
- `tests/test_dataset_registry.py`
- `tests/test_web_app.py`

## 推荐验证

文档/计划变更：

```powershell
git diff --check -- docs/plans/2026-05-21-self-evolution-development-guide.md
```

运行控制与 WorkRun：

```powershell
pytest tests/test_self_evolution_control_service.py -v
pytest tests/test_runtime_manager.py -k "evolution or close_workbench" -v
pytest tests/test_work_run_store.py -v
pytest tests/test_work_run_leases.py -v
pytest tests/test_web_app.py -k "work_run or runtime_summary or self_evolution" -v
```

事务边界：

```powershell
pytest tests/test_tool_executor.py -k "evolution or risky or transaction" -v
pytest tests/test_evolution_governor.py -v
pytest tests/test_git_memory.py -k "evolution or transaction or risky" -v
```

候选与监督边界：

```powershell
pytest tests/test_dataset_registry.py -k "generated_cases or chat_reviewed or provenance or holdout" -v
pytest tests/test_web_app.py -k "chat_review or supervised or self_evolution" -v
```

## 第一轮建议优先补的 3 件事

1. 先建 experience repository。
   状态：第一版已完成。它现在是 EvolveR 闭环的入口，也是 self-questioning / self-navigating / self-attributing 的共同数据底座；下一步是让 P2 bounded reflection 消费这些记录，而不是继续从散落日志和自由文本里直接推断。

2. 把三种自反机制固化为 bounded step。
   self-questioning 只从证据生成问题，self-navigating 只复用有验证的路径，self-attributing 只生成可追溯归因；三者都不能直接修改 runtime 标准。

3. 建立 skill / prompt / proposal candidate 池并接回监督线。
   generated cases 已有较强边界，下一步要把 prompt、skill、proposal 也纳入同样的 provenance、review_state、downstream_use 和 supervised_required 契约。

## 提交说明

无监督进化线提交建议使用：

- `feat(self-evolution): ...`
- `fix(self-evolution): ...`
- `refactor(self-evolution): ...`
- `test(self-evolution): ...`
- `docs(self-evolution): ...`

不要把监督 selection policy、Chat UI、Config security 的无关改动混进无监督提交。
