# 2026-08-31 挑战杯假说质量与链路效率优化方案（假说优先链）

- **Status**: user-approved（方向与范围已获用户拍板，2026-08-31）
- **Owner**: challenge 链路 lane（实施任务各自建 claim）
- **Claim**: 本文档自身无代码 claim；实施任务 claim 按 §6 任务图逐任务建立
- **Scope**: `docs/plans/2026-08-31-challenge-cup-hypothesis-quality-efficiency-plan.md`（本文件）
- **Supersedes**: 无（不取代任何 ACTIVE 计划；与兄弟计划的去重边界见 §10）
- **Implementation link**: 实施分支按任务图命名 `codex/challenge-hypothesis-quality-*`，逐任务回填
- **Validation**: 见 §8 验证矩阵
- **Close condition**: §6 全部任务合入 main 且 §8 对照运行证据采集完成，本文移入 `docs/archive/`
- **证据基线**: main@fc700e8e2，2026-08-31；运行数据来自 `model_invocation_receipts`（463 条）、`meeting_rounds.jsonl`（332 轮）、`hypothesis_rounds.jsonl`（4 轮 12 候选）、22 个 source_collection run
- **非完成声明**: 本文是实施合同，不是完成证据；文中所有"目标值"为监测指标，除机制验收外不构成硬门（质量分数提升属实验结果）。

---

## 1. 结论

假说优先链当前有四个结构性短板，均有运行时实测证据：

1. **假说盲生成**：候选生成会议（round-0）开幕 topic 只含赛题正文+领域，无任何文献证据；候选几乎不带文献引用（12 个候选 11 个 `lineageRefs` 为空），五维均分 novelty=0.41 / evidenceSupport=0.51。
2. **评审全对开打**：pairwise 全对 C(n,2)（n=16 时 120 次调用），单次预算 450s、IO 并发 4，最坏小时级且易撞会议级 deadline 整会作废。
3. **无模型分级**：digest 与四个评审跑器全部钉死 evaluator 的 dialogue 槽 primary profile；实测 GLM-5.3-flash avg=184s vs deepseek-v4-flash avg=39s（4.7 倍）。
4. **检索串行且丢摘要**：3 provider × ≤12 query 全串行、arXiv 每请求 sleep 3s、15s 超时无重试、Crossref 429×14；去重"先到先得"使无摘要的 Crossref 版本挤掉带摘要的 OpenAlex/arXiv 版本。

本方案用六个任务（T1–T6）对应四个目标合同（C1–C4），核心机制全部来自已验证的外部实践（§4）：生成前证据预热 + 候选必带引用（T2/T5）、按跑器用途分槽分级（T1）、评审分层 tournament（T3）、检索并行化+摘要优先合并+课题级复用（T4/T5）、跨 attempt 候选去重（T6）。

**优先级与批次**：批次 1 = T1+T2（面不相交，可并行）；批次 2 = T3+T4；批次 3 = T5+T6。全部带配置开关，默认关闭，灰度开启。

---

## 2. 现状证据与根因

### 2.1 盲生成（质量第一根因）

- 开幕 topic 组装 `_generation_opening_topic`（`core/web/services/team_workflow/meeting_runtime.py:989-1012`）只拼 6 类内容：标题、赛题正文、领域、议程、规则、主持语。`_catalog_question_context`（`:973-987`）只读冻结目录 `science_125_questions.json`（`core/research/competition/resources.py:53`）。
- **时序事实（决定 T2 设计）**：生成会议是 round-0，开台时上游唯一可读领域知识就是赛题目录正文。problem_understanding artifact 是 `source_finding` 的输入合同（`problem_understanding_artifact_writer.py:1-6`），在生成会议**之后**产生；stage-1 collection 只在评审会 `request_new_evidence` 决策后触发（`hypothesis_first_chain.py:6-9` docstring、调用点 `:5249`、`:6012`）。三条开台路径（`run_creation.py:40-102` 自动开台、链内 `open_generation`/`retry_generation` `:2572`、HTTP `hypothesis_first.py:508`）都不传 artifact 上下文；`inputArtifactRefs` 机制已存在但链路传空（`hypothesis_first_chain.py:4630-4640`、`meeting_runtime.py:1422`）。
- 后果实测：12 候选 11 个 `lineageRefs` 空；metaReview 批评"缺少可追溯的具体文献、数据集和独立复核记录""本质上是 RH 的经典等价表述"（`hypothesis_rounds.jsonl`）。

