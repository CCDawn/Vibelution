# 科研工作流三栏与当前任务统一改造计划

> **Status**: `user-approved`
> **Plan mode**: `TASK_GRAPH`
> **Owner**: `codex-root-research-workflow-three-pane-plan`
> **Date**: 2026-08-21
> **Claim**: `claim-1e0f72b5a938`
> **Branch**: `codex/research-workflow-three-pane-plan`
> **Worktree**: `.worktrees/research-workflow-three-pane-plan`
> **Scope**: 挑战杯科研流程工作区的统一当前任务投影、左侧定位栏、中央流程画布、右侧当前任务 Inspector、题目档案分层、响应式降级、实施任务图与一轮真实浏览器验收。
> **Supersedes**: 不替代 `AGENTS.md`、`docs/standards/`、ADR、VUI design spec 或运行时代码；实施稳定后将长期交互契约提炼到 owning docs。
> **Implementation link**: 待预览批准后，由各实施任务的 branch/commit 回填；实施轮同时更新 `挑战杯/build_research_flow_site.mjs` 及生成站点；本文本身不代表功能已经实现。
> **Validation**: Markdown 结构、相对链接、索引登记、Git diff 与方案完整性审查；正式实施按第 12 节验证矩阵执行。
> **Close condition**: 隔离预览获批，Critical Path 全部实施并合入本地 `main`，完成一轮真实浏览器闭环验收；随后把本文状态改为 `implemented` 并迁入 `docs/archive/plans/<yyyy-mm>/`。

本文记录用户已确认的产品与实施方向。当前批准覆盖解决方案和任务图，不等于正式 UI 预览已批准，也不授权远端 push、PR、发布、数据迁移、后端协议变更或无关页面重构。

---

## 1. 执行结论

本次改造不能继续按“分别修改左右栏文案和画布样式”推进。当前根因是左栏、顶栏、画布和右栏分别解释不同状态源，导致页面同时出现：

- 左栏：`开始知识搜集 / 知识搜集未开始`；
- 顶栏：`资料搜集 · 资料寻找`、`N 条假说已收敛`；
- 右栏：`第 N 轮讨论·评审 / 正在整理`；
- 中央：布局尚未提交或视口丢失时只剩空网格。

推荐改为：

> **一个 `ResearchWorkflowContext.currentTask` 投影，驱动一个由 `ResearchProcessWorkspace` 统一拥有的三栏工作台。**

关键架构决策：

1. 挑战杯 workflow 页面停用外层通用 `TeamShellStatusRail`，避免项目三阶段摘要继续与题目假说链竞争。
2. `ResearchProcessWorkspace` 通过现有 `VCanvasWorkbenchPage` 同时挂载左侧流程定位栏、中央画布和右侧 Inspector。
3. `currentTask` 只包装现有 `resolveHypothesisFirstNextAction` 和正式运行事实，不新建第二套流程状态机。
4. 左栏和顶栏只执行导航；确认、重试、交接、人工裁决等写操作只出现在右侧当前任务 Inspector。
5. 完整假说、证据、会议长发言和历史产出移入独立宽屏“科研档案”，不再塞进 300–520px Inspector。
6. 继续使用现有 VUI、`@xyflow/react` 和 ELK；只改造现有外壳，不引入 n8n、LangGraph Studio、Temporal UI 或第二套设计系统依赖。

---

## 2. 目标、非目标与成功定义

### 2.1 目标

- 用户进入页面后，无需理解内部状态机，就能判断“当前是哪道题、处于哪个阶段、系统正在做什么、我下一步点哪里”。
- 左栏、顶栏、画布和右栏展示同一个 `currentTask.key`、阶段和状态。
- 当前任务与用户正在浏览的历史节点分离；浏览历史不能改写流程权威。
- 每个状态最多只有一个真正的写操作主按钮，且按钮始终位于用户能感知的位置。
- 切换题目、运行或团队时立即隔离旧作用域，禁止旧节点、会议、按钮或滚动位置闪现。
- 画布加载、布局、空、错误、阻塞和节点在视口外等状态都有明确反馈和恢复入口。
- 完成一轮真实假说流程验收，不通过重复跑五轮来证明基础闭环。

### 2.2 非目标

- 不修改后端 workflow schema、数据库、API DTO 或研究业务规则。
- 不重写 `resolveHypothesisFirstNextAction` 已有闭环算法。
- 不把投影变成新的写入者，不从 URL 或 selected node 反推业务真值。
- 不在本计划内重做整个 Teams 工作台、Challenge Cup overview 或其他团队类型的状态栏。
- 不复制外部商业产品 UI，不引入新画布/流程依赖。
- 不把手机端变成完整画布编辑器；窄屏只保证导航、查看和关键操作可完成。
- 不把视觉动效或品牌重做当作 P0；先修状态权威和操作闭环。

### 2.3 成功定义

以下证据必须同时成立：

