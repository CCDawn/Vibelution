# Teams Source Collection 阶段 A+B Implementation Plan

- **Status:** in-progress
- **Owner:** codex-teams-source-collection-stage-a-b
- **Approved spec:** [`2026-07-13-teams-source-collection-vertical-split-design.md`](../specs/2026-07-13-teams-source-collection-vertical-split-design.md)
- **Planning claim:** `claim-229348c3d41b`
- **Implementation claim:** `claim-8c6da6444134`
- **Target branch/worktree:** `codex/teams-source-collection-stage-a-b` / `C:\Users\17533\Desktop\Vibelution-worktrees\teams-source-collection-stage-a-b`
- **Current blocker:** 已解除；`claim-6d545068f72a` 已关闭，loading commit `d86cd310` 已进入 local `main`
- **Scope:** 只实施 spec 的阶段 A（纯模型与测试接缝）和阶段 B（共享 read-query ownership）
- **Close condition:** 阶段 A+B 的代码、测试与 ownership 迁移完成，selector-selected gates 通过，提交合入 local `main`，claim/memory/Launcher/version decisions 收口；阶段 C/D 仍保持 deferred

## 1. 目标与执行结论

把 `TeamsRoute.tsx` 中 source collection 的纯推导和九个 shared research read queries 迁入唯一 typed owners，同时保持 UI、URL、query keys、`enabled`、AbortSignal、polling、mutation invalidation 和 backend contract 不变。

路由判定为 `DIRECT_IMPLEMENTATION`：A1、A2、A3、B 顺序修改同一个 hot Route，必须由一个 owner 在一个 worktree 串行执行，不创建并行实现分支。每个 checkpoint 独立 RED/GREEN、独立审查 diff，后一步消费前一步已验证的代码。

第一轮不得创建 controller/workspace/styles，不得迁移 mutation、draft、navigation、panel paths、Canvas、experiment 或 iteration 行为。

## 2. 已核验基线

计划编写时 local `main` 为 `ee20df33`。并发分支 `codex/route-loading-structure` 已有 clean commit `d86cd310`，相对 main 对 Teams 的有效变化是：

- 新增 `showTeamInitialLoadingSurface`，把初始 loading 与 unavailable 分开；
- `TeamsRoute.layout.test.ts` 新增 loading skeleton 与 unavailable tone contract；
- 不改 source collection query、model、mutation 或 workspace ownership。

`d86cd310` 只用于预审，不视为已合入事实。实施前必须读取 `claim-6d545068f72a` 的最终状态、实际 merge commit、diff 和验证结果，并重新运行 baseline。

当前 shared read-query 候选精确为九个：

1. `teamWorkflowQuery`；
2. `researchStageRoundStatusQuery`；
3. `teamWorkflowCandidatesQuery`；
4. `teamWorkflowCandidateGraphQuery`；
5. `teamWorkflowCoordinationStatusQuery`；
6. `teamWorkflowKnowledgeIngestionStatusQuery`；
7. `teamWorkflowOfficialModelEvidenceStatusQuery`；
8. `teamWorkflowSourceQualityStatusQuery`；
9. `teamWorkflowPaperNoteChunkStatusQuery`。

`sourceCollectionRunsQuery`、`sourceCollectionSummaryQuery`、`runtimeSummaryQuery`、run status/records/assignments queries 均属于后续 source controller ownership，不进入阶段 B。

selector probe 对计划文件路径同时命中 `teams-knowledge` 与 `frontend-workbench`，当前无需修改 `tests/test_matrix.yaml`。

## 3. 文件职责