### 2.2 评审全对 tournament（质量+效率双害）

- 评审 executor 四步：reflection（每候选 1 次）→ pairwise 全对 C(n,2) → Pareto → metaReview（`hypothesis_review_executor.py:227-248`；真跑器 `llm_review_runners.py:499-548`）。候选上限 `MAX_SELECTED_CANDIDATES=16`（`meeting_runtime.py:60`）→ 最多 120 次 pairwise。
- 单调用预算默认 450s（`challenge_deadline_policy.py:20-22`），评审 IO 并发 4（`hypothesis_review_executor.py:61-64`）。实测 review 阶段 avg=123s > generation 81s。
- 撞 `challengeDeadlineAtMs` 时整会作废（`meeting_runtime.py:1997-2027`），已花费调用全部浪费。

### 2.3 无模型分级（效率第一根因）

- `resolve_review_llm()` 是 digest+四跑器共用的唯一解析点（`llm_review_runners.py:168-243`）：硬编码 evaluator Agent 的 dialogue 槽（`:203-212`），`LLMInvocationContext.llm_slot` 亦钉死 `"dialogue"`（`:309`）。
- Agent 槽位机制本身完备：六槽位（`core/llm/agent_runtime.py:26-40`）、`llmBindings` SSOT（`:97-105`）、槽位解析回退链（`:128-188`）；仓内已有按任务选槽先例（`git_status_service.py:842` summary 槽、`config_service.py:1497` vision 槽），但挑战链未用。
- 正式 policy 兼容性（已核实）：`family` 精确匹配 `"qwen"` 走前缀正则（`question_result_package.py:68,389-392`），**turbo/plus/max 任意 qwen* 档位均通过 family 检查，无档位白名单**；且执行与门禁解耦（`challenge_question_runs.py:913-917`：非官方 provider 可跑，只是不进 official evidence ledger）。qwen 家族内分级合法。

### 2.4 检索串行 + 丢摘要 + 限流（效率第二根因）

- 3 provider × ≤12 query 全串行（`search_execution.py:234-364`）；arXiv 每请求后无条件 sleep 3s（`:853-854`，API ToU 要求保留）；15s 超时无重试（`:878-880`）。
- 去重按 `sourceIdentityKey`（DOI/URL/title+container，`residual.py:3283-3295`）**先到先得**，provider 顺序 Crossref 在前；Crossref 记录常无摘要，会把带重建摘要的 OpenAlex/arXiv 版本挤掉——`residual.py:3143-3145` 自认会 "starve the evidence pipeline"。
- 实测：crossref 429 失败 14 次；08-31 单题重跑 13 个 collection run；`duplicate_skipped` 137 次（去重在工作，但保的是错版本）。

### 2.5 不应误判为根因的现象

- **GLM 单次 184s 慢**不是根因——根因是"所有用途都跑同一强档模型"（§2.3）；换更快的全家桶不解决分级缺失。
- **429 限流**不是根因——根因是无限速治理的串行循环里单源失败拖垮整批；auto-retry（fc700e8e2）已兜终态，本方案治理"别打爆+别等死"。
- **会议卡 summarizing / open**（332 轮中 open=190、summarizing=63）属调度/生命周期域，已由 08-30 可靠性计划与 08-31 修复批覆盖，**本方案不碰会议调度**。
- **候选数量少（4 轮 12 候选）**是上游选区行为，非生成端缺陷；本方案提"单次 fan-out 多候选"只通过议程规则引导，不硬造数量。

---

## 3. 与既有计划/修复的去重边界

以下各项已有 owner，本方案**不做**：

