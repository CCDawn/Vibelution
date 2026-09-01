# 挑战杯 10 并发链路改造与并发缺陷修复任务清单

> 文档 ID：`CC-PARALLEL-CONCURRENCY-10P-20260902`
>
> 状态：`USER-REQUESTED DIRECTION / ACTIVE PLAN / IMPLEMENTATION NOT STARTED`
>
> 权威路径：根 `main` 的 `docs/plans/2026-09-02-challenge-cup-10-parallel-concurrency-plan.md`
>
> 适用范围：挑战杯科研工作流（`challenge-cup-research@2.1.0/3.0.0`、knowledge sideflow、评审假说链、来源收集链、formal run）在 **10 条链路并发** 目标下的并发正确性改造与存量竞态修复
>
> 输入依据：2026-09-02 五路只读并发审查（账本/运行时、runner 批处理、评审假说、证据来源收集、跨链路共享资源），关键结论已由主 agent 亲验源码确认；同日四路仓外成熟方案调研（编排框架/科研多 agent/限流与基础设施工件/lease-fencing 工业实践）裁决结论见 §6，正文各任务方案要点已标注对标小节
>
> 非完成声明：本文是任务合同，不是代码完成、测试通过或并发能力已达成的证据

## 1. 结论与目标

用户目标：**10 条挑战杯链路（题目/run 级）同时推进**，不串线、不竞态、不超额烧预算。

审查结论决定改造分两层：

1. **存量缺陷层**：核心状态机（ledger 单写者 + run_version CAS + outbox lease + 五方 Discussion Scope 绑定门 + receipt 候选归属校验）防串线是扎实的；真实暴露面在搜索 circuit 并发失效、评审 fan-in 双花预算、文件读改写丢更新三类。
2. **并发能力层**：当前生产形态是「单 pump 线程串行驱动全部 ledger worker」——10 个 run 在 dispatch 层是排队推进的（LLM 等待型节点靠评审波 ThreadPoolExecutor 局部并行）。要真 10 并发必须并行化 dispatch 层，而这被三个未编码的隐性契约（单例无锁、lease 无中途续租、单 pump 唯一执行者）阻塞。

前置事实（已核实）：生产 backend 单进程多线程（`scripts/web_workbench.py:124`、`scripts/vibelution_desktop_entry.py:814` 的 `uvicorn.run` 均无 workers 参数）。所有 `threading` 锁在该前提下有效；跨进程窗口仅在 restart 重叠期存在。

## 2. 任务图

依赖关系：A（存量 P0）无依赖可立即开工；B1→B2→B3 为 10 并发关键路径；C 与 A/B 可并行；D 收口。**B3 合闸前 B1/B2 必须全绿**（否则多 worker 直接踩 lease fencing 与双 pump 缺口）。

### 批次 A — 存量 P0 修复（不依赖并发改造，先行）

#### A1 搜索 circuit 并发闭环

- **问题**（三叠加）：
  - 去重 TOCTOU：`core/web/services/team_workflow/source_collection/facade.py:947-1008`「读账本 gate 决策 → 建 run → 补记账本」无锁 check-then-act；`hypothesis_first_chain.py:6243` 与 `:7586` 两处调用均不在 `_WORKFLOW_LOCK` 内 → 并发相同 goal 双双全量执行。
  - 账本丢失更新：`search_circuit.py:626-653` append/outcome/marker 各自 read-modify-write 无锁 → 已用 variant 记忆丢失、重复派发。
  - 失败永久卡死：`core/web/services/data_processing_service.py:20` `RUN_STATUSES` 无 `failed`；`runs.py:979-1011` 搜索异常先 re-raise 不回写 outcome → run 永停 `collecting`，`facade.py:689` liveness 门不认死 → 该 goal 后续请求永久 `reuse_in_flight`。
