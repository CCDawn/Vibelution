# 本地质量门闭环设计

## 状态元数据

- **状态：** 用户已批准设计；进入实施规划前必须完成书面 spec 审阅
- **Owner：** `codex-local-quality-gate`
- **Claim：** `claim-4bd578460e73`
- **分支：** `codex/local-quality-gate-closure`
- **Worktree：** `C:\Users\17533\Desktop\Vibelution-worktrees\local-quality-gate-closure`
- **范围：** 在不恢复自动 GitHub Actions 的前提下，闭合本地 commit、任务收口、本地 main 集成与任务资源清理的证据链
- **替代关系：** 替代 `.githooks/pre-commit` 当前无效行为；不替代 `tests/select_tests.py`、`tests/test_matrix.yaml` 或既有 worktree 协作协议
- **实施链接：** 无；书面 spec 通过审阅前，实施规划被明确阻止
- **验证：** 用户逐段批准、当前文件与 Git 历史审查、spec 自审、Markdown 范围检查和 `git diff --check`
- **关闭条件：** 书面 spec 获批并转成实施计划，实施在任务 worktree 完成并合入本地 `main`，任务 claim、worktree 与分支完成清理

## 目标

通过任务 worktree 隔离普通开发、用轻量门保护中间 commit、用强门保护任务收口、以 fast-forward 合入本地 `main`，并立即清理已完成任务的临时资源，使本地开发同时具备独立性、效率和低冲突成本。

所有活跃任务完成后，仓库的长期分支只保留本地 `main`。任务分支与 worktree 只在任务活跃或真实阻塞时存在。

## 已确认的用户决策

1. 开发和提交主要发生在本地 Git。
2. 本地 `main` 是集成事实源。
3. 普通开发使用独立任务分支和 worktree，不直接在根 `main` 开发。
4. 中间 commit 必须保持快速，不能每次都运行大范围测试或 build。
5. 强验证放在任务收口和合入本地 `main` 前。
6. 每个已完成任务必须清理自己拥有的 claim、worktree 和分支。
7. 清理不得删除其他活跃任务的 worktree、分支、junction 或 claim。
8. 冲突必须在任务 worktree 解决，根 `main` 不得进入冲突状态。
9. GitHub Actions 保持手动触发，避免自动消耗 Actions 分钟。
10. 质量门只验证和记录证据，不执行 merge、分支删除、worktree 删除或应用状态修改。
11. 现有 unused import 与 unused variable 债务不纳入本轮。

## 当前证据

- `.github/workflows/ci.yml` 只声明 `workflow_dispatch`，但 Ruff 步骤受 `pull_request` 条件约束，手动 lint job 实际跳过 Ruff。
- `.githooks/pre-commit` 调用 `pytest -m unit`，但当前测试文件和 collection hook 均未提供 `unit` marker。
- `tests/select_tests.py` 已具备影响面选择能力，`tests/test_matrix.yaml` 已是项目拥有的验证映射。
- 若干高频改动文件没有 focused matrix 规则，只能回退到 runner smoke 与 collect-only。
- runtime、Launcher、Web、Team workflow、evolution 等套件已通过模块级 `pytestmark` 表达 serial 所有权。
- `.runtime/` 已被忽略，可承载有界本地验证证据而不污染 Git。
- 项目 worktree 与 guard 标准已要求任务隔离、claim 检查、自审、本地 main 集成和资源清理。
- Git 历史明确记录：自动 push/PR CI 是为节省 Actions 分钟而主动关闭。

复用决策为 **ADAPT**：

- 复用 `tests/select_tests.py` 选择改动影响；
- 复用 `tests/test_matrix.yaml` 作为唯一验证映射；
- 复用模块级 `serial` marker 和现有 hybrid/serial runner；
- 复用 `.githooks/pre-commit` 作为 Git hook 入口；
- 复用 `scripts/doctor.ps1` 做环境和 hook 诊断；
- 复用已安装的 project-memory guard 做 active claim 检查；
- 只新增一个有界编排脚本，不创建第二套测试 registry，也不替换现有 runner。

