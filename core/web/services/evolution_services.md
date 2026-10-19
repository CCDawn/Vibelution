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
| **autonomous self-evolution loop**（默认用户批准，可显式委托本地集成） | `self_evolution_autonomous_loop_service.py` + `self_evolution_local_integration.py` | 冒充 user 决策；无固定 SHA 独立验收直接合入；扩 iteration |
| **有限持续多轮调度**（成功后继续，达到轮数或期限停止） | `self_evolution_campaign_service.py` + `self_evolution_autonomous_loop_orchestrator.py` | 续签子授权；复制候选执行队列；重跑未知子任务；自动部署 |
| Candidate **隔离执行**（harness 协议） | `supervised_candidate_runtime_service.py` | 可见控制台 sandbox；超协议 limit 仍落盘全文 |
| Candidate **Git 集成**（唯一晋级路） | `supervised_candidate_integration_service.py` + `evolution_promotion_lane.py` | `expected_head` 不匹配仍 force merge；Gym/live run 当第二写入者改 baseline |
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
  → supervised_candidate_integration_service：唯一允许写 local main 的晋级（expected_head）
  → evolution_promotion_lane：工作台只读「当前 Git 基线」；Gym apply 仍是提案记录，不是 baseline 写入

Domain SSOT（业务规则与持久化）
  → core/evaluation/supervised_evolution.py · self_evolution_* · gym · chat_*
  → web/services 只做 workbench 编排与 DTO；新规则优先落 evaluation 包
```

触 FE Evolution 工作台时：route/recipe 在 `web/src/routes/` evolution 相关模块；改可见 UI 必须 VUI + contract + `tsc -b`。

## 有限的本地集成委托

`POST /evolution/self/autonomous-runs` 的 `localIntegration` 是可选对象；省略时仍停在用户审批。对象要求 `acknowledge=true`、`allowedFiles`（最多 8 个准确的仓库相对文件路径，拒绝 glob/目录/越界）、既有 `teamId` 和 `validForSeconds`（60–3600 秒）。此增量接口兼容旧客户端，不改变 `maxIterations=1`。HTTP 入口必须校验控制令牌并捕获服务器配置的 privileged operator，客户端的身份字段和 operator headers 不授予权限。

委托仅存在本次 WorkRun snapshot 的 `localIntegrationAuthorization`，包含操作员、期限、文件范围、既有 Agent 绑定与权限指纹。观察、执行、验收三名 Agent 必须不同，执行和验收 Agent 已属于显式 Team；验收 Agent 保留项目现有 canonical `permissionPreset`，解析后的工具策略完整上界必须只含 catalog 的只读工具。检查也覆盖验收 Session/Turn 的临时授权和完整工具 journal：任何非只读调用尝试都拒绝验收，且至少有一次本回合成功的只读工具结果；仅返回通过 JSON 不算读取证据。该路径不会补建 Agent、发放运行工具 grants，或放宽既有审批与工具预算。阶段开始前和合入前重查授权与配置，越界计划在执行前拒绝。

候选沿用受管 worktree、质量 manifest 和唯一 Git 集成服务。先冻结并验证候选，再用来源为 `self_evolution_candidate_review` 的隐藏原生 Session 独立验收；回执绑定同一 run、Session、精确 Turn、reviewer 和候选 SHA，并在 integration lease 内重读原生 journal 与授权，随后只 `ff-only` 合入验收过的 SHA。审计记录使用 `delegated_operator`，不会伪装成用户审批。

`POST /evolution/self/autonomous-runs/{run_id}/actions` 新增 `revoke_local_integration`，同样要求可信 privileged operator；撤销与最终合入共用授权锁，已完成撤销后不再接纳合入。缺权限返回 403，冲突返回 409，非法授权字段返回 422。合入成功后用安全、可重试的非强制清理；已合入事实恢复与新的合入审批分开，清理失败不重复合入。部署、产品重启、远端发布和扩权仍需用户决定。

通用总监修复可通过启动来源 Run 时的可选 `localIntegration` 有限委托接入此候选链路，详见 [generic code repair](team_workflow/generic/README.md#scoped-code-repair-through-the-existing-candidate-owner)。父 Run 保留授权和确定子任务引用，WorkRun 继续拥有候选执行及集成事实；后台不伪造 operator，不扩大文件范围或延长期限。代码合入后仍等待用户部署及独立效果验收。源码与本地测试通过不代表正式运行实例已部署或完成原生 Session 实机验收。

## 有限持续多轮调度

新增兼容接口 `POST /evolution/self/campaigns`：`goal`、必填 `idempotencyKey`、`rounds`（默认 3、1–10）以及必填 `localIntegration`。总时限直接使用该授权的 `validForSeconds`（60–3600 秒），从首次接纳开始计算；重复请求复用同一 campaign，不重新签权、不重置时间。同一 key 换请求返回 409。旧 `autonomous-runs` 仍保持单轮及原审批行为。

| 状态或字段 | 唯一权威 | 消费者 |
| --- | --- | --- |
| 轮数、截止时间、root grant、精确 child 引用 | WorkRun `self_evolution_campaign` | campaign 调度与授权 adapter |
| 候选开发、独立审查、Git 回执、清理和执行结束事实 | 既有 WorkRun `self_evolution_autonomous_loop` | campaign 只读汇总 |
| 原生 Agent 输出与工具证据 | 原生 Session Journal | 原审查及执行 adapter |
| HTTP schema / TS 客户端 | `evolution_models.py` / `api/types/evolution.ts` | 专用 API；正式配置 UI 待预览批准 |

所有修改命令校验控制令牌与服务器 privileged operator；客户端身份字段不授予权限。`GET /campaigns/active` 和 `GET /campaigns/{id}` 查询状态；`POST /campaigns/{id}/actions` 接受 `stop` 或 `revoke_local_integration`。child 固定为 `<campaign-id>-round-N`，只从私有来源派生 root grant，保留原角色指纹、文件范围和截止时间。每轮从最新 main 创建候选，只有独立审查、真实本地合入与安全清理均成功且同步执行已结束，才再次观察和计划。

失败、部分完成、撤销、到期或未知执行状态均阻止下一轮。期限 watchdog 请求精确 child 停止；已在执行的原生调用或原子合入可继续到安全返回，期间显示 `stopping`，不会谎报已结束。即使整轮未成功，已证明的合入 SHA 仍保留。重启只恢复精确结果及停止意图，不自动重跑未知 child；未明确结束的候选会阻止新的委托执行，需保留现场处理。部署、产品重启和远端操作仍由用户决定。

`web/harness-supervision-preview.html` 是使用模拟数据的独立配置预览，不连接生产写接口；预览批准前不接正式配置页面。

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
