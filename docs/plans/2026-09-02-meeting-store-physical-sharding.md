# 会议存储物理分片计划（meeting-store-physical-sharding）

> 状态：设计阶段（调研进行中）。本计划是 `2026-09-02-challenge-cup-10-parallel-concurrency-plan.md` 的写入层根治延伸，两条线并行推进、领地互斥（见 §5）。

## 1. 背景与定案

2026-09-02 晨 SCI-001 真实验收中，hypothesis-first 两个候选评审会议（`hf-review-hsel-3e278e50b271d28b-{c1,c2}-r3`）的 digest LLM 调用均已成功，但落盘线程在 `meeting_rounds.py` 模块级全局 `threading.RLock()`（`_LOCK`）上无限死等（py-spy 两次 dump：82 线程中无任何持锁者，4 线程静止等锁，含 2 个 API 读线程），只能重启后端解卡；重启后 startup sweep re-drive 3 分钟内恢复。同日另有评审编排缺陷（每轮只归档首个候选）与 deadline 次数模型未对齐问题，分别在 `codex/hf-sibling-archive-gate`、`codex/hf-digest-lock-timeout`、`codex/hf-deadline-call-count` 止血/对齐。

用户定案：**这类竞态的根因是「每会议逻辑隔离、但物理写入共享一个文件 + 一把全局锁」，止血补丁修不完，必须物理分离**。

存储现状（事故点）：团队级单文件 `research_workflow/meeting_rounds.jsonl`，写路径 `append_jsonl_locked`（storage_durability.py）= 跨进程文件锁 + 读全文件 + 临时文件全量重写 + fsync，整段持 `_LOCK`。多候选并行时所有会议写入在这「一扇门」串行：2 候选可忍，10 并发为瓶颈与卡点源。

## 2. 设计决策（草案，调研后定稿）

- **分片键 = `meetingRoundId`**：每会议一个独立 jsonl（`research_workflow/meetings/<meetingRoundId>.jsonl`），同 id 多条取最新的 append 语义不变。锁粒度与既有 `_summary_draft_lock`（每会议）对齐。
- **每分片独立锁**：线程锁 + 既有 inter-process 文件锁按分片文件生效；全局 `_LOCK` 降级为仅目录/清单操作（创建分片、列举）使用。
- **旧数据不迁移**：旧 `meeting_rounds.jsonl` 转只读历史源；读路径合并新旧两个来源（同 id 优先新分片、按记录时间戳/序取最新）。启动迁移与双写过渡均不做（风险收益比不佳，符合「不动活数据权威」）。
- **全量读方**（state_v2 投影、启动清扫、题目档案导出等）：目录扫描 + 轻量内存缓存；会议数量级 ≤ 数百，扫描成本可控；缓存失效由写方发布（具体以调研结论为准）。
- **兼容外部直读**：任何按旧路径直读文件的外部消费者（调研中盘点）通过读 API 或合并视图覆盖；仓库外工具若存在则在计划定稿时单独列出处理策略。

## 3. 批次划分

- 本批：`meeting_rounds`（事故现场）分片 + 读方合并视图 + 分片锁；`meeting_driver_work`、链级 ledger、chat room store 等**同模式存储不在本批**，按本图纸逐文件后续批次，防止范围爆炸。
- 编排层「物理分离」不在本计划：兄弟归档门（`codex/hf-sibling-archive-gate`）先收紧编排边界；链级状态是否分片待本批落地后按实际瓶颈评估。

## 4. 验收标准

1. 并行 N 候选评审的 digest 落盘互不阻塞（并发测试：两分片并发写无交叉等待）。
2. 单分片锁异常（模拟持锁超时/死锁）不影响其他会议读写。
3. 旧单文件数据在新读路径下完整可见（合并视图正确性测试）。
4. 10-parallel 计划的 D2 验收（10 并发端到端）在本批合入后复跑一次作为回归基线。
5. 存量测试面：走服务层/API 的测试零改动通过；直读文件形态的测试（调研盘点）随本批迁移到新视图。

## 5. 领地与协同（对 10-parallel 线）