本轮跳过外部研究。问题由仓库内现有 workflow 与本地 main 运行契约直接决定，当前项目已包含完成设计所需的复用原语。

## 非目标

- 不恢复自动 GitHub Actions。
- 不在每次 commit 运行全量 pytest、前端 build 或 bundle check。
- 不清理当前 `F401`、`F841` 基线债务。
- 不替换 pytest、Vitest、Ruff、npm、Vite、Launcher 或 project-memory guard。
- 不建立第二套 changed-file/test ownership matrix。
- 不让质量门拥有 `git merge`、分支删除、worktree 删除、junction 删除、claim release 或 project-memory 写权限。
- 不修改应用 runtime 行为、前端行为、后端 API、DTO、数据、权限、模型配置或 operator config。
- 不顺带优化 bundle、锁定 Python 依赖、拆分巨型模块或重构无关测试。
- 不触碰当前 Team Workflow、Chat、HeroUI 或其他 active-claim 实现文件。
- 不以当前任务收口为理由清理历史分支或其他任务分支。

## 选定工作流

### 1. 创建任务

普通任务从当前本地 `main` 创建：

- branch：`codex/<task-slug>`；
- worktree：`C:\Users\17533\Desktop\Vibelution-worktrees\<task-slug>`；
- base：当前本地 `main`，不是 `origin/main`；
- claim：仅覆盖任务实际需要写入的窄 scope。

根 `C:\Users\17533\Desktop\Vibelution` 始终是本地 main 集成 checkout。

### 2. 中间开发与 commit

任务 Agent 可创建多个小型本地 commit。每个 commit 只运行 staged-content 轻量门，不运行行为测试、前端 build、bundle budget、Launcher 检查或大范围 lint。

### 3. 任务收口

实现完成后，任务 Agent 在任务 worktree 运行强收口门。质量门验证已提交范围 `main...HEAD`，记录验证所依据的本地 main SHA，并在以下任一情况拒绝通过：worktree 脏、当前分支是 `main`、claim 证据无效、必需命令失败或出现不支持的验证命令。

### 4. 与本地 main 收敛

合并前再次验证 manifest。如果本地 `main` 在验证后移动，manifest 进入 `stale_main`。任务必须在自己的 worktree 吸收当前本地 `main`、在那里解决冲突并重跑受影响验证。根 `main` 不接收未解决冲突。

### 5. 集成与清理

fresh `passed` manifest 和 clean merge preflight 之后：

1. fast-forward 任务分支到根本地 `main`；
2. 在本地 `main` 运行最小必要 post-merge 验证；
3. 携带证据 release 当前任务 claim；
4. 如存在任务自有依赖 junction，先移除 junction；
5. 移除干净的任务 worktree；
6. 删除已合并任务分支；
7. 确认没有遗留已完成任务的分支或 worktree。

验证、merge、post-merge 复验、claim release、junction 清理或 worktree 清理任何一步失败时，Agent 必须报告确切残留状态，不得宣称任务已关闭。

## 质量门架构

### `scripts/local_quality_gate.py`

新增跨平台 Python 编排器，公开三个 mode：

```text
python scripts/local_quality_gate.py commit
python scripts/local_quality_gate.py closeout --base main --claim-id <claim-id>
python scripts/local_quality_gate.py verify-manifest --manifest <path>
```

脚本对应用代码和 Git 历史保持只读；唯一写入是 `.runtime/quality_gates/` 下的有界 manifest。

#### `commit`

1. 从 `git diff --cached --name-only --diff-filter=ACMR` 获取 staged path。
2. 运行 `git diff --cached --check`。
3. 从 Git index 读取 staged Python 内容，不读取 worktree 内容。
4. 通过 stdin 调用 Ruff，并把 staged path 作为 `--stdin-filename`。
5. 只选择致命规则 `E9`、`F63`、`F7`、`F82`。
6. 跳过 deleted file 和非 Python 内容。
7. 失败时输出一个紧凑摘要和可复现命令。
8. 没有相关 staged 内容时退出 0，不运行行为测试。

