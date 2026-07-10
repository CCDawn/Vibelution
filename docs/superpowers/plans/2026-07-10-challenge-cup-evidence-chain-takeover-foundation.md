# Challenge Cup Evidence Chain Takeover Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 root 中继承的 12 个挑战杯/研究 Agent 改动无损收口为两个可独立审查、验证和提交的语义分区，并在不越过 `chat_room_service.py` owner 边界的前提下建立后续单条科学证据链的可信代码基线。

**Architecture:** 保持 `team_workflow_orchestration_service.py` 作为兼容 facade 和 `SCHEMA_VERSION` 运行时事实源，把 split module 使用的 compact context/writeback helper 放在 `team_workflow` package；未拆分 orchestration callsite 继续使用 facade 中既有的 `_source_collection_count` / `_normalize_text_list`，并以行为等价测试守住渐进迁移边界。研究 Agent 测试从 `agent_role_tool_profile_service` 读取策略事实，但继续单独断言权限红线。先提交分区 A，再等待 `chat_room_service.py` owner 结果进入 local `main` 并以无冲突 main 同步满足分区 B 的完整基线，最后提交分区 B；本计划不启动运行态工作、不写比赛数据、不合并 root。

**Tech Stack:** Python 3、pytest、Git worktree、Vibelution project-memory guard、PowerShell。

## Global Constraints

- 工作目录固定为 `C:\Users\17533\Desktop\Vibelution-worktrees\challenge-cup-evidence-chain`，分支固定为 `codex/challenge-cup-evidence-chain`。
- durable local integration checkout 固定为 `C:\Users\17533\Desktop\Vibelution`，必须保持在 `main`；不得 reset、stash、清理或覆盖其中的继承改动。
- 只拥有下文列出的 12 个继承文件、design spec 和本 plan；不得编辑、暂存或提交 `core/web/services/chat_room_service.py`。
- `chat_room_service.py` 结果只能由其 owner 提交并进入 local `main`，本任务只消费该提交，不复制 root 未提交 hunk。
- `SCHEMA_VERSION` 继续由 `team_workflow_orchestration_service.py` facade 注入 `source_collection_stage_task_writeback_contract` 的 `schema_version: int` 参数。
- 测试策略可以复用 `agent_role_tool_profile_service.resolve_role_tool_policy`，但必须保留禁止工具、空写入范围、`mutationAccess == "none"`、关键 context/writeback 工具和公开 `argsSchema` 断言。
- 禁止 `git add .`；每次暂存都列出精确文件。
- 本计划不修改 `挑战杯/**`、CandidateStore、Team Knowledge、RAG、official graph、experiment plan、Research Loop、项目 memory lane/overview、版本文件、远端分支或 PR。
- 本计划不要求前端 build、Launcher refresh 或挑战杯 HTML regeneration；原因是没有前端、运行态、workflow schema、运行数据或用户流程变更。
- 继承 diff 已同时包含实现和回归测试；禁止通过回滚实现伪造 red-green 历史。测试锚点采用 scoped diff 等价性、接口契约和完整回归执行。

---

## File Responsibility Map

