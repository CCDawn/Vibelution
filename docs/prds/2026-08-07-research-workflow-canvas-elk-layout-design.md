# 实现技术方案 · 科研工作流画布 ELK 自动布局

Status: **T1 冻结完成（2026-08-07）**——layoutOptions、真实 ELK Worker 资产名与 Browser Worker handshake 均已通过 T1 实测（bundled 探针 / Browser probe / 生产构建三类证据见 §4.2）；**两级布局架构返工（2026-08-08）**——单次 compound 图被两级布局取代（阶段内 DOWN + 阶段元图确定性 RIGHT + 跨阶段 gateway 通道），见 §3/§4/§5 修订

Date: 2026-08-07

依据：

- [开发交接 PRD](./2026-08-07-research-workflow-canvas-elk-layout-handoff.md)（本方案的验收契约与停止条件唯一来源）
- [ADR 0006](../adr/0006-challenge-cup-workflow-runtime-and-single-canvas.md)（§11 待 T0 同步）
- [VWorkflowCanvas design contract](../../web/src/components/vui/designs/product/workflow.md)

基线事实（2026-08-07 已勘察）：

| 事实 | 值 |
| --- | --- |
| worktree / branch | `research-workflow-canvas-maturity` / `codex/research-workflow-canvas-maturity`；实现代码基线 `7505f0b5605598a67b856028aa163311caac5cdf` |
| `elkjs` 待装版本 | `0.12.0`；许可证头为 **EPL-2.0 OR GPL-3.0-or-later**（必须如实登记，不得误标 MIT） |
| `@xyflow/react` | `12.11.2`（已装） |
| 测试环境 | vitest 3 + happy-dom；hook 测试先例 `useResearchWorkflowRun.test.tsx`（`createRoot` + `act`，不依赖 @testing-library/react） |
| bundle 门 | `web/scripts/checkBundleBudget.mjs`；route/feature chunk 上限 390 KiB |

---

## 1. 决策摘要

在 PRD 结论之上，本方案新增 6 个实施决策（D1–D6）。D1/D2 是基于 bundle 门与 `elkjs` 包结构得到的推荐实施决策；只有真实构建产物和 Worker 浏览器探针通过后才冻结。

### D1 · ELK 加载方式：固定 Worker factory（预算驱动，非性能驱动）

- PRD §7 允许首轮主线程 API；但实测 `elkjs/lib/elk.bundled.js` 为 **1.61 MB**，任何主 bundle / feature chunk 都超预算门（470/390 KiB）。
- 采用 `elkjs` Worker 组合：主线程只引 `elk-api.js`（~10 KB），算法核心走 `elkjs/lib/elk-worker.min.js`（1.6 MB 独立 worker asset）。
- 生产接入固定为 Vite `?worker` + `workerFactory`，不再保留二选一：

```ts
import ELK from "elkjs/lib/elk-api";
import ElkWorker from "elkjs/lib/elk-worker.min.js?worker";

const elk = new ELK({
  workerFactory: () => new ElkWorker(),
});
```

- `workflowElkClient.ts` 负责稳定创建实例、暴露 layout、卸载时调用 `terminateWorker()`，并处理 React StrictMode 重挂载；hook 不直接 new Worker。
- 附带收益：布局计算天然不阻塞主线程；为后续图规模增长预留路径。
- 若实际 Browser/Vite 探针证明该 package worker 无法稳定加载，停止并报告；备选主线程动态 import 属于新的架构决策，不能在实现中静默切换。

### D2 · bundle 预算治理（真实产物驱动）

`checkBundleBudget.mjs` 的 `BUNDLE_BUDGETS` 新增一条 known worker chunk 规则：

- 必须位于通用 `route or feature chunks` 规则之前，因为预算匹配采用 first-match；
- 候选正则为 `/^elk-worker(?:\.min)?-[\w-]+\.js$/`，最终以一次真实 Vite build 的产物名修订；
- maxBytes 初始约 1800 KiB，单位是当前脚本使用的未压缩文件大小；
- 增加 budget fixture，证明真实 worker 文件被该规则命中，同时没有进入 `index-*`、Teams route 或 vendor chunk；
- 不改动任何现有预算上限。这是对新独立 Worker 资产的登记，不是放宽主应用门。

### D3 · 节点尺寸策略：设计契约尺寸 + 一次性受控校准

- 布局输入首轮使用设计契约尺寸：宽 248 固定；高按 `visualKind`：decision 112 / 其余 88（与现状一致）。
- 布局完成后用受控测量（隐藏容器 off-screen 渲染节点，读 `offsetWidth/offsetHeight`）校准一次；若与设计尺寸偏差超过阈值，更新尺寸并触发**至多一次** relayout。
- 所有节点内文案 truncate 到固定行数；边 label 申报**固定设计宽度**（如 152px）并 truncate——label 文本变化不改变宽度，因此不进入 structural hash。