使用 staged blob 可以避免同一文件的 unstaged 改动影响 commit 结果。

以下 gate-definition 文件必须完整 staging；同一文件同时存在 staged 与 unstaged 改动时，commit mode 以 `gate_definition_dirty` 失败：

- `.githooks/pre-commit`；
- `scripts/local_quality_gate.py`；
- `scripts/doctor.ps1`；
- `tests/select_tests.py`；
- `tests/test_matrix.yaml`；
- `.github/workflows/ci.yml`。

gate-definition 文件完整 staging 后运行最小 gate 自测；完整 gate 行为测试仍由任务收口强制执行。

#### `closeout`

1. 要求当前为非 `main` 任务分支。
2. 要求 worktree 干净且任务改动已经 commit。
3. 定位当前本地 main worktree，并把其 `HEAD` 记录为 `validatedMainSha`。
4. 把任务分支 `HEAD` 记录为 `headSha`。
5. 从 `git diff --name-only main...HEAD` 推导 changed file。
6. 通过现有 project-memory guard 和输入的 `claim-id` 检查任务所有权。
7. 使用 changed-file set 调用 `tests/select_tests.py`。
8. 把选中命令转换成结构化 argv 与 cwd。
9. 拒绝 approved command family 之外的任何命令。
10. 对 changed Python file 运行致命规则 Ruff。
11. 运行所有必需 focused command，记录 exit code 与 duration。
12. 在不修改根 `main` 的前提下运行 merge preflight。
13. 写入最终 manifest outcome。

首版只支持以下 validation command family：

- `git diff --check`；
- project Python 的 `-m pytest ...`；
- project Python 的 `tests/select_tests.py ...`；
- project Python 的 `tests/prompt_debugger.py ...`；
- `npm --prefix web run test ...`；
- `npm --prefix web run build`；
- `npm --prefix web run check:bundle`；
- `node 挑战杯/build_research_flow_site.mjs`。

shell metacharacter、任意 executable、命令链、重定向、网络 installer、process-kill 命令和 delete/move 命令一律拒绝为 `unsupported_validation_command`。

当任务修改 selector、matrix、gate script、hook、doctor 或 CI workflow 时，closeout 无条件追加 gate、selector、doctor、workflow contract tests，即使任务分支里的 matrix 没有选择它们。任务不能通过修改正在验证自己的 matrix 来削弱门禁。

#### `verify-manifest`

合并前的廉价复核必须确认：

- manifest schema 有效且 `outcome == passed`；
- 当前任务 `HEAD == headSha`；
- 当前本地 `main HEAD == validatedMainSha`；
- 当前仍是非 `main` 任务分支；
- 任务 worktree 仍然干净；
- claim 对本次集成仍然有效；
- 没有必需命令失败，也没有 unsupported command 被跳过。

该 mode 不执行 merge 或 cleanup。

### `.githooks/pre-commit`

tracked hook 变成薄适配器：定位 repository root，并优先用项目 virtual environment 调用 `scripts/local_quality_gate.py commit`。hook 不再拥有独立验证策略。

hook 保留 gate exit status，并输出精确恢复命令。它不安装依赖、不修改文件、不运行 fix，也不能在 Python 或 Ruff 缺失时降级成成功。

### `scripts/doctor.ps1`

Doctor 新增只读 Git hook 诊断：

- expected hook path `.githooks`；
- 当前 `core.hooksPath` 的来源和值；
- tracked pre-commit hook 是否存在；
- project Python 是否可用；
- Ruff import/executable 是否可用；
- local quality-gate script 是否存在。

Doctor 输出明确修复命令，但不静默修改 `.git/config`：

```powershell
git config core.hooksPath .githooks
```

### `.github/workflows/ci.yml`

CI 保持 manual-only。Python lint job 移除不可达的 PR changed-file 路径，改为对以下 production Python root 无条件运行致命 Ruff 规则：

```text
agent.py config core scripts tools
```

