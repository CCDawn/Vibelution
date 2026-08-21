# Product workflow surfaces

## VWorkflowCanvas

### 功能

三阶段科研工作流**运行态画布**：阶段分组、语义节点（Agent / 人工 / 系统 / 决策 / 起终点）、节点运行状态、语义边（主路径 / 门禁 / 重跑 / 修订 / 晋级 / 回滚 / 停止）、当前运行高亮、UI 选中与 Inspector 联动、画布内 pan/zoom 与「定位当前 / 适应全部」。

布局所有权：**ELK 引擎 + auto-layout hook**（`renderers/shadcn/workflow/useWorkflowAutoLayout.ts`）。生产走 `?worker` 构建的 `elkjs` worker 引擎（`workflowElkClient.createWorkflowLayoutEngine`），每次画布挂载创建一次、卸载 terminate（StrictMode 不遗留 Worker）。结构不变时 status-only 更新**不触发重新布局**（几何零跳变），拓扑/尺寸变化才重跑 ELK，失败保留 last-good 并标记 degraded。

### 适用范围

- Challenge Cup / research process workspace 唯一阶段导航与运行观察表面
- 只读运行投影 + UI selection（`selectedNodeId` 不得回写 runtime）
- graph 输入使用公共 `WorkflowLayoutInput`（从 `components/vui` 导入，禁止 route 直连 renderers/shadcn）

### 使用方式

```tsx
import { VWorkflowCanvas, type WorkflowLayoutInput } from "@/components/vui";
import { projectionToCanvasGraph } from "./researchProcessGraphModel";

const graph: WorkflowLayoutInput = projectionToCanvasGraph(projection);

<VWorkflowCanvas
  graph={graph}
  selectedNodeId={selectedNodeId}
  runtimeCurrentNodeIds={projection.run.runtimeCurrentNodeIds}
  onSelectNode={setSelectedNodeId}
  height="100%"
/>
```

#### 可延展蛇形模式

挑战杯科研流程正式工作台使用 `layoutMode="serpentine"`：阶段区域纵向堆叠，阶段内部任务横向铺开并逐阶段反向折返；它仍共享一个 React Flow viewport、同一运行投影和同一节点选择事实源。该模式可配合 `showMiniMap` 提供大型流程定位，但小地图只承担导航，不成为第二张流程图或第二状态写入者。

`stage-columns` 保留为默认兼容模式；调用方不得自行复制 renderer 或直接引入 `@xyflow/react` 来实现另一套几何。

节点在 `serpentine` 模式下使用约 `300 × 72` 的模块卡：左侧实心类型色块（Agent 蓝 / 人工琥珀 / 起点灰 / 系统深色 / 决策暖色）加白图标，标题 15px、下一行按种类写副标题（决策「晋升 / 回滚 / 停止」、系统「受控执行」、人工优先用节点 description（当前 HITL 任务说明）；缺省时按 status 写副标题，不再写死「角色 · 待确认」、Agent「角色 · 已绑定/未绑定」）12px。状态叠在图标右下角标（待运行隐藏角标；运行中为旋转标记），不再铺三行脚注、类型胶囊或顶部强调条。长描述、输入/输出、检查项与技术 `agentId` 不在画布常驻，完整信息进入节点 tooltip 与 Inspector。卡片用实底 `--vui-surface-panel` 加 `--vui-elevation-2`；状态按四桶经**边框 + 类型色块旁角标**表达：完成（`--state-success` 绿）、进行（`--accent-cool` 蓝）、等待/关注（`--state-warning` 琥珀）、失败（`--state-error` 红）、待运行（最淡描边）；选中另用细蓝色 outline，不与状态色冲突。

该模式不绘制包住成员节点的大背景框，也不再绘制左上角紧凑阶段标签（编号、名称、0/5）。那些标签不会跟着视口滚动，只占画布空间。阶段分组只靠节点空间排布；不得改全局 `--vui-surface-region`（浅色 rail 等于侧栏白底）。普通相邻边默认不常驻标签；只有 `knowledge_package`、`smoke`、`promotion` 和决策/回路语义常显，其他标签仅在 hover 或 active/attention 状态出现。跨阶段交接按卡片相对位置选朝向，走短正交桥（先一弯 L，再两弯 Z；只有线段真正穿过其他卡片内部才绕行，避免为贴边擦过绕整团卡片走出楼梯折线）；同侧入边和出边共用相对磁铁（短边 3 点、长边 5 点），按对端换点且同一点只占用一次。同协议重跑沿所在阶段底部的局部反馈轨道返回，禁止绕画布或阶段绘制大矩形回路。ELK 仍负责初始节点顺序、阶段位置与空间预算；手动调整后由 renderer 的受控位置与智能正交路由接管显示几何。