### D4 · z-index 层级

- stageRegion `0` < task node `2`；edge 常驻 `1`（**边在节点下方绘制**，修正现状 edges `2` > nodes `1`）。
- 选中/hover 边不提升 zIndex，用加粗描边 + 变色表达；交互热区用 `interactionWidth`（现状 20px）维持。

### D5 · 测试与生产同核心、显式引擎注入

- renderer 内定义私有 `WorkflowLayoutEngine` 接口，hook 通过 factory/injection 消费，不直接 import bundled 或 worker 实现；
- 单元/算法探针注入 `elkjs/lib/elk.bundled.js`；
- 生产注入 `workflowElkClient.ts` 创建的 Worker engine；
- 增加一条真实 Browser Worker handshake 验收，因为 bundled 单测不能证明 Worker URL、CSP、Vite asset 和终止生命周期有效。

### D6 · 五种决策能力与四条当前 run 内边分离

后端权威 definition 的当前拓扑是：

| outcome | 当前 run 内目标 | 布局分类 |
| --- | --- | --- |
| `rerun` | `controlled_run` | feedback |
| `promote` | `candidate_promotion` | forward parallel |
| `rollback` | `candidate_promotion` | forward parallel |
| `stop` | `result_package` | forward |
| `revise` | 创建 child `WorkflowRun` | 无当前 run 内边 |

- 决策节点能力契约完整保留 `rerun / revise / promote / rollback / stop` 五种 outcome。
- ELK graph 只接收投影中真实存在的四条当前 run 内边，禁止为 `revise` 伪造回到当前 `protocol_design` 的边。
- `sourceHandleIds` 从真实 outgoing edges 派生；另增 `decisionOutcomeIds` 表达五种能力，供 Inspector、菜单和 aria 使用。
- `decisionSourceHandle(revise)` 改为 `"revise"`，仅供未来真实 child-run lineage edge 使用；没有 lineage edge 时不创建 React Flow edge。
- `revise` 的执行结果通过 Inspector/RunTimeline 展示 child-run lineage；若以后要在画布显示，必须消费服务端真实 lineage 投影，并使用独立 `run_lineage` edge 类型。

---

## 2. 目标与非目标

目标（= PRD §1）：ELK 驱动的三阶段 compound 自动布局；零遮盖（节点/标题/边/标签）；固定语义端口；反馈回路外绕通道；状态更新不跳变；保持 VUI 边界与单画布。

非目标（= PRD §1/§2.2，红线）：不新增/删除/拖拽连线；不做低代码编辑器；不用 `getSmoothStepPath` 推翻布局；不逐图手修间距/rail 坐标；不拆三页/多 viewport；Route 不感知 ELK/React Flow。

---

## 3. 数据流

### 3.1 两级布局架构（2026-08-08 修订；2026-08-08b 外层改为真实 ELK + spacer node）

```text
WorkflowLayoutInput (public, 无状态字段参与布局 hash)
  → workflowStageSubgraphAdapter.buildStageSubgraphs()
      按 stageId 分组；每阶段子图只含阶段内 edges（跨阶段 edges 明确排除）
  → workflowStageLayout.layoutStages()            // 阶段 A：每阶段独立 ELK DOWN
      串行执行（elkjs 非并发安全）；输出本地坐标 + 阶段 box（标题区 + padding）
  → workflowOuterElkGraphAdapter.buildOuterElkGraph()
      阶段 B：真实外层 ELK graph——
        · 三阶段 meta nodes（宽高 = 阶段 A box，FIXED_SIDE gateway ports）
        · 每条跨阶段边一个虚拟 label spacer node（尺寸 = 共享标签契约）
        · 跨阶段边 → 两条布局边：stage A port → spacer → stage B port
  → workflowOuterElkLayout.layoutOuter()          // 外层 ELK RIGHT/ORTHOGONAL
      ELK 输出：阶段坐标（自动 gap）、spacer 位置、两段边 sections
  → workflowLayoutComposer.composeFinalLayout()
      task 绝对坐标 = stage meta 位置 + 阶段本地坐标；内部边偏移；
      跨阶段边 = 两段 leg 重组；label rect = spacer 位置
  → sections → workflowElkEdgePath.toSvgPath()    // → WorkflowSemanticEdge 直接消费
```

**为什么用 spacer node 而非原生 edge label**（2026-08-08b 探针结论）：elkjs
0.12 原生 edge label 在 ORTHOGONAL 外层图**不参与 spacing 求解**——80px 与
180px 标签产生相同 stage gap（20px），标签矩形溢出 stage 边界。虚拟 spacer
node 作为布局占位对象：标签 80px → gap 120px；180px → 220px（自动扩张）。
spacer 只承担布局占位，不渲染为用户节点；渲染仍保留一个领域 edgeId 与一个
可见标签。

