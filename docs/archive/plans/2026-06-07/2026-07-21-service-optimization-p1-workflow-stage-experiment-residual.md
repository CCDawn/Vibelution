# Service Optimization P1 — Workflow Stage Residual + Experiment Private Kernel

Date: 2026-07-21
Status: **phase5_closed** (P1 residual executed)
Owner lane: backend web services / team_workflow
Parent evaluation: 后端重新评估（Phase 1–4 已 closed & pushed）
Related maps: `core/web/services/team_workflow/README.md`
Prior closed plans:

- Phase 1 SC search/writeback: `docs/plans/2026-07-21-service-optimization-phase1-sc-search-kernel.md`
- Phase 2 knowledge public: `docs/plans/2026-07-21-service-optimization-phase2-knowledge.md`
- Phase 3 session projection/publish: `docs/plans/2026-07-21-service-optimization-phase3-session-projection.md`
- Phase 4 session control/lifecycle: `docs/plans/2026-07-21-service-optimization-phase4-session-lifecycle.md`

> **命名说明：** 本文「P1」指评估报告中的 **Priority-1（workflow residual）**，不是历史上的 Phase 1 SC search。
> 落地编号建议使用 **Service optimization Phase 5**（相对已 closed 的 1–4 连续）。

---

## 1. 目标与非目标

### 1.1 目标

消掉 workflow facade 上仍存在的 **「入口在 pack、身体在 facade」** 第二分裂脑，聚焦两块已有产品入口：

1. **SC stage 对账 / 投影 / 回合同步** — 被 `source_collection/stages.py` 大量 `s._xxx` 调用
2. **Experiment 私有记录 / readiness / steward notify** — 被 `experiment.py` 大量 `s._xxx` 调用

**成功标准：**

- 上述簇有 **独立 claim 文件**，新逻辑默认不进 facade
- 公共 import 仍走 `team_workflow_orchestration_service`
- 行为与协议不变（REST / 字段 / event 名冻结）
- facade 行数从 ~**13.4k** 再下降约 **2.0–3.5k**（视 helper 截止边界）
- structure re-export 断言 + 聚焦 orchestration 测试绿

### 1.2 非目标（本 P1 不做）

| 排除项 | 原因 |
|--------|------|
| Knowledge 私有 helper 大迁（~2.2k 命名簇） | 评估列为更后；与 knowledge 公开 pack 交织，范围膨胀 |
| 全量去 late-bind | 高成本；仅在「迁出同文件内」允许顺手减少 `s.` |
| Session facade residual | 已走 Phase 3–4；本批专 workflow |
| `runtime_scene` / `agent_directory` 二级 god | 评估 P2/P3 |
| 改搜索质量、实验算法、stage 业务规则 | 结构-only |
| Routes 层拆分 `team_workflows.py` | 独立议题 |
| Push / PR | 需用户另行授权 |

---

## 2. 现状证据（为何是 P1）

### 2.1 Facade 残局

| 指标 | 当前（约） |
|------|------------|
| `team_workflow_orchestration_service.py` | ~13.4k 行 / ~490 函数 |
| 已迁出 packs（SC + knowledge + experiment 入口等） | ~13.3k 行 |
| 仍在 facade 的 SC stage 相关 | **~84 函数 / ~2.8k LOC**（reconcile+other） |
| 仍在 facade 的 experiment 私有 | **~31 函数 / ~1.15k LOC** |

### 2.2 分裂脑证据

| 入口 pack | 现状 | 身体仍在 facade 的代表 |
|-----------|------|------------------------|
| `source_collection/stages.py` | 公开：seed/start/writeback/get/reconcile_after_turn | `_source_collection_stage_cards_projection` (~191)、`_source_collection_stage_task_tool_progress_from_trace` (~188)、`_repair_missing_source_collection_stage_round` (~166)、`_source_collection_stage_session_task_message` (~162)、`_reconcile_*` 簇 |
| `experiment.py` | 公开：plan/smoke/full-run/register/ingest | `_notify_knowledge_steward_for_experiment_result` (~198)、`_experiment_lifecycle_projection` (~131)、`_build_experiment_plan_record` (~114)、`_experiment_planning_status` (~95)、各类 `_*_record` |

