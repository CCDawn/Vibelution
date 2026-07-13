# Teams Source Collection 垂直拆分设计

- **Status:** draft
- **Owner:** codex-teams-source-collection-split-design
- **Claim:** `claim-a6c64dcaf2e1`; branch `codex/teams-source-collection-split-design`; worktree `C:\Users\17533\Desktop\Vibelution-worktrees\teams-source-collection-split-design`
- **Scope:** 在不改变用户可见行为、后端 API、React Query 契约和 Challenge Cup 工作流语义的前提下，把 `TeamsRoute.tsx` 中的 source collection 纯模型、共享读取资源、行为控制器和视图组合迁入明确的 route-local ownership boundary
- **Supersedes:** 仅取代 [`2026-07-04-frontend-componentization-migration-playbook.md`](2026-07-04-frontend-componentization-migration-playbook.md) 中 Q3 第 1 项和第 18 节关于 Teams source collection 的 helper-only 下一批建议；该 playbook 的其余组件化与视觉规则继续有效。本设计不重新激活任何 historical large-file plan
- **Implementation link:** 尚未创建；须先完成书面 spec 审阅，并等待 `claim-6d545068f72a` 对 `TeamsRoute.tsx` / `TeamsRoute.layout.test.ts` 的工作结束（合入、取消或释放）后，从届时最新 local `main` 重新基线化
- **Validation:** 当前基线 53/53 Teams focused tests 通过；实施阶段使用 selector-selected Teams backend tests、拆分后的 focused Vitest、全量 frontend Vitest、production build、Challenge Cup flow regeneration/diff check、桌面与窄屏视觉等价检查
- **Close condition:** 用户批准书面 spec，且后续实施计划能把第一阶段映射到具体文件、依赖、回滚点和验证命令；实现完成不属于本 spec 当前状态

用户已通过“继续”批准进入本方向的书面设计阶段；本文件中的具体边界、契约和实施门禁仍须用户审阅后才可进入实施计划。

## 1. 设计结论

`TeamsRoute.tsx` 仍是当前风险调整后 ROI 最高的前端拆分目标，但拆分不能继续停留在 JSX/panel extraction，也不能把现有复杂度整体搬进一个新的 giant hook。

采用以下顺序：

1. 先迁移纯模型和相应测试，建立不依赖 React Route 的稳定逻辑边界；
2. 再建立一个共享 research workflow 读取层，消除 source collection 与 overview/graph/candidates 之间的 query ownership 歧义；
3. 后续按 run、evidence、completion 三个能力边界迁移状态、mutation、effect 和 cache reconciliation；
4. 最后让 source collection workspace 组合现有 panels，并把 route 缩成 Team 选择、顶层导航和 workspace mount。

第一份实施计划只覆盖步骤 1 和步骤 2。步骤 3、步骤 4 必须在第一阶段验证并合入后重新审阅，不允许在同一初始 patch 中顺手完成。

## 2. 当前基线与问题机制

当前 `web/src/routes/TeamsRoute.tsx`：

- 13,488 行、约 650 KB；
- 组件主体从约第 4,677 行延伸到文件末尾；
- 直接或嵌套拥有 32 个 `useState`、25 个 `useQuery`、31 个 `useMutation`、37 个 `useMemo`、11 个 `useEffect` 和 4 个 `useRef`；
- 从 43 个模块导入约 157 个符号；
- AST 按 owning declaration 保守统计，source collection 相关纯声明和组件语句至少覆盖 5,770 行；
- 2026-07-01 以来有 67 个修改该文件的提交，增删 churn 约 6,359 行。

项目已经有 18 个 `TeamSourceCollection*.tsx` 展示组件，共约 1,839 行。这些组件没有 `useQuery`、`useMutation` 或业务状态 hook。现有 `teams/TeamsSourceCollectionPanel.tsx` 也只是把 props 原样转交给 `TeamSourceCollectionOverviewPanel` 的 9 行 wrapper。