画布必须提供平移、缩放、适应全部和定位当前工作；页面本身不得产生横向滚动。工具条叠在画布之上（`z-20`），画布列只吃工具条以下的剩余高度，避免 `h-full` 把第一排任务卡画进顶栏。宿主宽度变化（右栏挂载/拖拽）且用户尚未手动平移时，画布会再 fit 一次，不让卡片从右侧切出。

`VCanvasWorkbenchPage` 的 inspector 列始终挂载（默认 360px，下限 300px），避免画布把右栏挤没、工具条「查看详情」贴死窗口边。无运行且未选节点时右栏展示启动面板，而不是拆掉整列。当前人工门会打开操作栏。工具面板（agents/team/timeline/progress/launch）打开时不抢回 node inspector。

### 节点视觉种类

| visualKind | 用途 |
| --- | --- |
| `start` / `end` | 流程锚点 |
| `agent_task` | 普通 Agent 任务 |
| `human_gate` | 人工门禁（等待确认） |
| `system_task` | 系统执行 |
| `decision` | 迭代决策多出口 |

### 运行状态

严格使用 `NodeRunStatus`：`pending | ready | running | waiting_human | succeeded | failed | blocked | skipped | stale | cancelled`。

- `running`：system blue tint/轮廓/轻 ring
- `waiting_human`：琥珀 + 人工图标
- `succeeded`：`--state-success` 绿边框 + 绿角标 check（与 pending 在边框、角标两通道拉开；沿用 VUI 既有 success token，与 VDenseTable 等一致）
- `failed` vs `blocked`：不同图标（x / ban）与文案
- selected：细蓝色 outline；runtime current：独立游标（下一处会继续的节点），**不得**把 `pending`/`ready` 的 current 节点改画成 `running`
- 阶段头（仅 `stage-columns`）：`done` 绿实心编号 + 对勾徽章，`active` 仅当成员节点 status 为 `running`（蓝实心编号 + 旋转进行中徽章），`attention` 琥珀实心编号 + 需关注徽章；进度条随 tone 着色。queued 运行的 current 节点只保留游标 ring，阶段保持 `idle`。`serpentine` 不绘制阶段头。

### 边语义

| semanticKind | 说明 |
| --- | --- |
| `main` | 主流程；auto 标签默认隐藏，hover 显示 |
| `human_gate` | 人工门禁边，标签常显 |
| `decision_branch` / `rerun` / `revise` / `promote` / `rollback` / `stop` | 条件与回路；决策节点多 Handle 出边；标签常显；回路外侧 routing |

pathState：`idle | traversed | active | attention | danger` — 仅由 nodeRuns + runtimeCurrent 推导，**不猜测**未观测的决策分支选择。pathState 优先于语义色；idle 决策扇出按 semanticKind 上色并降低不透明度（promote 绿实线、rollback/revise 琥珀虚线、rerun 蓝虚线、stop 红虚线），箭头颜色与描边同源。所有有向边带箭头 marker。

#### 边几何（引擎所有权，T3）

- 自动布局边由 `workflowElkEdgePath.sectionsToSvgPath` 从引擎 `WorkflowEdgeSection[]` 直接生成（绝对坐标正交 section，无重复与虚假连接线）；生产源码禁止 `getSmoothStepPath`。手动布局激活后改用下方「手动布局与智能连线 v2」契约，不覆盖 ELK 的初始/自动整理结果。
- 标签锚点由引擎 `labelBounds`（中心）决定，缺失时不渲染标签；三阶段统一 viewport，跨阶段边同坐标空间。蛇形跨阶段标签在 **layout composer** 里把 `labelBounds` 放到竖线右侧（回路标签放到横轨上方），禁止渲染后再用 CSS transform 挪开。
- 画布短名：定义协议仍可保留 `Knowledge Package`；`resolveEdgeLabelSpec` 映射为「知识包」并用中英混排字宽计量，避免把 ASCII 当 CJK 截成 `Knowledge Pa…`。tooltip `title` 保留原文。
- z-index：自动阶段区 `0` < edge `1` < task node `2`。蛇形模式不渲染阶段标签节点。**边不浮在任务节点上方**，选中/hover 不抬升 zIndex，用描边加粗与变色表达。选中卡片只点亮碰到该卡的入出边，不压暗其余边。
- 标签契约：`workflowEdgeLabelGeometry` 是唯一几何权威——布局 spacer 尺寸与渲染 label box 完全一致（同宽高、同截断策略）；长标签截断后矩形仍参与布局；禁止渲染后 transform 移动。标签胶囊用不透明 panel 底 + workspace halo 盖住穿过的线。