**为什么阶段布局串行**：elkjs 实例并发调用 `layout()` 会串扰输出（实测
leg 边方向错乱）——阶段布局与外层布局串行执行，三阶段规模可接受。

职责边界（= PRD §5）：`product/workflow` 只产公共类型；`renderers/shadcn/workflow` 独享 elkjs 与 @xyflow；Route 只消费 `VWorkflowCanvas`。

---

## 4. ELK 图模型构建

### 4.1 图模型：两级（`workflowStageSubgraphAdapter.ts` + `workflowOuterElkGraphAdapter.ts`）

**阶段 A · 阶段内部子图**（每阶段一个，`workflowStageSubgraphAdapter`）：

```text
stage:knowledge_collection { layoutOptions: { direction DOWN, edgeRouting ORTHOGONAL, ... } }
  └─ (children: 该阶段全部 task/decision 节点，带显式 ports 与 labels)
  edges: 只含阶段内部 edges（from/to 均在本阶段）
```

- 子图 **不设 padding、不挂阶段标题 label**：padding 与标题区由
  `workflowStageLayout` 显式计算（标题区保留在顶部，任何边不得穿过）；
- 跨阶段 edges **明确排除**——它们不参与阶段内 layering（这是单次 compound
  拉伸阶段的根因）；
- 三阶段布局**并行**发起（`layoutStages` 用 `Promise.all`）。

**阶段 B · 外层真实 ELK**（`workflowOuterElkGraphAdapter` + `workflowOuterElkLayout`）：

- 三阶段折叠为 meta nodes（width/height = 阶段 A box）；
- 每条跨阶段边一个 **label spacer node**（尺寸 = `workflowEdgeLabelGeometry`
  共享契约）；跨阶段边映射为两条布局边：`stage A EAST port → spacer →
  stage B WEST port`；
- gateway ports 用 `FIXED_SIDE`（elkjs layered 实测忽略 FIXED_POS/FIXED_RATIO/
  anchor 等固定坐标，端口 Y 由引擎决定）；`workflowLayoutComposer` 在外部
  路段前后补齐「任务边界 → 阶段 gateway → 引擎通道 Y」的正交 stub 段，
  最终折线从任务实际端口出发、节点到节点连续；
- 阶段顺序由 ELK RIGHT 分层 + 阶段间真实连接边保证。

**坐标合成**（`workflowLayoutComposer`）：

- `task 绝对坐标 = stage meta 位置 + task 本地坐标`；
- 阶段内边 sections 按 meta 位置整体偏移；跨阶段边 = 两段 leg 重组
  （leg 边界被 label spacer 覆盖——标签压在边上，语义关联合法）；

### 4.2 layoutOptions 候选与探针（`workflowElkOptions.ts`）

候选（**全部 key/取值以探针为准，不得靠字符串猜测交付**）：

```ts
{
  "elk.algorithm": "layered",
  "elk.direction": "RIGHT",                    // stage 内覆盖为 "DOWN"
  "elk.edgeRouting": "ORTHOGONAL",
  "elk.hierarchyHandling": "INCLUDE_CHILDREN",
  "org.eclipse.elk.portConstraints": "FIXED_ORDER",
  "elk.padding": "[top=52,left=66,bottom=28,right=66]",   // stage 级；顶部 52 为标题保留区
  "elk.nodeLabels.placement": "INSIDE V_TOP H_LEFT",      // stage 标题
  "elk.edgeLabels.placement": "CENTER",
  "elk.spacing.nodeNode": "18",
  "elk.spacing.edgeNode": "24",
  "elk.spacing.componentComponent": "36",
}
```

探针清单（T1 第一步，见 §9.1）：algorithm/direction/hierarchyHandling/edgeRouting 四键被接受且方向符合预期；FIXED_ORDER 端口顺序确定；edge label 输出 `x/y`；跨层级边 section 坐标的坐标系（根绝对坐标 or 所属父坐标——决定 §5.2 换算）；feedback 边是否绕行阶段内容区。

**T1 实测探针结论（elkjs 0.12.0，2026-08-07）**：

- 短名 key（`elk.algorithm` 等）是长名的官方别名：`knownLayoutOptions()` 只列长名（`org.eclipse.elk.algorithm`），但用短名跑 `elk.layout` 正常生效，因此 options 常量保留短名。
- compound 定向：**无跨阶段边的独立 stage 被 ELK 竖直堆叠**（`elk.priority` / `elk.position` / `considerModelOrder` 对无连接 compound 排序均无效，已实测）；**存在跨阶段边时三 stage 沿 `RIGHT` 正确水平排**。三阶段正向交接（knowledge → experiment → execution）是真实拓扑的固有边，保证生产路径排序；adapter 中以注释记录该事实，不伪造排序边。
- `FIXED_ORDER` 端口按声明顺序输出；边端点用 port id 填入 `sources[]/targets[]`（`ElkExtendedEdge`），layout 可解析且输出 sections。
- 边 label：`elk.edgeLabels.placement=CENTER` 下 ELK 输出 label 坐标，`fromElkLayout` 直接消费 `labels[0].x/y`，不做 50% 估算。
- 输入输出确定性：相同 `WorkflowLayoutInput` → 相同 ELK graph 与相同布局（已有单测锁定）。

