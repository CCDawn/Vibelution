# 挑战杯科研工作流单画布 · 开发 Agent 实施任务图

Status: **Ready for implementation**

Created: 2026-08-07

Close condition: 新工作流运行事实源、三阶段单画布、节点交接、Agent 精确会话锚点、旧页面收敛、最终清理和正式验收全部完成后，将本计划保留在 archive 作为历史交付记录。

Product contract: `docs/prds/2026-08-07-research-process-flow-single-page-workspace.md`

Architecture authority: `docs/adr/0006-challenge-cup-workflow-runtime-and-single-canvas.md`

Handoff/session authority: `docs/adr/0007-research-workflow-handoff-and-agent-session-binding.md`

Legacy cleanup inventory: `docs/archive/plans/2026-08-07/challenge-cup-legacy-surface-disposition.md`

## 1. 目标与边界

交付一个真实可运行的挑战杯科研工作流：

- 知识搜集、实验设计、执行迭代同处一张连续画布；
- 三个阶段有明确画布内分区；
- LangGraph 是运行事实源；
- 支持持久 checkpoint、人工等待、恢复、失败、重试和历史 lineage；
- 每条运行边有显式 handoff，跨阶段只消费人工接受的不可变 package/protocol；
- 每个 Agent node run 可定位到准确 session task / turn；
- 节点操作复用现有科研功能；
- Agent 配置、证据图和组织图保持次级职责；
- 旧科研页面和 query 全部有唯一归宿，交付后没有孤儿页、重复主导航或 legacy writer；
- 不实现自由低代码编辑器；
- 不处理移动端；
- 不直接修改或覆盖用户活跃 operator 数据。

模式：`TASK_GRAPH`

拆分理由：

- 运行域、HTTP/SSE、VUI renderer 和 Teams 产品组合是不同 owner；
- definition/run/checkpoint 是公共契约，需要先于前后端实现锁定；
- migration 和真实恢复属于独立高风险验收；
- 共享 DTO、VUI public API 和 Teams workbench 都需要串行 claim。

## 2. 开发前置门

开发 Agent 开始前必须：

1. 从包含本 PRD/ADR 的 commit 建立新的任务 worktree。
2. 运行 project `preflight --write-kind development`。
3. 认领精确文件范围；不得复用本规划 claim。
4. 重新检查 `main`、active claims、`logs/runtime_scenes/` 和现有 Launcher 状态。
5. 读取：
   - `AGENTS.md`
   - `docs/prds/2026-08-07-research-process-flow-single-page-workspace.md`
   - `docs/adr/0006-challenge-cup-workflow-runtime-and-single-canvas.md`
   - `docs/adr/0007-research-workflow-handoff-and-agent-session-binding.md`
   - `docs/archive/plans/2026-08-07/challenge-cup-legacy-surface-disposition.md`
   - `docs/guides/{README,route,ownership,loop}.md`
   - `docs/standards/development-standard.md` 相关节
   - `core/web/services/README.md`
   - `core/web/services/team_workflow/README.md`
   - `web/src/routes/teams/README.md`
   - `web/src/components/vui/README.md`
   - `web/src/components/vui/designs/README.md`
6. 记录现有 `/api/research/flow-canvas` 查询/执行分裂的 characterization evidence。
7. 确认项目 venv 的 LangGraph 版本与准备声明的直接依赖兼容。

禁止直接在脏 `main` 开发或覆盖现有未提交 PRD/README WIP。

## 3. SSOT 表

| 事实 | 唯一写入者 | 前端来源 | 禁止 |
| --- | --- | --- | --- |
| Workflow definition/version | definition service | definition API | Route 本地定义拓扑 |
| Run status | LangGraph runtime/service | run snapshot + SSE | React 自行推进 |
| Node run status | runtime projection | node projection | 把 selected 当 current |
| Checkpoint lineage | checkpointer/runtime | run history API | 客户端修改 checkpoint |
| Human task | human task service | task API/SSE | 关闭弹窗即视为解决 |
| Artifact metadata | artifact service | ArtifactRef | 把大 payload 塞节点 |
| Agent binding | binding service | binding API | 用显示名授权 |
| Run Agent binding snapshot | workflow runtime | run/node projection | 用当前 Agent 配置改写历史 |
| Agent session point | session binding service | node detail | 跳到默认直聊或只记 session |
| Node handoff | handoff service/runtime | handoff projection | 前端因“有进度”自行解锁 |
| UI selection/viewport | frontend store/URL | local UI state | 回写运行当前节点 |