- **改动面**：`source_collection/facade.py`、`search_circuit.py`、`runs.py`、`data_processing_service.py`。
- **方案要点**：ensure 的 gate→create→记账全序列纳入 team 级互斥（复用 `_WORKFLOW_LOCK` 或新增 per-team 锁）；circuit 账本 RMW 加锁（进程内 RLock，写已原子）；`RUN_STATUSES` 增 `failed` + 异常路径 finally 回写 outcome + liveness 门认 `failed` 为死。
- **验收**：并发双 ensure 恰建一 run；provider 抛异常后 run 转 `failed` 且后续同 goal 请求不再 `reuse_in_flight`；并发追加 circuit entry 无丢失；既有 `tests/test_source_collection_search_circuit.py` 22 用例全绿。

#### A2 评审 fan-in 生成前置查重

- **问题**：`hypothesis_first_chain.py:7185-7220`（`_generate_hypothesis_round`）在调用 `generate_hypothesis_round_from_meeting` 跑 LLM executor 前不预查同 roundId 是否已生成；幂等仅在落库时判定且要求逐字节一致 → 并发触发（sibling 会议先后 close、双击 approve、regenerate×自动）双花 n+C(n,2)+3 次 LLM 调用后才报 `hypothesis_round_content_conflict`。
- **改动面**：`hypothesis_first_chain.py`、`hypothesis_rounds.py`。
- **方案要点**：生成前按 roundId（内容寻址哈希已现成）+ 状态锁预读：存在非失败 round 直接复用返回；存在进行中生成则拒绝或等待（不伪装成功）。锁与 `hypothesis_rounds._LOCK` 同源。对标：见 §6.6（Stripe 式幂等表可作副作用级加固的二期选项，前置查重为一期最小闭环）。
- **验收**：并发两次触发，第二次在零 LLM 调用下复用/被拒；既有 fan-in、revision envelope 测试全绿。

### 批次 B — 10 并发架构前置（关键路径）

#### B1 生产 runtime 单例加锁

- **问题**：`core/web/services/team_workflow/research_runtime/runtime_factory.py:290-352` `start/stop_production_workflow_runtime` check-then-act 无锁，并发可双开 store + 双 pump，start/stop 交错可让旧 pump 引用已 close 的 store。
- **方案要点**：模块级锁包住 start/stop 全序列；双开 fail-closed 抛结构化错误；stop 等待 pump 排空后再关 store。对标 §6.1：补第二道持久层闸——ledger 状态机单行 CAS（`idle→starting`）作权威，CAS 失败拒绝启动。
- **验收**：并发 start 恰一成功；start×stop 交错无 `WorkflowLedgerClosedError` 抖动（并发用例钉住）。

#### B2 outbox lease invoke 中途续租（fencing 补强）

- **问题**：lease 默认 30s（`outbox.py:24`）无 invoke 心跳续租；`graph_dispatch_worker.py:746-770` 仅提交点 renew 作 fencing。单调用 >30s 且存在第二租用者时可双 invoke 同一 LangGraph thread，graph 副作用（checkpoint 双写/双 interrupt）不被撤销。当前单 pump 下靠隐式约定保护，多 worker 后立即放大。
- **方案要点**：长 invoke 期间周期性 `renew_outbox_lease`（复用 `adapter_dispatch_worker.py:669` 既有续租模式）；renew 失败（租已被夺）即中止本地副作用推进。lease 期限与 per-call 预算（450s 上限）对齐复核。对标 §6.2：续租周期 lease/3（10s）用 `Event.wait` 可中断；凭据升级为单调 `lease_epoch`（每次 re-claim +1）替代时钟比较；副作用发生点前置检查剩余租期。
- **验收**：invoke 超过 lease 期无第二执行者误入；被夺租的 worker 中途停止且提交点被既有 fencing 拒绝（扩展 `tests/test_research_workflow_graph_dispatch_lease_fencing.py`）。

#### B3 dispatch 并行化（10 并发本体）

