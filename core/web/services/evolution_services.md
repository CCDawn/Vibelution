# Self / Supervised Evolution 迷你索引（R11）

**读者：coding Agent。**
**目标：30 秒内分清 evolution 控制面、payload 投影与 worktree/harness 边界；不要在 route 或 projection 里堆新业务。**

权威细则：[`docs/agents/domain.md`](../../../docs/agents/domain.md) · [`docs/ops/config/06-agent-evolution.md`](../../../docs/ops/config/06-agent-evolution.md) · ADR0001（Gym promotion proposal）。
全量 facade 表：[`README.md`](README.md) § Self / Supervised evolution。

---

## 30 秒编辑表

| 你在改… | 先打开 | 禁止 |
| --- | --- | --- |
| Supervised 工作台概览 / proposal / library / run 列表 | `evolution_service.py` → `core/evaluation/*` | 在 web service 复制 gym runner 逻辑；route 直连 evaluation 包 |
| Self-evolution 证据 / audit / transaction 读模型 | `self_evolution_service.py` → `core/evaluation` snapshot/audit | 把 run 控制或 LLM 调用塞进 payload service |
| Chat 数据集候选审核队列 | `chat_review_service.py` → `core/evaluation/chat_*` | 第二套 review 存储或绕过 lifecycle |
| 三类 runtime 统一投影（只读合并） | `evolution_runtime_projection_service.py` | projection 当第二写入者改 run 状态 |
| Supervised **live run** 启停/暂停/推进 | `supervised_control_service.py` | 与 `supervised_worktree_evolution_service` 平行实现 lifecycle |
| Supervised **worktree loop**（隔离 checkout + harness） | `supervised_worktree_evolution_service.py` → `scripts/evolution_harness.py` · `work_run_store` lease | 直接写本地 `main`；无 lease 开 worktree write |
| Self **observation / worktree run** 控制 | `self_evolution_control_service.py`（route：`evolution.py` · `agents.py`） | 在 `self_evolution_service` 里 spawn agent/LLM |
| 用户批准的 **autonomous self-evolution loop** | `self_evolution_autonomous_loop_service.py` + `self_evolution_autonomous_loop_*.py` | 绕过 user approval 扩 iteration；写 score loop 第二套 |
| Candidate **隔离执行**（harness 协议） | `supervised_candidate_runtime_service.py` | 可见控制台 sandbox；超协议 limit 仍落盘全文 |
| Candidate **Git 集成**（promote 到 main） | `supervised_candidate_integration_service.py` | `expected_head` 不匹配仍 force merge |
| Supervised Agent 角色对齐 | `supervised_agent_service.py`（route：`agents.py`） | 与 evolution control 双写 AgentInstance |
| HTTP 路由 / DTO | `core/web/routes/evolution.py` + `evolution_models.py` | route 业务体；泄露 harness 原始 prompt/secret |

**「改 supervised run 启停挂哪？」** → `supervised_control_service.py`（bundle/dataset live run）或 `supervised_worktree_evolution_service.py`（worktree loop）；读侧概览在 `evolution_service.py`，runtime 合并看 `evolution_runtime_projection_service.py`。

---

## 控制面 vs Payload vs Worktree

```text
Payload（读模型 / 工作台投影）
  → evolution_service：supervised overview、proposal、library、workspace dashboard
  → self_evolution_service：self overview、audit、transactions、history delete 校验
  → chat_review_service：chat candidate review queue
  → evolution_runtime_projection_service：supervised | self_worktree | self_observation 只读合并

Control plane（可变 run 状态 / LLM / launcher 编排）
  → supervised_control_service：dataset/gym live supervised run
  → supervised_worktree_evolution_service：supervised worktree self-evolution loop
  → self_evolution_control_service：self observation + self worktree run
  → self_evolution_autonomous_loop_service：持久 no-score loop（WorkRunStore kind=self_evolution_autonomous_loop）

Worktree / Harness / Git（隔离与证据）
  → scripts/evolution_harness.py：create_worktree、checkpoint、harness 执行
  → core/runtime_manager/work_run_store + lease：WORKTREE_WRITE / EVALUATION 冲突检查
  → developer_sandbox + launcher_service：隔离路径与 active-work 语义
  → supervised_candidate_runtime_service：candidate 协议执行
  → supervised_candidate_integration_service：expected_head 保护下的 promote

Domain SSOT（业务规则与持久化）
  → core/evaluation/supervised_evolution.py · self_evolution_* · gym · chat_*
  → web/services 只做 workbench 编排与 DTO；新规则优先落 evaluation 包
```

触 FE Evolution 工作台时：route/recipe 在 `web/src/routes/` evolution 相关模块；改可见 UI 必须 VUI + contract + `tsc -b`。

---

## 主测（可复制）

```powershell
# 矩阵 web-evolution 行（route + harness + gym）
.\.venv\Scripts\python.exe -m pytest tests\test_web_evolution_routes.py tests\test_evolution_harness.py tests\test_gym_engine.py tests\test_gym_runner.py tests\test_gym_promotion.py -q

# Payload / projection
.\.venv\Scripts\python.exe -m pytest tests\test_evolution_service.py tests\test_evolution_runtime_projection_service.py tests\test_self_evolution_service.py -q

# Control plane
.\.venv\Scripts\python.exe -m pytest tests\test_supervised_runtime_activation_intent.py tests\test_runtime_manager.py tests\test_self_evolution_autonomous_loop_service.py -q

# Candidate harness / Git integration
.\.venv\Scripts\python.exe -m pytest tests\test_supervised_candidate_runtime_service.py tests\test_supervised_candidate_integration_service.py -q

# Worktree 路径 / sandbox 路由
.\.venv\Scripts\python.exe -m pytest tests\test_developer_sandbox_path_routing.py -q

# 影响面（改 facade 后）
.\.venv\Scripts\python.exe tests\select_tests.py --changed-file core/web/services/supervised_worktree_evolution_service.py --commands-only
```

改 `core/evaluation/*` 时按 `tests/test_matrix.yaml` `web-evolution` 行加跑 evaluation 聚焦测试；改 runtime scene 时含 `test_runtime_scene_package_diagnosis.py`。

---

## 相关

| 文档 | 用途 |
| --- | --- |
| [`docs/guides/loop.md`](../../../docs/guides/loop.md) | 验证/完成块 |
| [`docs/guides/agent-dev-roi-backlog.md`](../../../docs/guides/agent-dev-roi-backlog.md) | R11 DoD |
| [`config_services.md`](config_services.md) | 同类迷你索引 |
| [`launcher_runtime.md`](launcher_runtime.md) | worktree / 无控制台 / RM lease |
| [`tests/test_matrix.yaml`](../../../tests/test_matrix.yaml) | `web-evolution` 聚焦命令 |