### 布局与 fit 协议（T4 + 两级布局 2026-08-08 + 外层真实 ELK 2026-08-08b）

- 布局：`useWorkflowAutoLayout(graph, createWorkflowLayoutEngine)` 内部走**两级布局**（`layoutTwoLevel`）。默认 `stage-columns` 为阶段 A 各自 ELK DOWN、阶段 B 外层 ELK RIGHT；`serpentine` 为阶段 A 依次 RIGHT / LEFT / RIGHT、阶段 B 外层 ELK DOWN。两种模式都只包含真实 edges；跨阶段边通过 label spacer 交给 ELK 分配通道，任务绝对坐标 = meta 位置 + 阶段本地坐标，结构 hash 包含 layout mode 并避免重复布局。
- 目标：默认模式阶段内主链单列；蛇形模式阶段内横向铺开、阶段纵向延展；gap 由 ELK 按内容自动决定（非固定值）。
- fit：`useWorkflowInitialFit` 编排——`initialFitRevision` 只在 **settled 布局**提交后设置；等待节点进入 React Flow 内部（`useNodesInitialized`）并在下一帧执行**仅一次**；校准重排不取消 pending fit，拓扑切换（structureKey 变化）取消并重新武装；`acknowledgeInitialFit()` 后 status-only 更新不再 fit。`<ReactFlow>` 不设隐式 `fitView`；「适应全部」经 `onFitAll` 显式 fit。

### 阶段分区

- `stage-columns` 的阶段为 React Flow 父节点（`parentId` + 相对坐标）；`serpentine` 不再把阶段标签画成独立节点。
- 阶段归属严格来自 `stages[]` 的 `stageId` / `nodeIds` 与节点 `stageId`，不得按屏幕坐标猜测。
- 分组靠 workspace 实底 + 不透明任务卡；状态色不用于阶段身份。
- stageTone：`idle | active | done | attention`

### 手动布局与智能连线 v2（serpentine）

- 普通节点与决策节点都按真实 ELK port 为每条出边、入边渲染独立 Handle。决策出边继续用 `rerun/promote/rollback/stop` 等语义 id；普通出边使用完整 ELK port id。禁止多条边复用匿名 source Handle。自动布局把同侧 Handle 放到相对磁铁上（短边 `0.25/0.5/0.75`，长边 `1/6…5/6`），入边和出边共用同一侧磁铁集合并按对端卡片位置换点，避免交叉或叠在同一点；画布不可连线，因此不绘制未占用磁铁。没有布局锚点时回退到 `1/(n+1)` 分布。
- 节点拖动时，边每帧读取 React Flow 当前端点，并使用本地正交回退路线实时跟随；源端和目标端都先沿 Handle 方向保留 `32px` 笔直引线，再进入主体通道，避免线头重合后互相遮挡。拖卡片时先按相邻卡片的边/中线对齐（进入阈值 `8px`，出现参考线并吸附；离开超过 `16px` 才松开，避免上下拖时在邻边/中线和网格之间闪烁）；参考线画在 `ViewportPortal` 里（与卡片同一视口变换），禁止用盖住 `.react-flow__renderer` 的全屏兄弟层。未贴齐的轴仍落到 `16px` 网格，点状背景间距与该网格相同。禁止只用网格、错过中线或邻边贴齐。
- 松手后继续用自动布局同一套 L/Z 正交连接器（`routeOrthogonalConnectorFromEnds`）：保留已经挂上的磁铁坐标，只在线段真正穿过其他卡片内部时绕开阻挡卡。禁止 A* 迷宫或 smooth-step。拖动中若正交器尚未给出结果，回退到上述本地路线，不得让边消失或停留在旧端点。改挂过程中的预览线必须走同一套本地 L/Z 橡皮筋（`connectionLineComponent`），禁止 xyflow 默认贝塞尔。
- 阶段标签默认不再绘制，也不作为路由障碍。拖任务时边仍实时跟随；自动整理清空节点位置和箭头磁铁覆盖；锁定禁止任务拖动和箭头改挂。
- 浏览器本地布局状态为 v3：`positions + stageLabelOffsets + edgeAnchors + locked + structureKey + runId + nodeIds + stageIds`。读取兼容 v1/v2（旧节点位置保留，缺省磁铁覆盖为空）。`edgeAnchors` 只改箭头在已连接卡片上的磁铁，不改 source/target。卡片位置保留边/中线吸附结果，不再强制写回 16px 网格；阶段标签偏移仍按网格。自动整理同时清空节点位置、标签偏移和磁铁覆盖。锁定禁止任务拖动和箭头改挂。
- 蛇形画布解锁后，可拖现有箭头端点改挂到**同一张卡片**的磁铁；拖向其他卡片会被拒绝。改挂过程中才绘制未占用磁铁。运行图拓扑仍不可编辑。