- **问题**：`outbox_pump.py` 单线程串行驱动全部 worker；10 run 排队推进，不满足目标。
- **方案要点**：pump 并发 drain——N 个 worker 线程（目标 10，可配）各自经 outbox lease CAS 领任务天然分片；`run_workers_once` 与 coordinator 的线程安全复核（账本侧单写者模型已支持多线程提交）；`prepare_initial_checkpoint` 所在 HTTP 线程与 pump worker 的 checkpoint 并发写经 B4 兜底。对标 §6.3：`ThreadPoolExecutor(10)` 固定 worker；认领即执行严禁预取（Celery 教训）；LLM 型 action 认领前过 B5 全局信号量（slot supplier 思想）；退出用 cancel event 不干等 shutdown。
- **决策点**（对标 §6.3 已裁决）：固定 10 worker（不做弹性）；共享 coordinator + 每操作独立 SqliteSaver 连接保持；sideflow child run 与主 run 同池混跑（lease CAS 天然分片）。
- **前置**：B1、B2 全绿。
- **验收**：10 run 同时推进的并发压测中——每 action 恰一执行者、无 `INVALID_CONCURRENT_GRAPH_UPDATE` 未恢复残留、账本无 `database is locked` 失败、投影与账本一致。

#### B4 checkpoint 并发写加固

- **问题**：`checkpoint_store.py:884` 直连 sqlite3 未显式 busy_timeout（默认 5s，与 ledger 侧显式 5000ms 不一致）；B3 后 pump worker 与 HTTP 线程（`run_creation.py:688` 的 `prepare_initial_checkpoint`）真实并发写同库；`runtime.py:16-21` `VerticalSliceRuntime` 常驻连接是绕过单执行者约定的遗留第二写者。
- **方案要点**：显式 busy_timeout + WAL 校验对齐 ledger 标准；归档或强制独立路径处理 `VerticalSliceRuntime`；10 线程并发写压测（不同 thread_id）。对标 §6.4：每线程独立连接（严禁共享 connection）；统一连接工厂固定 `WAL + busy_timeout=5000 + synchronous=NORMAL + journal_size_limit=64MB`；autocheckpoint 默认不动、不常态化 TRUNCATE；10 run 单进程不迁 Postgres（LangGraph 官方定位）。
- **验收**：并发压测零锁失败；`_ensure_readable` 修复路径在并发 interrupt 下不产生脏 checkpoint。

#### B5 全局 LLM 并发/预算总闸

- **问题**：评审波每题各开 `MAX_CONCURRENT_REVIEW_CALLS=4`（`hypothesis_review_executor.py:78`），跨题无全局限额——10 并发即 40 路同时打 LLM；预算公式是每生成局部预算（`:1197`），无批次级总闸。
- **方案要点**：进程级全局信号量（上限可配，建议初始 10–16）包住评审 LLM 调用 acquire/release；per-call 450s 墙钟与 challenge deadline fence 保留不变；配速策略与 125 题批次编排层（zero-human roadmap §1.4）对齐。对标 §6.5：上限公式 ≈ provider_RPM × 平均墙钟 / 60（全局 8–12 起步）；三级结构（全局闸 → per-run ≤4 配置化 → candidate 内串行）；acquire 超时 120s 快速失败；429 冷却 30–60s 仅限该 model；10 链路 kickoff 错峰数十秒；对备方案为同库升级 `litellm.Router`（现有 `core/llm/client.py:1720` 走 `completion()` 直连）。
- **验收**：10 题并发下实测同时在途 LLM 调用 ≤ 上限；单题评审时长劣化有界（排队不饥饿，按 run 轮转或 FIFO）。

### 批次 C — 10 并发下放大的串线/丢写（与 A/B 并行）

#### C1 `PROJECT_ROOT` 全局换入换出改显式传参