| 已有项 | Owner | 出处 |
|---|---|---|
| 来源血缘按数组位置配对 | 已立项 | `docs/plans/2026-08-31-challenge-cup-nodes-1-7-high-roi-repair-plan.md` §1/§3 |
| pinned workflow definition 未贯穿下游 | 已立项 | 同上 §3 |
| writeback 预算 1×5 vs 四视角矛盾 | 已立项 | 同上 §1 结论 3 |
| 抽取回写契约失配（T5，0 物化） | 进行中 | 08-31 深夜自动化批（见项目记忆） |
| 采集失败自动重试 | 已合入 | fc700e8e2 |
| 三源 provider 集合（crossref+arxiv+openalex） | 已合入 | b4c93a211 / 14621a5fb |
| 会议调度/生命周期可靠性 | 另计划 | `2026-08-30-challenge-cup-automatic-chain-reliability-plan.md` |
| 自动推进政策（AutoAdvancePolicyV2） | shadow 阶段 | T2a 安全阶梯，不与本方案决策点重叠 |
| 节点 8–17 深实验 | 阶段 2 | a_then_b 合同（78c467b01），本方案仅阶段 1 |

本方案与上述计划的**接触面**只有一个：T2 的证据预热会新增一个检索触发点（生成前），与既有"评审会 evidenceRequest→子 run"回路并存，不改变后者语义（§5 C1）。

---

## 4. 外部调研与采用边界

采用（机制已核实）：

| 机制 | 来源 | 采进 |
|---|---|---|
| 分层评审：便宜初审淘汰→配对选择优化→仅 top 配对升级对辩 | Google AI co-scientist（arXiv 2502.18864；消融：无 debate 的 Elo 与专家偏好相关性差） | T3 |
| 假说必带证据链、每跳可回链文献 | KG-CoI（arXiv 2411.02382）；COLM 2024（2407.08940）：带检索的生成仍多数是幻觉，接地须显式 | T2 |
| 文献查重门（相似度阈值判"已有知识"） | AI Scientist v1/v2（2408.06292 / 2504.08066，τ=0.85） | T6（降级为无依赖版本，见 §5 C5） |
| 便宜模型跑量、贵模型综合终选 | FrugalGPT（2305.05176）/RouteLLM（2406.18665）；Agent Laboratory 实践 | T1 |
| 全局限速器治理并发检索 | paper-qa issue #381 实证 | T4 |
| 检索结果跨查询复用+delta 补新 | paper-qa 索引模式 | T5 |
| 3 并行 critic 最优、交互 3 轮封顶 | SIGDIAL 2025（2507.08350，7000 idea 扫描） | T3 参数依据（现有 3 轮预算不动） |
| LLM 自评不可靠，终排靠对辩+人类校准 | Stanford 2409.04109；novelty mirage 2606.12071 | T3 保留 metaReview+人工门，不引入"LLM 打分直选 top" |

不采用（明确出界）：

- **parallel tempering 冷热双池**（EvoDiverse 2606.10587）：质量证据好，但需多代进化循环编排，超出本阶段投入；列为远期演进。
- **embedding 语义去重/查重**（AI Scientist 模式）：仓内无 embedding 依赖（已核实 §2.3 边界），知识侧实施纪律是禁装新依赖；T6 用规范化文本相似度+LLM 判重的零依赖版本。
- **ToolUniverse / proxy 实验**：生物医学专用工具面，与 125 题（数学/物理等）不匹配；方向 A 不要求实验结果。
- **agentic tree search**（AI Scientist-v2）：依赖可执行实验反馈，阶段 1 无实验回路。

---

## 5. 目标合同

### C1 生成证据合同（T2，批次 1）