- 进入题目 3 秒内，测试者能说出题目、阶段、当前任务、状态和唯一下一步。
- 四个工作区表面共享同一 `currentTask.key`，不存在互相矛盾的阶段文案。
- 点击“回到当前任务”一次即可看到目标节点和可操作 Inspector。
- 切换 SCI-001 / SCI-004 后，上一题内容立即消失，新数据未到时只显示 loading。
- 布局未完成时显示“正在整理流程”，而不是空网格。
- 从档案点击“查看评审讨论”会进入可写 `hf_meeting_<round>` Inspector，而不是只读会议记录。
- 主 CTA 在桌面与窄屏都不被滚动、裁切或面板宽度挤出；禁用时有可感知原因。
- 一轮真实浏览器验收通过，console 无 error/warn。

---

## 3. 当前事实与根因

### 3.1 三套状态源互相竞争

- 外层左栏在 [`useTeamsWorkbenchShellPhase.tsx`](../../web/src/routes/teams/useTeamsWorkbenchShellPhase.tsx) 中使用 `researchPrimaryAction` 和项目三阶段 board columns。
- workflow 顶栏在 [`ResearchWorkflowToolbar.tsx`](../../web/src/routes/teams/research-workflow/ResearchWorkflowToolbar.tsx) 中同时从正式 runtime node、`navigationLabel` 和 `nextActionStage` 推断阶段。
- 画布和右栏在 [`ResearchProcessWorkspace.tsx`](../../web/src/routes/teams/research-workflow/ResearchProcessWorkspace.tsx) 中使用题目假说链、会议、资料搜集请求、运行 projection 和 URL selection。
- 右栏 `panel=question` 在 [`ResearchProcessInspectorPane.tsx`](../../web/src/routes/teams/research-workflow/ResearchProcessInspectorPane.tsx) 中直接挂载完整 `ChallengeQuestionDetailPanel`。

这些状态各自可能正确，但组合后没有唯一“当前任务”。

### 3.2 `hypothesisConverged` 过早激活正式阶段

当前 [`ResearchProcessWorkspace.tsx`](../../web/src/routes/teams/research-workflow/ResearchProcessWorkspace.tsx) 使用 `hypothesisConverged` 直接决定 `formalRuntimeActive`。但 [`hypothesisFirstNextAction.ts`](../../web/src/routes/teams/research-workflow/hypothesisFirstNextAction.ts) 已明确：尚未闭环的候选/评审会议应优先于收敛状态。

因此“已收敛”和“第 N 轮正在整理”会同时出现。新模型必须保留 next-action 的会议优先规则，不得再由 toolbar 或实验切换器独立推断。

### 3.3 左栏承诺“下一步”却没有操作

`TeamShellStatusRail` 支持 CTA，但当前 shell phase 固定 `statusCta = undefined`。用户看到行动式标题，却找不到按钮，也无法判断它是否是真实下一步。

### 3.4 右栏承担了档案页职责

`panel=question` 包含完整候选、证据、评审、Agent 长发言、轮次和产出，超过窄 Inspector 的可扫描边界。项目既有 workflow design 已规定：Inspector 是当前阶段活操作面，题目详情是验收档案。

### 3.5 空网格缺少布局反馈

[`useWorkflowAutoLayout.ts`](../../web/src/components/vui/renderers/shadcn/workflow/useWorkflowAutoLayout.ts) 在 ELK 异步提交前以空 `nodes/edges` 初始化；[`ResearchWorkflowCanvasPane.tsx`](../../web/src/routes/teams/research-workflow/ResearchWorkflowCanvasPane.tsx) 只区分 `graph === null`，无法表达“图已到、布局未提交”。实机等待后节点可以出现，因此需要修复的是状态反馈和 viewport recovery，而不是假设后端没有节点。

---

## 4. 成熟方案调研与复用裁决

