# 挑战杯 10 并发链路改造与并发缺陷修复任务清单

> 文档 ID：`CC-PARALLEL-CONCURRENCY-10P-20260902`
>
> 状态：`USER-REQUESTED DIRECTION / ACTIVE PLAN / IMPLEMENTATION NOT STARTED`
>
> 权威路径：根 `main` 的 `docs/plans/2026-09-02-challenge-cup-10-parallel-concurrency-plan.md`
>
> 适用范围：挑战杯科研工作流（`challenge-cup-research@2.1.0/3.0.0`、knowledge sideflow、评审假说链、来源收集链、formal run）在 **10 条链路并发** 目标下的并发正确性改造与存量竞态修复
>
> 输入依据：2026-09-02 五路只读并发审查（账本/运行时、runner 批处理、评审假说、证据来源收集、跨链路共享资源），关键结论已由主 agent 亲验源码确认
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
- **方案要点**：生成前按 roundId（内容寻址哈希已现成）+ 状态锁预读：存在非失败 round 直接复用返回；存在进行中生成则拒绝或等待（不伪装成功）。锁与 `hypothesis_rounds._LOCK` 同源。
- **验收**：并发两次触发，第二次在零 LLM 调用下复用/被拒；既有 fan-in、revision envelope 测试全绿。

### 批次 B — 10 并发架构前置（关键路径）

#### B1 生产 runtime 单例加锁

- **问题**：`core/web/services/team_workflow/research_runtime/runtime_factory.py:290-352` `start/stop_production_workflow_runtime` check-then-act 无锁，并发可双开 store + 双 pump，start/stop 交错可让旧 pump 引用已 close 的 store。
- **方案要点**：模块级锁包住 start/stop 全序列；双开 fail-closed 抛结构化错误；stop 等待 pump 排空后再关 store。
- **验收**：并发 start 恰一成功；start×stop 交错无 `WorkflowLedgerClosedError` 抖动（并发用例钉住）。

#### B2 outbox lease invoke 中途续租（fencing 补强）

- **问题**：lease 默认 30s（`outbox.py:24`）无 invoke 心跳续租；`graph_dispatch_worker.py:746-770` 仅提交点 renew 作 fencing。单调用 >30s 且存在第二租用者时可双 invoke 同一 LangGraph thread，graph 副作用（checkpoint 双写/双 interrupt）不被撤销。当前单 pump 下靠隐式约定保护，多 worker 后立即放大。
- **方案要点**：长 invoke 期间周期性 `renew_outbox_lease`（复用 `adapter_dispatch_worker.py:669` 既有续租模式）；renew 失败（租已被夺）即中止本地副作用推进。lease 期限与 per-call 预算（450s 上限）对齐复核。
- **验收**：invoke 超过 lease 期无第二执行者误入；被夺租的 worker 中途停止且提交点被既有 fencing 拒绝（扩展 `tests/test_research_workflow_graph_dispatch_lease_fencing.py`）。

#### B3 dispatch 并行化（10 并发本体）

- **问题**：`outbox_pump.py` 单线程串行驱动全部 worker；10 run 排队推进，不满足目标。
- **方案要点**：pump 并发 drain——N 个 worker 线程（目标 10，可配）各自经 outbox lease CAS 领任务天然分片；`run_workers_once` 与 coordinator 的线程安全复核（账本侧单写者模型已支持多线程提交）；`prepare_initial_checkpoint` 所在 HTTP 线程与 pump worker 的 checkpoint 并发写经 B4 兜底。
- **决策点**（实施前须裁决）：worker 数固定 10 还是按 outbox 深度弹性；per-worker coordinator 还是共享（影响 `_ensure_readable` 修复路径的并发面）；sideflow child run 与主 run 是否允许同 worker 池混跑。
- **前置**：B1、B2 全绿。
- **验收**：10 run 同时推进的并发压测中——每 action 恰一执行者、无 `INVALID_CONCURRENT_GRAPH_UPDATE` 未恢复残留、账本无 `database is locked` 失败、投影与账本一致。

#### B4 checkpoint 并发写加固

- **问题**：`checkpoint_store.py:884` 直连 sqlite3 未显式 busy_timeout（默认 5s，与 ledger 侧显式 5000ms 不一致）；B3 后 pump worker 与 HTTP 线程（`run_creation.py:688` 的 `prepare_initial_checkpoint`）真实并发写同库；`runtime.py:16-21` `VerticalSliceRuntime` 常驻连接是绕过单执行者约定的遗留第二写者。
- **方案要点**：显式 busy_timeout + WAL 校验对齐 ledger 标准；归档或强制独立路径处理 `VerticalSliceRuntime`；10 线程并发写压测（不同 thread_id）。
- **验收**：并发压测零锁失败；`_ensure_readable` 修复路径在并发 interrupt 下不产生脏 checkpoint。

#### B5 全局 LLM 并发/预算总闸

- **问题**：评审波每题各开 `MAX_CONCURRENT_REVIEW_CALLS=4`（`hypothesis_review_executor.py:78`），跨题无全局限额——10 并发即 40 路同时打 LLM；预算公式是每生成局部预算（`:1197`），无批次级总闸。
- **方案要点**：进程级全局信号量（上限可配，建议初始 10–16）包住评审 LLM 调用 acquire/release；per-call 450s 墙钟与 challenge deadline fence 保留不变；配速策略与 125 题批次编排层（zero-human roadmap §1.4）对齐。
- **验收**：10 题并发下实测同时在途 LLM 调用 ≤ 上限；单题评审时长劣化有界（排队不饥饿，按 run 轮转或 FIFO）。

### 批次 C — 10 并发下放大的串线/丢写（与 A/B 并行）

#### C1 `PROJECT_ROOT` 全局换入换出改显式传参

- **问题**：`core/research/agent_runner.py:524-548,555-578,585-592,609-619` 对 `agent_directory_service` / `agent_mode_binding_service` / `prompt_template_service` 三个模块级 `PROJECT_ROOT` 做无锁 save-swap-restore——审查中**唯一真正的跨上下文串线口**（并行线程互相覆盖根目录，解析错 workspace 的 agent/prompt）。单 workspace 部署下症状隐匿，10 并发下高频触发。
- **方案要点**：三个 service 的读取路径增加显式 `project_root` 参数（默认回落模块值），agent_runner 直传不再改全局；全局字段保留只读兼容。
- **验收**：并发解析不同 workspace 的 agent profile 互不串线（并发用例）；移除 swap 后全部现有测试绿。

#### C2 `knowledge_base.json` 读改写加锁

- **问题**：`core/research/knowledge_base.py:90-141,187-200` `ingest_sources` 无锁 read-modify-write，并行 ingestion 丢条目；Windows 上 `os.replace` 目标被并发 reader 打开会 PermissionError。
- **方案要点**：模块级锁 + 走 `storage_durability`/原子写标准；读端容忍瞬态缺失（重试）。
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
- **方案要点**：per-provider 进程级 token bucket（arXiv 1 req/3s 对齐 etiquette）；统一重试+指数退避。
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