任何任务无法维持此表时停止实现并重新对齐。

## 4. Critical Path

```text
Task 0 Characterization
  -> Task 1 Domain Contract
  -> Task 2 LangGraph Vertical Slice
  -> Task 3 API + SSE + HITL
  -> Task 5 Single-Canvas Workspace
  -> Task 6 Existing Stage Adapters
  -> Task 7 Agent / Handoff / Session Integration
  -> Task 8 Migration
  -> Task 9 Legacy Cleanup
  -> Task 10 Formal Acceptance

Task 1 -> Task 4 VUI Workflow Canvas
Task 3 + Task 4 -> Task 5
Task 3 + Task 6 -> Task 7
```

一个开发 Agent 执行时按依赖顺序串行推进。若后续授权多人并行，Task 2/3 与 Task 4 可在 Task 1 后分开，但共享 DTO 与 VUI public export 必须由单一 owner 串行合入。

## 5. 任务卡

### Task 0：锁定当前分裂行为与迁移保护

- Owner/Boundary:
  - `core/web/services/research_service.py` 只读 characterization；
  - 新增聚焦测试应放在现有 research service / route test owner。
- Dependency: PRD + ADR。
- Mode: `BDD_TDD`
- Deliverable:
  - 测试证明 GET 返回组织派生画布、execute 读取保存流程；
  - 测试记录旧深链、旧 payload、现有数据路径和全部科研 router/query 入口，包括挑战杯上下文的 `teamMode=canvas`；
  - 证明 `ResearchRoute.tsx` 已是 router 不可达的孤儿实现；
  - 记录现有项目 Agent session 的复用/重试规则，以及 task 中可用的 `sessionId/taskId/turnId`；
  - 以[旧页面处置表](challenge-cup-legacy-surface-disposition.md)为基线标注 KEEP / EMBED / REDIRECT / REMOVE；
  - 明确哪些行为保留、哪些行为由新域替代。
- Verification/Stop:
  - 聚焦 pytest 绿；
  - 若发现第三个执行事实源或现有 production writer，停止并修订迁移图；
  - 若存在处置表未覆盖的科研页面或内部链接，先补表，不进入新 UI；
  - 不在本任务直接修行为。

### Task 1：工作流领域契约与固定定义

- Owner/Boundary:
  - 新 `core/research/workflow/`；
  - 新 backend DTO；
  - 新 frontend `researchWorkflow` types；
  - 共享 DTO 由一个 owner。
- Dependency: Task 0。
- Mode: `BDD_TDD`
- Deliverable:
  - `WorkflowDefinition/Version/Run/NodeRun/CheckpointRef/HumanTask/ArtifactRef/AgentBinding`；
  - `RunAgentBindingSnapshot/NodeAgentSessionBinding/NodeHandoffRecord`；
  - 三阶段、全部固定节点和每个节点的 `actorKind` / 主责角色；
  - 状态机和允许的状态转换；
  - Knowledge Package、Frozen Protocol、smoke 放行和 result package 的输入输出 schema；
  - rerun / revise protocol / rollback / stop 四类迭代回边语义；
  - 规范化 definition snapshot 和 hash；
  - Canvas projection DTO。
- Verification/Stop:
  - Python 和 TypeScript contract tests；
  - definition hash 稳定；
  - selected node 不出现在服务端运行模型；
  - “有资料进度”不能替代 accepted Knowledge Package；
  - “有实验计划”不能替代 Frozen Protocol + smoke human gate；
  - SSOT 表仍完整。

### Task 2：LangGraph 最小垂直切片

- Owner/Boundary:
  - `core/research/workflow/{graph_builder,checkpoint_store,runtime}.py`；
  - requirements/lock；
  - 不触碰正式 UI。
- Dependency: Task 1。
- Mode: `BDD_TDD`
- Deliverable:
  - 声明 LangGraph 和 SQLite checkpointer 直接依赖；
  - 三节点最小图：开始 → 人工门禁 → 完成；
  - 上游 artifact → handoff → 下游 input snapshot 的最小闭环；
  - persistent `thread_id`；
  - interrupt/resume；
  - restart recovery；
  - fork from checkpoint；
  - idempotency contract。
- Verification/Stop:
  - 首次执行、重启恢复、人工提交、handoff 接收/拒绝、失败恢复、fork 测试；
  - InMemorySaver 不得作为交付实现；
  - 不能证明副作用幂等时停止扩展正式节点。

### Task 3：运行 service、命令、HTTP/SSE 与投影