### 状态/交互约束

- `@xyflow/react` 仅允许在 `renderers/shadcn/workflow/**`（入口 `ShadcnWorkflowCanvas.tsx`）
- 业务路由禁止 import renderer 或 xyflow
- `stage-columns` 默认不可拖；`serpentine` 允许任务节点做浏览器本地展示调整，仍不可改运行图拓扑。解锁时可把箭头改挂到同一张卡片的磁铁，不可接到另一张卡片。
- MiniMap 默认关闭；长流程由生产工作台显式 `showMiniMap` 开启
- 单击节点 → 选中；点空白 → 取消；键盘可聚焦节点（aria-label 含名称/类型/状态）
- 选中卡片时点亮其入边和出边：描边加粗/提亮（idle 主路径改用 `--accent-cool`），箭头颜色跟描边；不抬 `zIndex`，也不因此展开标签
- 状态栏、Inspector 或 URL `node=` 选中时，等首次 fit 结束后把该卡平移进视口（保持当前缩放）；画布上点击同一张卡不平移；卡片位置在拖动中变化时不再重复平移
- 控件：放大、缩小、适应全部、定位当前工作
- 数据 loading：由调用方 `VStateSurface` 处理；已有 graph 但 ELK 尚未提交几何时，canvas 显示“正在整理流程布局”；graph 确认无任务时显示明确 empty，不得只留下空网格
- 布局失败：保留 last-good 几何并显示 `workflow-degraded` 诊断；不得静默清空节点
- **页面壳**：`VCanvasWorkbenchPage`，`layoutId` = `WORKBENCH_LAYOUT_IDS.researchFlow`
- 画布默认 `height="100%"`；fill 宿主 absolute inset
- **禁止**固定 `height={440}` 式死高

### 文件结构

- product：`VWorkflowCanvas.tsx`、`workflowCanvasTypes.ts`、`workflowCanvasModel.ts`
- renderer：`renderers/shadcn/workflow/*`（节点/边/布局/状态/控件各一文件）

## 假说先行区域

### 功能

科研流程画布的**显示层第一类区域**：把假说先行链（选假说 → 讨论·评审 → 资料搜集 → 再讨论 → 收敛）合成为 `stages[0]` 的「假说先行」阶段带，由链台账状态驱动，不改动任何执行拓扑。区域由路由层纯函数 `buildHypothesisFirstCanvasRegion`（`routes/teams/research-workflow/hypothesisFirstCanvasRegion.ts`）从链状态 + 会议轮 + 搜集请求 + 续轮台账 + 选择记录产出 `{ stage, nodes, edges }` 片段，再经 `composeHypothesisFirstGraph` 插入主图；无链活动时区域不合成，画布保持原 16 节点形态。

卡片映射（nodeId 均以 `hf_` 前缀，Inspector 据此路由到**当前任务操作面**，不是只读摘要）：