| 方案 | 最值得借鉴 | 本项目裁决 |
| --- | --- | --- |
| [n8n](https://docs.n8n.io/build/understand-workflows/workflow-components/work-with-nodes/) | 画布编辑与 executions 分离；空画布给明确第一步 | `REFERENCE_ONLY`；许可和领域均不适合直接嵌入 |
| [LangSmith Studio](https://docs.langchain.com/langgraph-platform/langgraph-studio) | 输入/图/线程分层；当前执行与历史 fork 分离 | `REFERENCE_ONLY`；Studio UI 不是可直接复用前端 |
| [W&B Projects](https://docs.wandb.ai/models/track/project-page) | Workspace、Runs、Reports、Artifacts 分层 | `REFERENCE_ONLY`；借“当前工作与历史证据分层” |
| [Temporal UI](https://docs.temporal.io/web-ui) | 当前运行操作、Timeline、History 与 Metadata 分层 | `REFERENCE_ONLY`；不采用其运行时模型 |
| [GitHub Actions visualization graph](https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows/monitoring-workflows/using-the-visualization-graph) | 图只表达依赖和状态，点击节点再看局部日志 | `REFERENCE_ONLY`；不复制闭源 UI |
| [React Flow / xyflow](https://reactflow.dev/learn/concepts/built-in-components) | `Controls`、`MiniMap`、fit viewport、Panel | `ADAPT`；项目已使用 `@xyflow/react`，继续改造现有 VUI facade |

最终复用决策：

> **总体 `REFERENCE_ONLY`；画布基础设施 `ADAPT`；产品状态与三栏交互 `BUILD_IN_HOUSE`。**

---

## 5. 统一状态契约

### 5.1 推荐模型

新增纯模型：

`web/src/routes/teams/research-workflow/researchWorkflowContextModel.ts`

建议核心结构：

```ts
type ResearchWorkflowContext = {
  scope: {
    key: string;
    teamId: string;
    workflowId: string;
    questionId: string | null;
    runId: string | null;
    runVersion: number | null;
  };
  loadState: "idle" | "loading" | "ready" | "refreshing" | "error" | "scope_mismatch";
  currentTask: {
    key: string;
    stage: "launch" | "hypothesis_first" | "knowledge_collection"
      | "experiment_design" | "execution_iteration" | "blocked";
    step: "generation" | "selection" | "review" | "evidence_gap"
      | "convergence" | "formal_runtime" | "launch";
    status: "not_started" | "running" | "waiting_system" | "waiting_user"
      | "recoverable_error" | "blocked" | "completed";
    title: string;
    detail: string;
    targetNodeId: string | null;
    meetingRoundId?: string;
    collectionRequestId?: string;
    progress?: { current: number; total: number; label: string };
    navigationAction: WorkflowNavigationAction | null;
    commandAction: WorkflowCommandAction | null;
    blocker?: { code: string; message: string; retryable: boolean };
    authority: "hypothesis_first" | "formal_runtime" | "project_summary" | "route";
  } | null;
  stages: WorkflowStageSummary[];
  view: {
    panel: ResearchProcessPanel;
    selectedNodeId: string | null;
    selectedIsCurrentTask: boolean;
    archiveMode: boolean;
  };
};
```

字段名可在实现时按现有类型收敛，但以下语义不可改变：

- `currentTask` 是业务权威；`selectedNodeId` 只是用户查看位置。
- `navigationAction` 只移动视图，不写业务状态。
- `commandAction` 才能确认、重试、交接或裁决，而且只由 Inspector 渲染。
- `scope.key` 至少由 `teamId/workflowId/questionId/runId` 组成；异步结果作用域不匹配时不得落到 UI。
- 项目三阶段只作为 `stages` 摘要，不能覆盖已选题目的 `currentTask`。

### 5.2 当前任务裁决顺序

新模型不重新编码完整状态机，而是以 `resolveHypothesisFirstNextAction(...)` 的结果为第一输入，再做 UI 归一化：

1. scope mismatch / 新题目仍在加载：清除旧任务并显示加载。
2. 候选生成会议未闭环：进行中、整理中、等待确认或整理失败。
3. 评审会议未闭环：进行中、整理中、等待确认或整理失败。
4. 已有候选但尚未完成选择。
5. 资料补充、失败恢复、搜集中或等待自动交接。
6. 预算耗尽，需要人工裁决。
7. 假说闭环后，才使用正式 runtime current node。
8. 假说闭环但没有正式节点：显示“假说阶段完成”。
9. 无链条、无运行：选择题目/开始实验。
10. 其他冲突：明确 blocked，不得猜成 completed。

兼容边界：没有 hypothesis-first chain 的旧正式运行可以直接使用 runtime current node；一旦存在链条，必须由链条闭环门控正式阶段。

### 5.3 切换与 freshness 规则

切换有 checkpoint 的题目时，原子写入：

```text
questionId + runId + node=currentTask.targetNodeId + panel=node
```

切换无 checkpoint 的题目时：

```text
questionId + 清除 runId/node + panel=launch
```

必须同步清除：

- 旧 `selectedQuestionRunId`；
- 旧 node detail；
- 旧会议/讨论展示；
- 旧画布 selection 与 history scroll；
- 旧题目写操作按钮。

同一 scope 的 `refreshing` 可以保留最后一次当前任务；不同 question/run 的数据绝不能保留。

当前 hypothesis-first meeting 查询包含 team 级缓存面。实施时必须在 query selector 或 context adapter 增加 question scope / request generation 校验；不能仅依赖 React Query 返回顺序。至少用 SCI-001 与 SCI-004 互切证明旧会议不会短暂进入新题目的 context。

---

## 6. 信息架构与交互契约

### 6.1 页面所有权

workflow 页面由同一个 `ResearchProcessWorkspace` 提供：

```text
VCanvasWorkbenchPage
├─ rail: ResearchWorkflowStageRail
├─ canvas: ResearchWorkflowCanvasPane
└─ inspector: ResearchCurrentTaskInspector / ResearchWorkflowToolPane
```

外层 Teams board 只在该 surface 激活时停用通用 `TeamShellStatusRail`。普通团队、组织画布和其他研究视图继续使用原有外层 rail。

该方案优于在 shell 与 workspace 之间新增 Provider 或重复调用 workflow queries：当前题目链数据已经由 workspace 持有，同一个 context 对象可以直接传给三栏。

### 6.2 左栏：流程定位

顶层只显示四个稳定阶段：

1. 假说先行；
2. 知识搜集；
3. 实验设计；
4. 执行迭代。

只有当前阶段展开当前内部步骤：候选形成、假说选择、团队评审、证据补充或收敛确认。用“证据补充”区分假说轮次中的资料缺口与正式“知识搜集”阶段。

左栏首屏内容：

- 当前题目编号与短标题；
- 当前阶段、任务和状态；
- 轮次/阶段进度；
- 一个 `回到当前任务` 导航按钮；
- 四阶段状态列表。

禁止：

- 不可点击的“下一步”行动卡；
- 在左栏执行确认/重试/交接；
- 完整会议、Agent 发言或长证据内容；
- 同时展示旧三阶段与画布假说链两个主流程。

### 6.3 顶栏：题目切换与轻导航

桌面常驻：

- 团队切换；
- 实验切换；
- 当前阶段与当前任务；
- `回到当前任务`；
- `题目档案`。

成员、Agent、运行记录、新建运行等次要入口移入“更多”菜单。没有运行时，`开始实验` 才提升为主操作。

`panel=question` 必须显示“题目档案”，不得再映射成“题目进度”。Toolbar 不根据 `navigationLabel` 文本包含关系独立生成另一套阶段真值。

### 6.4 中央：流程画布

画布只负责结构、依赖、handoff、证据边和当前位置：

- 新增独立 `currentTaskNodeId`，不要把假说虚拟节点伪装成正式 runtime current node。
- 当前任务：强高亮 + 当前游标；selected node：独立细描边。
- 已完成路径弱化；未来节点进一步降噪；blocked/failed 使用图标、文案和颜色多通道表达。
- 长描述、Agent 发言和完整证据不进入节点卡。
- 保留 `回到当前任务` 和 `适应全部` 两个主要控件；MiniMap 仅在长流程启用。

状态表：

| 状态 | 画布反馈 | 操作 |
| --- | --- | --- |
| graph 未到 | 正在读取流程 | 无写操作 |
| graph 已到、layout 未提交 | 正在整理流程布局 | 保留取消/切题能力 |
| graph 真为空 | 当前题目还没有流程节点 | 打开当前任务或启动面板 |
| 当前节点在视野外 | 当前任务在视野外 | 回到当前任务 |
| layout degraded | 保留 last-good，显示“布局暂不可用” | 重试布局 / 适应全部 |
| 数据错误 | 明确错误原因 | 重试 |

Viewport 规则：

- 首次题目/拓扑加载完成后 `fit all` 一次。
- 当前任务变化且用户未手动移动时自动定位。
- 用户已经平移/缩放后不抢回视角，只提示“回到当前任务”。
- 右栏挂载或宽度变化时，仅在用户未手动操作视口的情况下重新适配。
- 点击当前任务定位只改变视口，不改变业务状态或 selection authority。

### 6.5 右栏：当前任务唯一操作面

默认顺序固定为：

1. 当前任务标题；
2. 状态及系统正在做什么；
3. 为什么现在需要操作；
4. 输入和依据；
5. 操作后会发生什么；
6. 唯一主按钮；
7. 最近活动。

主按钮固定在首屏或 sticky footer。禁用按钮必须显示原因。

等待系统状态必须说明“正在处理什么、完成后谁操作”，例如：

> 正在整理第 1 轮评审。系统正在把 9 条发言整理为本轮结论；完成后需要你确认，暂时无需操作。

写操作继续由 `HypothesisFirstNodeInspector`、`HypothesisFirstMeetingOps` 和正式 node inspector 承担。左栏与顶栏不得复制同一个 command。

用户主动选择历史节点时，右栏切换为只读“历史回顾”，顶部保留当前任务提示和 `返回当前任务`；历史节点不能冒充当前任务。

### 6.6 科研档案：独立宽视图

保留 `panel=question` 兼容，但将其解释为“题目档案”，在主内容区域使用宽视图，不再占用窄 Inspector。

建议分区：

- 概览；
- 假说；
- 证据；
- 评审记录；
- 研究产出。

长发言、证据轨迹和历史轮次默认折叠或按需展开。档案只读；`查看评审讨论` 必须把 URL 导航到当前 `hf_meeting_<round>` + `panel=node`，直接打开可操作 Inspector。

现有只读 `TeamMeetingRoundPanel` 保持只读，不把写命令塞入历史展示组件。操作区和历史区必须使用不同、唯一的 anchor/id。

### 6.7 响应式与无障碍

| 视口 | 布局 |
| --- | --- |
| `>=1280px` | 左栏 232–248px；中央自适应；右栏 360–440px |
| `900–1279px` | 左栏可收起；右栏使用抽屉或更窄临时面板 |
| `<900px` | 画布全宽；阶段和 Inspector 分别使用抽屉 |
| `<640px` | 顶部只保留题目、当前阶段和主操作；主 CTA 固定底部 |

抽屉要求：

- `aria-modal` 与可读标题；
- 打开后焦点进入标题或主按钮；
- Escape 关闭；
- 关闭后焦点返回触发按钮；
- 背景不可滚动；
- reduced-motion 下取消非必要位移动画；
- 画布和 CTA 不被抽屉/顶栏遮挡。

优先复用现有 Teams Inspector overlay 交互模式；若扩展 `VCanvasWorkbenchPage` 响应式 API，必须同步更新 VUI design spec 和 contract tests。

本计划选择把响应式 rail/aside overlay 作为 `VCanvasWorkbenchPage` 的可选 recipe 能力实现，而不是在 research route 自造第二套 drawer。该能力默认关闭，只有显式传入 responsive 配置的页面启用；复用现有 Teams overlay 的焦点、Escape、backdrop 和滚动锁定语义。研究 workflow 不再依赖外层 board 的窄屏 Inspector drawer。

现有 Toolbar contract 明确禁止 `flex-wrap`。实施时不直接删除约束并让工具栏任意换行，而是先按本节减负：保留题目、当前任务和主导航，把次要入口放入“更多”；窄屏仍放不下时才在 design spec 中定义有限两行布局并同步更新 contract。

### 6.8 禁用与操作反馈

- `ResearchRunLaunchPanel` 未选题时，“开始实验”必须显示可访问的禁用原因。
- 假说选择达到最小/最大数量时，checkbox 或相邻说明必须解释为什么不可继续选择；若现有 `VCheckbox` API 不足，应先在 VUI 设计契约中扩展，而不是 route 里自造 tooltip。
- 所有写操作点击后 1 秒内进入 pending/disabled 状态，防止重复提交，并用 `aria-live` 说明系统已经受理。
- `waiting_system` 不渲染伪按钮；必须说明系统正在处理什么以及完成后由谁操作。

---

## 7. 文件与职责边界

### 7.1 新增建议

| 文件 | 职责 |
| --- | --- |
| `researchWorkflowContextModel.ts` | 纯状态投影与 scope/freshness 规则 |
| `researchWorkflowContextModel.test.ts` | 表格化状态优先级与作用域测试 |
| `ResearchWorkflowStageRail.tsx` | workflow 专用左侧定位栏 |
| `ResearchCurrentTaskInspector.tsx` | 当前任务、状态、输入/输出与唯一写操作 |
| `ResearchWorkflowToolPane.tsx` | progress/team/agents/timeline/launch 工具视图 |
| `ResearchQuestionArchiveWorkspace.tsx` | 题目档案宽视图与返回当前任务 |

### 7.2 主要修改面

- `ResearchProcessWorkspace.tsx`
- `ResearchWorkflowToolbar.tsx`
- `ResearchProcessInspectorPane.tsx`
- `ResearchWorkflowCanvasPane.tsx`
- `HypothesisFirstNodeInspector.tsx`
- `HypothesisSelectionPanel.tsx`
- `ChallengeQuestionDetailPanel.tsx`
- `renderTeamsWorkbenchBoardPage.tsx`
- `useTeamsWorkbenchShellPhase.tsx`
- `TeamResearchBoardPrimarySurface.tsx`
- `teamResearchPrimarySurfaceRenderers.tsx`
- `useHypothesisFirstChain.ts`
- `VWorkflowCanvas` / `ShadcnWorkflowCanvas.tsx`
- `useWorkflowAutoLayout.ts`
- `useWorkflowInitialFit.ts`
- `workflowFitOnResize.ts`
- `VCanvasWorkbenchPage.tsx`（仅在确认需要共享响应式能力时）
- `web/src/components/vui/designs/product/workflow.md`
- `web/src/components/vui/designs/layout/pages.md`
- `web/src/components/vui/designs/INDEX.md`

### 7.3 结构决策

`ResearchProcessInspectorPane` 当前同时拥有 question query、archive、tool panels、launch、hypothesis node、definition node 和 formal node routing。实施时采用最小 `SPLIT`：保留该文件为面板分发/组合层，把“当前操作”“工具面板”“科研档案”提取成完整职责组件。

拆分不改变 lazy pack、公共 URL、错误语义或命令所有权；不得为了降行数创建只转发 props 的碎片组件。

`ResearchProcessWorkspace` 继续遵守 composition-only contract，不新增 `useState/useEffect` 或直接 API 调用。

### 7.4 Challenge Cup / Teams 投影同步

正式实施属于 Teams research workflow 用户可见行为变更，必须同步生成的挑战杯流程站点。实施 owner 优先修改 `挑战杯/build_research_flow_site.mjs`，重新生成 `挑战杯/research_team_flow_design.html` 与需要的 per-node pages，并验证站内链接。

| Source or fact | Backend source | API DTO | Teams UI | Generated flow site | Project memory/docs | Validation | Deferred debt |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 当前任务与状态优先级 | 现有 hypothesis chain、meeting ledger、collection request、formal run | 保持现有 DTO；不新增第二真源 | 左栏、顶栏、画布、Inspector 统一 `currentTask` | 更新流程阶段与操作面说明，不模拟运行时状态 | 本计划 + 实施后 VUI workflow spec | 状态模型表格测试 + 三栏一致性测试 | 无；发现 DTO 缺口须另立任务，不在前端猜测 |
| 当前操作与历史档案分层 | 现有 question/run/meeting/evidence 读取面 | 保持现有详情 DTO | Inspector 只放当前操作；archive 使用宽视图 | 更新题目档案与可操作节点的导航说明 | 本计划 + owning module/design docs | archive deep-link + meeting inspector 测试 | 无 |
| 画布 loading/layout/viewport | 前端 graph projection 与 ELK layout | 不影响 API | 显式 loading、degraded、out-of-view 与恢复入口 | 说明画布可见状态和恢复控件 | VUI workflow/page design spec | layout/fit/resize tests + 浏览器截图 | 静态站点不复刻交互，只保持说明与链接一致 |
| 一轮真实闭环 | 真实候选、选择、会议、纪要、资料交接台账 | 使用现有 API | 通过同一 currentTask 完成一轮操作 | 对应节点和入口链接可达 | 验收记录 + 本计划状态更新 | Launcher + 内置浏览器一轮验收 + HTML link check | 不跑第 2–5 轮；不改变正式默认预算 |

---

## 8. 实施任务图

### 8.1 Critical Path

```text
Task 0 隔离交互预览
  ↓ USER APPROVED
Task 1 统一 CurrentTaskProjection
  ↓
Task 2 工作流接管三栏与共享接线
  ├─ Task 3A 左栏 + 顶栏
  ├─ Task 3B 当前 Inspector + 科研档案
  └─ Task 3C 画布状态 + viewport + 响应式
          ↓
Task 4 VUI/视觉契约收敛
  ↓
Task 5 集成与一轮真实浏览器验收
```

Task 1 和 Task 2 是串行关键路径。Task 3A/3B/3C 在文件 scope 明确后可以并行；共享 `ResearchProcessWorkspace.tsx` 和 VUI renderer 由主 integration owner 串行接线。进入本地 `main` 的合并始终串行。

### 8.2 任务卡

#### Task 0：可审查的隔离交互预览

- **Owner/Boundary**：UI design owner；只写 preview/example surface 和安全 mock 数据，不改正式 route/业务组件。
- **Dependency**：本文 `user-approved`。
- **Mode**：`SIMPLE`。
- **Deliverable**：桌面与窄屏可访问预览 URL、代表截图、关键状态说明。
- **States**：正在整理、等待确认、资料搜集中、可恢复失败、blocked、科研档案。
- **Verification/Stop**：用户回复 `APPROVED` 后进入正式实施；`REVISE` 只迭代预览；`ABANDON` 不落地。

#### Task 1：统一状态投影

- **Owner/Boundary**：`researchWorkflowContextModel*`、`hypothesisFirstNextAction` 适配、`useHypothesisFirstChain` question-scope/freshness adapter、location/scope tests；不改 UI。
- **Dependency**：Task 0 approved。
- **Mode**：`BDD_TDD`。
- **Verification/Stop**：generation/review awaiting approval 优先于 converged；selection、collection recovery/handoff、人工裁决、formal runtime、无 HFC 的正式运行、无题目、无 checkpoint、scope mismatch 与 SCI-001/SCI-004 互切全覆盖。

#### Task 2：工作流接管三栏

- **Owner/Boundary**：`ResearchProcessWorkspace`、`useTeamsWorkbenchShellPhase`、`renderTeamsWorkbenchBoardPage`、`TeamResearchBoardPrimarySurface`、`teamResearchPrimarySurfaceRenderers`、双层 layout ownership；不改变普通团队 surface。
- **Dependency**：Task 1。
- **Mode**：`BDD_TDD`。
- **Verification/Stop**：workflow 页只存在一套 rail 和一套 `researchFlow` pane persistence；外层 `TEAMS_LAYOUT_ID` 不再保存该 workflow 的重复 rail 几何；三栏消费同一 context；Workspace 保持 composition-only；切题清除旧 scope。

#### Task 3A：左栏与顶栏

- **Owner/Boundary**：`ResearchWorkflowStageRail*`、`ResearchWorkflowToolbar*`、相关 model/tests。
- **Dependency**：Task 2。
- **Mode**：`BDD_TDD`。
- **Verification/Stop**：四阶段定位、唯一导航 CTA、`panel=question` 语义正确、窄屏不裁切主操作。

#### Task 3B：当前操作与科研档案

- **Owner/Boundary**：`ResearchProcessInspectorPane` 拆分、current inspector、tool pane、archive workspace、selection/review navigation。
- **Dependency**：Task 2。
- **Mode**：`BDD_TDD`。
- **Verification/Stop**：写操作只在 current inspector；历史只读；档案的“查看评审讨论”进入可操作 meeting inspector；旧 question deep link 可用。

#### Task 3C：画布状态、视口和响应式

- **Owner/Boundary**：`ResearchWorkflowCanvasPane`、`VWorkflowCanvas`、`VCanvasWorkbenchPage` optional responsive overlay、shadcn workflow renderer、fit/layout/overlay tests；VUI renderer 与 page recipe 文件串行。
- **Dependency**：Task 2。
- **Mode**：`BDD_TDD`。
- **Verification/Stop**：布局中不显示纯空网格；currentTaskNodeId 与 selectedNodeId 同时可见且互不覆盖；用户移动后不抢视角；last-good/degraded、resize、900px/640px 抽屉、焦点返回与 Escape 行为可验证。

#### Task 4：视觉与 VUI 契约收敛

- **Owner/Boundary**：各 lane styles、VUI workflow/page design docs、`designs/INDEX.md`、VUI contracts、挑战杯生成流程站点投影。
- **Dependency**：Task 3A/3B/3C。
- **Mode**：`SIMPLE`。
- **Verification/Stop**：当前/selected/成功/等待/阻塞/失败语义一致；不引入第二套组件库；设计登记与实现同步；重新生成挑战杯流程站点并验证 HTML 链接。

#### Task 5：集成与一轮验收

- **Owner/Boundary**：integration owner；只整合、验证、修复阻塞，不增加新功能。
- **Dependency**：Task 1–4 全部通过各自 gate。
- **Mode**：focused tests + browser acceptance。
- **Verification/Stop**：第 12–13 节全部满足后才算完成。

---

## 9. 并行、claim 与合入边界

可并行：

- Task 3A 左栏/顶栏；
- Task 3B Inspector/档案；
- Task 3C canvas/VUI renderer；
- 独立测试审查与实机验收脚本准备。

必须串行或由明确 owner 统一接线：

- `ResearchProcessWorkspace.tsx`；
- `useTeamsWorkbenchShellPhase.tsx`；
- `renderTeamsWorkbenchBoardPage.tsx`；
- `ShadcnWorkflowCanvas.tsx`；
- VUI design index/spec；
- local `main` 集成。

每个实施任务使用独立 `.worktrees/<task-slug>` + `codex/<task-slug>`，claim 精确文件 scope。Agent 不得覆盖未知 diff；发现 active overlap 先缩 scope 或协调。远端 push/PR/发布仍需用户单独授权。

---

## 10. 状态与交互验收矩阵

| 场景 | 左栏/顶栏 | 画布 | 右栏 | 预期主操作 |
| --- | --- | --- | --- | --- |
| 未选择题目 | 选择题目开始研究 | 空状态，不显示坏网格 | 启动说明 | 选择题目/开始实验 |
| 候选生成中 | 假说先行 · 候选形成 | generation current | 说明系统正在讨论 | 无写操作 |
| 候选待确认 | 假说先行 · 等待确认 | generation waiting_user | 候选清单与后果 | 确认候选清单 |
| 待选择 | 假说先行 · 假说选择 | selection current | 候选勾选 | 记录选择并开启评审 |
| 评审整理中 | 假说先行 · 第 N 轮 | meeting waiting_system | 说明整理内容和下一责任人 | 无写操作 |
| 评审待确认 | 假说先行 · 等待确认 | meeting waiting_user | 结论、依据和后果 | 确认并结束本轮 |
| 资料补充中 | 假说先行 · 证据补充 | collection current | 进度和请求 | 查看/必要时继续 |
| 可恢复失败 | 当前步骤 · 需恢复 | failed/blocked | 失败原因与恢复结果 | 重试/继续 |
| 人工裁决 | 假说先行 · 预算耗尽 | convergence blocked | 裁决依据 | 人工裁决 |
| 正式阶段 | 知识搜集/实验设计/执行迭代 | formal node current | 正式 node inspector | backend-declared command |
| 历史节点 | 当前任务摘要保持 | selected != current | 只读历史回顾 | 返回当前任务 |
| 题目档案 | 档案模式 | 宽档案替代画布 | 不挂窄 Inspector | 返回当前任务 |
| 切换题目 | 正在切换题目 | loading | 清除旧内容 | 暂无写操作 |

---

## 11. 隔离预览批准门

本任务改变信息架构、布局、右栏职责和窄屏行为，正式实施前属于 `PREVIEW_REQUIRED`。

预览必须覆盖：

- 1440px 桌面三栏；
- 1024px 左栏收起 + 右侧抽屉；
- `<900px` 窄屏阶段/Inspector 抽屉；
- “第 1 轮评审正在整理”；
- “等待确认并结束本轮”；
- “资料补充中”；
- blocked/retry；
- 科研档案宽视图；
- current 与 selected 节点同时存在；
- 主 CTA sticky、长中文、禁用原因和键盘焦点。

批准语义：

- `APPROVED`：按预览契约进入 Task 1–5；
- `REVISE <反馈>`：只改预览；
- `ABANDON`：不修改正式 UI。

计划方向已获用户确认，不得把它误记为 preview 已批准。

---

## 12. 测试与验证矩阵

### 12.1 纯模型与路由

- `researchWorkflowContextModel.test.ts`
- `hypothesisFirstNextAction.test.ts`
- `researchExperimentSwitchModel.test.ts`
- `researchProcessLocation.test.ts`
- `researchProcessPanelSelection.test.ts`
- `useHypothesisFirstChain.test.tsx`

关键断言：

- 未闭环 meeting 优先于 `hypothesisConverged`；
- command/navigation 分离；
- scope mismatch 不展示旧任务；
- checkpoint/no-checkpoint 切题 patch 原子化；
- `panel=question` 是 archive，不是 progress。
- `awaiting_approval → confirm → collection/handoff → next task` 状态连续且不回跳。
- 没有 HFC 数据的正式运行仍显示 runtime current node。

### 12.2 三栏组件

- `ResearchProcessWorkspace.test.tsx`
- `ResearchWorkflowToolbar.test.tsx`
- `ResearchProcessInspectorPane.test.tsx`
- `HypothesisFirstNodeInspector.test.tsx`
- `HypothesisSelectionPanel.test.tsx` / contract tests
- `ChallengeQuestionDetailPanel.test.tsx`
- 新 `ResearchWorkflowStageRail.test.tsx`

关键断言：

- 三栏共享同一任务；
- 只有 Inspector 渲染写 command；
- archive 返回 current task；
- 历史 meeting read-only；
- 查看评审讨论进入可操作节点；
- 主 CTA/禁用原因可感知。

### 12.3 画布与 VUI

- `useWorkflowAutoLayout.test.tsx`
- `workflowInitialFitStructure.test.tsx`
- `workflowFitOnResize.test.ts`
- selection/current-task focus tests
- `researchWorkflowWorkspaceStructure.contract.test.ts`
- `researchWorkflowNoDuplicateSurface.contract.test.ts`
- `researchWorkspaceRouteContract.test.ts`
- `vuiShadcnRouteContract.test.ts`
- `vuiComponentDesignContract.test.ts`
- `node 挑战杯/build_research_flow_site.mjs` 及生成 HTML 链接检查

关键断言：

- layout pending/degraded 可感知；
- last-good 不被空布局覆盖；
- current task 可定位；
- 用户移动后不自动抢回；
- route 不直连 shadcn renderer；
- Workspace 保持 composition-only；
- 新/修改 VUI 契约已登记。

### 12.4 交付前检查

```powershell
cd web
npx tsc -b --pretty false
npm run build
```

再运行 selector-selected tests、`git diff --check`、Markdown 链接检查和当前任务 diff 自审。所有证据在合入本地 `main` 前完成。

---

## 13. 一轮真实浏览器验收

只跑一轮，不跑五轮。使用 `roundBudget=1` 的验收题目或等价受控本地场景，不修改正式默认轮次。

通过 Launcher 启动项目，在内置浏览器按鼠标真实操作：

1. 进入挑战杯科研流程并选择验收题目。
2. 3 秒内识别题目、阶段、任务、状态和唯一主操作。
3. 点击左栏或顶栏“回到当前任务”，目标节点进入视口，右栏打开对应 Inspector。
4. 完成候选形成并确认候选清单。
5. 选择假说，点击“记录选择并开启评审”。
6. 等待第 1 轮评审与系统整理；页面明确说明系统正在做什么。
7. 点击“确认并结束本轮”。
8. 系统自动进入证据补充、资料交接或收敛；不继续第 2–5 轮。
9. 从题目档案打开评审讨论，确认跳到可操作 `hf_meeting_*` Inspector。
10. 切换另一个题目，确认旧题目的节点、会议、按钮和滚动位置立即消失。
11. 手动把画布拖离 current node，确认系统不抢回；点击“回到当前任务”恢复。
12. 执行“适应全部”，确认完整流程可见。
13. 在 1440px、1024px 及键盘路径检查 CTA、抽屉、焦点、溢出和 console。

验收完成条件：

- 用户全程不需要猜测该点哪个区域；
- 每个主按钮在点击前可见，并说明操作后果；
- 后台状态不会使用含糊的“正在生成纪要”；
- 一轮闭环中没有只读页面阻断写操作；
- 无 stale question/run UI；
- console 无 error/warn。
- 关键请求没有未解释的 4xx/5xx；点击写操作后 1 秒内出现 pending 或状态反馈。

---

## 14. 风险、兼容与回滚

### 14.1 主要风险

| 风险 | 防护 |
| --- | --- |
| 新投影成为第二状态机 | 只包装 `resolveHypothesisFirstNextAction`，用现有测试表固定优先级 |
| 切题仍闪现旧内容 | scope key + mismatch fail-closed；不同 scope 不复用 previous data |
| 外层 rail 与 workflow rail 同时存在 | workflow surface contract 明确只允许一套 rail |
| 档案拆出后旧深链接失效 | 保留 `panel=question`，仅改变展示职责 |
| responsive 改动污染其他 VUI 页面 | 优先复用现有 overlay；共享 VUI API 必须有独立 contract |
| 自动 focus 打断用户浏览历史 | current task 与 selected node 分离；用户移动后只提示不抢视角 |
| 多 Agent 修改共享 workspace/renderer | 精确 claim，shared files 由主 owner 串行接线 |

### 14.2 兼容策略

- 保留 `questionId`、`runId`、`node`、`panel` URL 参数。
- `panel=question` 继续可访问，内部语义升级为 archive。
- 保留现有 backend command offers、query keys、meeting ledger 和 node IDs。
- 没有 hypothesis-first chain 的旧正式运行继续可用。
- 不改变 `TeamMeetingRoundPanel` 的只读语义。

### 14.3 回滚

- 各 Task 独立分支、独立提交、独立验证。
- 无 schema/API/数据库迁移，回滚不需要数据修复。
- 某一 UI lane 失败时只回退该 lane；状态模型和兼容 URL 可独立保留。
- 新 context 出错时显示错误/blocked，不回退到旧 `researchPrimaryAction`，避免重新产生矛盾状态。
- local `main` 合入前完成所有浏览器证据；不得把运行时问题留给合入后发现。

---

## 15. 完成与文档生命周期

本文在以下条件全部满足前保持 `user-approved` 或 `in-progress`：

- 隔离预览已获 `APPROVED`；
- Task 1–4 已完成并通过各自验证；
- Task 5 一轮真实浏览器验收通过；
- 稳定的 UI/状态契约已提炼到：
  - `web/src/components/vui/designs/product/workflow.md`；
  - `web/src/components/vui/designs/layout/pages.md`；
  - 必要的 route/module README 或 ADR；
- 实施 commit/branch 已回填到本文 metadata 或完成记录。

关闭时：

1. 把 Status 改为 `implemented`、`superseded` 或 `historical`；
2. `git mv` 到 `docs/archive/plans/<yyyy-mm>/`；
3. 更新 `docs/plans/README.md` 和 `docs/README.md`；
4. 不把本文继续当成运行时或 UI 规则真源。