Python test matrix、coverage gate、frontend tests 和 frontend build 保持不变，除非实现证据证明必须做直接兼容调整。

## 验证 manifest

路径：

```text
.runtime/quality_gates/<task-id>.json
```

`.runtime/` 已整体忽略，不需要修改 `.gitignore`。

Schema：

```json
{
  "schemaVersion": 1,
  "taskId": "local-quality-gate-closure",
  "branch": "codex/local-quality-gate-closure",
  "worktree": "C:/Users/17533/Desktop/Vibelution-worktrees/local-quality-gate-closure",
  "claimId": "claim-4bd578460e73",
  "validatedMainSha": "40-character Git SHA",
  "headSha": "40-character Git SHA",
  "changedFiles": ["path/from/repository/root"],
  "commands": [
    {
      "kind": "pytest",
      "argv": ["project-python", "-m", "pytest", "tests/test_local_quality_gate.py", "-q"],
      "cwd": "repository-root",
      "exitCode": 0,
      "durationMs": 1,
      "status": "passed",
      "failureSummary": ""
    }
  ],
  "checks": {
    "worktreeClean": true,
    "claimValid": true,
    "mergePreflight": true,
    "commandsAllowlisted": true
  },
  "outcome": "passed",
  "generatedAt": "ISO-8601 timestamp"
}
```

真实 manifest 写入真实值；上例只定义 field shape，不能复制为任务证据。

manifest 不保存完整 stdout/stderr、prompt、secret、provider payload、source file、diff 或 environment dump。失败摘要必须限行、限长并做 redaction；详细输出只保留在当前 terminal 或项目已有的有界 task log。

## Outcome 与恢复状态

| Outcome | 含义 | 恢复动作 |
| --- | --- | --- |
| `passed` | 所有必需检查在记录的 main/task SHA 上通过 | 运行 `verify-manifest` 后进入 merge gate |
| `failed` | lint、focused validation、自测或 merge preflight 失败 | 在任务 worktree 修复并 commit，重新 closeout |
| `stale_main` | 验证后本地 `main` 已移动 | 在任务 worktree 吸收当前 main 并重跑受影响验证 |
| `claim_conflict` | claim 缺失、过期、外属或冲突 | 通过既有 guard 协调后重试 |
| `dirty_worktree` | 任务改动尚未 commit 或 partial staging | commit 或明确移除当前任务改动后重试 |
| `merge_conflict` | 任务分支无法与本地 main 干净收敛 | 只在任务 worktree 解决并重验 |
| `unsupported_validation_command` | matrix 请求了 allowlist 外命令 | 审查并显式扩展 executor contract，或修正 matrix |
| `gate_definition_dirty` | gate-definition 文件只有部分 staged | 完整 stage gate 改动或拆成独立 commit |

非 `passed` 状态均不授权 merge 或 cleanup。

## 单一事实源

| Fact | Canonical source | Writer | Readers / derived surfaces | Refresh / invalidation | 旧面处理 |
| --- | --- | --- | --- | --- | --- |
| 本地集成状态 | 根本地 `main` | 通过 merge gate 的任务 Agent | task worktree、quality gate、Launcher/dev tooling | 当前 main SHA | remote main 不作为 reset authority |
| 任务 changed file | `git diff main...HEAD` | Git commit | selector、gate、review | 任意 task/main commit 使派生结果失效 | copied file list 不成为权威 |
| 验证 ownership | `tests/test_matrix.yaml` | quality-and-operations 任务 | selector 与 local gate | matrix commit | unmatched file 保留现有 fallback |
| 验证执行策略 | `scripts/local_quality_gate.py` | quality-and-operations 任务 | hook、task Agent、manual CI contract test | gate script commit | hook body 不再保存策略 |
| commit 入口 | `.githooks/pre-commit` | quality-and-operations 任务 | local Git | hook 或 `core.hooksPath` 变化 | 删除旧 `pytest -m unit` 行为 |
| active write ownership | local-main workspace 的 project-memory guard | guard claim/release | closeout 与 integration gate | 每次 claim transition | task worktree copy 不覆盖 live guard output |
| 验证证据 | `.runtime/quality_gates/<task-id>.json` | local quality gate | pre-merge check 与 final report | task HEAD、main HEAD、claim、command 变化 | stale manifest 仅作本地诊断 |
| cleanup ownership | 当前任务 Agent 与 worktree protocol | 当前任务 Agent | final report 与 guard registry | merge 和 post-merge check 成功 | 只删除当前任务资源 |

