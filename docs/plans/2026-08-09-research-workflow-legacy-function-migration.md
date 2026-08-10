# 挑战杯旧功能完整迁移方案 · Workflow 工作台

Status: **Completed (T-M1 ~ T-M6 implemented and verified)**

Created: 2026-08-09

Product contract: `docs/prds/2026-08-07-research-process-flow-single-page-workspace.md`

Implementation authority: `docs/archive/plans/2026-08-07/challenge-cup-workflow-implementation-plan.md`（Task 0-10 任务图，本方案是其 Task 6 "EMBED by node adapters" 的补完 + 后续面）

## 0. 执行结果（2026-08-09）

| 任务 | 状态 | 交付 |
| --- | --- | --- |
| T-M1 后端命令接线 | ✅ | `result_package.py`（结果包组装/幂等/availability）、`evidence_graph_projection.py`（证据图投影：artifact dict 优先 + research-loop evidenceRecords 回退）、`node_command_adapter.py` capability+handler 扩展（`build_package`/`open_evidence_graph`）；前端 `EXECUTABLE` 全量接线、删除 `EXPLICITLY_UNAVAILABLE` 硬禁 |
| T-M2 执行迭代抽屉 | ✅ | `panel=iteration`（`IterationDecisionPanel`：5 种结构化决策表单 + 历史 + 错误/阻塞态）；execution_iteration 5 节点 `drawerPanel: "iteration"`；复用 `renderResearchLoopPanel(null,"iteration")` 注入 |
| T-M3 知识抽屉扩展 | ✅ | knowledge 抽屉按节点切换：`evidence_relations` → `EvidenceGraphView`（走 `open_evidence_graph` 命令投影渲染）；`knowledge_ingestion` → 完成流面板注入 |
| T-M4 题目级/MVP 投影 | ✅ | `getChallengeQuestionRunStatus` API + `ChallengeMvpProgressPanel`（有效/已验证/已批准 + 题目行深链）+ `panel=question` 单题验收（复活 `ChallengeQuestionDetailPanel`） |
| T-M5 跨阶段入口+清理 | ✅ | launcher 死分支 `challengeProgramSurfaceSelected` 删除（单题入口收敛到 workflow 深链）；`challengeProgramProjection` 半死状态修复（overview 直接投影）；workspace 工具栏项目 ID 显示；lazy/queryKeys/getChallengeQuestionRunDetail 残留 import 清理 |
| T-M6 正式验收 | ✅ | 端到端命令链测试（真实 run → stop → build_package 幂等；promote → 人工门禁 → 官方候选）；后端 research_workflow 全量 105 绿；前端 research-workflow+launcher+layout 172 绿；VUI 门禁绿；`tsc -b` 绿 |

已知 pre-existing 债（不在本方案改动面，待独立处理）：
- `web/src/design/chat-selection-persistence-preview.{tsx,css}` 违反 VUI 边界（inline Tailwind + raw 颜色），chat 域历史引入；
- 6 个 teams 契约测试（`teamMutationSurface`/`useSourceCollectionPresentation`/`teamsWorkbenchBagContract`/`TeamResearchWorkflowPanelHost`/`createSourceCollectionController`）在基线 commit 已红（`useTeamsScComposition` 等断言漂移），与本次改动零交集。

## 1. 目标与边界

把挑战杯旧版（已删除的 ChallengeCup 阶段页面 + 仍存活但无挑战杯入口的面板族）的全部用户功能同步进单画布 workflow 工作台，且：

- 复用现有功能组件与数据流，**不复制业务逻辑**（遵循处置表 EMBED 原则）；
- 所有操作必须可在 `ResearchProcessWorkspace` 内完成或直达，不产生孤儿组件与死代码；
- 后端命令能力与前端按钮完全一致（无假按钮、无禁用占位）；
- 保留 SSOT：workflow run 是运行事实源，题目级/MVP 状态只读投影。

不迁移（明确废弃，由画布/检查器替代）：三阶段 stage rail、四步进度步骤条、挑战杯阶段主页面壳、`challengeTeamSurface` 切换（死代码清理）。

## 2. 现状基线（2026-08-09 审计）

### 已同步 ✅
知识搜集：搜索范围/主题简报（knowledge 抽屉）、知识包交接门禁。实验设计：假设治理全链路、协议冻结、受控 Smoke、full-run 登记、知识入库请求（experiment 抽屉）。执行迭代：受控运行（`start_controlled_run` 后端已实现）、候选晋升门禁。跨面：绑定/会话/产物查看、运行切换、时间线、Agent 任务启动与精确会话。

### 已声明但前端禁用 ⚠️（后端可接线）
- `build_package`（结果打包）——后端 node_command_adapter 无实现；
- `open_evidence_graph`（证据图）——后端无投影 API；
- 后端已实现但前端 capability 未暴露的面：`run_smoke`/`start_controlled_run` 依赖 planId 才 available（需要 run 上下文投影）。