**T1 验证证据（三类区分，2026-08-07 实测）**：

- bundled 算法探针：`workflowElkLayout.test.ts` 25 用例全绿（elkjs 0.12 API 事实、compound/ORTHOGONAL/FIXED_ORDER/label 坐标/坐标归一/multi-section 链/feedback 通道、三阶段真实拓扑、ports/endpoint 契约、`fromElkLayout` 几何消费）。
- Browser Worker 探针：`web/probes/workflow-elk-handshake.html` + `workflow-elk-handshake.ts`，由 **test-only probe build**（`VIBELUTION_PROBE_BUILD=1 vite build --outDir dist-probe`，`npm run build:probe`）纳入构建，普通 `npm run build` 不包含；`npm run check:elk-worker-handshake` 一键完成 probe 构建 → 预算断言 → Edge headless 实机验证 `ok: true`（页面完成后 POST 回写结果，避免 dump-dom 无法等待 Worker 异步的时序问题）：Worker 资产真实加载且仅构造一次、URL 命中 `elk-worker.min-*.js`、`terminate()` 确被调用、终止后未再新建 Worker、无 bundled 回退、最小 compound layout 返回节点坐标与 edge sections（terminate 后再次 layout 不再产生新答案，实测 timeout）。
- 生产构建证据：T1 收尾后普通 `npm run build` **不再**产出 Worker 资产（probe 已移出普通构建，产品代码 T4 才 import `workflowElkClient`）；worker asset 的存在/唯一/预算断言改由 `npm run check:elk-worker-handshake`（对 `dist-probe/assets`，`expectElkWorker: true`）承担，T4 后普通构建自然恢复产出且 `check:bundle` 移回默认门（见 §13 过渡说明）。

### 4.3 端口模型（`workflowElkPorts.ts`）

端口 id 全局唯一、语义化、顺序确定（数组声明，禁止依赖对象遍历）：

| 端口 | 所在节点 | side |
| --- | --- | --- |
| `out:south` / `in:north` | 阶段内普通节点 | SOUTH / NORTH |
| `out:east` / `in:west` | 阶段首/末节点（跨阶段交接） | EAST / WEST |
| `decision:rerun` | `iteration_decision` | WEST，连接 `controlled_run` 的专用 feedback input |
| `decision:promote` / `decision:rollback` | `iteration_decision` | SOUTH，连接 `candidate_promotion` 的两个独立 input |
| `decision:stop` | `iteration_decision` | SOUTH，连接 `result_package` |
| `decision:revise` | 能力/未来 lineage | 当前 run 无 edge，因此不进入 ELK graph |

- 五种 decision outcome 必须齐全且唯一，但当前 run 只有四条实际 edge。
- `promote` 与 `rollback` 是同源同目标的 parallel edges，必须使用不同 source/target port，并验证标签与路径可区分。
- 只有 `rerun` 是当前拓扑中的反馈回路；`rollback` 不得按名称误判为 feedback。
- `WorkflowLayoutEdge.sourceHandle` 与真实 edge port 一一对应；端口分配纯函数必须以 edge topology 为第一依据、semantic kind 为辅助，不按文案猜测。
- `revise` 只有在服务端投影真实 child-run lineage edge 时才获得布局端口；当前实现不得伪造。

### 4.4 尺寸与标签申报

- 节点：`width/height` 必须显式传入（D3 策略）。
- 节点 label：`{ text, width: 节点设计宽 - 2×内边距, height: 标题行高 }`。
- 边 label：`{ text, width: 152（设计上限，truncate）, height: 24, layoutOptions: { "elk.edgeLabels.placement": "CENTER" } }`。
- 阶段标题：进入 stage 的 `elk.padding` 顶部保留区，不覆盖绘制。

### 4.5 类型适配

`ElkExtendedEdge` 使用 `sources: string[]` / `targets: string[]`。连接显式端口时，数组元素直接填**全局唯一 port id**：

```ts
const elkEdge: ElkExtendedEdge = {
  id: edge.id,
  sources: [sourcePortId],
  targets: [targetPortId],
};
```

不得向 `ElkExtendedEdge` 私自增加 `sourcePort/targetPort`：这两个字段属于已废弃的 `ElkPrimitiveEdge`，ELK extended-edge 路径不会消费该兼容字段。adapter 必须验证每个 endpoint id 都能在 node ports 中解析。

---

## 5. 输出消费与边路径

### 5.1 公共类型扩展（`workflowCanvasTypes.ts`，不泄漏 ELK 类型）