| File | 阶段 | 责任 |
| --- | --- | --- |
| `web/src/routes/teams/source-collection/runModel.ts` | A1 | run 过滤/选择/计数、stable count、display state、runtime active-run projection |
| `web/src/routes/teams/source-collection/runModel.test.ts` | A1 | run fallback、显式选择、nested metrics、loading labels、display phase、runtime active item |
| `web/src/routes/teams/source-collection/stageProjection.ts` | A2 | stage card types、状态/readiness/count/label、writeback-observed task projection |
| `web/src/routes/teams/source-collection/stageProjection.test.ts` | A2 | active/partial/blocked/completed、count fallback、interrupted/recovery labels、observed task IDs |
| `web/src/routes/teams/source-collection/evidenceModel.ts` | A3 | provenance、source category/filter/count、candidate trace、Evidence Ledger、excluded recovery |
| `web/src/routes/teams/source-collection/evidenceModel.test.ts` | A3 | PDF/web/dataset/local/missing 分类、filter counts、missing anchor、excluded recovery |
| `web/src/routes/teams/useResearchWorkflowResources.ts` | B | 九个 shared query 与 custom query-key owner；只读 typed resources |
| `web/src/routes/teams/useResearchWorkflowResources.contract.test.ts` | B | query key/signal/enabled/polling/唯一 owner 与禁止 mutation/state/navigation contract |
| `web/src/routes/TeamsRoute.tsx` | A+B | 保留 route state/navigation/mutation；改为导入 models 并无条件调用 shared hook |
| `web/src/routes/TeamsRoute.logic.test.ts` | A | 只保留 Route 自身 polling；source model behavior 迁往 scoped tests |
| `web/src/routes/TeamsRoute.layout.test.ts` | A+B | 保留 Route mount/loading/navigation/shared-hook contract；移除已迁移 internals 的 raw assertions |
| `web/src/routes/teams/teamsRouteViewModel.ts` + test | A1 | 所有消费者迁移并 GREEN 后删除，不留 alias |

若实际 selector 不再命中新目录，才最小更新 `tests/test_matrix.yaml` 与 `tests/test_select_tests.py`；否则禁止顺手修改 matrix。

## 4. 类型与依赖规则

- 三个 model 文件不得 import React、React Query、Router、navigation、mutation、styles 或 Route。
- model 可依赖 `web/src/api/types/**` 和本目录纯模型；遇到 Route-local 大类型时定义最小结构类型，不把 UI/mutation fields 整体拖入。
- `ResearchStageRoundStatusPayload`、stage card/phase/round 的共享只读类型迁入 `stageProjection.ts` 并从 Route/hook type-import。
- official-model-evidence、paper-note-chunk、source-quality 的只读 response types 迁入 `useResearchWorkflowResources.ts` 并导出给 Route；mutation payload types 继续留在原 owner。
- Evidence tone 使用 model 自有字符串 union，不 import `TeamSourceResultTone`；Route 在 UI boundary 做结构兼容。
- custom keys `researchStageRoundStatusQueryKey`、`officialModelEvidenceStatusQueryKey`、`paperNoteChunkStatusQueryKey`、`sourceQualityStatusQueryKey` 从 shared hook 模块导出。Route mutation 暂时继续 import 它们做现有 `setQueryData` / invalidation，禁止复制 key。
- 不新增 barrel、index file、compatibility alias 或空 scaffold。

## 5. Shared hook contract

```ts
type ResearchWorkflowResourceDemand = {
  workflow: boolean;
  stageRound: boolean;
  candidates: boolean;
  candidateGraph: boolean;
  coordination: boolean;
  knowledgeIngestion: boolean;
  modelEvidence: boolean;
  sourceQuality: boolean;
  paperNoteChunks: boolean;
};

type ResearchWorkflowResourcesInput = {
  teamId: string;
  demand: ResearchWorkflowResourceDemand;
  pageVisible: boolean;
  stageWritebackSync: {
    active: boolean;
    pendingTaskIds: readonly string[];
  };
};
```

Route 继续计算当前九个 `enabled` 条件，并一一映射到 `demand`。hook 对每个 query 使用 `enabled: Boolean(teamId && demand.<resource>)`；不得把多个 demand 合并成更宽条件。

hook 内部返回按领域命名的 typed query results：`workflow`、`stageRound`、`candidates`、`candidateGraph`、`coordination`、`knowledgeIngestion`、`modelEvidence`、`sourceQuality`、`paperNoteChunks`。Route 初始集成时通过解构 alias 保持现有变量名和下游 callsites，降低行为 diff。

`stageWritebackSync` 仅供 candidates/source-quality polling 复用现有 writeback grace；hook 不创建 `useState`、`useMutation`、effect、navigation 或第二份 pending IDs。

## 6. 实施步骤