- Owner/Boundary:
  - `core/web/services/team_workflow/research_runtime/`；
  - `core/web/routes/team_workflows/research_runtime.py`；
  - `web/src/api/researchWorkflow.ts`。
- Dependency: Task 2。
- Mode: `BDD_TDD`
- Deliverable:
  - definition、runs、run snapshot、node detail、human task、command API；
  - effective binding、run binding snapshot、node session binding 和 handoff API；
  - SSE sequence、resume、snapshot + delta；
  - command idempotency；
  - `rebind_node`、handoff resolve 和 session anchor 的权限/lineage 校验；
  - thin routes、typed response models；
  - bounded/error-safe projection。
- Verification/Stop:
  - service tests + HTTP contract + SSE reconnect tests；
  - full-stack API boundary 不新增 Route 硬编码 fetch；
  - 不记录 secrets、Prompt 或无界 output；
  - node detail 缺少 task/turn 时必须显式 degraded，不能回退到默认 Agent 直聊；
  - 未完成断线恢复时不得进入正式 UI。

### Task 4：VUI 工作流画布能力

- Owner/Boundary:
  - `web/src/components/vui/`；
  - `renderers/shadcn/`；
  - `designs/product/workflow.md` 和 INDEX；
  - 不触碰 Teams 业务数据。
- Dependency: Task 1。
- Mode: `BDD_TDD`
- Deliverable:
  - `VWorkflowCanvas` 公共 API；
  - `@xyflow/react` 只存在于 renderer；
  - 三个 `StageRegion` group node；
  - 确定性固定布局；
  - task/gate node renderer；
  - selected/current/hover/focus/disabled states；
  - keyboard navigation、fitView 和内部 pan/zoom；
  - 全局/聚焦阶段两级 LOD，低缩放隐藏次要信息但保留节点名与状态；
  - loading/empty/error skeleton。
- Verification/Stop:
  - `vuiComponentDesignContract`；
  - `vuiShadcnRouteContract`；
  - renderer focused tests；
  - 1280/1440/1920 画布截图；
  - 页面无横向滚动；
  - 三阶段不能被实现为三个 Tab 或三张独立图。

### Task 5：单画布 ResearchProcessWorkspace

- Owner/Boundary:
  - `web/src/routes/teams/research-workflow/`；
  - `researchWorkspaceModel` / navigation adapter；
  - 不扩张 `TeamsRouteWorkbench` 巨石。
- Dependency: Task 3 + Task 4。
- Mode: `BDD_TDD`
- Deliverable:
  - header、run switcher、同画布三阶段、NodeInspector、Agent 分工抽屉、折叠 timeline；
  - canonical URL `researchView=workflow` + `runId` / `node` / `panel`；
  - `runtimeCurrentNodeIds` 与 `selectedNodeId` 分离；
  - inspector 使用 shared pane persistence；
  - 旧 stage/view/query 通过单一 compatibility resolver 映射到同壳；
  - 当前 stage、跨阶段 gate 和 pending human task 可见。
- Verification/Stop:
  - route/navigation/layout tests；
  - canonical route 从 Teams 主导航可达；
  - selection 不发运行命令；
  - inspector 开关不重置 viewport；
  - 页面只挂载一个科研阶段导航语义；
  - 不新增 ad-hoc localStorage key；
  - 不在 UI 显示解释图例、开发组件名或常驻灰色补充文字。

### Task 6：现有科研面板节点化适配

- Owner/Boundary:
  - knowledge collection、experiment、iteration 现有 panel adapters；
  - 每个节点 adapter 独立文件；
  - 不复制原组件业务逻辑。
- Dependency: Task 5。
- Mode: `BDD_TDD`
- Deliverable:
  - 搜集、提炼、关系、入库；
  - 假设、协议、冻结、smoke；
  - 正式 run、评价、迭代决策和 result package；
  - 原操作面板通过 NodeInspector slots 使用；
  - 原 stage-specific route 只进入统一 compatibility resolver；
  - `ChallengeCupOperationsWorkspace`、stage rail、overview strip 和 completion flow 不再作为并行主表面挂载。
- Verification/Stop:
  - 原功能 focused tests 保持绿；
  - 每个功能只有一个写路径；
  - 禁止把完整旧页面嵌入检查器形成嵌套工作台；
  - 每个旧组件的实际处置与[旧页面处置表](challenge-cup-legacy-surface-disposition.md)一致；
  - 发现 route 参数成为隐性 SSOT 时先抽 adapter/model。

### Task 7：Agent、会话锚点、节点交接、人工任务和 Artifact