| 分区 | 文件 | 单一职责 |
|---|---|---|
| A | `core/web/services/team_workflow/source_collection_common.py` | 为 split module 提供有界计数、metadata 与文本列表规范化；与未迁移 facade helper 保持行为等价 |
| A | `core/web/services/team_workflow/source_collection_context.py` | source collection compact context、分页提示、record/candidate/run/task/writeback/boundary 投影 |
| A | `core/web/services/team_workflow/source_collection_stage_tasks.py` | stage task checklist、completion gate、formal knowledge 边界与显式 schema-version writeback contract |
| A | `core/web/services/team_workflow_orchestration_service.py` | 兼容 facade、`SCHEMA_VERSION` 注入和既有公共调用面 |
| A | `tests/test_team_workflow_orchestration_service.py` | split module 单实现、package-backed helper、schema authority 和 207 项编排回归 |
| B | `tests/test_agent_config_workspace_service.py` | research agent 修复后的 role profile 策略契约 |
| B | `tests/test_agent_lifecycle_create_delete.py` | challenge stage role 的 context/writeback 工具与 preferred order 契约 |
| B | `tests/test_agent_membership_indexes.py` | Challenge Cup agent prompt ownership 和 role policy 修复契约 |
| B | `tests/test_research_organization_service.py` | research organization 核心角色的工具策略事实源 |
| B | `tests/test_team_knowledge_service.py` | knowledge steward 与 paper reader 的 role policy 契约 |
| B | `tests/test_team_service.py` | research team sync/repair 的 allowed/preferred tools 与权限红线 |
| B | `tests/test_tool_registry_service.py` | source context tool 公开 `argsSchema` 契约 |
| prerequisite | `core/web/services/chat_room_service.py` | 由外部 owner 保留 compact participant 的 team context；本计划只验证已进入 `main` |

## Interfaces

分区 A 必须保留这些精确签名：

- `source_collection_count(value: Any, *, maximum: int = 100_000) -> int`
- `normalize_text_list(value: Any, *, max_items: int, max_length: int) -> list[str]`
- `compact_source_collection_stage_task_context(context: dict[str, Any]) -> dict[str, Any]`
- `compact_source_collection_context_candidate(candidate: dict[str, Any], *, minimal: bool = False) -> dict[str, Any]`
- `source_collection_stage_task_writeback_contract(team_id: str, run_id: str, task_id: str, *, stage_id: str, agent_id: str, agent_role: str, schema_version: int) -> dict[str, Any]`

facade 必须继续用下面的唯一适配方式传入 schema version：

```python
def _source_collection_stage_task_writeback_contract(
    team_id: str,
    run_id: str,
    task_id: str,
    *,
    stage_id: str,
    agent_id: str,
    agent_role: str,
) -> dict[str, Any]:
    return _source_collection_stage_task_writeback_contract_payload(
        team_id,
        run_id,
        task_id,
        stage_id=stage_id,
        agent_id=agent_id,
        agent_role=agent_role,
        schema_version=SCHEMA_VERSION,
    )
```

分区 B 只消费生产事实源，不新增生产接口：

```python
expected_policy = agent_role_tool_profile_service.resolve_role_tool_policy(
    role_key=role_key,
    primary_mode="research",
    policy_id=str(agent["toolPolicyId"]),
)
assert expected_policy is not None
assert agent["toolPolicy"]["allowedTools"] == expected_policy["allowedTools"]
assert agent["toolPolicy"]["preferredTools"] == expected_policy["preferredTools"]
```

---

### Task 1: 固化继承快照与执行边界

**Files:**
- Inspect: 上述 12 个继承文件
- Inspect: `docs/superpowers/specs/2026-07-10-challenge-cup-evidence-chain-design.md`
- Inspect: `docs/superpowers/plans/2026-07-10-challenge-cup-evidence-chain-takeover-foundation.md`
- Modify: none

**Interfaces:**
- Consumes: root 中 12 个继承文件、`claim-6014f58cee98`、已批准 design spec。
- Produces: `12/12` 文件哈希等价证据、无 claim 越界证据、明确的 A/B 文件集合。

- [ ] **Step 1: 确认分支、worktree 和 guard owner**

Run:

```powershell
git status --short --branch
py -3 "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" status
```

Expected: 当前分支为 `codex/challenge-cup-evidence-chain`；`claim-6014f58cee98` 仍为当前 Agent 的 active claim；`core/web/services/chat_room_service.py` 仍属于其他 owner 或已由该 owner 正常关闭，不属于当前 claim。

- [ ] **Step 2: 比较 12 个继承文件的 SHA-256**

Run:

```powershell
$root = 'C:\Users\17533\Desktop\Vibelution'
$wt = 'C:\Users\17533\Desktop\Vibelution-worktrees\challenge-cup-evidence-chain'
$paths = @(
  'core/web/services/team_workflow/source_collection_common.py',
  'core/web/services/team_workflow/source_collection_context.py',
  'core/web/services/team_workflow/source_collection_stage_tasks.py',
  'core/web/services/team_workflow_orchestration_service.py',
  'tests/test_agent_config_workspace_service.py',
  'tests/test_agent_lifecycle_create_delete.py',
  'tests/test_agent_membership_indexes.py',
  'tests/test_research_organization_service.py',
  'tests/test_team_knowledge_service.py',
  'tests/test_team_service.py',
  'tests/test_team_workflow_orchestration_service.py',
  'tests/test_tool_registry_service.py'
)
$mismatches = foreach ($path in $paths) {
  $rootHash = (Get-FileHash -LiteralPath (Join-Path $root $path) -Algorithm SHA256).Hash
  $wtHash = (Get-FileHash -LiteralPath (Join-Path $wt $path) -Algorithm SHA256).Hash
  if ($rootHash -ne $wtHash) { $path }
}
if (@($mismatches).Count -ne 0) { throw "Inherited mirror drift: $($mismatches -join ', ')" }
"MIRRORED_FILE_COUNT=$($paths.Count)"
"HASH_MISMATCH_COUNT=$(@($mismatches).Count)"
```

Expected: `MIRRORED_FILE_COUNT=12` and `HASH_MISMATCH_COUNT=0`. Any mismatch stops execution; do not overwrite either side.

- [ ] **Step 3: 验证 diff 健康和文件边界**

Run:

```powershell
git diff --check
git diff --stat
git diff --name-only
```

Expected: `git diff --check` exit 0；代码/测试 diff 只包含 12 个继承文件。若出现 `core/web/services/chat_room_service.py`、`挑战杯/**`、版本文件或项目 memory 文件，立即停止。

- [ ] **Step 4: 记录当前继承规模用于审查**

Run:

```powershell
git diff --numstat -- core/web/services/team_workflow/source_collection_common.py core/web/services/team_workflow/source_collection_context.py core/web/services/team_workflow/source_collection_stage_tasks.py core/web/services/team_workflow_orchestration_service.py tests/test_agent_config_workspace_service.py tests/test_agent_lifecycle_create_delete.py tests/test_agent_membership_indexes.py tests/test_research_organization_service.py tests/test_team_knowledge_service.py tests/test_team_service.py tests/test_team_workflow_orchestration_service.py tests/test_tool_registry_service.py
```

Expected at the approved snapshot: 12 files, exactly 404 insertions and 392 deletions. Whitespace-only drift is not accepted；任何 changed total 都必须返回 Step 2 并解释 root 为什么变化。

---

### Task 2: 验证并提交分区 A 的 workflow helper 提取

**Files:**
- Modify: `core/web/services/team_workflow/source_collection_common.py`
- Modify: `core/web/services/team_workflow/source_collection_context.py`
- Modify: `core/web/services/team_workflow/source_collection_stage_tasks.py`
- Modify: `core/web/services/team_workflow_orchestration_service.py`
- Test: `tests/test_team_workflow_orchestration_service.py`

**Interfaces:**
- Consumes: Task 1 的 12/12 等价快照和上文列出的 helper/facade 签名。
- Produces: 只包含分区 A 的提交 `refactor: move source collection context helpers`；分区 B 七个测试文件继续保持未暂存。

- [ ] **Step 1: 审查分区 A 只移动纯 helper，保留 facade**

Run:

```powershell
git diff -- core/web/services/team_workflow/source_collection_common.py core/web/services/team_workflow/source_collection_context.py core/web/services/team_workflow/source_collection_stage_tasks.py core/web/services/team_workflow_orchestration_service.py tests/test_team_workflow_orchestration_service.py
rg -n "def compact_source_collection_|def normalize_text_list|def _source_collection_stage_task_writeback_contract|schema_version=SCHEMA_VERSION" core/web/services/team_workflow/source_collection_common.py core/web/services/team_workflow/source_collection_context.py core/web/services/team_workflow/source_collection_stage_tasks.py core/web/services/team_workflow_orchestration_service.py
```

