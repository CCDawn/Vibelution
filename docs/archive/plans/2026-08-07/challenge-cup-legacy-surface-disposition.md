# 挑战杯科研工作流 · 旧页面与导航处置表

> 类型：实施迁移清单。产品契约见 [PRD](../../../prds/2026-08-07-research-process-flow-single-page-workspace.md)，运行决策见 [ADR 0006](../../../adr/0006-challenge-cup-workflow-runtime-and-single-canvas.md)，交接与会话决策见 [ADR 0007](../../../adr/0007-research-workflow-handoff-and-agent-session-binding.md)。

## 1. 复审结论

当前挑战杯科研入口同时存在：

- `overview + teamMode=canvas` 组织画布首页；
- `knowledge_collection / experiment / iteration` 阶段工作台；
- `ChallengeCupOperationsWorkspace` 内部三阶段 rail；
- `ResearchStageNav` 顶部三阶段导航；
- `TeamKnowledgeCollectionCompletionFlowPanel` 一键流程图；
- 可直接访问的 `/research/flow-canvas`；
- 已从 router 移除、但仍保留源文件和测试的 `ResearchRoute.tsx`；
- `coordination / ingestion / graph / candidates / discussion` 等 legacy query 页面。

这些表面混合了流程运行、组织配置、Agent 配置、证据关系和旧研究入口。新方案必须将每个入口映射到一个明确归宿，不能只新增 workflow 页面后保留全部旧页面。

## 2. 唯一正式入口

正式科研流程 URL：

```text
/teams
  ?team=<team-id>
  &researchView=workflow
  &workflowId=challenge-cup-research
  &runId=<run-id>
  &node=<node-id>
  &panel=<node|agents|team|timeline>
```

规则：

- 缺少 `runId` 时显示固定定义与“创建运行”；
- `node` 只选择节点；
- `panel=agents` 打开 Agent 分工抽屉，不创建第二页面；
- `panel=team` 打开团队组织/讨论次级面；
- 旧 URL 只做确定性解析，不再渲染旧主页面；
- 兼容解析完成后使用 replace 导航到 canonical URL。

## 3. 路由与查询参数归宿

| 现有入口 | 当前行为 | 目标归宿 | 迁移动作 |
| --- | --- | --- | --- |
| `/teams` 挑战杯团队 | 根据 shell state 进入 overview/canvas/board | canonical workflow global view | 保留路由，替换默认内容 |
| `/research` | `LegacyTeamsRedirect` | canonical workflow global view | redirect 保留一轮，随后仅保留 router alias |
| `/research/flow-canvas` | 独立 3000+ 行组织/流程画布 | workflow `panel=agents` | 先改 redirect，再删除独立 route |
| `researchView=overview` | 流程条 + 组织画布 | workflow global `fitView` | alias → `workflow` |
| `researchView=canvas` | 解析为 overview | workflow `panel=agents` | alias → `workflow&panel=agents` |
| `teamMode=canvas`（挑战杯上下文） | 组织画布成为科研默认表面 | workflow `panel=agents` | 仅挑战杯兼容解析；通用 Teams 继续保留 |
| `researchView=knowledge_collection` | 知识搜集独立工作台 | 聚焦知识阶段 | alias → `workflow&node=<mapped>` |
| `researchView=source_collection` | parse 为 knowledge collection | 聚焦 `source_finding` | alias → canonical node |
| `researchView=experiment` | 实验独立页或 launcher | 聚焦实验阶段 | alias → `workflow&node=hypothesis_design` |
| `researchView=iteration` | 迭代独立页或 launcher | 聚焦迭代阶段 | alias → `workflow&node=controlled_run` |
| `researchView=coordination` | legacy 协调状态页 | workflow `panel=team` | alias → team panel |
| `researchView=discussion` | 团队沟通页 | workflow `panel=team` 或 room deep-link | 不保留科研主页面 |
| `researchView=ingestion` | legacy 入库状态页 | `node=knowledge_ingestion` | alias → node inspector |
| `researchView=graph` | legacy 候选关系图 | `node=evidence_relations&inspector=evidence` | alias → node artifact view |
| `researchView=candidates` | legacy 候选列表 | `node=source_extraction&inspector=artifacts` | alias → node artifact view |