### Task 0：解除 blocker 与重建基线

- [x] 确认 `claim-6d545068f72a` 已 completed/released，且不存在 replacement claim。
- [x] 读取其 final commit、`git diff main...<branch>`、focused tests 和 build 证据；确认 loading ownership 已进入 local `main` 或明确取消。
- [x] 确认 root `main` clean；从最新 local `main` 创建目标 branch/worktree。
- [x] 运行 guard `status`、exact-scope `check`，认领本计划列出的 Route/tests/new files/old helper files。
- [x] 重新测量 `TeamsRoute.tsx` 行数、query/mutation/hooks 数量，运行当前 Teams focused baseline；若 baseline 非全绿，停止并归因。

### Task A1：runModel 紧凑 TDD

- [x] RED：新增 `runModel.test.ts`，迁入旧 helper tests，并为 `deriveSourceCollectionDisplayState`、`sourceCollectionStableCountText`、`sourceCollectionActiveWorkRunFromRuntime` 建立行为用例；运行最窄 Vitest，确认因新 owner/exports 缺失而失败。
- [x] GREEN：移动 run metrics/default selection、run labels/count text、display state、runtime active-run projection 及其最小类型依赖。
- [x] 更新 Route imports 和 `TeamsRoute.logic.test.ts`；确认 Route 不再定义已迁移函数。
- [x] 所有旧消费者归零且新 tests GREEN 后删除 `teamsRouteViewModel.ts` 与旧 test，不保留 re-export。
- [x] checkpoint：focused model/logic/layout tests、`git diff --check`，提交 `refactor(web): extract source collection run model`。

### Task A2：stageProjection 紧凑 TDD

- [x] RED：覆盖 stage state/count fallback、partial/blocked/completed、task progress、interrupted/recovery label、writeback observed task IDs。
- [x] GREEN：移动 stage projection types/functions；对 Route 大 payload 使用窄结构 input，不移动 mutation 或 URL logic。
- [x] polling interval 的 React Query adapter 留给阶段 B；纯 stage model 只提供 cards/observed-task facts。
- [x] 迁移对应 raw assertions，保留 loading-state 与 route shell assertions。
- [x] checkpoint：stage/run/logic/layout tests、`git diff --check`，提交 `refactor(web): extract source collection stage projection`。

### Task A3：evidenceModel 紧凑 TDD

- [x] RED：覆盖 source category、PDF/web/dataset/local/missing、filter counts、candidate/record provenance、Evidence Ledger missing-anchor 与 excluded recovery。
- [x] GREEN：移动 provenance/filter/trace/ledger/recovery types/functions；UI-specific ReactNode、panel props 和 styles 留在 Route/view。
- [x] 从 Route 删除已迁移 declarations 和无消费者 imports；不得复制同一计算形成双 owner。
- [x] checkpoint：三个 model tests、logic/layout tests、`git diff --check`，提交 `refactor(web): extract source collection evidence model`。

### Task A Gate

- [x] `TeamsRoute.logic.test.ts` 不再从完整 Route import source model functions。
- [x] Route 不包含已迁移 helper definitions；三 model 文件不依赖 React/Query/Router/styles。
- [x] 运行 focused Vitest 与 `npm --prefix web run build`；失败必须在进入 B 前解决或回滚 A。

### Task B1：shared query contract RED

- [x] 新增 `useResearchWorkflowResources.contract.test.ts`，先断言新模块存在且拥有精确九个 query。
- [x] 对每个 query 锁定原 query key、`queryFn: ({ signal })`、`{ signal }` 传递、独立 demand-enabled 条件。
- [x] 锁定 stage-round/candidates/source-quality/ingestion 当前 polling policy，以及 hook 不包含 `useMutation`、`useState`、navigation、draft 或 panel import。
- [x] 锁定 Route 只调用 shared hook，不再声明九个同 key queries；先运行得到目标 RED。

### Task B2：实现唯一 read-query owner