Expected: `_compact_source_collection_*` 实现在 package 中，facade 只为该 compact surface 保留 import aliases；writeback contract 由 facade 的 `SCHEMA_VERSION` wrapper 调用 package payload。facade 中旧 `_source_collection_count` / `_normalize_text_list` 仍服务未拆分 callsite，测试验证行为等价；本任务不得顺手删除它们。

- [ ] **Step 2: 运行三个结构与 schema authority 回归锚点**

Run:

```powershell
py -3 -m pytest tests/test_team_workflow_orchestration_service.py::test_source_collection_stage_round_sync_has_single_implementation_across_split_modules tests/test_team_workflow_orchestration_service.py::test_source_collection_pure_helpers_are_package_backed tests/test_team_workflow_orchestration_service.py::test_source_collection_writeback_contract_uses_facade_schema_version -q
```

Expected: `3 passed`, exit 0。不得删除 AST single-implementation 检查或把 facade schema 断言改成 package 常量。

- [ ] **Step 3: 编译四个生产模块**

Run:

```powershell
py -3 -m py_compile core/web/services/team_workflow/source_collection_common.py core/web/services/team_workflow/source_collection_context.py core/web/services/team_workflow/source_collection_stage_tasks.py core/web/services/team_workflow_orchestration_service.py
```

Expected: exit 0, no syntax error.

- [ ] **Step 4: 运行完整挑战杯编排回归**

Run:

```powershell
py -3 -m pytest tests/test_team_workflow_orchestration_service.py -q
```

Expected at the approved snapshot: `207 passed`, exit 0。重点失败均视为分区 A blocker，包括 compact context、分页 continuation、stage completion、formal knowledge boundary 和 writeback contract。

- [ ] **Step 5: 精确暂存并复核 staged diff**

Run:

```powershell
git add -- core/web/services/team_workflow/source_collection_common.py core/web/services/team_workflow/source_collection_context.py core/web/services/team_workflow/source_collection_stage_tasks.py core/web/services/team_workflow_orchestration_service.py tests/test_team_workflow_orchestration_service.py
git diff --cached --check
git diff --cached --stat
git diff --cached --name-only
```

Expected: staged set 恰好 5 个分区 A 文件，`git diff --cached --check` exit 0；7 个分区 B 文件仍未暂存。

- [ ] **Step 6: 提交分区 A**

Run:

```powershell
git commit -m "refactor: move source collection context helpers"
```

Expected: commit succeeds. Then `git status --short` only lists the seven partition B test files.

---

### Task 3: 消费 `chat_room_service.py` owner 前置结果

**Files:**
- Inspect only: `core/web/services/chat_room_service.py`
- Inspect only: `tests/test_team_service.py::test_team_detail_uses_lightweight_agent_references_for_member_repair`
- Modify through main merge only: none authored by this task

**Interfaces:**
- Consumes: Task 2 commit、`chat_room_service.py` owner 的已提交 local-main 结果。
- Produces: 当前分支与 local `main` 的安全同步，以及 lightweight team detail 单测绿色证据。

- [ ] **Step 1: 确认 owner 已完成或明确交付 commit**

Run:

```powershell
py -3 "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" status
git -C "C:\Users\17533\Desktop\Vibelution" log -5 --oneline -- core/web/services/chat_room_service.py
```

Expected: `claim-bb7d81a888a6` 不再处于 active/ready，或 owner 已明确提供一个包含 participant context 投影的 commit。仅看到 root 未提交 hunk 不算完成，必须等待 owner。

- [ ] **Step 2: 验证前置结果已提交到 local `main`**

Run:

```powershell
$root = 'C:\Users\17533\Desktop\Vibelution'
git -C $root diff --quiet -- core/web/services/chat_room_service.py
if ($LASTEXITCODE -ne 0) { throw 'chat_room_service.py still has an uncommitted owner diff' }
$mainChat = git -C $root show main:core/web/services/chat_room_service.py
if (-not ($mainChat | Select-String -SimpleMatch '_PARTICIPANT_CONTEXT_FIELDS if field in item')) {
  throw 'local main does not contain the participant context projection prerequisite'
}
git -C $root log -1 --format='%H %s' -- core/web/services/chat_room_service.py
```

Expected: scoped root diff is clean；`main` 中存在 `_PARTICIPANT_CONTEXT_FIELDS if field in item`；最后一条日志给出可追溯 commit。不得从 root 复制该行。

- [ ] **Step 3: 检查 main 增量不覆盖当前任务文件**

Run:

```powershell
$base = git merge-base HEAD main
$incoming = @(git diff --name-only "$base..main")
$owned = @(
  'core/web/services/team_workflow/source_collection_common.py',
  'core/web/services/team_workflow/source_collection_context.py',
  'core/web/services/team_workflow/source_collection_stage_tasks.py',
  'core/web/services/team_workflow_orchestration_service.py',
  'tests/test_agent_config_workspace_service.py',
  'tests/test_agent_lifecycle_create_delete.py',
  'tests/test_agent_membership_indexes.py',
  'tests/test_research_organization_service.py',
  'tests/test_team_knowledge_service.py',
  'tests/test_team_service.py',
  'tests/test_team_workflow_orchestration_service.py',
  'tests/test_tool_registry_service.py'
)
$overlap = @($incoming | Where-Object { $owned -contains $_ })
if ($overlap.Count -ne 0) { throw "Incoming main overlaps owned files: $($overlap -join ', ')" }
$incoming
```

Expected: incoming main may contain owner 的 chat room 文件和其他非重叠提交，但 `$overlap.Count` 为 0。任何重叠都停止，不自动解决冲突。

- [ ] **Step 4: 合并无重叠 local `main`**

Run:

```powershell
git merge --no-edit main
```

Expected: merge succeeds without touching 七个未提交 partition B 测试文件。若 Git 因工作区改动拒绝 merge，停止并报告；不得 stash、reset 或强制 checkout。

- [ ] **Step 5: 运行前置回归并确认没有自有 chat diff**

Run:

```powershell
py -3 -m pytest tests/test_team_service.py::test_team_detail_uses_lightweight_agent_references_for_member_repair -q
git diff --exit-code main -- core/web/services/chat_room_service.py
```

Expected: `1 passed`；当前分支相对 `main` 没有自有 `chat_room_service.py` diff。

---

### Task 4: 验证并提交分区 B 的研究角色策略测试对齐

**Files:**
- Modify: `tests/test_agent_config_workspace_service.py`
- Modify: `tests/test_agent_lifecycle_create_delete.py`
- Modify: `tests/test_agent_membership_indexes.py`
- Modify: `tests/test_research_organization_service.py`
- Modify: `tests/test_team_knowledge_service.py`
- Modify: `tests/test_team_service.py`
- Modify: `tests/test_tool_registry_service.py`

**Interfaces:**
- Consumes: Task 3 的 local-main prerequisite、`agent_role_tool_profile_service.resolve_role_tool_policy` 和 Tool Registry 公开 `argsSchema`。
- Produces: 只包含七个测试文件的提交 `test: align research agent policies with role profiles`。

- [ ] **Step 1: 运行所有被修改的行为锚点**

Run:

```powershell
py -3 -m pytest tests/test_agent_config_workspace_service.py::test_repair_agent_directory_fills_research_agent_profiles tests/test_agent_lifecycle_create_delete.py::test_challenge_stage_task_roles_include_context_and_writeback_tools tests/test_agent_membership_indexes.py::test_repair_agent_directory_applies_challenge_cup_research_tool_profiles tests/test_research_organization_service.py::test_research_organization_initializes_protected_core_agents_with_explicit_tools tests/test_team_knowledge_service.py::test_knowledge_steward_policy_includes_skill_library_search_tool tests/test_team_knowledge_service.py::test_research_agent_creation_and_readiness_report_expose_unified_memory_search tests/test_team_service.py::test_research_team_sync_applies_challenge_cup_agent_tool_profiles tests/test_team_service.py::test_research_team_repair_applies_challenge_cup_agent_tool_profiles tests/test_team_service.py::test_challenge_cup_research_team_agent_repair_purges_stale_and_rebuilds_complete_team tests/test_tool_registry_service.py::test_tool_registry_lists_builtins_as_protected -q
```

Expected: all selected tests pass, exit 0. Parameterized lifecycle test must run all declared role cases.

- [ ] **Step 2: 审查测试没有退化为只验证 helper 自己**

Run:

```powershell
rg -n "resolve_role_tool_policy|cli_tool|apply_patch_tool|writeScopes|mutationAccess|source_collection_context_tool|source_collection_stage_writeback_tool|argsSchema" tests/test_agent_config_workspace_service.py tests/test_agent_lifecycle_create_delete.py tests/test_agent_membership_indexes.py tests/test_research_organization_service.py tests/test_team_knowledge_service.py tests/test_team_service.py tests/test_tool_registry_service.py
```

Expected: helper 仅提供 allowed/preferred list 的事实源；禁止工具、权限红线、关键工具和公开 schema 仍有独立断言。不得重新引入完整硬编码工具数组或读取 `tools/Key_Tools.py` 源文本。

- [ ] **Step 3: 运行七个相邻测试文件的完整集合**

Run:

```powershell
py -3 -m pytest tests/test_agent_config_workspace_service.py tests/test_agent_lifecycle_create_delete.py tests/test_agent_membership_indexes.py tests/test_research_organization_service.py tests/test_team_knowledge_service.py tests/test_team_service.py tests/test_tool_registry_service.py -q
```

Expected: exit 0 and zero failures. Approved snapshot collected 266 tests；若 main 同步后收集数变化，必须审查新增/删除原因，不能只看退出码。

- [ ] **Step 4: 精确暂存并确认没有生产代码**

Run:

```powershell
git add -- tests/test_agent_config_workspace_service.py tests/test_agent_lifecycle_create_delete.py tests/test_agent_membership_indexes.py tests/test_research_organization_service.py tests/test_team_knowledge_service.py tests/test_team_service.py tests/test_tool_registry_service.py
git diff --cached --check
git diff --cached --name-only
```

Expected: staged set 恰好七个测试文件，不包含 production、`chat_room_service.py`、flow HTML、memory 或版本文件。

- [ ] **Step 5: 提交分区 B**

Run:

```powershell
git commit -m "test: align research agent policies with role profiles"
```

Expected: commit succeeds and `git status --short` is clean.

---

### Task 5: 运行最终门禁并形成后续证据链交接

**Files:**
- Inspect: 本计划拥有的全部 12 个文件、design spec、implementation plan
- Modify: none

**Interfaces:**
- Consumes: Task 2 和 Task 4 的两个语义提交、Task 3 的 owner prerequisite。
- Produces: `PARTIAL/READY_FOR_INTEGRATION` 交接证据；下一阶段固定路由到一个代表性研究对象的证据链设计，而不是直接写运行数据。

- [ ] **Step 1: 重新运行最终 Python 和 Git 验证**

Run:

```powershell
py -3 -m py_compile core/web/services/team_workflow/source_collection_common.py core/web/services/team_workflow/source_collection_context.py core/web/services/team_workflow/source_collection_stage_tasks.py core/web/services/team_workflow_orchestration_service.py
py -3 -m pytest tests/test_team_workflow_orchestration_service.py -q
py -3 -m pytest tests/test_agent_config_workspace_service.py tests/test_agent_lifecycle_create_delete.py tests/test_agent_membership_indexes.py tests/test_research_organization_service.py tests/test_team_knowledge_service.py tests/test_team_service.py tests/test_tool_registry_service.py -q
git diff --check
```