### `collectionStage` 映射

| legacy 值 | canonical node |
| --- | --- |
| `search` / `collection` / `finding` | `source_finding` |
| `review` / `candidate` / `screening` / `extraction` | `source_extraction` |
| `graph` / `relations` | `evidence_relations` |
| `ingest` / `memory` / `ingestion` | `knowledge_ingestion` |

未知值不得落入空页面；忽略未知值并进入 workflow global view，同时记录 bounded runtime scene。

## 4. 组件处置

| 组件/文件 | 处置 | 保留内容 |
| --- | --- | --- |
| `ResearchProcessWorkspace`（新） | **KEEP / canonical** | 唯一三阶段流程壳 |
| `ResearchProcessNodeInspector`（新） | **KEEP / canonical** | 节点操作、Agent、artifact、human task |
| `ChallengeCupOperationsWorkspace` | **REMOVE after adapters** | 数据投影与可复用阶段业务动作迁入独立 adapter |
| `ChallengeCupStageRail` | **REMOVE** | 三阶段分区由 workflow canvas 表达 |
| `ChallengeCupKnowledgeStage` | **EMBED by node adapters** | 问题/资料业务动作，不保留整页 |
| `ChallengeCupExperimentStage` | **EMBED by node adapters** | 假设、协议、smoke 动作 |
| `ChallengeCupIterationStage` | **EMBED by node adapters** | run、评价、迭代、晋升动作 |
| `ResearchOverviewSurface` | **REMOVE after default switch** | 主要动作由 workflow header / node inspector 接管 |
| `ResearchPrimaryActionBar` | **REMOVE after gate migration** | 继续/跨阶段动作改读 runtime handoff |
| `ResearchStageNav` | **REMOVE** | 不再用 Tab/按钮模拟阶段 |
| `TeamResearchStageStandalonePagePanel` | **REMOVE after adapters** | composer 内的业务面板按节点复用 |
| `ExperimentStageComposer` | **REMOVE or generalize outside research** | 不得继续成为挑战杯阶段主壳 |
| `TeamKnowledgeCollectionCompletionFlowPanel` | **REMOVE** | 状态与会话入口进入对应 workflow nodes |
| `TeamResearchWorkflowPanelHost` | **REMOVE for Challenge Cup** | 非挑战杯调用若仍存在须由 owner 明确保留 |
| `TeamResearchWorkflowStageModules` | **DECOMPOSE** | source/graph/candidate 面板进入 node adapters |
| `ChallengeCupStageAgentConfigurationPanel` | **REPLACE** | 使用 NodeInspector Agent section + Agent 分工抽屉 |
| `researchStageAgentBindings.ts` | **KEEP as migration input** | 转换为 node-effective binding，不能当 run history |
| `ResearchProjectAgentTaskPanel` | **DECOMPOSE** | 启动/继续/重试动作进入对应节点 |
| `TeamOrganizationCanvasSurface` | **KEEP for generic Teams** | 挑战杯只在 `panel=agents` 次级配置视图复用必要能力 |
| `TeamNodeBindingPanel` | **KEEP for generic Teams** | 挑战杯节点绑定使用 workflow binding service |
| `TeamCanvasReadOnlyInspector` | **REMOVE from Challenge Cup path** | 节点信息由 workflow inspector 统一 |
| `ResearchFlowCanvasRoute.tsx` | **REMOVE** | 必要组织/绑定能力迁入现有 Teams/VUI owner |
| `ResearchFlowCanvasRoute.styles.ts` 与 route tests | **REMOVE with route** | 兼容 redirect 测试移入 canonical navigation test |
| `ResearchRoute.tsx` / styles / layout test | **REMOVE first** | router 已不加载，不保留孤儿实现 |