```ts
export type WorkflowLayoutPoint = { x: number; y: number };
export type WorkflowEdgeSection = {
  id: string;
  start: WorkflowLayoutPoint;
  end: WorkflowLayoutPoint;
  bendPoints: WorkflowLayoutPoint[];
  incomingSectionIds: string[];
  outgoingSectionIds: string[];
};
export type WorkflowLabelBounds = { x: number; y: number; width: number; height: number };
export type WorkflowLayoutResult = {
  nodes: WorkflowLayoutNode[];          // 复用现有类型，增补尺寸
  edges: Array<WorkflowLayoutEdge & {
    sections: WorkflowEdgeSection[];    // 唯一几何事实
    labelBounds?: WorkflowLabelBounds;  // ELK 输出坐标，不做 50% 估算
  }>;
  width: number;
  height: number;
};
```

### 5.2 sections → SVG path（`workflowElkEdgePath.ts`）

- 单 section：`M start L bend1 L ... L end`。
- 多 section：按 section id 构造有向关系，从无 incoming 的 section 开始遍历 outgoing 链。
- 只有前一 section 的 `endPoint` 与后一 section 的 `startPoint` 连续时才追加 `L`；不连续链必须重新输出 `M`。
- 一个 edge 可以产生多个 SVG subpath；不得为“拼成一个字符串”虚构 ELK 未返回的连接线。
- 对环、缺失 section id、断链和分支 section 做显式诊断；当前非 hyperedge 图仍要用 cross-hierarchy 多 section 夹具覆盖。
- 坐标换算：先按探针结论把 ELK 坐标系归一到**画布绝对坐标**（若 ELK 对父内边输出相对坐标，加父坐标偏移），再交 React Flow 渲染。
- 纯函数、无 React 依赖，可单测（segment 求交直接喂给几何断言）。

### 5.3 label 坐标

- 用 ELK 输出 `edge.labels[0].x/y` 作为 label 锚点（±宽高修正）；不保留 `getSmoothStepPath` 的 50% 估算。
- 探针若发现 ELK 不输出可用 edge label 坐标（预期支持，`CENTER` + ORTHOGONAL），则**停止并报告**（PRD §12），不得回退估算。

---

## 6. 布局生命周期（`useWorkflowAutoLayout.ts`）

### 6.1 structural hash

```ts
hash = stableStringify({
  stages: [{ id, nodeIds }],                                  // 顺序敏感
  nodes: [{ id, visualKind, width, height }],                 // 设计尺寸（D3）
  edges: [{ source, target, sourceHandle, semanticKind }],    // 不含 pathState
})
```

- **显式排除**：`status / pathState / stageTone / attempt / isRuntimeCurrent / primaryAgentId / blockedReason / 边 label 文本（宽度固定，D3）`。
- 实现为纯函数模块（可单测），hook 内仅做比较。

### 6.2 并发与 last-good

- `workflowElkClient.ts` 为每个画布生命周期创建一个稳定 engine；React render 不得重复创建 Worker。
- hook unmount 时使 token 失效并调用 `terminateWorker()`；React StrictMode mount → cleanup → remount 必须无遗留 Worker。
- `layoutTokenRef` 单调递增；每次 `ELK.layout` 完成时仅当 token 仍为最新才提交。
- hash 未变 → 直接复用缓存布局，`ELK.layout` 调用次数为 0（行为测试断言）。
- 失败 → 保留 last-good 布局，置 `degraded` 状态（含可诊断原因字段）；**禁止**静默回退旧固定坐标布局。
- 布局执行期间保留最后一次有效布局渲染，不白屏。

### 6.3 fit 策略

- 首次布局完成：先提交新的 React Flow nodes/edges，等待 node internals 对应当前 `layoutRevision` 后，再于下一 animation frame 执行 `fitView({ padding: 0.08 })` 一次；禁止在异步布局 promise resolve、节点尚未进入 store 时提前 fit。
- 移除现状 `fitView` prop 与 `onInit` fitOnce，见 §7。
- 后续状态更新：不 fit，保持用户 viewport。
- 「查看全局」控件：显式触发 fit。
- 视图控制通过 `useReactFlow()`（需在 `ReactFlowProvider` 内）；hook 仅返回视图动作函数，由 `WorkflowCanvasControls` 调用。

---

## 7. React Flow 集成

### `ShadcnWorkflowCanvas.tsx`