| 卡片 | nodeId | visualKind | 状态事实源 |
| --- | --- | --- | --- |
| 候选假说生成 | `hf_generation` | `agent_task` | 第 0 轮 `hypothesis_candidate_generation`：`open→running`、`summarizing/awaiting_approval→waiting_human`、`closed` 有候选→进入选择 |
| 假说选择 | `hf_selection` | `human_gate` | 最新选择记录存在→`succeeded`，否则 `waiting_human` |
| 第 N 轮讨论·评审 | `hf_meeting_<roundIndex>` | `agent_task` | 会议 `open→running`、`summarizing/awaiting_approval→waiting_human`、`closed` 有纪要→`succeeded`、无纪要→`blocked`（fail-closed） |
| 资料搜集 · 缺口 j | `hf_collection_<requestId>` | `system_task` | 请求 `pending→pending`、`handed_off`/有交接引用→`succeeded`、`failed→failed` |
| 假说收敛门 | `hf_convergence_gate` | `human_gate`（单出口门，非迭代决策五出口 `decision`） | `hypothesisConverged→succeeded`；预算耗尽未收敛→`blocked`；否则 `pending` |

边语义（只画台账里真实存在的关联；常显复用现有叙事标签过滤 `workflowEdgeKeepsNarrativeLabel`——只有叙事语义/门禁种类的边在蛇形模式保留标签，`main`+`auto` 边标签始终 hover 才显示，不为区域开口子）：

| 边 | 语义 | 标签 |
| --- | --- | --- |
| `hf_e_sel_m1` 选择→首轮会议 | `decision_branch`（人工选定即分支决策） | 常显「选定假说」 |
| `hf_e_m{i}_c{j}` 会议→其触发的搜集请求 | `decision_branch` | 常显「搜集决策」 |
| `hf_e_c{j}_m{i+1}` 已交接搜集→续轮会议 | `main`（gateKind `knowledge_package`，交接内容即知识包） | 常显「知识包交接」 |
| `hf_e_m{i}_m{i+1}` 无搜集直接续轮 | `main` | 「再讨论」（hover 显示） |
| `hf_e_m{last}_gate` 最新会议→收敛门 | `main` | 无标签 |
| `hf_e_m1_stage1` 首轮会议→`source_finding` | `human_gate`（gateKind `knowledge_package`） | 常显「首轮搜集范围就绪」 |
| `hf_e_gate_stage2` 收敛门→`hypothesis_design` | `human_gate`（gateKind `knowledge_package`） | 常显「假说集就绪」 |

阶段头计数：`stage-columns` 区域 stage 可通过 `WorkflowCanvasStageInput.progress = { completed: 已闭环轮次, total: 轮次预算 }` 覆盖默认的「成功卡数/卡数」。`serpentine` 不绘制该计数。生成/评审讨论进行中时，`composeHypothesisFirstGraph(..., { demotePipelineStages: true })` 把 16 节点阶段 `stageTone` 降为 `idle`，假说先行阶段为 `active`。`progress` 是可选字段，不进入结构 hash，更新不触发重排。

### 适用范围

- 仅假说先行题目（存在选择记录或 scoped 会议/搜集请求）的科研流程工作区画布；定义视图与运行视图同样合成。
- 区域卡片无后端 node detail：画布右侧 Inspector 是该阶段的**活操作面**（看讨论、生成纪要、确认、勾选假说、看搜集进度与恢复）。赛题详情只当验收档案；目录题无审核工件时详情 fail-soft，选择和会议仍可操作。`useNodeDetailState` 对 `hf_` 前缀节点直接返回 empty。
- 假说选择 Inspector 使用单开候选：未展开候选只保留可扫描标题，当前候选展开机制、预测与可用的证据轨迹；空预测和空证据不重复占位。评审关门后切换为只读归档，只显示最终采用候选与归档数量，不保留复选框、全选或提交入口。
- 验收档案读取失败时，错误摘要只占局部并默认折叠技术细节；只要团队和题目标识仍有效，假说选择与评审讨论继续可操作，不用整页空态覆盖。
- 顶栏只做「前往/查看」导航（`navigationLabel`）；Inspector 才执行写命令（`commandLabel`）。禁止同名按钮既导航又写入。有 run 时顶栏主按钮是前往当前任务；URL 已指向该任务时弱化为「当前任务」。等待人工确认时工作区把 `node` 写入 URL 并打开操作栏。「新建运行」为次要。切换器文案为「切换实验」。
- 创建/切换实验后按下一步模型定位 `hf_generation` / `hf_selection` / 已有搜集运行的 `source_finding`，不得默认落到被锁住的资料寻找。`collectionReady` 只表示搜集决策已成立；ensure 成功后 Inspector 显示「资料搜集中」，不再提供第二个「开始资料搜集」。
- 轮次增加 = 拓扑变化 → 结构 hash 变化 → 自动重排；状态翻转不重排。