- **问题**：`core/research/agent_runner.py:524-548,555-578,585-592,609-619` 对 `agent_directory_service` / `agent_mode_binding_service` / `prompt_template_service` 三个模块级 `PROJECT_ROOT` 做无锁 save-swap-restore——审查中**唯一真正的跨上下文串线口**（并行线程互相覆盖根目录，解析错 workspace 的 agent/prompt）。单 workspace 部署下症状隐匿，10 并发下高频触发。
- **方案要点**：三个 service 的读取路径增加显式 `project_root` 参数（默认回落模块值），agent_runner 直传不再改全局；全局字段保留只读兼容。
- **验收**：并发解析不同 workspace 的 agent profile 互不串线（并发用例）；移除 swap 后全部现有测试绿。

#### C2 `knowledge_base.json` 读改写加锁

- **问题**：`core/research/knowledge_base.py:90-141,187-200` `ingest_sources` 无锁 read-modify-write，并行 ingestion 丢条目；Windows 上 `os.replace` 目标被并发 reader 打开会 PermissionError。
- **方案要点**：模块级锁 + 走 `storage_durability`/原子写标准；读端容忍瞬态缺失（重试）。对标 §6.7：`with FileLock(path+".lock")` 包住 RMW 临界区、临界区内保留自研原子写；`thread_local=True` 默认 + `is_singleton=True`；`os.replace` 外包 PermissionError 指数退避（3–5 次）兜底 Windows 共享冲突。
- **验收**：并发 ingest 不丢条目用例；并发 read×write 无未捕获 PermissionError。

#### C3 同候选并发 dispatch TOCTOU 闭环

- **问题**：`hypothesis_first_chain.py:3923-3946` active-binding 检查 read-then-act 无锁；`meeting_rounds.py:280-284` `create_meeting_round` 无同 id 复用 → RETRY×自动派发并发时同 meeting id 双记录、讨论 token 翻倍。
- **方案要点**：meeting 创建幂等（同 id reuse，与 attempt 账本复用语义对齐）或 dispatch 全序列入 per-candidate 锁。
- **验收**：并发 dispatch 同候选恰一 meeting 记录。

#### C4 work-run active 单槽改多槽

- **问题**：`residual.py:1924-1936` active 判定仅认本 run；`work_run_store.persist_snapshot` 无锁 RMW；一 run 终态清空全局唯一 active 槽，抹掉他 run 活跃标记 → 第三路可再并发启动，投影错乱。
- **方案要点**：active 集 map 化（runId→snapshot）+ 写入加锁。
- **验收**：两 run 并行期间互不清除对方 active 标记。

#### C5 候选导入 check+register 同临界区

- **问题**：`source_collection/candidates.py:111-215` identity 去重在 `_WORKFLOW_LOCK` 内、`register_candidate_source`（`:23` 起，只 append 不查重）在锁外 → 并发导入同一 source 双份 manifest 候选。
- **方案要点**：register 挪入同一临界区，或 register 内部做 identity 幂等。
- **验收**：并发导入同一 source 恰一候选。

#### C6 外部搜索 provider 全局限速闸

- **问题**：`search_execution.py:879` arXiv 限速是线程内 sleep，多线程并行时全局失效（同 3s 窗口并发打 arXiv）；三 provider `urlopen(timeout=15)` 无重试无退避。历史 8/11 源 auth wall 背景下封禁代价高。
- **方案要点**：per-provider 进程级 token bucket（arXiv 1 req/3s 对齐 etiquette）；统一重试+指数退避。对标 §6.7：选 `pyrate-limiter` v4（新增轻依赖）——每 provider 一个模块级 `Limiter` 单例、`try_acquire()` 阻塞等许可、删除线程内 sleep；arXiv `Rate(1, 3s)`、Crossref polite pool ~3 req/s（URL 带 `mailto=`）；InMemoryBucket 进程内够用。
- **验收**：多线程并发搜索下 arXiv 实际请求间隔 ≥3s（mock 时钟断言）。

#### C7 formal run 纳入 active-work 体系与产物隔离