因此问题不再是“JSX 没有拆开”，而是 ownership inversion：

- 展示 DOM 已经分散；
- query、mutation、URL sync、draft、阶段推进、Evidence Ledger、cache invalidation 和大量 view-model assembly 仍集中在 Route；
- Route 同时为 standalone knowledge collection、legacy embedded source collection、research overview、candidate、graph 和 ingestion 视图准备数据；
- 新增 presentation wrapper 只会继续增加 props 和 source-string tests，不会降低状态耦合。

本设计以 ownership 和依赖方向作为成功标准，不把任意行数阈值当作主要验收条件。

## 3. 目标与非目标

### 3.1 目标

- `TeamsRoute.tsx` 最终只拥有 Team 选择、顶层 workspace routing、URL/导航适配、通用 Team/Canvas shell 和子 workspace mount；
- source collection 的纯状态推导可以在无 React、无 React Query、无路由环境下单元测试；
- 跨 research 视图复用的 read query 有唯一 owner，不因拆分重复请求或分叉 cache key；
- source collection 的 run、evidence、completion 行为各有明确 controller owner；
- standalone 和 embedded 两种 UI 使用同一份 controller state，并保留当前 URL、草稿和选中批次行为；
- 现有 child panels 继续复用，不做批量重命名或搬目录；
- 每一阶段可独立验证、提交和回滚。

### 3.2 明确不做

- 不修改 backend route、service、DTO 或 Challenge Cup workflow semantics；
- 不修改 React Query key identity、`enabled` 条件、AbortSignal 传播、轮询频率或 invalidation 语义；
- 不重构 experiment、iteration、AI Search、Canvas drag/layout、普通 Team chat 或 archive 行为；
- 不做视觉重设计、copy 改写、HeroUI/VUI 迁移或响应式 IA 改造；
- 不新增全局 store、React context、第三方依赖或第二套 source collection state；
- 不把 18 个现有 panels 批量移动到新目录；
- 不保留无消费者的 compatibility barrel、alias wrapper 或重复 helper；
- 不把 `TeamsRoute.layout.test.ts` 一次性重写成与本次迁移无关的大测试工程。

## 4. 已否决方案

### 4.1 继续抽 presentation components

项目已经有 18 个无业务 hook 的 source collection panels，但 Route 仍有 13,488 行。继续抽 JSX 会降低局部 DOM 密度，却不会移动 query、mutation、effect 或 cache ownership，ROI 已经明显递减。

### 4.2 一个 `sourceCollectionModel.ts` 加一个 giant hook

把所有纯 helper 放进一个 2,000+ 行 model，再把所有查询、变更和状态放进一个数千行 `useSourceCollectionWorkspace.ts`，只会把原 god file 变成两个新的 god files。根 composite hook 必须只负责组合子 controller 和生成稳定的 workspace contract，不直接承载大段 endpoint/mutation body。

### 4.3 先拆 experiment/iteration

experiment/iteration 是更干净的未来垂直边界，但不会解决 source collection 与 shared research resources 的当前耦合。它可以成为本设计完成后的下一条 UI lane，不作为本轮前置替代。

## 5. 目标模块边界

目标形态如下；文件只在真实代码迁入时创建，不预建空目录、barrel 或单导出 wrapper：

```text
web/src/routes/
  TeamsRoute.tsx
  TeamsRoute.styles.ts
  TeamSourceCollection*.tsx                 # 现有展示组件，第一阶段不搬路径
  teams/
    useResearchWorkflowResources.ts         # 跨 research 视图共享的 read-query owner
    useResearchWorkflowResources.contract.test.ts
    source-collection/
      runModel.ts                           # run 选择、计数、运行显示状态
      runModel.test.ts
      stageProjection.ts                    # 阶段卡片、状态、readiness 投影
      stageProjection.test.ts
      evidenceModel.ts                      # provenance、过滤、Evidence Ledger
      evidenceModel.test.ts
      useSourceCollectionRun.ts             # 后续：run/search/output/storage
      useSourceCollectionEvidence.ts        # 后续：extraction/screening/quality
      useSourceCollectionCompletion.ts      # 后续：graph/ingestion/completion
      useSourceCollectionController.ts      # 后续：只组合子 controller 与 UI-local state
      SourceCollectionWorkspace.tsx         # 后续：选择 standalone/embedded view
      SourceCollectionWorkspace.styles.ts
      SourceCollectionStandaloneView.tsx
      SourceCollectionOverviewView.tsx
```