`stages.py` 上仍有 **~74** 个 `s._private` 调用点落在 facade；其中 stage-专属大块是本批主菜。
`experiment.py` 上核心 plan/status/notify 私有函数 **几乎全部** 仍在 facade。

### 2.3 测试触点（搬家必须保持 facade 属性）

| 符号 / 行为 | 测试证据 |
|-------------|----------|
| `_source_collection_stage_cards_projection` | 多处 `test_team_workflow_orchestration_service` 直接调用 facade |
| `_reconcile_source_collection_stage_session_tasks` / retry_coverage | orchestration 测试 |
| `reconcile_source_collection_stage_session_task_after_turn` | structure re-export + orchestration |
| `_experiment_lifecycle_projection` | `test_experiment_lifecycle_projection_*` |

→ **绑定策略必须与 Phase 1–4 一致：** pack 实现 + facade re-export；pack 内兄弟/跨模块调用走 `s.`（monkeypatch 友好）。

---

## 3. 推荐架构

### 3.1 目标布局

```
core/web/services/team_workflow/
  experiment.py                         # 已有公开入口（保持）
  experiment_records.py                 # NEW Gate B：plan/smoke/full records + planning status + readiness
  experiment_steward.py                 # NEW Gate B 可选：notify/steward 大函数（或并入 experiment_records）
  source_collection/
    stages.py                           # 已有公开入口（保持）
    stage_reconcile.py                  # NEW Gate A：reconcile 簇 + cards projection + task message/progress
    stage_support.py                    # NEW Gate A 可选：isolation/clean/sync/tool_policy 等 stages 强依赖
    search_execution.py                 # 已有
    writeback_materialize.py            # 已有
    ...
  knowledge.py                          # 已有（本批不扩）
```

**推荐默认（最小文件数、仍可 claim）：**

| 新文件 | 职责 |
|--------|------|
| `source_collection/stage_reconcile.py` | 对账 + 投影 + task message/progress/repair |
| `experiment_kernel.py`（或 `experiment_records.py`） | experiment 私有记录/status/readiness/notify |

> 若 `stage_reconcile.py` 因 helper 截止超过 ~2k 行，再垂直拆 `stage_support.py`（Gate A.2），不要一上来切三刀。

### 3.2 绑定与 re-export

与既有 stage 包一致：

```python
# pack
def _service():
    from core.web.services import team_workflow_orchestration_service
    return team_workflow_orchestration_service

def _source_collection_stage_cards_projection(...):
    s = _service()
    ...
```

```python
# facade
from core.web.services.team_workflow.source_collection.stage_reconcile import (
    _source_collection_stage_cards_projection,
    ...
)
```

**硬规则（Phase 4 教训固化）：**

1. AST 删除函数时 **必须包含 decorator 行**（`min(decorator.lineno, def.lineno)`）。
2. **禁止**用「`s.CapitalName` → `Any`」这类宽松注解改写；常量/运行时值不得被改成 `typing.Any`。
3. pack 内互调与 facade 私有调用一律 **`s.name(...)`**，保证 monkeypatch 打在 facade 上生效。
4. 标准库名（`os`/`Path`/`json`/`hashlib`…）不得被 prefix 成 `s.os` / `oreplace`。
5. 若存在 `@session_agent_lifecycle_serialized` 类装饰器：在 facade 于装饰器定义后 rebind；structure 测试可用 `__wrapped__`。
6. 行为零变更；禁止顺手改 stage/experiment 业务文案或阈值。

### 3.3 与现有 pure modules 的边界

| 已有 | 本批关系 |
|------|----------|
| `source_collection_projection.py` | **保留**；facade 已 alias 部分 pure 函数。`_source_collection_stage_cards_projection` 是 **有状态/对账型** 大函数，放 `stage_reconcile`，不塞进 pure 模块 |
| `source_collection_stage_tasks.py` | 纯 checklist/title/tool_progress 载荷；本批不搬 pure，只搬 facade 上依赖 session/run 状态的包装 |
| `research_memory_context.py` | experiment 可能调用其 summary；**保留 pure**，不并入 experiment_kernel |

---

## 4. 范围明细

### Gate A — SC stage residual（主路径，先做）

#### A.1 必迁（reconcile + projection 核，~1.2k+ 直接簇）