- **问题**：`daemon.py:329-383` 只枚举 chat/evolution 五种 run kind，formal full run（HTTP 线程同步执行最长 8 seed×7200s）不在 active-work/lease 体系，restart 打断留下孤儿子进程/半写产物；`formal_runner.py:166-180,274-296` 产物路径无 run 唯一段、`write_text` 非原子；`full_run.py:262-272` 防重入只按 (team,plan) 不校验 outputRoot 独占。
- **方案要点**：formal run 注册 work-run snapshot + lease；outputRoot 独占校验（同根拒绝启动）；汇总文件原子写；训练子进程挂 Job 对象实现 restart 连带清理（遵守无控制台红线）。
- **验收**：restart 期间 formal run 的子进程被确定性清理或明确报告为需人工处理；两个不同 plan 指向同一 outputRoot 时第二个被拒。

### 批次 D — 测试与验收收口

#### D1 并发回归矩阵

- 每个修复任务自带并发用例（上文各验收已列）；集中补齐缺口：circuit 并发、fan-in 双生成、并发 dispatch、knowledge_base 并发 ingest、PROJECT_ROOT 并发解析、shadow JSONL 并发追加（接入 `storage_durability.append_jsonl_locked` 的迁移用例）。
- 选择器：并发相关测试聚合成一个 marker/文件组，纳入 closeout selector。

#### D2 10 并发端到端验收（runtime-scene）

- 场景：10 题（或 10 run 混合主流程+sideflow）并发推进至各自首个 LLM 等待节点。
- 断言：receipt 候选归属 100% 正确（无串线）；账本零 `database is locked`/零双执行；全局 LLM 在途 ≤B5 上限；投影 `awaitingHumanCount` 与 Ledger 一致；预算消耗与单 run 基线对比无异常放大（无 fan-in 双花类重复）。

## 3. 遗留核实项（开工前/对应批次内先闭合）

| # | 事项 | 影响任务 | 现状 |
| --- | --- | --- | --- |
| V1 | reset 全链路是否所有入口都在 maintenance fence 内先停 pump（`challenge_cup_reset_service.py` 调用链） | B3（purge 后复活行） | 未核实 |
| V2 | Launcher restart 新旧进程是否严格串行（旧退再拉新） | C7、shadow 跨进程面 | 未核实 |
| V3 | shadow JSONL（`knowledge_rollout.py:196-246`）迁移到 `storage_durability.append_jsonl_locked` | D1 | 基础设施在，未接入 |
| V4 | `routes` 层 close/approve 是否有请求级 idempotency key 挡双击 | A2 兜底深度 | 未核实 |

## 4. 明确不做

- 不改普通 Agent 会话内核（Session admission/Journal/SSE）——并发改造只在挑战杯 research/team_workflow 面内。
- 不做多进程化——10 并发在单进程多线程内达成；跨进程仅 restart 窗口，经 C7 收敛。
- 不放松任何既有 fail-closed 门（lease fencing、scope 绑定、receipt 校验、预算门）来换取并发度。

## 5. 关键路径与推进顺序

```
A1 ─┐
A2 ─┼─→ (各自独立合入)
C1~C7 (与 A/B 并行，按 C1→C6→C2→C3→C4→C5→C7 建议序)
B1 → B2 → B3 → D2
B4 ─┘（B3 前置或同批）
B5（B3 合闸前）
D1（随各任务）
```

10 并发能力验收以 D2 通过为准；在此之前「10 并发」仅是配置目标，不是已达成事实。

## 6. 仓外成熟方案借鉴（2026-09-02 四路调研裁决）

> 依据：编排框架（Temporal/LangGraph/Celery/Azure DTF）、科研多 agent（co-scientist/AI-Scientist v1-v2/AutoGen/CrewAI/LiteLLM）、限流与基础设施工件（pyrate-limiter/filelock/SQLite 调优）、lease/heartbeat/fencing 工业实践（SQS/Azure/Kleppmann/Percolator/Sidekiq/Stripe）四路并行调研；AI-Scientist 部分为源码级取证。本节为裁决结论，正文各任务的「方案要点」已标注对标小节。