1. 候选生成会议开台前，必须完成 **evidence pack 物化**：优先命中 question 级缓存（T5 前为最小 per-question JSONL）；未命中时以受控 envelope（≤4 query × 三源 × ≤3 条）同步预检索一次（复用 `research_knowledge_collection_facade`，不新建 provider 逻辑），产物落 `workflow_artifact_store`，开台 payload 经 `inputArtifactRefs` 引用。
2. `_generation_opening_topic` 渲染 evidence pack 摘要段（题录+一句话摘要，上限 ~8 条、每条 ≤300 字符，防开幕 prompt 膨胀）。
3. CANDIDATE 发言行格式扩展：`CANDIDATE: <id> | <陈述> | <理由> | REFS: <分号分隔文献键> | CHECK: <可检验预测>`；解析器向后兼容旧三段格式；REFS 的文献键必须来自 evidence pack 或本轮会议已引用记录，登记时物化进 `hypothesis_candidate.lineageRefs`。
4. 既有"评审会 evidenceRequest→子 run"回路语义零变更（新增触发点为并行加法）。
5. 开关 `research.generation_evidence.mode = off|on`（默认 off），off 时行为与 main 完全一致。

### C2 评审分层合同（T3，批次 2）

1. executor 改三层：reflection 五维均分**粗排**，仅保留 top-K（默认 K=8，可配）进入配对；top-K 两两配对 C(K,2)；**top-M 配对（默认 M=4）升级对辩**（每对正反各一轮+裁决，复用现有 pairwise 跑器提示词扩展 debate 变体）；Pareto 与 metaReview 照旧。
2. n=16 时评审调用从 ~138 降至 ≤60（16 reflection + 28 pairwise + ≤18 debate + 2 汇总），K/M 可经配置校准。
3. FORMAL 模式（`HYPOTHESIS_REVIEW_FORMAL_MODE`）契约不破：分层各层仍用 provider-bound 真跑器并各出 receipt。
4. 开关 `research.hypothesis_review.tiering = off|on`（默认 off）；off 走旧全对路径（代码保留）。

### C3 模型分级合同（T1，批次 1）

1. `resolve_review_llm()` 增加 purpose 参数（`digest|reflection|pairwise|debate|pareto|metareview`），各 builder 按用途解析各自槽位；purpose→槽位映射默认表：digest/reflection→`summary` 槽，pairwise/debate/pareto/metareview→`dialogue` 槽。
2. 槽位缺失回退 dialogue（复用 `resolve_agent_llm` 回退链 `:144-149`），保证未配置 operator 环境行为不变；`LLMInvocationContext.llm_slot` 按实际槽位记录，receipt 可审计每个调用的槽位与模型。
3. operator 配置指引（文档）：`challenge_cup_evaluator` Agent 的 `llmBindings` 配 summary 槽为快档模型（dev 环境如 deepseek-v4-flash；正式环境 qwen 家族快档如 qwen-turbo），dialogue 槽维持强档。正式 policy family 检查对 qwen* 任意档位放行（§2.3 已核实）。
4. 不改会议讨论发言（round-robin 发言仍走各角色 Agent 自身模型）；只分级 digest+评审跑器这两个"链路侧"调用面。

### C4 检索层合同（T4+T5，批次 2/3）

1. provider 层并行执行（ThreadPool，per-provider 并发 1–2），arXiv 3s 间隔保留但不阻塞其他源；全局限速器（token bucket，per-provider 上限默认 crossref 1 rps polite / openalex 10 rps / arxiv 0.33 rps）；429/5xx 指数退避 ≤2 次后交 auto-retry 终态兜底。
2. 去重合并改**摘要优先**：同 identity key 多源命中时，保留带非空摘要版本（摘要最长者优先），Crossref 无摘要版本仅补元数据字段；`duplicate_skipped` 事件携带被挤出版本与原因。
3. T5：question 级 content-addressed 检索缓存——以 (questionId, provider, normalized query) 为键存最后结果集与时间戳，TTL 默认 24h；命中即零外呼。envelope/POLICY_VERSION 变更绕过缓存（与既有 ensure 指纹语义一致）。
4. 开关：并行与限速 `research.source_collection.parallel = off|on`（默认 off）；缓存 `research.source_collection.cache = off|on`（默认 off）。

### C5 候选去重合同（T6，批次 3）