删除前必须用 `rg` 验证是否仍有非挑战杯调用；若某组件被通用 Teams 使用，则只移除挑战杯调用，不机械删除通用能力。

## 5. API 与数据处置

| 现有面 | 目标 |
| --- | --- |
| `/api/research/flow-canvas` GET | 迁移期只读组织/配置 adapter；最终由 Teams organization / binding API 替代 |
| `/api/research/flow-canvas/execute` | 切换默认入口前停止写入；不得与 LangGraph runtime 双写 |
| organization graph data | 保留并迁移为团队/Agent 配置数据，不转成 workflow run |
| stage task stores | 迁移/适配到 `NodeRun`、session binding 和 artifact refs，不删除历史 |
| old `researchView` / `collectionStage` | 只保留兼容解析模块，不在业务组件散落判断 |
| 旧 layout/localStorage keys | 映射到 `WORKBENCH_LAYOUT_IDS` 后删除 |

## 6. 清理顺序

```text
1. 建立 canonical route + compatibility resolver
2. 新 workflow 默认入口通过机器与浏览器验收
3. 停止 legacy execute writer
4. 将旧页面业务动作全部接入 node adapters
5. 将所有内部链接切到 canonical URL
6. router 将 /research/flow-canvas 改为 redirect
7. 删除孤儿 ResearchRoute
8. 删除重复 stage rail / overview / completion-flow 主表面
9. 删除 ResearchFlowCanvasRoute 及其专属 styles/tests
10. 删除无调用 query 分支、DTO、API helper、storage key 和 CSS
11. 关闭 feature gate，更新 README / VUI design registry / docs index
12. 清理 task worktree、claim 和临时验证资产
```

不得在第 2 步通过前提前删除回滚路径；不得在第 5 步完成前删除 legacy resolver。

## 7. 删除门

全部满足后才允许 contract：

- `rg` 找不到产品内部指向 `/research/flow-canvas` 的链接；
- router 不再 lazy import `ResearchFlowCanvasRoute`；
- `ResearchRoute.tsx` 不存在且没有测试/样式清单引用；
- 除 compatibility resolver 外，没有业务文件直接判断 legacy `researchView`；
- 所有 `collectionStage` 值都有 canonical node 测试；
- Challenge Cup 路径只挂载一个阶段导航语义：workflow canvas；
- Challenge Cup 路径不再挂载组织画布作为默认首页；
- 旧 execute writer 被拒绝或移除，LangGraph runtime 是唯一 writer；
- 现有组织配置、Agent identity、知识、协议、artifact 和历史运行可读取；
- feature gate rollback 在删除前已演练；删除后更新回滚说明为版本回退。

## 8. 自动化验证

新增或更新：

```text
researchWorkflowNavigation.test.ts
researchLegacyRouteResolver.test.ts
researchWorkspaceRouteContract.test.ts
researchWorkflowNoDuplicateSurface.contract.test.ts
researchWorkflowAgentBinding.contract.test.ts
```

断言：

- 每个 legacy URL 只有一个 canonical 结果；
- canonical URL 可由 `/teams` 主导航到达；
- canonical route 不再挂载旧 page shell；
- workflow node 到 Agent session 的链接包含 `session + focusTask + focusTurn + returnTo`；
- NodeInspector 关闭/打开不改变 `runId`、node coordinates 或 runtime current nodes；
- 没有未注册页面、死链接和重复主导航。

## 9. 人工验收

从以下入口逐个打开并记录最终 URL 与可见节点：

- `/research`
- `/research/flow-canvas`
- overview / canvas
- 三个 stage view
- 七个 legacy view
- 全部 `collectionStage` aliases
- Agent 配置返回
- Agent 精确会话返回
- evidence graph / artifact 返回

任何入口出现空白、旧主页面、第二套阶段导航、错误节点或无法返回，均视为迁移未完成。