### 6.0 总体裁决

现有「SQLite lease CAS + 单写者线程 + 提交点 fencing」骨架与业界成熟实践**同构**：对标 Temporal 的 activity lease + fencing、Azure DTF 的存储层唯一性、LangGraph 官方对 SqliteSaver 的单进程定位，且优于 Celery 原生（静态 visibility timeout 无 fencing，超时即静默双执行）。**10 并发不需要任何重架构**——不引 broker、不引 Redis、不迁 PostgresSaver、不部署 LiteLLM 网关；全部缺口都是在现有骨架上补标准件。新增依赖仅两个轻库：`filelock`（零依赖，Windows 走内核 LockFileEx）、`pyrate-limiter`（v4，InMemoryBucket 线程安全）。

### 6.1 B1 对标：启动唯一性靠存储层，不靠调用方自觉

Azure Durable Functions 用固定 instance ID，重复 start 直接抛 `OrchestrationAlreadyExists`；Temporal workflow ID 同样由服务端唯一性拒绝。落法：**两道闸**——进程内 `threading.Lock` 串行化 start/stop 路径（挡并发线程）+ ledger 状态机单行 CAS（如 `idle→starting`）作为持久层权威（挡语义重复与重启竞态），CAS 失败即拒绝启动。不引入外部锁。

### 6.2 B2 对标：心跳续租 + epoch 验票

- **心跳模型**（SQS `ChangeMessageVisibility` / Temporal `RecordHeartbeat` / Azure `AutoLockRenewer` 同构）：worker 领取成功后起续租循环，**周期 = lease/3（30s lease → 10s）**，用 `threading.Event.wait(10)` 实现可中断睡眠；续租本身是 CAS（`UPDATE ... WHERE id=? AND <凭据>=?`），**rows_affected==0 即租约被夺，立即置 cancel event、中断 invoke，绝不跑完再试提交**。心跳线程必须活到任务结束才停——Azure Java SDK 自动续期默认只跑 5 分钟窗口导致长任务静默丢锁，是已知事故模式，不可复刻。
- **凭据升级为单调 epoch**（Percolator epoch 的单机版）：给每次 re-claim 的租约加单调 `lease_epoch` 列（每次重租 +1），领取/续租/提交/副作用前置检查全部比对 epoch，替代「owner 字符串 + expires_at 时钟」判断。Kleppmann 的核心结论在此适用且已被满足：**校验必须内建在存储侧**——SQLite 单写事务就是线性一致存储，现有 CAS 就是存储侧验票点，不需要独立 fencing token 服务；epoch 只是把验票从时钟比较升级为序号比较，消除时钟跳变依赖。
- **副作用前置检查**（Kleppmann「最后一刻检查救不了中途写入」）：每个副作用发生点（invoke 前、每次 LLM 调用前、checkpoint 写前）检查剩余租期是否覆盖该副作用最坏时长（LLM 按 60–120s 预算），不足则先续租、续不上就不发起。

### 6.3 B3 对标：固定 worker + 双层并发 + 禁预取

- **固定 N worker 优于弹性**（Temporal worker 模型）：N=10 可配置，一个 `ThreadPoolExecutor(max_workers=10)` 即可——负载是纯 API IO，GIL 在 I/O 期间释放，无需进程池。
- **认领即执行、严禁预取**（Celery prefetch 教训）：worker 循环「CAS 认领一条 outbox → 执行 → 提交」，崩溃时不存在囤积在本地未执行却占着 lease 的任务。
- **双层并发控制**（Temporal `maxConcurrentActivityTaskPollers` vs `maxConcurrentActivityTaskExecutions` 思想）：LLM 槽位（B5 总闸）在认领前检查——认领 graph/LLM 型 action 前先过全局信号量，对标 slot supplier。
- **退出路径**：Launcher stop 用 per-task cancel event（B2 的续租失败通道复用）而非干等 `shutdown(wait=True)` 被长 future 阻塞。
- 决策点裁决：固定 10 worker；共享 coordinator + 每操作独立 SqliteSaver 连接（现状模型）保持；sideflow child run 与主 run 同池混跑（lease CAS 天然分片，无串线风险）。