1. 闭会登记候选时跨 attempt 语义去重：规范化陈述（小写、去停用词、n-gram）token Jaccard ≥ 阈值（默认 0.75）判疑似重复，疑似对交 cheap-LLM 判重（复用 T1 summary 槽），确认重复则合并进原 candidateId 并记录 alias，不再按新候选登记。
2. 零新依赖（无 embedding）；`hypothesis_candidate` 记录新增 `dedup: {method, matchedAliasOf?}` 字段。
3. 开关 `research.hypothesis_dedup = off|on`（默认 off）。

---

## 6. 实施任务图

| 任务 | 内容 | 主要文件面 | 依赖 | 验收点 |
|---|---|---|---|---|
| **T1 模型分级**（批次 1） | C3 全部：purpose 参数、槽位映射、回退、receipt 槽位记录、operator 配置指引文档 | `llm_review_runners.py`、`hypothesis_review_executor.py`（传参）、`tests/test_llm_review_runners*.py` 新增 | 无 | 单测：四跑器+digest 按 purpose 解析不同槽位；未配 summary 槽时回退 dialogue 且行为不变；receipt 含 slot 字段 |
| **T2 生成证据预热**（批次 1） | C1 全部：evidence pack 物化、topic 注入、CANDIDATE 格式扩展与解析、lineageRefs 物化、开关 | `meeting_runtime.py`（topic/议程/解析）、`hypothesis_first_chain.py`（开台 payload+登记）、`run_creation.py`（自动开台路径）、`research_knowledge_collection_facade` 调用（只读复用）、`docs/ops/config/INDEX.md` | 无（T1 独立） | 单测：命中缓存/未命中预检索两条注入路径；旧格式候选照常解析；lineageRefs 物化断言；off 开关回归零差异 |
| **T3 评审分层**（批次 2） | C2 全部：粗排/top-K 配对/top-M 对辩/debate 提示词变体、开关与回退 | `hypothesis_review_executor.py`、`llm_review_runners.py`（debate 跑器）、`tests/test_hypothesis_review_executor*.py` | T1（槽位接线先行，弱依赖） | 单测：n=16 调用数 ≤60 断言；K/M 参数化；FORMAL 模式 receipt 完整；off 路径与旧 executor 输出等价 |
| **T4 检索并行+摘要优先**（批次 2） | C4.1+C4.2：provider 并行、全局限速、退避、摘要优先合并 | `search_execution.py`、`residual.py`（合并策略）、`tests/test_source_collection_*.py` | 无 | 单测：并行执行收敛、限速器节流、同 key 多源保留带摘要版本、事件含挤出原因；arXiv 3s 间隔不阻塞他源 |
| **T5 检索缓存**（批次 3） | C4.3：question 级 content-addressed 缓存、TTL、指纹绕过；同时把 T2 的最小缓存升级为该 store | `search_execution.py`、`facade.py`、新 store 模块、`tests/` | T2（接管其最小缓存） | 单测：同键二次零外呼；envelope/POlICY_VERSION 变更绕过；TTL 过期重查 |
| **T6 候选去重**（批次 3） | C5 全部：规范化相似度+LLM 判重+alias 合并 | `hypothesis_first_chain.py`（登记）、新 dedup 模块、`tests/` | T1（summary 槽）、T2（登记物化点同区域，串行） | 单测：同陈述跨 attempt 合并 alias；非重复不误杀（构造近义不同题对照组）；off 零差异 |

批次纪律：批次内任务文件面不相交才并行；T2 与 T6 都触 `hypothesis_first_chain.py` 候选登记区域，必须串行（分批 1/批 3 已隔开）。

---

## 7. 预计文件影响面