- [x] 创建 typed hook，按当前顺序无条件调用九个 `useQuery`；`enabled` 只控制请求，不控制 hook mount。
- [x] 移入四个 custom query-key helpers 和三个 Route-local只读 status type families；Route mutation 通过 import 继续使用同一 key。
- [x] 内部使用 `stageRound.data` 与显式 `stageWritebackSync` 保持 candidates/source-quality polling；knowledge-ingestion 继续只在 active work run 时轮询。
- [x] 返回九个命名 query results，不返回 `Record<string, unknown>`，不包装 mutation 或 navigation。

### Task B3：Route 集成与 ownership 清理

- [x] Route 按现有 booleans 构造 exact `demand`，无条件调用 hook，并 alias 回现有 query variable names。
- [x] 删除 Route 中九个 `useQuery` bodies、已迁移 key/type definitions 和对应 raw-source ownership assertions。
- [x] 保持 `sourceCollectionRunsQuery`、summary/runtime/run details queries 和全部 mutations 原位。
- [x] contract/layout/logic/model tests GREEN 后运行 build；若任何 query key、enabled、polling、signal 或 invalidation diff，停止并恢复 Route declarations，不保留双 owner。
- [x] checkpoint：提交 `refactor(web): centralize research workflow reads`。

## 7. 验证命令

实施 worktree 中先生成 selector 输出：

```powershell
& ".\.venv\Scripts\python.exe" "tests\select_tests.py" --from-git main --json
```

Frontend focused RED/GREEN 在 `web` 目录运行直接 Vitest entry：

```powershell
node node_modules/vitest/vitest.mjs run `
  src/routes/teams/source-collection/runModel.test.ts `
  src/routes/teams/source-collection/stageProjection.test.ts `
  src/routes/teams/source-collection/evidenceModel.test.ts `
  src/routes/teams/useResearchWorkflowResources.contract.test.ts `
  src/routes/TeamsRoute.logic.test.ts `
  src/routes/TeamsRoute.layout.test.ts `
  src/routes/TeamsRoute.canvas-data.test.ts
```

最终 gate 从 repository root 串行执行：

```powershell
git diff --check
& ".\.venv\Scripts\python.exe" -m pytest `
  tests/test_team_service.py `
  tests/test_team_knowledge_service.py `
  tests/test_team_workflow_orchestration_service.py `
  tests/test_team_workflow_routes.py -q
npm --prefix web run build
node 挑战杯/build_research_flow_site.mjs
node web/node_modules/vitest/vitest.mjs run
```

Challenge Cup generator 前后记录 `git status --short`；generated HTML 出现语义 diff 即停止。阶段 A+B 不移动 DOM/styles，因此不要求新增视觉设计，但代码合入后仍须通过 Launcher 刷新做现有 Teams standalone/embedded smoke；若 active-work guard 阻止刷新，使用项目标准 blocker 文案。

## 8. 回滚与 Stop Conditions

阶段 A checkpoint 可通过恢复 Route helper declarations/imports 和旧 tests 独立回滚；阶段 B 通过恢复九个 Route query declarations 独立回滚。不得用 wrapper alias、双 query owner 或双计算路径作为长期回滚兼容层。

出现以下任一情况立即停止当前 checkpoint：

- loading claim 未关闭或出现新的 exact-scope collision；
- 需要修改 backend endpoint、DTO、persisted fact、mutation、URL、draft、styles 或 panel path；
- hook 需要条件调用，或 inactive demand 仍触发请求；
- query key、AbortSignal、polling、enabled、cache write/invalidation 与基线不一致；
- 纯 model 必须 import Route、React、React Query、Router 或 UI style owner；
- focused tests、build 或 generated site 暴露不可解释的行为变化。

## 9. 收口判断

- **Logging:** behavior-preserving ownership refactor，不新增 runtime-scene logging；若观察到运行时行为变化，停止并重新分类。
- **Version impact:** `none`；不修改 `VERSION`、`CHANGELOG.md`、`web/package.json`、`web/package-lock.json`。
- **Launcher:** code integration 后 required before runtime verification；docs-only planning 不需要。
- **Memory:** A+B 合入后同步 `web-workbench-surface` 的 durable ownership decision、commit 与验证结果；计划阶段只维护 claim，不写完成事实。
- **Deferred:** 阶段 C controllers 与阶段 D workspace/styles 必须在 A+B 合入后重新审阅，不能顺手进入本 worktree。