## 预计文件影响

- Create `scripts/local_quality_gate.py`。
- Create `tests/test_local_quality_gate.py`。
- Create `tests/test_ci_workflow_contract.py`。
- Modify `.githooks/pre-commit`。
- Modify `.github/workflows/ci.yml`。
- Modify `scripts/doctor.ps1`。
- Modify `tests/test_environment_doctor.py`。
- Keep `tests/select_tests.py` unchanged as the selector implementation dependency; the new gate consumes its existing structured result instead of moving or duplicating selector ownership。
- Modify `tests/test_matrix.yaml`，覆盖 local gate 和已确认高频缺口。
- Modify `tests/test_select_tests.py`。
- Modify `tests/README.md`。
- Modify `README.md`，记录本地入口和 manual-CI 边界。
- Modify `DEVELOPMENT_STANDARD.md`，固化三层本地门禁与 cleanup contract。

`.gitignore` 不改；application source、frontend source、runtime service、operator config、version file 和 package lockfile 均在实施边界外。

## 测试策略

### Unit tests

`tests/test_local_quality_gate.py` 覆盖：

- Windows/POSIX staged path normalization；
- 从 Git index 读取 staged Python blob；
- fatal Ruff command 构造；
- deleted-file 处理；
- irrelevant staged content 的 no-op success；
- gate-definition 文件 coherent-staging 拒绝；
- command-family 解析和拒绝；
- gate-definition 改动时强制注入 self-test；
- manifest 创建与 redaction；
- 每个 non-passed outcome；
- stale task HEAD 与 stale main SHA；
- main branch 拒绝；
- dirty worktree 拒绝；
- claim-check failure 传播；
- merge-preflight failure 传播。

subprocess、clock、Git output、guard output 和 filesystem root 必须可注入或 mock。测试验证真实行为，不测试 mock 调用本身。

### 临时仓库 integration tests

测试创建临时 Git repository 并证明：

1. staged invalid Python blob 使 commit mode 失败；
2. 同一文件的 unstaged edit 不影响 staged-blob lint；
3. staged valid Python blob 通过 commit mode；
4. closeout manifest 在固定 task/main SHA 上通过；
5. main 前移后 manifest 变为 `stale_main`；
6. required command 失败时不能得到 `passed`；
7. gate 从不运行 merge、branch delete、worktree remove 或 filesystem delete 命令。

### Workflow 与 doctor contracts

`tests/test_ci_workflow_contract.py` 保护：

- manual-only workflow dispatch；
- manual Ruff 无条件执行；
- fatal rule set 和 production root；
- 不再存在 unreachable PR-only Ruff branch。

`tests/test_environment_doctor.py` 保护：

- 正确 `.githooks` 配置；
- 缺失/错误 `core.hooksPath` 报告；
- gate script、Python 或 Ruff 缺失报告；
- read-only 行为和精确修复命令。

### Selector contracts

`tests/test_select_tests.py` 保护 gate file 和已确认 high-churn gap 的 focused mapping。实施计划必须给出精确 rule id 与 path，不能使用让每个任务都跑全量测试的 broad catch-all。

### Manual smoke

在隔离任务 worktree 的临时 Git repository 中：

1. 配置测试仓库使用 `.githooks`；
2. stage 一个故意非法的临时 Python 文件；
3. 确认 commit mode 以 fatal Ruff finding 非零退出；
4. 恢复临时文件且不影响其他工作；
5. stage 合法临时 Python 文件并确认 commit mode 成功；
6. 运行 closeout 并检查 bounded manifest；
7. 前移临时 main reference 并确认 manifest 变成 `stale_main`；
8. 恢复临时仓库状态。