### 6.4 B4 对标：SqliteSaver 单进程定位 + 统一连接工厂

LangGraph 官方明确 SqliteSaver 定位单进程/本地、多 worker 生产场景才指定 PostgresSaver——与本项目单进程架构恰好匹配，**10 run 并发不迁 Postgres**。落法：**每线程独立连接**（严禁多线程共享一个 connection）；全部连接经统一工厂固定执行 `journal_mode=WAL` + `busy_timeout=5000` + `synchronous=NORMAL` + `journal_size_limit=67108864`；`wal_autocheckpoint` 保持默认 1000 页，不常态化 TRUNCATE（会阻塞读者；WAL 膨胀优先排查长事务/常驻读者）。

### 6.5 B5 对标：三级并发结构 + 错峰 + 分账

- **上限公式**（LiteLLM Router「并发上限默认从 RPM 推导」同款逻辑）：全局并发 ≈ provider_RPM × 平均单次墙钟 / 60；评审调用平均墙钟长，**全局 8–12 路是稳妥起点**，按实测 429 频率校准。40 路需求必然超闸，总闸是必选项。
- **三级结构**：全局 LLM 信号量（跨 run 总闸，配置化）→ per-run 并发上限 ≤4（CrewAI `max_rpm` 范式，做成 per-run 配置）→ candidate 内部串行。跨 run 公平轮转（加权 round-robin）保证不饿死，不用纯优先级抢占。
- **acquire 超时快速失败**：信号量排队等待单独计量并计入 run 墙钟预算，设 120s acquire 超时，超时进重排队而非占位空等。
- **429 冷却**：连续 429 时对该 model 冷却 30–60s（LiteLLM 默认 60s），冷却只影响该 model 不全局停摆，防重试风暴。
- **错峰启动**（AI-Scientist v1 `launch_scientist.py` 启动间隔源码取证）：10 条链路 kickoff 错开数十秒即可显著削峰，成本近零。
- **可选升级路径**：现有 `core/llm/client.py:1720` 走 `litellm.completion()` 直连；同库内升级为 `litellm.Router` 可直接获得 per-deployment 并发信号量、rpm/tpm 限额、冷却与指数退避（无新依赖），作为信号量方案的对备裁决项。
- **token 分账**（AI-Scientist v2 `TokenTracker` 模式）：按 model/run 记账入 SQLite（软阈值告警、硬阈值拒新调用），与批次预算总闸双层。
- **结构性降峰（后期）**：co-scientist tournament 分层——首轮全候选单轮粗筛、只对头部候选追加多轮评审，从结构上把 40 路峰值压下来；比接入优先级队列收益更大但改动更深，排在信号量之后。

### 6.6 A2 对标：Stripe 式幂等键 + best-effort 定位

- **幂等表**：`(key TEXT PRIMARY KEY, request_hash, response, state intent/running/done, created_at)`；键 = `action_id + 副作用点标识`（如 `action_id:node:llm_review`），**不含 epoch/attempt**——接管者重放应拿到首个响应（Stripe「保存首个请求的响应，同键重放直接返回缓存响应」语义），而不是再调一次 LLM。
- **并发同键**：`INSERT` 唯一约束冲突即等价 Stripe `409 request_in_progress`——另一个执行者在跑，本次放弃；完成回填 response，接管者查到 `done` 直接复用。
- **同键不同 request_hash 直接报错**（防串写）；TTL 对齐业务保留策略（Stripe 24h 起步，可放宽至随 ledger 保留）。
- **定位**（Sidekiq unique jobs 官方教训「uniqueness 是 best effort 不是 100% 保证」）：幂等键让重复执行「白跑但无害」，fan-in 账本提交的现有 CAS 保留为最后闸门，两层各自兜底。