- Owner/Boundary:
  - `researchStageAgentBindings` adapter；
  - binding / handoff / session binding services；
  - Chat task / turn anchor；
  - NodeInspector Agent 区与 Agent 分工抽屉；
  - artifact/evidence projections；
  - 不修改 Agent 身份或权限模型。
- Dependency: Task 3 + Task 6。
- Mode: `BDD_TDD`
- Deliverable:
  - workflow/stage/node 配置继承与 run binding snapshot；
  - 节点 Agent 卡片、唯一配置链接和 `rebind_node`；
  - `sessionId + taskId + turnId + nodeRunId + checkpointId` binding；
  - “继续会话”定位到具体 task / turn，并返回原 workflow node；
  - 普通继续复用项目 Agent session；正式重试保留 session attempt lineage；
  - 每条运行边产生 handoff，跨阶段 handoff 关联 HumanTask；
  - human task form/approve/reject；
  - ArtifactRef 列表；
  - evidence graph 次级打开方式；
  - 历史运行绑定不随当前显示名变化。
- Verification/Stop:
  - identity、permission、session anchor、handoff、human resolution 和 artifact lineage tests；
  - 无 display-name 授权；
  - 无默认 Agent 直聊 fallback；
  - 下游不消费 pending/rejected/superseded handoff；
  - 无大 payload 常驻画布；
  - 组织图不得重新成为执行图。

### Task 8：兼容迁移与旧事实源收敛

- Owner/Boundary:
  - legacy route/query adapters；
  - research flow-canvas migration；
  - feature gate；
  - 不删除用户数据。
- Dependency: Task 6 + Task 7。
- Mode: `BDD_TDD`
- Deliverable:
  - 旧 `/research`、`/research/flow-canvas`、`researchView` / `collectionStage` 深链映射；
  - 新 workspace 默认入口；
  - legacy GET 明确组织/config 语义；
  - legacy execute 停止成为第二写入者；
  - feature gate rollback；
  - migration telemetry / runtime scene。
- Verification/Stop:
  - 旧页面处置表中的全部 URL、旧数据、新 run、rollback 测试；
  - 所有内部导航只生成 canonical URL；
  - `/research/flow-canvas` 不再 lazy import 独立 page；
  - 若仍有两个 writer，停止切换默认入口；
  - 不以静默 fallback 把新运行失败伪装成旧成功。

### Task 9：旧页面、重复入口和兼容残留清理

- Owner/Boundary:
  - router、legacy resolver、旧科研 route/components/styles/tests；
  - 旧 API writer、专属 DTO/query/storage keys；
  - README、VUI design registry 和文档索引；
  - 不删除用户知识、Agent identity、协议、artifact、checkpoint 或历史运行。
- Dependency: Task 8 默认入口和 rollback 验收通过。
- Mode: `BDD_TDD`
- Deliverable:
  - 删除 router 不可达的 `ResearchRoute.tsx` 及专属 styles/tests 引用；
  - 删除 `ResearchFlowCanvasRoute` 独立页面和专属实现，保留必要 redirect；
  - 删除 Challenge Cup 重复 stage rail、overview strip、completion flow 和独立 stage shell；
  - 删除无调用 legacy query branch、API helper、DTO、CSS 和 layout/storage key；
  - 关闭旧 execute writer 和完成后的 feature gate；
  - 更新 route contract、README、design registry；
  - 清理任务临时资产、claim 和 worktree 的条件写入交付报告。
- Verification/Stop:
  - 执行[旧页面处置表](challenge-cup-legacy-surface-disposition.md)全部删除门；
  - `rg` 证明没有内部 `/research/flow-canvas` 链接、孤儿 route import 或散落 legacy 判断；
  - generic Teams 仍需要的组织/绑定能力保持绿；
  - 任何历史数据不可读取时立即停止删除并恢复 feature gate；
  - 删除前后各保留一份 route/API characterization evidence。

### Task 10：正式验收与交付

- Owner/Boundary:
  - 全任务 diff review；
  - 不新增产品功能。
- Dependency: Task 9。
- Mode: `SIMPLE`
- Deliverable:
  - 完整机器门；
  - Launcher build/restart；
  - 桌面浏览器视觉和导航；
  - checkpoint restart/HITL/retry/fork；
  - migration/rollback；
  - 无孤儿页、无重复主导航、无 legacy writer；
  - Agent 精确会话锚点和 handoff lineage；
  - completion report。