### 5.1 第一阶段实际文件范围

第一阶段只允许：

- 新增 `runModel.ts`、`stageProjection.ts`、`evidenceModel.ts` 及对应测试；
- 新增 `useResearchWorkflowResources.ts` 及 scoped contract test；
- 修改 `TeamsRoute.tsx`，使其导入这些纯模型并调用共享读取 hook；
- 修改 `TeamsRoute.logic.test.ts` 和 `TeamsRoute.layout.test.ts` 中与已迁移 ownership 直接相关的断言；
- 在所有调用迁移后删除 `teams/teamsRouteViewModel.ts` 及其旧测试，把四个 run helper 收口到 `runModel.ts`；
- 如 selector 对最终路径不再命中，再最小修改 `tests/test_matrix.yaml` / selector tests。当前 probe 已确认上述新路径会同时命中 `teams-knowledge` 与 `frontend-workbench`，因此默认不改 matrix。

第一阶段不得创建 controller 或 workspace view 文件，也不得迁移 mutation、styles 或现有 panel paths。

### 5.2 后续清理

当 workspace composition 真正迁入后：

- 删除 `teams/TeamsSourceCollectionPanel.tsx`，不保留 alias；
- source collection 独占的 page/grid/run-badge/step-state classes 迁入 `SourceCollectionWorkspace.styles.ts`；
- 新 workspace 不得导入 `TeamsRoute.styles.ts`；
- `TeamsRoute.layout.test.ts` 只保留 route shell、导航、mount 和跨 workspace invariants；source collection 内部 composition assertion 迁到自己的 scoped tests。

## 6. Source Of Truth 与写入所有权

| Fact | Canonical source | Writer / owner | Readers / projections | Refresh / invalidation | 旧 owner 清理 |
| --- | --- | --- | --- | --- | --- |
| 当前 Team、顶层 research view、Team/Agent deep link | `TeamsRoute` URL 参数与现有 selected-Team resolution | `TeamsRoute` route adapter | Team shell、所有 workspace inputs | 现有 search-param 与 Team query 规则 | 不迁入 source controller |
| standalone 当前 source stage | `collectionStage` URL 参数 | Route adapter；controller 通过显式 callback 请求变更 | Source workspace stage selection | 保留 `replace` URL sync | Route 不再直接组装 stage view model |
| embedded 当前 source stage | source controller local state | `useSourceCollectionController` | embedded workspace | controller lifecycle | 删除 Route 中对应 `useState` / effect |
| research workflow、stage round、candidates、graph、coordination、ingestion、model evidence、source quality、paper chunks 的读取 snapshot | backend API + React Query cache | `useResearchWorkflowResources` | source workspace、overview、graph、candidates、ingestion | 完全复用现有 key、signal、enabled、polling | Route 删除对应 `useQuery` bodies |
| source run draft、output draft、selected run、records、assignments、run/runtime snapshot | backend API + controller local draft/selection | 后续 `useSourceCollectionRun` | source overview、finding、run switcher | 复用现有 source keys 与 mutation invalidation | Route 删除 source-specific state/query/mutation |
| extraction、screening、quality 与 Evidence Ledger projection | backend candidate/record metadata | 后续 `useSourceCollectionEvidence`；纯推导在 `evidenceModel.ts` | extraction、screening、detail、graph | 复用 candidate/source-quality invalidation | Route 删除 provenance/filter/quality assembly |
| relation graph、ingestion、completion flow | backend graph/knowledge work-run state | 后续 `useSourceCollectionCompletion` | relations、memory、completion panels | 复用 graph/knowledge invalidation 与 work-run polling | Route 删除 completion action/readiness assembly |
| source workspace DOM 与本地 style | typed workspace view model | `SourceCollectionWorkspace` 与现有 child panels | 用户界面 | React render | 删除 Route render helper 与独占 style keys |