- 在现有 `ReactFlowProvider` 内创建/消费稳定 Worker engine；移除 `fitView` prop 与 `onInit` fitOnce。
- 接入 `useWorkflowAutoLayout(graph, engine)`，返回 `{ nodes, edges, layoutRevision, fitAll, degraded }`。
- stage 节点：`position = ELK stage 坐标`，`style width/height = ELK 输出`。
- task 节点：`parentId + relativeX/Y = ELK children 坐标`（ELK 输出相对父，见探针确认项），`extent: "parent"`。
- edges：`data: { sections, labelBounds, ... }`；`zIndex: 1`；nodes `zIndex: 2`（D4）。
- 节点尺寸变化经 `useLayoutEffect` + 受控测量上报 hook（D3 校准环）。
- 初次 fit effect 必须等待当前 `layoutRevision` 对应 nodes 已提交，不复用旧 graph bounds。

### `WorkflowSemanticEdge.tsx`

- 删除 `getSmoothStepPath` 与 `sourceX/sourceY/...` 计算路径的全部逻辑。
- 改为：`const d = toSvgPath(data.sections)`；`labelX/labelY` 直接取 `data.labelBounds`。
- 保留状态配色、动画、hover 热区与 `EdgeLabelRenderer`（坐标来源换成 ELK 输出）。
- 生产路径不出现 `getSmoothStepPath`（行为测试断言源码文本）。

### `WorkflowCanvasControls.tsx`

- 「适应全部」改调 hook 的 `fitAll()`；「定位当前」逻辑不变。

---

## 8. 文件边界总表

新增（`renderers/shadcn/workflow/`）：

| 文件 | 职责 | 不含 |
| --- | --- | --- |
| `workflowElkClient.ts` | `?worker` factory、稳定 engine、terminate 生命周期 | graph 适配 |
| `workflowElkPorts.ts` | 端口 id 常量表 + 端口分配纯函数 | 布局算法 |
| `workflowStageSubgraphAdapter.ts` | 阶段 A：按 stageId 分组 + 阶段内 edges 子图 | 布局执行 |
| `workflowStageLayout.ts` | 阶段 A：并行 ELK DOWN 布局 + 阶段 box/本地坐标 | 元图 |
| `workflowLayoutGeometry.ts` | bounds/intersection/compactness 纯函数 | 状态 |
| `workflowLayoutCollision.ts` | 共享碰撞检测（rect/rect、segment/rect，测试与诊断用） | 布局 |
| `workflowLayoutSettling.ts` | design/calibration/settled 状态机纯函数 | 几何 |
| `workflowTwoLevelLayout.ts` | 两级布局编排器 → `WorkflowLayoutResult` | 渲染 |
| `workflowOuterElkGraphAdapter.ts` | 阶段 B：meta nodes + label spacer + 两条 leg 边（FIXED_POS gateway） | 引擎依赖 |
| `workflowOuterElkLayout.ts` | 阶段 B：外层 ELK 消费（阶段坐标/spacer 位置/leg 重组） | 引擎依赖 |
| `workflowElkOptions.ts` | layoutOptions 常量（探针验证后冻结） | 逻辑 |
| `workflowElkLayout.ts` | 兼容/单次 compound 输出消费（遗留测试） | 渲染 |
| `workflowElkEdgePath.ts` | sections → SVG path（纯函数） | 状态 |
| `useWorkflowAutoLayout.ts` | hash / 单飞 / last-good / settling / fit / 尺寸校准上报 | 几何 |
| `workflowElkLayout.test.ts` | 探针 + 几何不变量 + 确定性断言 | Browser Worker 验收 |
| `web/probes/workflow-elk-handshake.html` / `.ts`（T5 后恢复） | Browser Worker handshake 测试入口；仅 test-only probe build（`VIBELUTION_PROBE_BUILD=1`）构建，不进入普通 `npm run build` 产物 | 产品 UI |

调整：

| 文件 | 调整 |
| --- | --- |
| `web/bundleBudget.test.ts` | 增真实 Worker 命名 fixture，锁定专用规则优先于 generic feature rule |
| `ShadcnWorkflowCanvas.tsx` | 组装 hook / React Flow / controls；删 fitView 逻辑 |
| `WorkflowSemanticEdge.tsx` | 只消费 `data.sections/labelBounds` |
| `workflowCanvasLayout.ts` | 生产路径移除；保留兼容导出或测试夹具，不作为 fallback |
| `workflowCanvasTypes.ts` | 增 §5.1 公共类型与 `decisionOutcomeIds`，区分能力和真实 edges |
| `workflowCanvasModel.ts` | D6：真实 outgoing edges → handles；`revise` 不伪造当前 run edge |

VUI 红线：不新建第二套画布 API；更新 `designs/product/workflow.md` 与 `designs/INDEX.md`（如登记项变化）；`elkjs` 只出现在 `renderers/shadcn/workflow/`。

---

## 9. 测试策略

### 9.1 探针测试（T1 第一步，先于 adapter）