- `core/web/services/team_workflow/llm_review_runners.py`（T1/T3）
- `core/web/services/team_workflow/research_runtime/hypothesis_review_executor.py`（T1/T3）
- `core/web/services/team_workflow/research_runtime/hypothesis_first_chain.py`（T2/T6）
- `core/web/services/team_workflow/meeting_runtime.py`（T2）
- `core/web/services/team_workflow/research_runtime/run_creation.py`（T2）
- `core/web/services/team_workflow/source_collection/search_execution.py`、`residual.py`、`facade.py`（T4/T5）
- 新增：evidence pack 物化模块、dedup 模块、检索缓存 store（各任务内定）
- `docs/ops/config/INDEX.md`（新开关登记）
- 对应 `tests/test_*` 若干

不触碰：`challenge_question_runs.py` policy 校验、会议调度/lifecycle、AutoAdvance 政策、普通 Agent Session 域、web/ 前端（无用户可见 UI 变更；receipt 槽位字段为后端 DTO 扩展）。

---

## 8. 验证矩阵

| 层 | 必须证明 | 建议命令/证据 |
|---|---|---|
| 单元/契约 | 各任务验收点（§6 末列） | 聚焦 pytest：`tests/test_research_workflow_hypothesis_first_chain.py`、`tests/test_llm_review_runners*.py`、`tests/test_hypothesis_review_executor*.py`、`tests/test_source_collection_*.py`（最终命令由 closeout selector 追加，不得删减） |
| 开关回归 | 四个开关全 off 时与 main 行为零差异 | 定向 pytest 全绿 + 一次 off 模式 dev 链路冒烟 |
| runtime-scene（机制） | T2 注入路径、T3 调用数、T4 并发限速、T5 缓存命中在真实链路生效 | dev 链路单题运行（SCI-003 或等价），receipts/事件流取证 |
| 对照运行（质量监测，非硬门） | 同题新旧配置各跑一次：五维均分、lineageRefs 非空率、评审调用数、检索批墙钟、二次运行外呼数 | `model_invocation_receipts` 聚合对比；基线=本文 §2 数据（novelty 0.41 / lineageRefs 1/12 / n=16 评审 138 次） |
| 真实 Launcher / 正式跑 | 正式 qwen 分级与 FORMAL 评审 receipt 完整性 | 另行授权（`CatalogRunAuthorization` 约束照旧） |

对照运行的预期监测值（非验收硬门）：lineageRefs 非空率 ≥80%；novelty/evidenceSupport 均分较基线提升（幅度作为实验结果记录）；n=16 评审调用 ≤60；检索批墙钟降幅 ≥40%（12 query×3 源场景）；同题二次运行检索外呼降 ≥70%。

---

## 9. 兼容、迁移与回滚

- 四个开关（`generation_evidence` / `hypothesis_review.tiering` / `source_collection.parallel+cache` / `hypothesis_dedup`）默认 off：合入即安全，operator 显式开启才生效；模式切换需重启后端（get_settings 懒单例，与 knowledge_sideflow 同语义）。
- CANDIDATE 旧格式解析保留（无 refs 字段照旧登记，lineageRefs 为空不算失败）；`hypothesis_candidate` 新字段均为可选追加，旧 JSONL 记录无需迁移。
- 旧全对 pairwise 路径代码保留为 tiering=off 分支，回滚=关开关；缓存 store 为纯新增文件，回滚=关开关+忽略旧缓存。
- T4 并行只改执行拓扑，不改 provider 协议与 POLICY_VERSION；若需让旧 run 受益新合并策略，由既有 POLICY_VERSION 机制另行决定（本方案不主动 bump）。

---

## 10. 停止条件与完成定义

1. **立即停止重对齐**：T2 预检索引入不可接受的开台延迟（>90s 且缓存未命中路径无法收敛）；T3 分层在 FORMAL 模式 receipt 出现缺口；T4 并行后限流/失败率不降反升；对照运行质量指标显著回退。
2. **代码阶段完成定义**：§6 六任务全部合入 main、聚焦测试绿、开关默认 off 的零差异回归通过。
3. **计划关闭归档**：§8 runtime-scene + 对照运行证据采集完成并回填本文 Implementation link 后，本文移入 `docs/archive/`；质量分数结论与参数校准（K/M/阈值）沉淀到新的校准记录，不回写本合同。
