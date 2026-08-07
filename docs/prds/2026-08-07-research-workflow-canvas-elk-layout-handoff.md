# 开发交接 · 科研工作流画布 ELK 自动布局

Status: **Ready for implementation**

Decision date: 2026-08-07

Target worktree: `C:\Users\Administrator\Desktop\Vibelution-worktrees\research-workflow-canvas-maturity`

Target branch: `codex/research-workflow-canvas-maturity`

Related product contract:

- [科研流程单画布工作台 PRD](./2026-08-07-research-process-flow-single-page-workspace.md)
- [ADR 0006 · 挑战杯科研工作流运行时与单画布](../adr/0006-challenge-cup-workflow-runtime-and-single-canvas.md)
- [VWorkflowCanvas design contract](../../web/src/components/vui/designs/product/workflow.md)

## 1. 交接目标

把当前科研工作流画布从“固定坐标 + React Flow 临时折线路由”升级为成熟的自动编排画布：

- 三个科研阶段仍在同一个 viewport 中，通过 compound stage region 明确分区；
- 节点、阶段标题、边、回路和边标签不得互相遮盖；
- 正向流、跨阶段交接、条件分支和反馈回路均由同一布局结果驱动；
- 运行状态变化不能导致画布持续跳动；
- 继续遵守 VUI + shadcn/Radix 边界以及“一项职责一个文件”；
- 不改变 LangGraph 运行事实源、节点语义、人工门禁和 Agent 会话绑定契约。

本任务只更换**画布布局与边路由实现**，不是低代码流程编辑器改造，也不授权自由新增、删除或拖拽连线。

## 2. 当前问题与根因

当前画布虽然已经拆分出语义节点、语义边和三个阶段分区，但仍不是成熟的自动布局。

### 2.1 已确认的实现缺口

1. `workflowCanvasLayout.ts` 仍使用固定宽度、固定间距和手工坐标。
2. `LOOP_RAIL_X` 只被声明，没有形成真实的反馈回路通道。
3. `WorkflowSemanticEdge.tsx` 仍通过 `getSmoothStepPath` 在渲染期重新计算路径。
4. 节点实际按阶段纵向排列，但多数边仍按左右 handle 形成回折线。
5. 边标签在布局完成后叠加，没有向布局引擎申报尺寸，因此不会预留空间。
6. 普通边的 z-index 高于节点，交叉时会直接压过节点内容。
7. 当前布局结果没有 bend points、edge sections、label bounds 和固定端口顺序。
8. `iteration_decision` 有五种 outcome 能力，但后端当前 run 只有四条实际边；现有前端没有明确区分 capability、当前 run edge 与 child-run lineage。

### 2.2 禁止继续采用的修补方式

- 不再通过增加 `stageGap`、`nodeGap`、`offset` 或手写 rail 坐标逐图修补。
- 不允许布局层给坐标、边组件再用 `getSmoothStepPath` 推翻布局结果。
- 不允许为每条反馈边编写独立 SVG path。
- 不允许仅通过提高边或标签 z-index 掩盖几何冲突。
- 不允许把三阶段拆回三个页面、Tab 或独立 viewport。
- 不允许在 Route 或业务组件中直接导入 `elkjs`、`@xyflow/react` 或 renderer。

## 3. 技术选型结论

### 3.1 推荐方案

采用：

> **REUSE `elkjs` + ADAPT React Flow 官方 ELK 集成模式**

保留 React Flow 作为交互与 viewport 容器，保留现有 VUI 语义节点、Inspector、状态投影和画布控制；使用 ELK Layered 作为唯一的自动节点布局与边路由引擎。

### 3.2 为什么不是 Dagre

Dagre 适合简单有向树，但当前画布存在：

- 三个 compound stage region；
- 跨层级边；
- 多出口 decision ports；
- 人工门禁和跨阶段交接；
- 同协议重跑反馈回路、同源同目标的晋升/回滚并行边，以及修改协议产生的 child-run lineage；
- 需要边标签参与避让。

React Flow 官方布局说明明确指出 Dagre 对 sub-flow/compound graph 和完整 edge routing 支持有限；ELK 支持动态尺寸、复合图、端口约束和边路由，更符合当前拓扑。

### 3.3 为什么不引入完整图编辑平台

Eclipse GLSP 等平台可作为成熟产品参考，但引入完整模型服务器、编辑协议和操作栈会超出本任务。当前产品是固定科研流程模板，不需要换成通用低代码编排器。

### 3.4 依赖与授权影响