### 使用方式

```tsx
import { buildHypothesisFirstCanvasRegion } from "./hypothesisFirstCanvasRegion";
import { composeHypothesisFirstGraph } from "./researchProcessGraphModel";

const base = projectionToCanvasGraph(projection);
const region = buildHypothesisFirstCanvasRegion({
  chainState, meetings, collectionRequests, reviewRoundLinks, selection,
});
const graph = composeHypothesisFirstGraph(base, region, {
  demotePipelineStages: discussionActive,
}); // region 为 null 时原样返回 base
```

链数据由 `useHypothesisFirstChain(teamId, questionId)`（React Query，questionId 为空不发请求）提供；run SSE 事件经 `useHypothesisFirstChainInvalidation` 防抖失效相关 query。

### 工作区顶栏实验切换（2026-08-19 统一选择器）

画布拓扑仍是一张图。顶栏切换器列出 **launch-options 全量题目目录**（125 题），不只是已开始的实例：包含无 checkpoint 的题与 `cancelled` checkpoint 的题，目录顺序稳定、当前题置顶。

- 选项来自 `launch-options.questions[]`（题目最新 workflow run checkpoint）。文案：`SCI-096 · 假说摘要`（未选则「假说待生成」）；description = 题目标题 + 可读的 checkpoint 可用性/状态/进度（`当前节点 · 完成/总数 · 状态文案`），无 checkpoint 的题明确写「无 checkpoint」。
- 触发器只显示紧凑摘要：**未选显示「假说待生成」；已选后按链路状态显示「N 条假说待评审 / N 条假说评审中 · 第 K 轮 / N 条假说已收敛」**，一律不显示一个或两个原始 candidate ID（即使候选 ID 超长也不外露）；题号前缀仍保留（`SCI-096 · 1 条假说待评审`）。题号、题目标题、checkpoint 节点/进度/状态完整保留在下拉选项的 label 与 description 中，全部 125 题的目录行为不变。
- 切换器宽度有明确上限（桌面 `md:min-w-[12rem] md:max-w-[24rem]`，窄屏 `max-w-[20rem]`），不再用 `1fr` 占满工具栏剩余空间；工具栏为 `flex flex-wrap`，空间不足时布局安全换行，右侧「查看详情」与主操作（前往/创建运行）永远保留、不被挤出。
- 选中**有 checkpoint** 的题即写入 URL：`questionId` + `runId` + `node=` 下一步模型算出的当前任务（生成讨论 / 选择 / 已有搜集运行），**不是**盲用 `checkpoint.currentNodeId` 的 `source_finding`。
- 选中**无 checkpoint** 的题写入无运行 patch：设置 `questionId`、清除旧 `runId`/`node`、`panel=launch` 打开预填该题的启动面板，**不自动创建运行**。
- 顶栏常驻当前题号、标题与假说摘要（未选则写「假说待生成 / 尚未选择实验」）。切换器 aria 为「切换实验」。假说正文仍在赛题详情，不把 125 题假说陈述预拉进切换器。
- 有 run 时主按钮是「前往…」当前任务；「创建运行 / 新建运行」降为次要并仍打开 launch 面板。

### 渲染契约补丁（2026-08-19 修复）

- 「首轮搜集范围就绪」边指向主图起点 `source_finding`（visualKind `start`）。`WorkflowStartEndNode` 的默认极性仍是「start 无 target 把手」；但当布局给 start 节点分配了真实 target 端口（`portSides.target` 非空）时，渲染器必须镜像该端口——否则 React Flow 因找不到 target handle 静默丢边。既有契约测试（无入边 fixture 下 start 无 target 把手）不受影响。

### 限制

- 画布节点仍是投影，不是新的 backend node；不改 16 节点执行拓扑
- 不把整份单题验收（审核工件、修订登记）塞进 Inspector
- 不引入第二套设计系统 / HeroUI；路由不直连 `renderers/shadcn`