`workflowElkLayout.test.ts` 内首组用例（import `elkjs/lib/elk.bundled.js`）：
- §4.2 候选 layoutOptions 全量接受（`knownLayoutOptions()` 与 `elk.layout` 无 warning）；
- 最小 compound 图输出 stage/children 坐标；
- ORTHOGONAL 输出 `sections.startPoint/endPoint`；
- FIXED_ORDER 端口顺序与声明一致；
- extended edge 使用 port id 作为 `sources[]/targets[]` endpoint，所有 endpoint 均可解析；
- edge label 输出坐标非空；
- cross-hierarchy 边坐标坐标系（相对 vs 绝对）；
- multi-section 不连续链输出多个 `M` subpath，不生成虚假连接线。
探针结论写入 `workflowElkOptions.ts` 与本文档 §4.2 修订。

生产 Worker 另做 Browser handshake：真实加载 worker asset、执行最小 layout、终止 Worker 后不再接受请求。bundled 探针不得替代该证据。

### 9.2 RED 基线（T0，对旧实现跑）

在现有输出上断言，全部 RED 于实现代码基线 `7505f0b5605598a67b856028aa163311caac5cdf`：
- `decisionSourceHandle(revise)` 错映射为 `branch`，同时缺少独立的五种 outcome 能力契约；
- adapter 必须保持 definition 的四条当前 run edges，不得为 `revise` 伪造第五条 edge；
- `rerun` 反馈边回折路径穿过非端点节点 → 以现有 layout 输出 + smooth-step 几何段求交断言，失败；
- `promote` / `rollback` 同源同目标路径与标签不可区分，失败；
- stage 标题区与边段相交 → 失败；
- 边 label 与节点 bounds 相交 → 失败。

### 9.3 几何不变量（GREEN，对应 PRD §10.1）

两两 node bounds 不相交；stage bounds 不相交且顺序 1→2→3；非端点节点扩展矩形与 edge segment 不相交；segment 不进入 stage 标题保留区；label bounds 与 node bounds / label bounds 两两不相交；feedback segment 位于阶段主体外通道；同输入同输出（确定性）。

### 9.4 行为测试（PRD §10.2）

- 五种唯一 `decisionOutcomeIds` 与四条当前 run outgoing edge ports 分离；
- `revise` 无 child-run lineage 投影时不创建 edge；
- `promote` / `rollback` 使用独立 port 且保持 parallel edge 可辨识；
- status-only update 不触发二次 `ELK.layout`（hook 测试，`createRoot` + `act`，参照 `useResearchWorkflowRun.test.tsx`）；
- topology/size 变化触发 relayout；
- 旧 promise 不覆盖新 run（注入可控延迟的 layout 替身）；
- StrictMode mount/cleanup/remount 不遗留 Worker，unmount 调用 `terminateWorker()`；
- 初次 fit 一次 / 普通更新不 fit；
- 初次 fit 发生在当前 layoutRevision 的 nodes 进入 React Flow store 之后；
- error 保留 last-good + degraded 标志；
- `WorkflowSemanticEdge.tsx` 生产源码不含 `getSmoothStepPath`。

### 9.5 合约测试

现有 `vuiShadcnRouteContract.test.ts` / `vuiComponentDesignContract.test.ts` 保持通过；Route 仍只消费 `VWorkflowCanvas`。

---

## 10. 实施步骤（T0–T5，文件级）

### T0 · ADR 同步 + RED 基线
- 改 `docs/adr/0006…` §11：删除「不引入 ELK」，改记「动态 compound/feedback 图出现真实遮盖 → ELK Layered，决策见本交接 PRD」；保留单画布/固定拓扑/VUI 边界。
- 新增 §9.2 RED 用例 → 在 HEAD 上跑至 RED。
- 完成证据：RED 输出 + ADR/PRD 无矛盾。

### T1 · elkjs + 探针 + adapter + ports
- `npm install --save-exact elkjs@0.12.0`（web/）；同步 `package-lock.json`、`THIRD_PARTY_COMPONENTS.md`（EPL-2.0 OR GPL-3.0-or-later）、`checkBundleBudget.mjs`（D2）。
- `workflowElkClient.ts` → `workflowElkPorts.ts` → `workflowElkGraphAdapter.ts` → `workflowElkOptions.ts`（探针结论冻结）。
- 探针测试专用化（T1 收尾）：probe 移出普通 `npm run build`（`VIBELUTION_PROBE_BUILD=1` 控制入口，独立 `dist-probe` 产物）；新增仓库内 `npm run check:elk-worker-handshake` 一键 Browser Worker 验收（构建/预算/实机/退出码）；`check:bundle` 过渡期 flag，T4 恢复默认。
- 完成证据：bundled 探针与 Browser Worker handshake 全绿；相同输入生成相同 ELK graph；四条当前 run edge endpoints 均连接真实唯一 port；五种 outcome 能力齐全且未伪造 `revise` edge；真实 worker asset 被专用 budget 规则命中。

### T2 · layout + hook 生命周期
- `workflowElkLayout.ts`（含 D5 双壳封装）+ `useWorkflowAutoLayout.ts` + hash 模块。
- 完成证据：§9.4 行为测试全绿（ELK 调用次数、last-good、过期丢弃、terminate、StrictMode、post-layout fit）。

