# 记忆图谱领域画布

## VMemoryGraphCanvas

### 功能

将服务端已授权的记忆与知识关系投影为可旋转、平移、缩放、选择节点与关系的主题簇画布。平台知识图谱使用用户于 2026-10-16 确认的宇宙预览：真实 XYZ 节点、端点之间的细直线、静态分层恒星与淡银河、局部深色工作区；按缩放显示稳定标签，选中邻域突出方向。其他调用方保留原有主题星云外观。

### 适用范围

用于记忆库的全局图谱及带 teamId 的团队知识图谱（共用 MemoryRoute 入口）。这是取代旧 MemoryGraphCanvas 的领域组件，不是新增通用按钮或布局 primitive。流程执行拓扑继续使用 VWorkflowCanvas；普通列表使用 VListDetailPage。

### 使用方式

```tsx
import { VMemoryGraphCanvas } from "../components/vui";

<VMemoryGraphCanvas nodes={nodes} edges={edges} selectedNodeId={selectedId}
  onSelectNode={setSelectedId} fallbackText="画布不可用，请使用节点列表"
  flat={false} onSelectEdge={setEdgeId} />
```

输入保留 MemoryKnowledgeGraphNode / Edge DTO 的身份与方向，节点详情与来源读取归 route 的现有 query。`flat` 将节点与关系投影至 z=0 并以左拖平移；3D 恢复空间坐标，左拖全方位环绕、右拖平移；`focusToken` 显式触发聚焦；普通 selection 不重建引擎或重置镜头；`highlightIds` 标记搜索命中。

`mode` 默认为 `galaxy`，保持记忆库与团队图谱现有行为；平台知识图谱可传 `mode="relations"` 在同一 facade 中切换为定向关系阅读。`selectedEdgeId` 控制关系选择，`onSelectEdge` 返回原 DTO 的关系 ID。所有新增节点与关系操作都由 `ShadcnButton` 实现，SVG 本身不接收点击。

`appearance="cosmos"` 由平台知识图谱显式启用，在同一 Three 引擎与 VUI facade 内应用已批准视觉；没有新图谱框架或依赖。平台总览显示当前返回的主题、正式知识和可见关系的端点，保留节点、来源和关系的真实 ID；共享来源只绘制一次。默认知识关联视图可同时显示来源连线，通过「来源连线」开关独立关闭来源上下文；证据、归属筛选、待确认与入库审核选项仍受原规则控制。进入主题保持 3D，用户可切换「关系图」沿用二维关系阅读。点知识显示原详情，点主题缩小到对应范围；切换 3D/关系图不更改读取权限或写入事实。

宇宙背景仅是装饰，不参与 Raycaster、不加入节点计数，随镜头产生视差；无自主闪烁或持续背景循环。背景、柔光和宽线资源进入原引擎的几何/材质 registry，卸载时统一释放。关系只连接实际返回的两端 XYZ，标签与方向箭头使用相同路径；候选关系使用虚线及「待确认」文字。主题根位于真实分区中心，来源位置由其实际知识邻居决定，不使用示例名称、ID 后缀或固定条目数。

「侧视」「俯视」「自动环绕」复用 OrbitControls 与按需绘制；环绕默认关闭，手动拖动、缩放、选点会暂停。标签页隐藏时暂停运动，系统切换 reduced-motion 时停止自动环绕。拖动、惯性和镜头聚焦期间固定标签身份和锚点偏移，相机稳定 180ms 后再避让；拖动标签不会被误判为点击。摘要留在详情面板，hover 不改变标签高度。WebGL 失败仍有可键盘操作的真实节点列表。

`groupByTopic` 默认为 `false`；平台星域显式启用后，非空 `metadata.topicId` 优先于节点类型，`metadata.topicLabel` 提供中文主题名。缺失主题的节点继续使用既有类型分组；稳定主题 key 决定色彩与星云相位，payload 重排不改变布局。聚合 `type="topic"` 节点的 label 包含主题名与数量，`metadata.memberCount` 决定主题体积；即使主题只有一个聚合节点，也绘制体积星云和星点。聚合主题使用原引擎的可键盘选择 nodeLabel，点击区域至少 44px，主题根优先常显；此投影标签沿用既有 DOM 图表几何例外。

### 非职责

不取数、不写入记忆、不审核、不扩大 ACL、不生成推断关系。渲染聚类是展示分组，不代表服务端事实或访问权限。搜索和邻域展开只在返回的 payload 内执行，截断提示由页面展示。

