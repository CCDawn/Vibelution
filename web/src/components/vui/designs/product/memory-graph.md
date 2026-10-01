# 记忆图谱领域画布

## VMemoryGraphCanvas

### 功能

将服务端已授权的记忆与知识关系投影为可旋转、平移、缩放、选择节点与关系的主题簇画布。落实用户确认的三维星域预览：节点在 XYZ 三轴分布、不同主题由彩色体积星云包裹，节点使用柔和哑光材质；按缩放显示标签、选中邻域突出方向。

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

### 非职责

不取数、不写入记忆、不审核、不扩大 ACL、不生成推断关系。渲染聚类是展示分组，不代表服务端事实或访问权限。搜索和邻域展开只在返回的 payload 内执行，截断提示由页面展示。

### 视觉与状态

页面顶部复用 VNativeSelect 显示紧凑的「读取身份」与「团队范围」，不增加范围卡片。
读取身份来自现有 Agent 目录；团队选项仅来自服务端已授权的团队节点。
切换身份重置团队范围、搜索、节点筛选和详情，切换团队也清空选中节点；图谱 URL 保留范围，刷新后仍可读取。
当前身份没有可见知识与私有记忆时，在画布上方用一行提示说明范围，保留结构节点。
普通知识与当前 Agent 的私有文件使用显式 include 接入；私有正文仅在选中节点后读取，遵循原 owner 边界。

遵循产品主题变量；星云复用已批准预览的有限步数体积噪声，按需渲染、不引入持续动画；资源随画布卸载释放。远景显示主题，近景逐步增加节点标签，文字避让节点及其他标签。选中突出一跳关系，关系名称保留服务端原值。画布空态、加载态、WebGL失败列表及键盘选择保持可用。详情默认收起，选点展开；窄屏复用 VCanvasWorkbenchPage 的受控 drawer，以保留产品级焦点和键盘约定。

### 实现落点

领域 API：`product/memory/VMemoryGraphCanvas.tsx`；交互与 Three 实现：`renderers/shadcn/memory/`；页面：`routes/MemoryGraphViewPanel.tsx`。Three 投影坐标与 canvas 绘制为受控 inline 几何例外，其他界面使用 Tailwind 与 VUI。

### 反冗余

替换旧 route 自建 Three 交互，不保留第二套正式图谱引擎。隔离 example 是视觉方案记录，不接正式 API。页面继续复用 VCanvasWorkbenchPage、VButton、VNativeInput、VSurface 与 WORKBENCH_LAYOUT_IDS.memory。