### T3 · 边 sections / 标签 / 层级
- `workflowElkEdgePath.ts`；`WorkflowSemanticEdge.tsx` 改造；z-index 调整（D4）。
- 完成证据：§9.3 几何不变量全绿；multi-section 不生成虚假连接线；parallel promote/rollback 可辨识；源码不含 `getSmoothStepPath`。

### T4 · 画布集成 + design contract
- `ShadcnWorkflowCanvas.tsx` 接入 hook；`WorkflowCanvasControls` 接 `fitAll`；更新 `designs/product/workflow.md`。
- 完成证据：Route 只导入 VUI 产品 API；三阶段同一 viewport；状态更新不跳变（行为测试）。

### T5 · 验收收尾
- 跑 §13 命令矩阵；清理由 `workflowCanvasLayout.ts` 引出的死代码/夹具；确认无第二个画布入口；按 PRD §13 格式汇报；Launcher 实测按 PRD §11 矩阵执行。

---

## 11. 依赖与授权变更清单

1. `web/package.json`：+ `elkjs@0.12.0` 精确 pin（dependencies；布局输出不得因 patch 更新漂移）。
2. `web/package-lock.json`（npm install 生成）。
3. `THIRD_PARTY_COMPONENTS.md`：登记 elkjs，许可证按包内 `LICENSE.md` 如实写 EPL-2.0 OR GPL-3.0-or-later。
4. `web/scripts/checkBundleBudget.mjs`：D2 新增 known worker chunk 规则。
5. `docs/adr/0006…` §11 布局决策同步（T0）。
6. `docs/prds/README.md`：登记本设计文档；交付后随 PRD 一并迁 archive（docs/README.md 治理）。

## 12. 风险与决策点

| 风险 | 处置 |
| --- | --- |
| ELK 配置 key/取值与候选不符 | 探针先行（§9.1）；按探针结论修订，不猜测交付 |
| edge label 坐标或 FIXED_ORDER 输出不满足预期 | 停止并报告（PRD §12），不启用 50% 估算回退 |
| 跨层级边坐标系不明 | 探针确认后统一归一为绝对坐标（§5.2） |
| Vite Worker factory / CSP / asset 无法通过真实 Browser handshake | 停止并报告；主线程动态 import 是新的架构决策，不静默回退 |
| 尺寸校准触发二次 relayout | 至多一次且收敛（D3）；测试断言校准环收敛 |
| Worker 产物名不匹配候选预算正则 | 按真实 build 产物修订专用规则并保持其位于 generic feature rule 之前 |
| ELK 布局耗时（首轮 worker 初始化） | 首图异步加载提示由调用方（VStateSurface/loading）承载，不阻塞交互 |
| outcome 与当前 run edge 再次混淆 | definition 为唯一当前拓扑；`revise` 只消费真实 child-run lineage 投影 |

## 13. 验证命令矩阵（web/ 下）

```powershell
npm.cmd test -- src/components/vui/renderers/shadcn/workflow/workflowElkLayout.test.ts
npm.cmd test -- bundleBudget.test.ts
npm.cmd test -- src/components/vui/vuiShadcnRouteContract.test.ts
npm.cmd test -- src/components/vui/vuiComponentDesignContract.test.ts
npx.cmd tsc -b --pretty false
npm.cmd run build
npm.cmd run check:bundle
npm.cmd run check:elk-worker-handshake
git diff --check
```

- `check:elk-worker-handshake`：T1 收尾新增的仓库内一键 Browser Worker 验收（probe build → worker asset 存在/唯一/预算断言 → Edge headless 实机 handshake → 结果 POST 校验，任一失败非零退出；无任何可见控制台，全部子进程 `windowsHide`/CREATE_NO_WINDOW）。
- T1–T4 过渡说明：`npm run check:bundle` 带 `--expect-elk-worker=0`（普通 build 无 probe 也无产品 `?worker` 引用，worker asset 由 `check:elk-worker-handshake` 门承担）；T4 产品接入 `workflowElkClient` 后普通 build 自然产出 worker asset，该 flag 移除、`check:bundle` 恢复默认断言。

实机验收（PRD §11）：1440×900 与 1920×1080；无 run / running / waiting_human / blocked / failed / succeeded / 五种 decision outcome 状态；Inspector 开闭、首次全图、聚焦阶段/节点、hover/selected 边、持续状态更新、历史 run 切换。

其中 `revise` 验收的是 child-run lineage 在 Inspector/RunTimeline 中可见且当前 run 画布不伪造 edge；`promote` / `rollback` 验收同源同目标 parallel edges 可区分。

停止条件：凡 PRD §12 任一情形出现，停止并报告；不得以「视觉上差不多」交付。