### 视觉与状态

页面顶部复用 VNativeSelect 显示紧凑的「读取身份」与「团队范围」，不增加范围卡片。
读取身份来自现有 Agent 目录；团队选项仅来自服务端已授权的团队节点。
切换身份重置团队范围、搜索、节点筛选和详情，切换团队也清空选中节点；图谱 URL 保留范围，刷新后仍可读取。
当前身份没有可见知识与私有记忆时，在画布上方用一行提示说明范围，保留结构节点。
普通知识与当前 Agent 的私有文件使用显式 include 接入；私有正文仅在选中节点后读取，遵循原 owner 边界。

普通外观遵循产品主题变量，星云采用有限步数体积噪声。平台宇宙外观的深色变量仅作用于本工作区，不更改全局主题。两种外观均按需渲染并在卸载时释放资源。远景显示主题，近景逐步增加节点标签，文字避让节点及其他标签。选中突出一跳关系，关系名称保留服务端原值。画布空态、加载态、WebGL失败列表及键盘选择保持可用。详情默认收起，选点展开；窄屏复用 VCanvasWorkbenchPage 的受控 drawer，以保留产品级焦点和键盘约定。

普通外观的关系线使用主题前景色而非面板边框色；浅色与深色的默认线透明度分别为 0.58 与 0.42。宇宙外观使用克制的冷灰线色与像素线宽，区分知识、来源和跨主题关系；选中、高亮与无关关系保持层级。主题切换保留当前选择。星空线性颜色经 Three.js 输出颜色空间转换，保持背景与可选知识实体的清楚区别。

关系模式使用常驻中文关系按钮与箭头表达 source → target，优先显示 DTO 的中文 label，已知类型使用中文映射，未知类型显示「关联（type）」。`edge.metadata.status="candidate"` 使用虚线与「待确认」文字。画布宽度小于 660px、节点超过 12 个、文字或关系密度无法清晰排布时，自动使用完整可滚动的关系列表；列表仍保留全部节点按钮和关系解释入口。缺失端点的关系不渲染，以免显示未授权或不存在的节点；空节点与空关系各有明确提示。

### 实现落点

拖动热路径使用 GPU 批量绘制：同形状、大小与主题颜色的节点共用实例批次；宇宙外观的直线使用已安装 Three.js 的 LineSegments2/LineMaterial 按关系种类批绘，普通外观保留 LineSegments。选中关系方向箭头只提交可见实例。实例透明度保持节点选择、邻域与搜索高亮语义；较大的点击命中球保留空间位置和选中缩放，仅用于 Raycaster，不进入渲染场景。

标签尺寸、候选顺序及状态按输入变化缓存，读尺寸与写位置分批处理；字体、主题几何、宽度以及摘要展开会失效缓存。候选保留选中优先与星域公平顺序，遍历全部视口内节点直到填满显示预算，避免密集星域因候选截断丢失标签；选中标签无空位时仍保留可见位置。字体加载、标签 hover/focus 可以唤醒按需画布，卸载时释放监听。图谱仍使用原 VUI product API 与同一 renderer，不新增第二套图谱实现。

领域 API：`product/memory/VMemoryGraphCanvas.tsx`；交互与 Three 实现：`renderers/shadcn/memory/`；页面：`routes/MemoryGraphViewPanel.tsx`。Three 投影坐标与 canvas 绘制为受控 inline 几何例外，其他界面使用 Tailwind 与 VUI。

关系 renderer 为 `renderers/shadcn/memory/ShadcnMemoryRelationGraph.tsx`。节点及关系按钮的位置与 SVG 路径是同一受控图表几何例外；页面不导入 renderer、不复制 Three 或 NebulaField。

平台全景的主题名称来自可读内容分类；按标题关键词分组时明确展示依据，不将分组当作事实关系。主题归属线不进入「知识关联」，入库审核线在「证据关系」中默认隐藏，可显式勾选查看。没有内容关系时说明原因并显示收录知识，不补造连线。关系列表直接展示中文节点类型、完整标题与最多三行摘要；节点编号和来源哈希收在默认关闭的技术详情中，知识归属使用显示名称。

### 反冗余

替换旧 route 自建 Three 交互，不保留第二套正式图谱引擎。隔离 example 是视觉方案记录，不接正式 API。页面继续复用 VCanvasWorkbenchPage、VButton、VNativeInput、VSurface 与 WORKBENCH_LAYOUT_IDS.memory。