| 符号簇 | 约 LOC | 说明 |
|--------|--------|------|
| `_source_collection_stage_cards_projection` | ~191 | 测试高频 |
| `_source_collection_stage_task_tool_progress_from_trace` | ~188 | trace→进度 |
| `_repair_missing_source_collection_stage_round` | ~166 | 缺 round 修复 |
| `_source_collection_stage_session_task_message` | ~162 | stage 任务消息 |
| `_reconcile_source_collection_stage_session_task_completion_gate` | ~140 | 完成闸门 |
| `_reconcile_source_collection_stage_session_task_sources` | ~96 | sources 对账 |
| `_reconcile_source_collection_stage_session_task_from_turn_result` | ~62 | turn 结果对账 |
| `_reconcile_source_collection_stage_session_task_retry_coverage` | ~47 | retry 覆盖 |
| `_reconcile_source_collection_stage_session_tasks_for_run` / `_tasks` / `_task` / turn_status | ~20–43 each | 批量/单任务对账 |
| `_attach_source_collection_stage_card_projections` | ~10 | 挂载投影 |
| `_sync_stage_round_with_source_collection_stage_task` | ~53 | stages 直接依赖 |
| 其他 **仅** 被上述函数 + `stages.py` 调用的叶子 helper | 按 call-graph 扩展 | 见 A.1 扩展规则 |

**A.1 扩展规则（BFS，硬停条件）：**

- 从 A.1 种子 + `stages.py` 的 `s._source_collection_stage_*` 调用出发
- **纳入** 仅被 stage 簇使用的私有函数
- **停止纳入** 若 helper 同时被：`knowledge.py` 公开路径、`runs.py` 搜索路径、`experiment.py`、或大量 generic `_normalize_*` 共享 glue 使用
- 共享 glue（`_normalize_required_id`、`_record_workflow_event`、`_trim_text` 等）**留 facade**

#### A.2 建议迁（stage_support，~0.6–1.0k，A.1 绿后）

优先来自 `stages.py` 强依赖且仍在 facade 的：

| 符号 | 约 LOC | 备注 |
|------|--------|------|
| `_clean_source_collection_stage_agent_sessions_for_new_round` | ~86 | 新轮清理 |
| `_ensure_source_collection_stage_agent_session_isolated` | ~69 | 隔离 |
| `_source_collection_stage_session_task_with_continuation_turn` | ~58 | 续写 turn |
| `_record_source_collection_stage_task_tool_policy_event` | ~61 | 工具策略事件 |
| `_source_collection_stage_retry_focus` / evidence_retry_focus | ~40–44 | retry 焦点 |
| `_source_collection_stage_task_needs_writeback_resume` | ~44 | writeback 恢复 |
| `_source_collection_stage_session_task_turn_*` 结果/快照族 | ~30–50 each | 若仅 stage 使用 |

**不强制 A.2 一次做完**；若时间紧，A.1 可单独收口为 P1 最小成功。

#### A.3 明确不进 Gate A

- writeback materialize（Phase 1 已迁）
- search_execution / exclusion ledger（可另开小批）
- `_import_source_collection_local_workspace_sources`（偏 import/workspace，可挂 candidates 后续）
- knowledge steward / graph 私有

### Gate B — Experiment private kernel（A 收口后）

#### B.1 必迁（experiment.py 直接依赖的记录/status/notify）

| 符号 | 约 LOC |
|------|--------|
| `_notify_knowledge_steward_for_experiment_result` | ~198 |
| `_experiment_lifecycle_projection` | ~131 |
| `_build_experiment_plan_record` | ~114 |
| `_experiment_planning_status` | ~95 |
| `_experiment_result_ingestion_pack_record` | ~86 |
| `_experiment_full_run_result_record` | ~58 |
| `_experiment_smoke_result_record` | ~51 |
| `_refresh_experiment_plan_readiness` | ~49 |
| `_experiment_result_steward_notification_child_log_payload` | ~35 |
| `_experiment_baseline_artifact_record` | ~33 |
| `_experiment_planning_gaps` / readiness_reason / next_actions / checklist / boundaries | ~10–33 each |
| `_experiment_hypothesis_summary` / candidates / select | ~9–30 |
| `_load_experiment_plan_store` / `_find_experiment_plan` / `_active_experiment_plan` 等 **experiment-store 私有** | 小函数族 |
| `_select_experiment_stage_round` / `_require_formal_full_run_ready` 若仅 experiment 用 | 按 call-graph |