不允许 controller、workspace component 或 legacy research panel 各自创建相同 query key 的第二个 owner。共享 snapshot 必须通过 typed contract 传递。

## 7. 数据流与接口契约

### 7.1 共享读取层

`useResearchWorkflowResources` 只拥有读取和 query-state projection，不拥有 mutation、导航、草稿或可见 UI：

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
};
```

第一阶段由 Route 按现有 view/selected-stage 条件产生 `demand`，不得放宽任何 `enabled` 条件。后续 controller 迁移完成时，source-specific demand 由 controller 计算，但 contract 不变。

输出按领域命名，保留 `data`、`isPending`、`isFetching`、`error` 和必要 refetch metadata。不得把所有 query object 放进无类型的 `Record<string, unknown>`。

### 7.2 Source controller

后续 `useSourceCollectionController` 始终在 `TeamsRoute` 顶层调用；不能放进条件分支，也不能只在 workspace 可见时 mount。它接收 `active` / demand flags 控制查询和后台动作，但保留 hook order、草稿、选中 run 和阶段 UI state。

```ts
type SourceCollectionControllerInput = {
  teamId: string;
  team: Team | null;
  canvas: TeamOrganizationCanvas | null;
  activeAgents: readonly AgentConfigWorkspaceAgent[];
  lang: "zh" | "en";
  pageVisible: boolean;
  active: boolean;
  standalone: boolean;
  requestedStage: SourceCollectionStageModuleId | null;
  resources: ResearchWorkflowResources;
  onStandaloneStageChange: (stage: SourceCollectionStageModuleId) => void;
  onNavigate: (target: SourceCollectionNavigationTarget) => void;
};
```

controller 输出必须按 `run`、`stages`、`evidence`、`completion`、`commands`、`errors` 分组。禁止返回未分组的几十个 Route props，也禁止返回 ReactNode；ReactNode 只在 workspace/view 层生成。

### 7.3 Workspace view

`SourceCollectionWorkspace` 接收 typed view model 和 command groups：

```ts
type SourceCollectionWorkspaceProps = {
  variant: "standalone" | "embedded";
  model: SourceCollectionWorkspaceModel;
  commands: SourceCollectionWorkspaceCommands;
};
```

它只选择 `SourceCollectionStandaloneView` 或 `SourceCollectionOverviewView`，并组合现有 `TeamSourceCollection*Panel`。它不调用 `fetchJson`、`useQuery`、`useMutation`，不拥有第二份 draft，也不自行推断 readiness。

## 8. 状态与生命周期不变量

拆分必须保持以下行为：

1. 切换 research view 后，当前 source draft、output draft、selected run、filter、分页和 candidate selection 不得因 child unmount 意外重置；
2. URL 带 `researchView=knowledge_collection` / `collectionStage=<stage>` 时，standalone view 继续由 URL 恢复阶段；
3. embedded legacy source view 不强制写入 standalone URL 参数；
4. Team 或 run 变化时，现有分页 reset、pending stage task、writeback grace 和 candidate selection effect 按原依赖顺序执行；
5. inactive workspace 的 query 继续由 `enabled` policy 停止，不因顶层 hook 常驻而后台请求；
6. mutation pending/error/result 必须继续按 selected Team/run/record identity 隔离；
7. query cancellation 继续把 React Query `signal` 传给 `fetchJson` 或 shared client；
8. source run start、search、extraction、quality、graph、ingestion 和 completion 的 invalidation 集合与执行顺序保持不变；
9. fallback、loading、partial、failed 和 completed 状态继续显式展示，不把 partial/fallback 投影成普通成功；
10. developer mode 与 formal mode 使用同一 frontend controller、query key 和 backend contract，判断为 `parity preserved`。

## 9. 实施阶段与回滚边界

### 阶段 A：纯模型和测试接缝

迁移 run selection/count/display state、stage projection/readiness/labels、provenance/filter/Evidence Ledger。每个模块只依赖 API types 和纯函数，不依赖 React、React Query、Router、navigation、mutation 或 styles。

成功证据：

- 现有 logic cases 在新 model tests 中通过；
- `TeamsRoute.logic.test.ts` 不再从完整 Route 导入 source collection 纯函数；
- Route 不再定义已迁移 helper；
- 无 API/query/mutation diff。

回滚：只恢复 imports/helper definitions 和对应 tests，不影响运行时写入。

### 阶段 B：共享 read-query ownership

按现有顺序迁移 shared research queries。第一份 implementation plan 到此结束。

成功证据：

- 每个 shared query key 只有一个 hook owner；
- `signal`、`enabled`、stale/refetch policy 和 typed response 保持一致；
- source、overview、graph、candidates、ingestion 仍读取同一 snapshot；
- focused Teams frontend tests、backend workflow tests 和 build 通过。

回滚：恢复 Route 内 query declarations；不保留 wrapper hook 或双 owner。

### 阶段 C：能力 controller

第一阶段合入并重新审阅后，依次迁移：

1. run/search/output/storage；
2. extraction/screening/quality/evidence；
3. relations/graph/ingestion/completion；
4. selected stage、URL adapter callback、focus/filter/pagination 等 workspace-local state。

每个能力迁移后立即删除 Route 旧 owner，不允许 temporary dual mutation owner 跨提交存在。

### 阶段 D：workspace composition 与清理

迁移 standalone/embedded composition、独占 styles 和 scoped layout tests；删除 Route render helpers、旧 wrapper 和无消费者 imports。现有 child panels 保持路径与行为。

成功后，Route 中允许保留 source collection route key、mount props 和 navigation adapter，但不再直接定义 source business helper、source-specific `useState`、`useQuery`、`useMutation` 或 `renderSourceCollection*`。

## 10. 测试迁移策略

当前基线：

- `TeamsRoute.canvas-data.test.ts`：8 tests；
- `TeamsRoute.logic.test.ts`：9 tests；
- `TeamsRoute.layout.test.ts`：36 tests；
- 合计 53/53 通过。

`TeamsRoute.layout.test.ts` 约 2,657 行、2,055 个 `expect`，大量断言依赖 `TeamsRoute.tsx?raw`、函数名和 `routeSource.slice(...)`。测试迁移遵循“代码 ownership 移到哪里，断言就随该 ownership 移到哪里”：

- Route test 保留 Team 选择、deep link、workspace mount、shared hook 调用、Canvas/generic Team shell 和跨 workspace invariant；
- model behavior 进入三个纯 model tests；
- shared query key/signal/enabled contract 进入 `useResearchWorkflowResources.contract.test.ts`；
- workspace 组合、局部 styles 和 panel ownership 在阶段 D 进入 scoped workspace test；
- 不为了减少行数删除仍保护用户行为的断言；
- 不继续用 `routeSource.slice("renderSourceCollection...")` 锁定已迁移内部函数位置；
- 与本次迁移无关的视觉 contract 不在第一阶段重写。

实施验证命令由 `tests/select_tests.py` 生成的 matrix 为准，当前预期至少包括：

```powershell
git diff --check
node web/node_modules/vitest/vitest.mjs run TeamsRoute.layout.test.ts TeamsRoute.logic.test.ts
npm --prefix web run build
.\.venv\Scripts\python.exe -m pytest tests/test_team_service.py tests/test_team_knowledge_service.py tests/test_team_workflow_orchestration_service.py tests/test_team_workflow_routes.py -q
node 挑战杯/build_research_flow_site.mjs
node web/node_modules/vitest/vitest.mjs run
```

Challenge Cup generation 应产生相同语义；若 generated HTML 出现行为内容 diff，停止并判断是否意外改变 workflow projection。styles 在阶段 D 迁移后，使用真实浏览器检查 standalone 与 embedded workspace 的桌面宽度和窄屏 fallback，确认无布局漂移、重叠、横向溢出或 loading-to-loaded shift。

## 11. 实施前置条件与并发治理

截至本 spec 编写时，`claim-6d545068f72a` 正在修改：

- `web/src/routes/TeamsRoute.tsx`；
- `web/src/routes/TeamsRoute.layout.test.ts`；
- route-loading shell/router files。

因此本 spec 可以评审，但任何代码阶段都必须等待该 claim 合入或释放。实施前必须：

1. 从届时最新 local `main` 创建新的 task worktree；
2. 重新运行 guard `status` / exact-scope `check`；
3. 读取该 claim 的最终 diff、commit 和验证结果，不依据其聊天总结；
4. 重新测量 Route ownership 和 53-test baseline；
5. 将 loading-state 新 ownership 纳入实施计划，避免回退已合入结构；
6. 为第一阶段精确 claim `TeamsRoute.tsx`、相关 tests 和新增 model/resource files。

由于所有阶段都修改同一 hot Route，不建议并行分支实现。采用一个 owner、一个 implementation worktree、按阶段 checkpoint commit 顺序推进；后续阶段消费前一阶段已验证 artifact。

## 12. Stop Conditions

任一情况出现即停止当前阶段，不用兼容层掩盖：

- 需要改变 backend endpoint、DTO 或 persisted source collection facts；
- 相同 query key 或 mutation 出现两个长期 owner；
- 为保持测试通过而保留 Route 和新模块双写/双算；
- hook 只能通过条件调用或 workspace mount 才工作；
- 切换 view、Team 或 run 后发生草稿/选择状态丢失；
- query `enabled`、AbortSignal、polling 或 invalidation 与当前行为不一致；
- 新 workspace 必须导入 `TeamsRoute.styles.ts`；
- 需要顺带修改 experiment、iteration、Canvas、AI Search 或 Challenge Cup workflow semantics；
- active claim 或 local `main` 发生新的 scope collision；
- focused tests、build 或 generated-site diff 暴露无法归因于结构迁移的行为变化。

## 13. 完成判据

本架构拆分最终完成需要同时满足：

- `TeamsRoute.tsx` 不再直接 import source collection panels 来组装业务 workspace；
- Route 不再拥有 source-specific query/mutation/state/effect 和 `renderSourceCollection*`；
- shared research reads、source commands 和 workspace view 各有唯一 typed owner；
- standalone/embedded URL、草稿、run selection、stage progress 和错误状态与基线一致；
- 旧 `teamsRouteViewModel.ts`、`TeamsSourceCollectionPanel.tsx` 和迁移后的 raw-source assertions 已删除，不留 alias；
- child style ownership 完整，workspace 不引用 parent Route styles；
- selector-selected backend/frontend tests、full Vitest、build、Challenge Cup generation diff check 和浏览器视觉等价检查通过；
- Launcher 在 active-work guard 允许后刷新，或以标准 blocker 文案明确延期；
- project memory、claim、version impact 和实施文档状态完成收口。

预期 line reduction 仅作规划信号：阶段 A/B 后 Route 约进入 10,500–11,500 行区间，阶段 C/D 后约进入 7,000–8,000 行区间。实际验收以 ownership、行为等价和无重复路径为准，而不是为了满足数字继续拆碎模块。

本次是内部结构重构，预期 version impact 为 `none`；若实施发现必须改变用户可见行为，则离开本 spec，重新评估为至少 `patch`。spec 本身无需 Launcher refresh，也不新增 runtime-scene logging；实施阶段若严格保持行为不变，logging 仍为 `not affected`。