smoke 不得使用根 `main`、当前 application file、active claim 或其他任务 worktree。

## 减少冲突规则

1. 任务只 claim 预期写入文件。
2. hot-file overlap 在实施前串行化，不等到 root-main merge 才发现。
3. 中间 commit 保持小且面向行为。
4. 验证记录精确 main SHA，main 移动后禁止复用旧证据。
5. 冲突在任务 worktree 解决并重验。
6. 根 `main` 一次只接收一个通过 gate 的任务，并使用 clean fast-forward。
7. 完成任务在 post-merge 证据后立即删除任务分支和 worktree。
8. active/blocked task 保留自己的 branch/worktree，直到能够安全收口。
9. 任何任务不得清理其他任务的 branch、worktree、junction、claim 或 manifest。

## 失败处理

- project Python 或 Ruff 缺失是 blocking environment failure，不是 skipped success。
- selector parse failure 记录 matrix path 和 bounded error type，并使 gate 失败。
- unsupported command 绝不通过 shell fallback 执行。
- test timeout 记录 command kind、duration 和 timeout state，不保存无界输出。
- claim-check unavailable 阻止 closeout，因为无法证明冲突保护。
- main 移动产生 `stale_main`，gate 不自动 merge 或 rebase。
- merge preflight 失败产生 `merge_conflict`，根 `main` 保持不变。
- post-merge 验证失败时任务保持未完全关闭，停止 branch/worktree cleanup，直到完成失败分类。
- cleanup 失败必须报告仍存在的 branch、worktree、junction 或 claim。

## 安全与日志

- matrix command string 仍视为需要 command-family validation 的 repository input。
- 禁止把选中命令交给 `shell=True`、`cmd /c` 或动态 PowerShell expression。
- 使用显式 argv 与 cwd。
- 不记录 environment variable、config content、prompt、provider payload、完整 source、完整 diff 或 secret。
- failure summary 必须限行和限长。
- 完整 command output 只存在当前 terminal，或项目策略要求的已有 bounded task log。
- gate 不提权、不安装依赖、不访问网络、不修改 operator config。

## Developer mode、runtime 与版本决策

- **Developer mode：** not affected；gate 操作 Git/validation surface，不改变应用 runtime mode。
- **Logging：** 仅新增 bounded local quality-gate manifest；无应用 runtime 行为变化，因此不新增 runtime-scene log。
- **Launcher refresh：** not needed；设计与实施只涉及 Git、tests、CI、scripts 和 docs。
- **Project memory：** 实施在本地 main 新鲜验证后更新或提议 quality-and-operations lane；设计轮不编辑 project memory。
- **Version impact：** `none`；这是本地开发治理和验证工具变化，不是 release application capability。

## 验收标准

1. tracked hook 不再选择空的 `unit` lane。
2. staged fatal Python error 阻止 commit，且不读取 unstaged content。
3. 普通中间 commit 不运行 broad behavioral test 或 frontend build。
4. 手动 GitHub Actions Ruff 在 `workflow_dispatch` 下实际执行。
5. closeout gate 从唯一现有 matrix 选择并执行 project-owned focused validation。
6. unsupported matrix command fail closed 且不执行。
7. gate-definition 改动不能削弱自身 mandatory self-test。
8. 本地 main SHA 变化使 prior closeout evidence 失效。
9. conflict detection 不修改根 `main`。
10. gate 从不执行 merge、branch delete、worktree remove、junction remove、claim release 或 application-state write。
11. 成功集成在本地 `main` 保留任务 commit，同时允许删除临时任务 branch/worktree。
12. validation 或 cleanup 失败留下显式可恢复状态，不产生 false completed。
13. 文档明确 completed task 清理自己的资源并保留 active foreign task。
14. focused gate、selector、CI contract、doctor 与 temporary-repository tests 通过。
15. 最终 implementation range 的 `git diff --check` 通过。