#### B.2 共享则保留 facade

| 符号类型 | 处理 |
|----------|------|
| `_load_or_create_workflow` / `_workflow_to_api` / `_write_json` / `_record_workflow_event` | 留 facade（多入口共享） |
| `_research_stage_memory_context` | 若 research_loop 也用 → 留 facade 或 pure；不要硬塞 experiment |
| `_record_formal_full_run_execution` | 确认唯一调用方后再决定 |

### Gate C — 文档 / structure 测试 / 收口

- 更新 `team_workflow/README.md` ownership 与 extraction 表
- 扩展 `tests/test_team_workflow_structure_packs.py`
- 本 plan 状态 → `phase5_closed`（或 `p1_closed`）
- 记录 facade 行数 before/after

---

## 5. 任务图（Critical Path）

Mode: **TASK_GRAPH**（串行；共享 facade 写入面）

```text
Task 0: Worktree + claim + 基线
- Branch: codex/svc-opt-p5-workflow-stage-experiment (suggested)
- Worktree: .../Vibelution-worktrees/svc-opt-p5-workflow-stage-experiment
- Baseline:
  - tests/test_team_workflow_structure_packs.py
  - tests/test_team_workflow_routes.py
  - tests/test_team_workflow_orchestration_service.py -k "stage_card or reconcile_source_collection_stage or experiment_lifecycle or experiment_plan or smoke_result or full_run"
- Stop: baseline 红且非已知既有债 → 先诊断

Task A.1: 新建 stage_reconcile.py；迁 A.1 种子 + BFS 叶子；facade re-export
- Dep: Task 0
- Mode: SIMPLE（机械搬家 + 固化 checklist）
- Verification: structure + stage_card/reconcile -k + routes 子集
- Stop: 行为测红 / 循环导入 / 装饰器丢失

Task A.2 (optional in-scope): stage_support 强依赖迁出
- Dep: A.1 绿
- Verification: 同上 + stages 相关更广 -k
- 可与用户约定「A.1 收口即可」则跳过并记 deferred

Task A.3: README stage ownership + structure asserts for stage_reconcile
- Dep: A.1（及已做的 A.2）

Task B.1: 新建 experiment_kernel.py（或 experiment_records.py）；迁 B.1；facade re-export
- Dep: A.3（避免双线改 facade 冲突；若独立 worktree 仍建议串行）
- Verification: experiment lifecycle/plan/smoke/full_run -k + structure
- Stop: steward notify 测红

Task B.2: README experiment ownership + structure asserts
- Dep: B.1

Task C: 收口 — plan 状态、行数证据、可选全 routes
- Dep: B.2
- Success checklist 全勾
```

**Critical path:** 0 → A.1 → A.3 → B.1 → B.2 → C
**可选支线：** A.2 插在 A.1 与 A.3 之间

**自然用户闸门：** A.3 后（stage 完成）、C 后（P1 完成）。闸门内连续执行，不中途只汇报。

---

## 6. 验证契约

### 6.1 每 Gate 必跑

```text
tests/test_team_workflow_structure_packs.py
tests/test_team_workflow_routes.py
```

### 6.2 Gate A 聚焦

```text
tests/test_team_workflow_orchestration_service.py -k "stage_card or reconcile_source_collection_stage or repair_missing or stage_session_task or stage_round"
```

### 6.3 Gate B 聚焦

```text
tests/test_team_workflow_orchestration_service.py -k "experiment_lifecycle or experiment_plan or experiment_smoke or experiment_full or steward or readiness or hypothesis"
```

### 6.4 Success evidence checklist

- [ ] 迁出符号 **唯一定义点** 在 pack（facade 仅 import/re-export）
- [ ] structure 测试：`facade._xxx is pack._xxx`（或装饰器 `__wrapped__`）
- [ ] 无 REST/协议字符串业务 diff
- [ ] facade 行数下降可量化
- [ ] version impact: **none**
- [ ] Launcher: **not needed**（结构-only）
- [ ] 无 force-push；push 仅用户授权