### 6.7 C2/C6 对标：filelock + pyrate-limiter + 退避重试

- **C6 限速**：`pyrate-limiter` v4，每 provider 一个模块级 `Limiter` 单例——arXiv `Rate(1, Duration.SECOND*3)`（官方 courtesy）、Crossref polite pool ~3 req/s（URL 带 `mailto=`）；worker 调 `try_acquire()` 阻塞等许可，**删除现有线程内 sleep**。单进程 InMemoryBucket 足够；未来多进程再换 `SQLiteBucket(use_file_lock=True)`。排除 `ratelimit` 库（sleep-based，与现有缺陷同构）与 `aiolimiter`（asyncio 专用）。
- **C2 文件锁**：`with FileLock(str(path) + ".lock"):` 包住读-改-写临界区，临界区内**保留**自研 temp+fsync+os.replace 原子写（锁管互斥、原子写管崩溃一致性，锁文件与数据文件分离）；`thread_local=True` 默认保持（同线程重入安全、跨线程正确互斥），`is_singleton=True` 按路径复用实例；Windows 崩溃后内核锁自动失效（勿用 SoftFileLock）。未接入的 JSON RMW 路径（versioning 快照等）全部按此模板收编。
- **os.replace 兜底**：Windows 上目标被并发 reader/Defender 短暂持句柄会 `[WinError 5]`（CPython bpo-46003）——外层包 PermissionError 指数退避重试（3–5 次）；reader 接入同一把 filelock 后多数冲突在源头消失，重试只是防御外部进程的最后防线。`ReplaceFile` API 同样受共享冲突约束且需 pywin32，不采用。

### 6.8 明确不借清单

| 不借 | 原因 |
| --- | --- |
| Temporal Server / broker / Redis / RabbitMQ | 单进程 10 并发引入分布式组件，收益完全不成比例 |
| PostgresSaver 迁移 | LangGraph 官方定位 SqliteSaver 适用单进程；当前瓶颈是单 pump 串行而非 SQLite |
| LangGraph Platform / Agent Server 部署形态 | Redis 信令层在单进程内由线程队列/条件变量等价替代，零运维 |
| Celery 静态 visibility timeout 模式 | 无 fencing，超时即静默双执行；现有 CAS 提交校验已优于它 |
| AI-Scientist「backoff-only 无总闸」限流 | 与 B5 已知缺口同款模式 |
| Sticky queue / 热缓存 | 与 ledger 持久化权威模型冲突，单进程 replay 成本本来就低 |
| best-first 完整树搜索 | 对现有链路改造代价高于收益，tournament 分层更贴合 |
| LiteLLM 完整网关部署 | 偏重；SQLite 账本已具备记账底座，借 Router 机制不引网关组件 |
| ReplaceFile API / pywin32 | 同受共享冲突约束，性价比低 |

### 6.9 来源索引

Temporal worker performance / activity timeouts / sticky execution（docs.temporal.io）；LangGraph checkpoints 官方参考 / Agent Server / Data Plane（docs.langchain.com）；Celery configuration + issue #2788；Azure DTF storage provider / singleton orchestrators / Service Bus locks & settlement（learn.microsoft.com）；Kleppmann《How to do distributed locking》+ Percolator (OSDI'10) + antirez Redlock 之争；Sidekiq Pro Reliability / Ent-Unique-Jobs wiki；Stripe idempotent requests API + blog；co-scientist arXiv:2502.18864；SakanaAI/AI-Scientist v1/v2 源码（launch_scientist.py 错峰、para_agent.py 工作池、token_tracker.py、backend_openai.py backoff_create）；LiteLLM Router / Virtual Keys 文档；pyrate-limiter、py-filelock、tenacity PyPI/ReadTheDocs；SQLite WAL 官方文档；arXiv API ToU、Crossref rate-limit 公告。