### 完全缺失 ❌
1. 执行迭代阶段无抽屉/面板；`version_governance` 无节点；结构化迭代决策（rerun/revise/rollback/stop，后端 `iteration_transition.py` 已有 `IterationDecisionKind` DTO）无 UI；`revise` 与 `reject_handoff` 同路径；结果包 case 列表。
2. 知识搜集深化：提炼/候选/关系图/入库审核面板未注入（面板代码仍在 source-collection 域）。
3. 题目级/MVP 级状态：黄金样例/试运行题表格、单题验收详情（`ChallengeQuestionDetailPanel` 孤儿）、MVP 验收结果（死代码）。
4. 跨阶段：研究关系图链接、项目切换器、per-stage Agent 配置 aside。
5. 任务卡片语义：`ResearchProjectAgentTaskPanel` 的 formalRetry（正式重试）未暴露。

## 3. 迁移策略（按缺口分组）

### 3.1 抽屉模式（已建立的 pattern，扩展三个抽屉）
`panel=experiment | knowledge` 已实现：shell 层渲染现有组件 → 注入 `ResearchProcessWorkspace` → 检查器按钮（`adapter.drawerPanel`）打开。同模式扩展：

| 抽屉 | 内容（复用组件） | 节点 |
| --- | --- | --- |
| `panel=iteration`（新） | `renderResearchLoopPanel`（迭代工作台：评价/决策/晋升/结果包）+ 结构化迭代决策表单 | `result_evaluation`/`iteration_decision`/`candidate_promotion`/`result_package` |
| knowledge 抽屉扩展 | 提炼/候选面板（`TeamSourceCollection*Panel` 族）、关系/证据图面板、入库审核 | 按节点切换 drawer 内部 tab |
| `panel=question`（新） | `ChallengeQuestionDetailPanel`（单题验收详情，复活孤儿） | 题目级深链 |

### 3.2 命令接线层（后端优先）
- `build_package`：后端 result_package 服务（复用 `iteration_transition.py` 的 promotion/result 逻辑）→ 前端取消禁用；
- `open_evidence_graph`：后端证据图投影 API（读取 run artifacts/evidence edges）→ 前端接线；
- 修正 `revise` 语义：与 `reject_handoff` 分离，走结构化 revise 输入（revise 理由）；
- `WIRED_COMMANDS` 按后端 capability 动态对齐，删除前端硬编码禁用。

### 3.3 结构化迭代决策（iteration_decision）
后端 `iteration_transition.py` 已有 `IterationDecisionKind`（rerun/revise/rollback/stop/promote）。前端在 iteration 抽屉提供决策表单（种类 + 理由 + 目标候选），命令走 `post_research_workflow_node_command`；`rerun_smoke`/`revise_protocol`/`rollback` 生成结构化 lineage（后端已有 `run_fork.py`/`iteration_transition.py` 支撑）。

### 3.4 题目级/MVP 状态（只读投影）
- 后端：workflow run 投影增加题目级状态（黄金样例/试运行题：机器验证 n/4、人工审核计数、证据数）——数据源为 research_project manifest（现有 data 域）只读投影；
- 前端：workflow 壳顶部或 drawer 展示 MVP 进度条；单题详情 `ChallengeQuestionDetailPanel` 通过 `panel=question&questionId=` 深链打开；
- 清理：删除 `challengeTeamSurface` 死分支，MVP 卡片作为 workflow 壳内次级表面（非独立状态）。

### 3.5 跨阶段入口
- 工作台工具栏：项目切换器（复用 `ResearchProjectSwitcher`）、研究关系图链接；
- per-stage Agent 配置：agents 抽屉保留只读卡片 + 外链，挑战杯路径不再挂旧配置 aside。

### 3.6 明确不迁移（废弃 + 清理）
- `ChallengeCupStageRail`/四步进度/阶段主页面壳（已删）；
- `challengeTeamSurface==="progress"` 死分支与 `renderChallengeProgramResults` 不可达代码（清理或并入 3.4）；
- `ChallengeQuestionDetailPanel` 孤儿状态消除（迁移到 3.1 或删除）。

## 4. 任务图（依赖顺序）

```text
T-M0 对齐与本方案确认（本文档）
  -> T-M1 后端命令接线（build_package / open_evidence_graph / revise 语义）
  -> T-M2 执行迭代抽屉（panel=iteration + 结构化决策表单）      [依赖 T-M1 部分]
  -> T-M3 知识抽屉扩展（提炼/候选/关系/入库 tab）               [依赖 T-M1 open_evidence_graph]
  -> T-M4 题目级/MVP 投影（后端投影 + 前端进度 + panel=question）
  -> T-M5 跨阶段入口（项目切换器/关系图链接/Agent aside 处置）+ 死代码清理
  -> T-M6 正式验收（Task 10 补完：真实 run 闭环、GUI 目测、全量门禁）
```

单 Agent 按依赖串行；T-M1 可与 T-M2 并行（不同面）。

## 5. 任务卡