### 6.5 回滚

- 单 Gate 红：修或 `git checkout` 该 Gate 文件
- 不跨 Gate 带伤前进
- 不在本地 `main` 上直接开发；worktree 合入前 self-review

---

## 7. 风险登记

| 风险 | 级 | 缓解 |
|------|----|------|
| stages 调用图过宽，BFS 吞下 knowledge/search glue | 中 | 硬停条件 + code review call-graph |
| experiment notify 与 knowledge pack 交叉 | 中 | notify 可放 experiment_kernel；调用 knowledge 公开 API 用 `s.` |
| 装饰器/AST 删除破坏语法 | 中 | decorator span；ast.parse 门禁 |
| 注解改写破坏运行时常量 | 中高 | **禁用** CapitalName→Any 规则；仅手写类型 import |
| monkeypatch 失效 | 中 | 兄弟调用走 `s.`；测直接打 facade |
| facade 双人冲突 | 中 | 单 worktree 串行 A→B |
| 测试耗时 | 低 | 先 -k 聚焦，再 routes |

---

## 8. 工作量与预期收益

| 项 | 估计 |
|----|------|
| 工程量 | 1 连续执行会话可完成 A；A+B 约 1–1.5 会话（视 A.2） |
| Facade 下降 | A: **~1.2–2.2k**；B: **~0.9–1.3k**；合计 **~2.1–3.5k** |
| 目标 facade | ~13.4k → **~10–11.5k** |
| 风险级 | STANDARD_TASK（机械搬家 + 既有测）；hot-file facade 需 claim |

---

## 9. 实施检查清单（执行者）

### 搬家前

1. worktree from local `main`
2. 基线测试绿（或记录已知债）
3. 用 AST 列出最终 WANTED 列表并写入 PR/commit 说明

### 搬家中

1. 新建 pack + `_service()` + 必要 stdlib import
2. 迁函数：**含 decorator 行**
3. 正文 `s = _service()`；跨模块/兄弟调用 `s.`
4. facade import block + 删除原定义
5. `ast.parse` 两文件；ruff F821

### 搬家后

1. structure asserts
2. 聚焦 -k 测试
3. README + plan log
4. 自审 diff：无业务逻辑改写

---

## 10. 决策默认值（已拍板，执行时可改）

| 问题 | 默认 |
|------|------|
| 新文件名 stage？ | `source_collection/stage_reconcile.py` |
| 新文件名 experiment？ | `experiment_kernel.py`（避免与公开 `experiment.py` 混淆） |
| A.2 stage_support？ | **建议做**，但不阻塞 A 收口 |
| Knowledge 私有？ | **不做** |
| 是否去 late-bind？ | **不做**（仅避免新增裸调用） |
| 合并本地 main？ | Gate 全绿后 self-merge（与 Phase 1–4 一致） |
| Push？ | 仅用户明确要求 |

---

## 11. 成功后的后端结构预期

| 表面 | 现在 | P1 后（目标） |
|------|------|----------------|
| workflow facade | ~13.4k | ~10–11.5k |
| stage claim | stages 入口 + writeback/search | **+ stage_reconcile（+support）** |
| experiment claim | 公开入口 only | **+ experiment_kernel** |
| 分裂脑 | stage/experiment 仍重 | 入口与内核同域可认领 |

下一评估焦点将转向：knowledge 私有、session metadata glue、或 `runtime_scene`/`agent_directory` 二级 god。

---

## 12. Execution log

| When | Gate | Notes |
|------|------|-------|
| 2026-07-21 | plan | 完整方案落盘；未改业务代码 |
| 2026-07-21 | A+B+C | stage_reconcile + experiment_kernel extracted; facade ~13.4k→~9.4k; tests green |

---

## 13. 审批后启动口令

用户确认后执行方可开工，建议口令：

- **「按 P1 方案开工」** → 从 Task 0 连续做到 C
- **「只做 Gate A」** → stage 收口后停
- **「A 含 A.2 / 不含 A.2」** → 调整 scope

**下一步建议（待你确认）：** 审阅本方案后回复开工范围；执行方建 worktree `codex/svc-opt-p5-workflow-stage-experiment` 从 Task 0 开始。