Expected: compile exit 0；workflow suite 当前基线 `207 passed`；adjacent suite zero failures；`git diff --check` exit 0。

- [ ] **Step 2: 验证提交与路径边界**

Run:

```powershell
git log --oneline --decorate -6
git status --short --branch
git diff --name-only main...HEAD
```

Expected: history 可追溯 design、plan、partition A、main prerequisite merge、partition B；相对 main 的文件只属于 12 个继承文件和两份 docs。工作区 clean。

- [ ] **Step 3: 判断 local-main integration gate**

Run:

```powershell
$root = 'C:\Users\17533\Desktop\Vibelution'
git -C $root status --short --branch
git -C $root diff --name-only -- core/web/services/team_workflow/source_collection_common.py core/web/services/team_workflow/source_collection_context.py core/web/services/team_workflow/source_collection_stage_tasks.py core/web/services/team_workflow_orchestration_service.py tests/test_agent_config_workspace_service.py tests/test_agent_lifecycle_create_delete.py tests/test_agent_membership_indexes.py tests/test_research_organization_service.py tests/test_team_knowledge_service.py tests/test_team_service.py tests/test_team_workflow_orchestration_service.py tests/test_tool_registry_service.py
```

Expected at current snapshot: root 仍持有 12 个重叠未提交副本，因此 local merge gate 不通过。本计划明确不清理 root、不强制 merge；状态报告为 branch ready、integration blocked by overlapping root diff。

- [ ] **Step 4: 记录无需执行的发布动作**

Record in the completion summary:

```text
Launcher refresh: not needed — only refactor/test ownership was committed; no integration or running runtime changed.
Challenge Cup HTML regeneration: not needed — no workflow schema, runtime data, or user flow changed.
Version impact: none — internal refactor and tests only.
Remote push / PR: not requested and not performed.
Project memory: no manual lane/overview edit; guard claim only.
```

- [ ] **Step 5: 关闭当前写 claim 并交接下一设计阶段**

Run only after every prior verification succeeds:

```powershell
py -3 "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" release --claim-id "claim-6014f58cee98" --status blocked --reason "Partition A and B committed and verified in codex/challenge-cup-evidence-chain; local main integration intentionally deferred because root retains overlapping inherited diffs. No chat_room_service, runtime data, flow HTML, version, remote, or manual project-memory writes."
```

Expected: claim leaves active state with a blocker reason that names the ready branch and overlapping root diff. If root is no longer dirty at execution time, do not silently change this step to merge; stop for a fresh integration review because root cleanup was outside the approved scope.

下一阶段只允许进入新的 brainstorming/design，选择一个代表性研究对象并固定：

```text
source_manifest
  -> paper_note
  -> neuro_mechanism
  -> mechanism_mapping
  -> algorithm_hypothesis
  -> review_record
  -> experiment_plan / smoke evidence
```

下一阶段必须把 `sourceRef/pageAnchor/citation/evidenceRef`、反例或边界条件、真实 Qwen/百炼 official model evidence、可执行 baseline/metric/dataset/smokePlan 和 Steward 正式知识门禁写入新的 spec；本计划不提前实施这些运行态写入。

---

## Execution Stop Conditions

出现以下任一情况立即停止，不进行“顺手修复”：

- 12 个 root/worktree 文件哈希不再一致；
- `chat_room_service.py` owner 尚未提交、claim 仍 active 且没有明确 handoff；
- incoming main 触碰任一 12 个 owned 文件；
- 分区 A 的 207 项编排测试失败；
- 分区 B 完整七文件 suite 失败；
- staged set 出现未列出的文件；
- 需要 stash、reset、force、root cleanup、运行态写入、版本修改、远端发布或用户需求变更。

任何停止都要保留 worktree 和 branch，报告具体命令、退出码、owner/claim、失败 selector 和恢复路由。