### T-M1 后端命令接线
- Owner/Boundary: `core/web/services/team_workflow/research_runtime/node_command_adapter.py`、`service.py`、`core/web/routes/team_workflows/research_runtime.py`、`web/src/routes/teams/research-workflow/nodeCommandAdapter.ts`、`ResearchProcessNodeInspector.tsx`
- Deliverable:
  - `build_package`：result package 生成（复用 `iteration_transition.py` 的 best-validated-result 逻辑）并登记 artifact；
  - `open_evidence_graph`：证据图投影（artifacts/evidence edges → graph DTO）；
  - `revise` 独立命令（revise 理由输入，不 alias reject）；
  - 前端移除 `build_package`/`open_evidence_graph` 硬编码禁用；capability 由后端驱动。
- Verification:
  - 后端 focused tests（package build 幂等、graph 投影、revise lineage）；
  - 前端 nodeCommandAdapter tests 更新；inspector 不再出现禁用态占位；
  - `vuiShadcnRouteContract` + `tsc -b`。

### T-M2 执行迭代抽屉
- Owner/Boundary: `web/src/routes/teams/research-workflow/ResearchProcessWorkspace.tsx`、`nodeAdapterModel.ts`、`ResearchProcessNodeInspector.tsx`、`teamResearchPrimarySurfaceRenderers.tsx`、`web/src/routes/teams/useTeamsWorkbenchShellPhase.tsx`
- Deliverable:
  - `panel=iteration` 抽屉：注入 `renderResearchLoopPanel`（复用）+ 迭代决策表单（IterationDecisionKind 选择 + 理由 + 目标候选）；
  - `execution_iteration` 5 节点 `drawerPanel: "iteration"`；
  - 决策提交走命令路径，错误/忙态与现有命令一致。
- Verification:
  - drawer 渲染测试、决策表单 contract 测试；
  - 全量 research-workflow vitest + tsc。

### T-M3 知识抽屉扩展
- Owner/Boundary: `web/src/routes/teams/teamResearchPrimarySurfaceRenderers.tsx`、source-collection 面板复用、`ResearchProcessWorkspace.tsx`（drawer tab）
- Deliverable:
  - knowledge 抽屉按选中节点切换 tab：`source_extraction` → 提炼/候选；`evidence_relations` → 关系/证据图（T-M1 后）；`knowledge_ingestion` → 入库审核；
  - 复用 `TeamSourceCollection*Panel` 族（draft/action 上下文沿用现有注入）。
- Verification: 面板渲染测试、无第二套 draft 状态、VUI 门禁。

### T-M4 题目级/MVP 投影
- Owner/Boundary: `core/web/services/team_workflow/research_runtime/`（只读投影）、`web/src/routes/teams/research-workflow/`（进度条 + panel=question）
- Deliverable:
  - 后端：run 投影含题目级状态（机器验证/人工审核/证据数）；
  - 前端：workflow 壳 MVP 进度 + `panel=question&questionId=` 深链复活 `ChallengeQuestionDetailPanel`。
- Verification: 后端投影 contract tests、深链导航测试、无孤儿组件（ChallengeQuestionDetailPanel 有入口）。

### T-M5 跨阶段入口 + 清理
- Owner/Boundary: `web/src/routes/teams/research-workflow/`、`teamResearchPrimarySurfaceRenderers.tsx`、`TeamResearchStageLauncherPanel.tsx`
- Deliverable: 项目切换器、关系图链接；`challengeTeamSurface` 死分支清理；不可达渲染器移除。
- Verification: `rg` 无死引用、TeamsRoute.layout.test 更新、全量测试绿。

### T-M6 正式验收
- Deliverable: 真实 run 闭环（创建→知识→交接→实验→冻结→smoke→受控运行→评价→决策→晋升→结果包）、checkpoint 恢复、Launcher 刷新、浏览器 GUI 目测、全量门禁（后端 focused + 前端 research-workflow + VUI 门禁 + tsc + build）。
- Stop: 任一运行真实性验收失败不得声称完成。

## 6. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 后端 result_package/evidence graph 数据不完整 | T-M1 先做能力审计（iteration_transition/artifacts 实际数据），缺口列为显式 blocked 而非假实现 |
| 迭代决策 UI 与后端 lineage 语义漂移 | 决策表单字段与 `IterationDecisionKind` DTO 一一对应，contract 测试锁定 |
| source-collection 面板复用引入第二 draft 状态 | 沿用现有注入（draft 由 shell 单例持有），drawer 不做本地 draft |
| VUI/门禁红 | 新 UI 全部 V* API + styles.ts；改前跑 `vuiShadcnRouteContract`/`vuiImportBoundary` |
| 并行 Agent 改动冲突 | 改动面与活跃 claims 无重叠（research-workflow 域），合并前 fetch 检查 |

回滚单位：新 panel 参数（remove URL 分支即可回退 UI）、新命令（后端 gate/回退）、新投影（只读不写，无数据风险）。

## 7. 完成定义

- 审计缺口清单全部闭合或显式标记为「明确不迁移」；
- 无孤儿组件、无死代码分支（`challengeTeamSurface` 等）；
- 无前端禁用占位命令；后端 capability 全驱动；
- 真实 run 完成三阶段闭环验收；
- 全量门禁绿、Launcher 刷新、浏览器目测通过。