- **本计划独占写入**：`core/web/services/team_workflow/meeting_rounds.py`、`core/web/services/team_workflow/storage_durability.py`、`research_workflow/meetings/` 新目录及读方合并视图。10-parallel 线后续批次如需触碰这些文件，先在本计划 issue 段落登记协调，不得并行修改。
- **10-parallel 线独占**：`hypothesis_first_chain.py` 编排并发（C 系列延续）、LLM 总闸/限速、runtime 单例/lease。两线通过 main 提交互相同步；D2 端到端验收作为分片改造的前置基线，分片落地后复跑即回归。
- **止血与根治的关系**：`hf-digest-lock-timeout`（锁获取超时 + in-process watchdog + 前端失败可见）在分片落地前保护现场，分片落地后超时防御保留为纵深（不再承担主要吞吐职责）。

## 6. 开放问题（调研后状态）

- 全量读方的完整清单与各自一致性要求（强一致 vs 可最终一致）。
- 幽灵锁根因（无人持有却不可获取）未定位；分片消除全局锁后该风险面收缩到单分片，超时观测事件（hf-digest-lock-timeout）继续留证。
- 分片文件的清理语义：重置本题 / 题目删除时分片文件与旧只读源的处理。

## 7. 调研定稿（2026-09-02，已合入 main 的调研结论）

影响面调研已完成，关键结论与追加决策：

- **外部直读：无**。仓外/前端均走 API；仓内仅 3 处路径级依赖需随批改造：meeting_driver_work.py:590（glob 跨 team 枚举）、hypothesis_first_chain.py:4650-4655（trail 缓存 mtime 戳）、hypothesis_first_state_v2.py:206-225（state_v2 文件 cursor stat）。后两者若漏改会出现「缓存永不失效或恒失效」。
- **全量读方 9 处**（REST 列表、state_v2 投影、启动清扫 sweep、anomaly inbox TTL、chain 5 处按题扫描、query_service、reset live adapter、reset_question_chain）统一经 `list_meeting_rounds` facade → 分片后由「目录扫描 + 旧文件只读源」合并视图实现，全量读方零改动（只改 facade 内部）。单会议读方（30+ 处）天然分片友好。
- **写方 18 处**全部已确认在 `_LOCK` 内 append 路径上；两个例外显式处理：(1) `reset_question_chain`（chain.py:872-964）是唯一绕过 append 的四锁重写，改为「按分片删除 + 旧源保留」，锁序维持 chain→selection→meeting→hypothesis_rounds 不成环；(2) `_persist_closure_artifacts` 锁内嵌套 personal_memory_candidates 锁，随分片把该调用移到分片锁外。
- **锁序确认**：summary_lock → meeting_rounds._LOCK 固定、无反序路径；chat→_LOCK 单向。今晨幽灵死锁不属于已知锁序环，分片后该风险面收缩到单分片，超时观测（hf-digest-lock-timeout）继续留证。
- **测试迁移清单**（直读文件形态，随批改）：test_research_workflow_meeting_rounds.py:342/:376、test_research_workflow_hypothesis_first_chain.py:5919/:3194-3208/:3276、test_challenge_review_budget_consistency.py:264、test_research_workflow_meeting_driver_recovery.py:251/:420/:488、`_digests_path/_decisions_path` monkeypatch 签名 5 处、test_research_workflow_hypothesis_first_e2e.py:700-704。服务层测试零改动预期通过。
- **storage inventory 基线**（分片改动前，2026-09-02）：instance bcabd5ca，totalFiles 12443，aggregateSha256 `c73299cb54a88f7414153b2f090e5d935070301a366586dc13a2cc3c669175c4`。
- **实施顺序**：hf-digest-lock-timeout（同文件止血）与 hf-sibling-archive-gate（state_v2 同文件）先合入 main，分片批 rebase 其上——分片锁改造吸收/替换全局 `_bounded_lock` 包装，避免互相踩踏。
- **范围确认**：本批对象为 meeting_rounds + meeting_digests + decision_records 三件套（同一 `_LOCK` 域）；其余 8 个同模式存储（driver_work、chain、selection、rounds、pmc、shadow/policy、chat rooms、circuit 账本）后续批次按同图纸迁移。