- Verification/Stop:
  - 后端 focused + selected matrix；
  - frontend focused Vitest；
  - `vuiShadcnRouteContract`；
  - `vuiComponentDesignContract`；
  - `npx tsc -b --pretty false`；
  - `npm run build`；
  - `git diff --check`；
  - Launcher steady；
  - browser console 无新增 error/warn；
  - 从全部 legacy URL 逐一导航并记录 canonical 结果；
  - Chat 从节点进入指定 task/turn，再返回原 run/node；
  - 任一运行真实性验收失败不得声称 UI 完成。

## 6. 视觉验收矩阵

| 视口 | 场景 | 必须证明 |
| --- | --- | --- |
| 1280×720 | 无 run | 三阶段同时可辨；创建运行可达；无页面横滚 |
| 1440×900 | running | 当前节点/阶段、selected、Agent 和检查器同时可辨 |
| 1920×1080 | waiting_human | 三阶段完整、人工任务和跨阶段 gate 清楚 |
| 1440×900 | failed | 失败节点、错误摘要、checkpoint 和 retry 同处 |
| 1440×900 | historical run | 原 run 不被新 run/fork 覆盖 |
| 1440×900 | disconnected | 最后可信 snapshot + 断线状态，不伪装实时 |

每个场景同时检查：

- 三阶段分割线、标题和空间层级；
- 没有解释图例和灰色补充段落；
- 没有绿色候选/成功按钮；
- 长节点名、多个 Agent、错误摘要不重叠；
- Hover 信息不遮挡主要命令；
- 键盘焦点可见；
- inspector 和 timeline 可达。

## 7. 运行验收场景

### A. 正常闭环

创建 run → 知识搜集 → Knowledge Package → 人工交接 → 实验设计 → Frozen Protocol → smoke 放行 → controlled run → result package。

证明三个阶段状态来自同一 run 和 workflow version。

### B. 人工等待恢复

运行到 `knowledge_handoff` → 关闭浏览器/重启 Launcher → 重新打开 → 仍等待同一 task → 批准 → 从同一 checkpoint 继续。

### C. 节点失败

节点失败 → 错误和 artifact 可见 → retry 创建新 NodeRun → 原失败记录保留 → 不重复外部写入。

### D. 历史 fork

从旧 checkpoint fork → 新 run 拥有 lineage → 原 run 不变 → UI 可切换比较。

### E. 兼容深链

旧 `/research`、`/research/flow-canvas`、全部 `researchView` 和 `collectionStage` 链接 → 同一 workflow 壳 → 聚焦对应 StageRegion/Node/Panel → runtime current 保持不变。

### F. Agent 精确会话

选择 Agent 节点 → “继续会话” → 打开绑定 session → 定位对应 task / turn → 返回原 `runId + node` → 节点选择与 viewport 保持。

普通继续复用 session attempt；正式重试创建新 attempt，原 session/task/turn 仍可追溯。

### G. 交接拒绝与修订

上游产生 artifact → handoff 等待/拒绝 → 下游保持不可运行 → 修订生成新 artifact version 和新 handoff → 人工接受 → 下游只消费 accepted snapshot。

知识阶段没有 accepted Knowledge Package、实验阶段没有 Frozen Protocol + smoke 放行时，跨阶段入口必须不可执行。

## 8. 回滚

回滚单位：

1. 默认入口 feature gate；
2. 新 API route 注册；
3. 新 workflow version；
4. 新 run 数据。

回滚规则：

- 关闭新入口不删除新 run/checkpoint；
- 旧 UI 只能只读或走明确 legacy adapter，不能恢复双写；
- schema migration 必须向前兼容已创建 run；
- dependency rollback 前确认没有活跃新 run；
- 所有回滚由明确命令和 runtime scene 记录。
- Task 9 contract 前使用 feature gate 回滚；删除旧实现并关闭 gate 后只能用版本回退，不临时复活部分旧页面。

## 9. Deferred

- 自由节点编辑和连线；
- 用户自定义 stage；
- 动态 ELK 复合图；
- 消息 token 级 trace；
- 多用户实时协同编辑；
- 移动端；
- Postgres checkpointer；
- 跨项目 workflow marketplace。

Deferred 不得进入 Critical Path，也不得成为第一版延期理由。

## 10. 开发 Agent 交接格式

每个任务结束报告：

```text
Task:
Worktree:
Branch:
Base / Head:
Claim:
Changed files:
Behavior delivered:
Tests:
Browser/runtime evidence:
Migration/rollback:
Launcher refresh:
Project-memory proposal:
Risks / blockers:
Next dependency:
```

“代码合入”“测试通过”“页面能打开”和“真实运行可恢复”是四种不同证据，禁止相互替代。