`elkjs@0.12.0` 的 npm license expression 为 `EPL-2.0 OR GPL-3.0-or-later`。开发 Agent 在新增依赖时必须同步：

- `web/package.json`
- `web/package-lock.json`
- `THIRD_PARTY_COMPONENTS.md`
- ADR 0006 的布局决策

不得误写成 MIT，也不得只改 lockfile 而遗漏第三方组件登记。依赖必须精确 pin `0.12.0`，避免布局算法随 patch 更新漂移。

## 4. 成熟项目研究基线

调研日期：2026-08-07。

| 来源 | 采用内容 | 不采用内容 |
| --- | --- | --- |
| [React Flow Layouting](https://reactflow.dev/learn/layouting/layouting) | React Flow 与外部布局引擎的职责分离；Dagre/ELK 能力边界 | 不复制示例视觉 |
| [React Flow ELK example](https://reactflow.dev/examples/layout/elkjs) | 异步 layout、提供节点尺寸、布局完成后 fit view | 不把示例单层树当产品拓扑 |
| [React Flow ELK multiple handles](https://reactflow.dev/examples/layout/elkjs-multiple-handles) | 唯一 port id、正确 port side、`FIXED_ORDER` | 不使用无语义 handle id |
| [ELK Layered reference](https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html) | compound graph、cross-hierarchy edge、orthogonal routing、fixed ports、labels | 不暴露 ELK 配置给终端用户 |
| [elkjs repository](https://github.com/kieler/elkjs) | JavaScript 异步布局 API；必要时可迁移 Web Worker | 不在首轮无测量依据地增加 worker |
| [Dagre repository](https://github.com/dagrejs/dagre) / [compound limitation](https://github.com/dagrejs/dagre/issues/238) | 作为简单图基线和取舍证据 | 不作为本画布正式布局引擎 |
| [Eclipse GLSP client](https://github.com/eclipse-glsp/glsp-client) | 参考模型、渲染和工具职责分离 | 不引入完整平台 |

Dify、n8n 等项目可继续作为交互和运行历史参考，但目前没有足够的一手证据证明其前端自动布局实现适合直接复用，因此不得把它们写成该技术选型的实现依据。

## 5. 目标架构

```text
Workflow canvas projection
  -> VUI graph adapter
  -> ELK compound graph
  -> ELK Layered async layout
  -> stage/node positions + fixed ports
  -> edge sections + bend points + label coordinates
  -> React Flow nodes/edges
  -> VUI semantic state styling and interaction
```

职责边界：

- 后端/LangGraph：运行、checkpoint、interrupt、恢复、事件与事实状态。
- `product/workflow`：公共输入、选择事件和布局输出类型，不依赖 React Flow/ELK。
- `renderers/shadcn/workflow`：ELK 适配、React Flow 节点/边、viewport 和交互。
- Route：只消费 `VWorkflowCanvas`，不得感知 ELK 或 React Flow。
- `WorkflowSemanticEdge.tsx`：只消费布局给出的几何路径并渲染状态，不自行寻找路径。

## 6. ELK 图模型

### 6.1 Compound graph

- 根图方向：`RIGHT`。
- 根图包含三个 stage compound node，顺序固定：
  1. `knowledge_collection`
  2. `experiment_design`
  3. `execution_iteration`
- 每个 stage 内部方向：`DOWN`。
- 启用 compound/cross-hierarchy 布局。
- 阶段标题、内边距和边界必须进入 stage 的 layout padding，而不是绘制后覆盖。

推荐基础配置：

```text
elk.algorithm = layered
elk.direction = RIGHT
elk.edgeRouting = ORTHOGONAL
elk.hierarchyHandling = INCLUDE_CHILDREN
org.eclipse.elk.portConstraints = FIXED_ORDER
```

配置项的实际命名必须以当前 `elkjs` API/类型为准，先写失败测试和最小运行探针，不得靠字符串猜测后直接交付。

### 6.2 节点尺寸

- ELK 输入必须使用节点真实或设计契约尺寸。
- 如果节点尺寸会随内容变化，使用受控测量结果更新结构 hash。
- 运行状态、颜色、进度或时间变化不得改变节点尺寸。
- 文案变化可能改变尺寸时，要截断或固定内容层级；不要让频繁 runtime 文案触发重排。

### 6.3 固定端口与决策拓扑

端口必须有稳定、可测试的语义 id。

| 边类型 | source port | target port |
| --- | --- | --- |
| 阶段内正向流 | `out:south` | `in:north` |
| 跨阶段交接 | `out:east` | `in:west` |
| `rerun` 反馈边 | `decision:rerun` | `controlled_run` 专用 feedback input |
| `promote` / `rollback` 并行边 | 独立 `decision:<outcome>` | `candidate_promotion` 独立 inputs |
| `stop` 正向边 | `decision:stop` | `result_package` input |
| `revise` child-run | 当前 run 不创建 edge port | 仅消费真实 lineage 投影 |

`iteration_decision` 的能力契约必须完整包含：

- `decision:rerun`
- `decision:revise`
- `decision:promote`
- `decision:rollback`
- `decision:stop`

端口顺序必须确定，不能依赖对象遍历偶然顺序。但 ELK graph 只能包含服务端当前投影中真实存在的 edge：

- 当前 run 中 `rerun` 是唯一反馈边；
- `promote` 与 `rollback` 是同源同目标的正向并行边；
- `stop` 是到 `result_package` 的正向边；
- `revise` 创建 child `WorkflowRun`，不得伪造当前 run 内回边。

Extended edge 必须将全局唯一 port id 直接写入 `sources[]/targets[]`。不得给 `ElkExtendedEdge` 增加不会被消费的 `sourcePort/targetPort` 兼容字段。

### 6.4 Edge sections 与标签

- ELK 输出的 `startPoint / bendPoints / endPoint` 是渲染唯一事实。
- 多 section 边必须按 `incomingSections/outgoingSections` 构造连续链；不连续链重新输出 `M` subpath，禁止虚构 section 之间的连接线。
- 边标签尺寸必须在布局输入中申报。
- 标签位置使用 ELK 输出坐标，不做 `50% path` 估算。
- 反馈回路必须位于阶段内容区之外的预留通道，不能穿过阶段标题、节点或人工门禁。
- 普通边绘制在节点下方；选中/hover 可增加交互层，但不得覆盖节点正文。

## 7. 布局生命周期

新增 `useWorkflowAutoLayout`，统一处理：

1. 根据**结构拓扑 + 节点尺寸**生成稳定 hash。
2. hash 未变化时复用上一次布局。
3. 状态、进度、错误、Agent 在线状态变化只更新节点数据，不重新布局。
4. topology、端口、节点尺寸或阶段结构变化才请求新布局。
5. 布局异步执行时保留最后一次有效布局，避免白屏和抖动。
6. 新布局只在仍对应当前 hash 时提交，旧请求不得覆盖新图。
7. 初次布局完成后执行一次 `fitView`。
8. 后续状态更新保持用户 viewport。
9. 只有用户点击“查看全局”或结构变化后明确请求时再次 fit。
10. 布局失败时保留最后有效布局，并进入可诊断 degraded state；禁止静默退回当前已知会遮盖的固定布局。

由于 `elkjs/lib/elk.bundled.js` 约 1.61 MB，会超过现有主 entry/feature chunk 预算，生产实现固定使用 `elk-api.js` + `elk-worker.min.js?worker` + `workerFactory`。Worker 必须由独立 client 管理稳定实例和 `terminateWorker()`；bundled 版本只用于算法单测。真实 Browser Worker handshake 是交付门禁，不能由 bundled 单测替代。

## 8. 文件边界

推荐新增文件：

```text
web/src/components/vui/renderers/shadcn/workflow/
├── workflowElkClient.ts
├── workflowElkGraphAdapter.ts
├── workflowElkOptions.ts
├── workflowElkPorts.ts
├── workflowElkLayout.ts
├── workflowElkEdgePath.ts
├── useWorkflowAutoLayout.ts
└── workflowElkLayout.test.ts
```

现有文件职责调整：

| 文件 | 目标职责 |
| --- | --- |
| `ShadcnWorkflowCanvas.tsx` | 组装 hook、React Flow、nodeTypes/edgeTypes 和 viewport；不含 ELK 转换细节 |
| `WorkflowSemanticEdge.tsx` | 渲染已生成路径、标签、状态和交互；禁止 `getSmoothStepPath` |
| `workflowCanvasLayout.ts` | 从生产路径移除固定坐标逻辑；可保留兼容导出或测试夹具，但不得作为静默 fallback |
| `workflowCanvasTypes.ts` | 必要时增加公共布局点、section、label bounds 类型；不得导出 ELK 私有类型 |
| `workflowCanvasModel.ts` | 保持业务投影到公共 graph input；不计算像素坐标 |

结构要求：

- 一个功能一个文件，不把 adapter、options、hook、path builder 和 renderer 合并到大文件。
- 业务节点 renderer 不直接调用 ELK。
- `elkjs` 只能出现在 shadcn workflow renderer 内部。
- 公共 `components/vui` 导出不得泄漏 `ELKNode`、`ElkExtendedEdge` 等第三方类型。
- 新建 VUI 元素前先查 designs registry；本任务优先更新现有 `VWorkflowCanvas` design，不制造第二套画布 API。

## 9. 开发任务图

### T0 · 决策同步与 RED 基线

Owner: workflow canvas developer

Depends on: none

动作：

- 更新 ADR 0006 第 11 节：由“v1 不引入 ELK”改为“由于动态 compound、反馈边和并行分支出现真实遮盖，采用 ELK Layered”。
- 在 ADR 保留单画布、固定拓扑和 VUI renderer 边界不变。
- 新增遮盖/端口/确定性测试，先证明当前实现失败。
- 记录当前截图所代表的失败类别，不用像素快照代替几何断言。

完成证据：

- 测试在旧实现上至少因节点/边或标签冲突而 RED。
- ADR 与本交接文档没有矛盾。

### T1 · ELK compound graph 与固定端口

Owner: workflow canvas developer

Depends on: T0

动作：

- 使用 `npm install --save-exact elkjs@0.12.0`，完成授权登记与独立 Worker 预算登记。
- 建立 `?worker` + `workerFactory` client，覆盖 StrictMode 与 terminate 生命周期。
- 建立三阶段 compound graph adapter。
- 输入真实节点尺寸、stage padding、labels 和固定 ports。
- 完整实现五种 decision outcome 能力，并只为四条当前 run edges 创建 ports。

完成证据：

- 三阶段顺序与节点归属确定。
- 相同输入生成相同 ELK graph。
- 所有真实 edge source/target port 均存在且唯一。
- `revise` 无真实 lineage 投影时不创建当前 run edge。
- Worker 真实构建产物被专用 budget 规则命中，Browser handshake 可 layout 并终止。

### T2 · 异步布局与缓存生命周期

Owner: workflow canvas developer

Depends on: T1

动作：

- 实现 `workflowElkLayout.ts` 和 `useWorkflowAutoLayout.ts`。
- 处理 structural hash、单飞、过期响应丢弃、last-good layout 和错误状态。
- 明确初次 fit 与用户 viewport 保持规则。

完成证据：

- status-only update 不触发第二次 layout。
- topology/尺寸变化会触发 layout。
- 慢旧请求不能覆盖新图。
- layout 失败仍保留 last-good layout。

### T3 · 边 sections、标签与反馈回路

Owner: workflow canvas developer

Depends on: T2

动作：

- 将 ELK edge sections 转换为 SVG path。
- 使用 ELK label coordinates。
- 删除生产路径中的 `getSmoothStepPath`。
- 调整边/节点/交互 overlay 层级。

完成证据：

- 反馈边不穿越非端点节点和阶段标题。
- 标签不覆盖节点。
- decision 分支的端口与标签稳定对应。

### T4 · React Flow/VUI 集成

Owner: workflow canvas developer

Depends on: T3

动作：

- 在 `ShadcnWorkflowCanvas.tsx` 接入自动布局结果。
- 保持现有节点选中、Inspector、hover、keyboard、controls 和状态样式。
- 更新 `VWorkflowCanvas` design contract 和必要的公共类型导出。

完成证据：

- Route 仍只导入 VUI 产品 API。
- 三个阶段同一 viewport、同一坐标系、同一组边。
- 运行状态更新不造成画布跳动。

### T5 · 验收与收尾

Owner: workflow canvas developer

Depends on: T4

动作：

- 跑聚焦测试、VUI contract、TypeScript、完整 frontend build。
- 用真实 Browser/Launcher 做桌面尺寸和状态矩阵验收。
- 清理被替代的固定布局代码、死常量、重复路径和无引用测试夹具。
- 确认旧页面/旧 route 处置仍符合原 PRD，不制造第二个工作流画布入口。

完成证据见第 10、11 节。

## 10. 自动化验收契约

### 10.1 几何测试

对布局结果做确定性几何断言，不只做 DOM 文案或截图测试：

- 任意两个可见 node bounds 不相交。
- stage bounds 不相交，顺序固定为 1 → 2 → 3。
- 非端点节点的扩展矩形不与 edge segment 相交。
- edge segment 不进入 stage title reserved area。
- edge label bounds 不与 node bounds 相交。
- edge label bounds 之间不相交。
- feedback loop 位于阶段主体外的保留通道。
- 相同 topology、尺寸和配置得到确定性结果。

### 10.2 行为测试

- `iteration_decision` 有五种唯一 outcome 能力，但当前 run edge ports 只对应 definition 中真实四条边。
- `revise` 有独立 outcome id；无 child-run lineage 投影时不得创建 edge。
- `promote` / `rollback` 同源同目标并行边使用独立 ports，路径和标签可区分。
- status-only update 不触发 relayout。
- topology/size update 触发 relayout。
- run 切换时旧 layout promise 不覆盖当前 run。
- Worker 在 StrictMode 重挂载后不泄漏，unmount 调用 `terminateWorker()`。
- 初次 layout fit 一次；普通状态更新不 fit。
- 初次 fit 必须发生在当前 layoutRevision 的 nodes 进入 React Flow store 之后。
- “查看全局”可显式恢复全图。
- layout error 保留 last-good layout 并可诊断。
- 生产 `WorkflowSemanticEdge.tsx` 不再使用 `getSmoothStepPath`。

### 10.3 必跑命令

在 `web/` 下：

```powershell
npm.cmd test -- src/components/vui/renderers/shadcn/workflow/workflowElkLayout.test.ts
npm.cmd test -- bundleBudget.test.ts
npm.cmd test -- src/components/vui/vuiShadcnRouteContract.test.ts
npm.cmd test -- src/components/vui/vuiComponentDesignContract.test.ts
npx.cmd tsc -b --pretty false
npm.cmd run build
```

另外运行触及的 Teams route/layout 测试和：

```powershell
git diff --check
```

命令名称如与仓库现有测试入口不一致，以 `tests/README.md` 和实际 package scripts 为准，但不得省略 VUI contract、TypeScript typecheck 和完整 frontend build。

## 11. 浏览器与 Launcher 实机验收

源代码测试和 build 通过不等于画布实机验收。

桌面视口：

- 1440 × 900
- 1920 × 1080

状态矩阵：

- 无 run；
- running；
- waiting_human；
- blocked；
- failed；
- succeeded；
- decision: rerun；
- decision: revise（验收 child-run lineage，不伪造当前 run edge）；
- decision: promote；
- decision: rollback；
- decision: stop。

交互矩阵：

- Inspector 打开/关闭；
- 首次查看全图；
- 聚焦阶段；
- 聚焦节点；
- hover/selected edge；
- 浏览运行状态持续更新；
- 从历史 run 切换回当前 run。

验收标准：

- 节点、边、标签、阶段标题零遮盖；
- 反馈边方向可读；`promote` / `rollback` 并行线不形成无法辨认的线束；
- 三阶段在同一画布中明显分区；
- Agent 节点仍能进入对应配置/会话点；
- 不出现页面级横向滚动；
- 浏览器控制台无新增 error/warning；
- Launcher 刷新后实际页面与 task HEAD 一致。

Launcher refresh 决策：

- 文档阶段：`not needed`。
- 前端实现完成、用户测试前：`recommended before user testing`。
- 建议刷新前必须先保证 `npx tsc -b --pretty false` 或完整 build 为绿。

## 12. 停止条件与禁止交付

出现以下任一情况，开发 Agent 必须停止并报告，不能以“视觉上差不多”交付：

- ELK 依赖授权或第三方登记不明确；
- ADR 仍写着“不引入 ELK”，但实现已增加 ELK；
- 任何 runtime 状态更新导致 layout 反复执行或 viewport 跳动；
- 仍有边穿过非端点节点、阶段标题或人工门禁；
- 仍有边标签覆盖节点；
- 五种 outcome 能力与当前 run edge 被混为一谈，或为 `revise` 伪造当前 run edge；
- `promote` / `rollback` 并行边无法区分；
- Worker 未通过真实 Browser handshake、未终止或逃逸现有 bundle 预算门；
- Route 直接导入 ELK、React Flow 或 shadcn renderer；
- 为修复遮盖新增另一套业务画布或旧页面入口；
- `tsc -b`、VUI contract、build 任一未通过；
- 只有组件预览，缺少 Launcher/Browser 实机验收。

## 13. 开发 Agent 完成汇报格式

```text
Task:
Worktree:
Branch:
Commit:
ADR decision synchronized:
Dependency and license changes:
Changed files:
RED evidence:
GREEN evidence:
Geometric invariants:
Browser viewport/state matrix:
Launcher refresh:
Removed obsolete layout code:
VUI boundary check:
Project-memory proposal:
Risks / blockers:
Merge status:
Next recommended step:
```

不得只汇报“build 通过”或“截图看起来正常”。必须分别给出布局几何、交互、类型/build 和真实 Browser/Launcher 证据。
