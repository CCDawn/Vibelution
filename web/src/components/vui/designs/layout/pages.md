# Layout — Page recipes & page roots

## 选型总表

| 布局需求 | Recipe | 设计一句话 |
| --- | --- | --- |
| 运维表/队列/工具 | `VDenseOpsPage` | 顶栏 + 可选工具条 + 满高 body |
| 左列表右详情 | `VListDetailPage` | 主从选中，可拖宽度 |
| 设置+底栏保存 | `VSettingsFormPage` | 滚动表单 + 粘性 footer |
| 左 rail + 看板 | `VBoardWorkbenchPage` | 团队看板类 |
| 画布+检查器 | `VCanvasWorkbenchPage` | 图/流程/画布 |
| 多轨（模式切换）+ 满高主区 | `VTrackWorkbenchPage` | Evolution 监督/自进化等 |
| 会话双轨（索引+会话+状态） | `VSessionWorkbenchPage` | Chat 等 session 工作台 |
| 仅分栏积木 | `VSplitWorkspace` | 被 recipe 组合 |
| 底层工作台 section | `VWorkbenchPage` | recipe 内部根 / 例外宿主 |
| 最简 section | `VPage` | 非满高最简页 |

共享几何 class：`layout/pageRecipeClasses.ts`。

---

## VPage

### 功能
最简页面 section 根（`data-vui="page"`），不强制满高工作台网格。

### 适用范围
- **适用**：被 `VSettingsFormPage` 等组合；极简单页。
- **不适用**：工作台满高 → `VWorkbenchPage` fill 或 dense/list/track recipe。

| 场景 | 选择 |
| --- | --- |
| 设置表单根 | `VPage`（经 Settings recipe） |
| 满高工作台 | `VWorkbenchPage` / 对应 recipe |

### 使用方式
```tsx
import { VPage } from "@/components/vui";

<VPage ariaLabel="简单页">{children}</VPage>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| ariaLabel / className | 地标与域样式 | 不自带 header |

### 非职责
- 不提供满高 fill / 分栏。

### 实现落点
- `layout/VPage.tsx`

---

## VWorkbenchPage

### 功能
工作台页面根 section：可选 `fill` 视口网格（header auto + body 1fr），是各 page recipe 的底层宿主。

### 适用范围
- **适用**：recipe 内部根；多轨/自定义 rail 等尚无专用 recipe 时的临时宿主（应尽快升到 Track/Dense/List）。
- **不适用**：直接堆业务字段而不走 recipe；左列表右详情应 `VListDetailPage`。

| 场景 | 选择 |
| --- | --- |
| Dense/List/Board 内部 | `VWorkbenchPage`（由 recipe 封装） |
| 路由直接用 | 仅例外；优先专用 recipe |

### 使用方式
```tsx
import { VWorkbenchPage, VRouteHeader } from "@/components/vui";

<VWorkbenchPage fill ariaLabel="工作台" ref={layoutRef}>
  <VRouteHeader title="标题" actions={...} />
  <div className="min-h-0 flex-1">{/* 主区 */}</div>
</VWorkbenchPage>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| `fill` | 满高网格 | 工作台默认 true（经 recipe） |
| `ariaLabel` | 地标 | 与路由标题一致 |
| ref | forwardRef | 可挂 pane resize 根 |

### 非职责
- 不规定左中右内容列。

### 实现落点
- `layout/VWorkbenchPage.tsx`

---

## VDenseOpsPage

### 功能
运维/队列页 recipe：路由顶栏 + 可选 toolbar + 满高 body（或空态）。

### 适用范围
- **适用**：Git / Logs / Tools / Usage / Reset / Pet / Memory 外层 / Launcher 等运维面。
- **不适用**：主从列表选中 → `VListDetailPage`；多轨模式切换壳 → `VTrackWorkbenchPage`。

| 场景 | 选择 |
| --- | --- |
| 日志/工具/Git | `VDenseOpsPage` |
| Skills 主从 | `VListDetailPage` |

### 使用方式
```tsx
import { VDenseOpsPage } from "@/components/vui";

<VDenseOpsPage
  ariaLabel="日志"
  eyebrow="Ops"
  title="日志"
  meta="只读"
  actions={<VIconButton label="刷新" ... />}
  toolbar={filters}
  data-vui-domain-recipe="logs-workbench"
>
  {tableOrWorkspace}
</VDenseOpsPage>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| title / eyebrow / meta / actions | 顶栏 | domain 用 `data-vui-domain-recipe` |
| `hideHeader` | 不渲染顶栏 | 窗口标题已能识别该页时使用，例如桌面 Launcher |
| `toolbar` / `toolbarSlot` | 过滤条 / 指标条 | 已是 strip 用 toolbarSlot |
| children / empty / isEmpty | 主区 | 默认 fill |

### 反冗余
- 不要 `VOpsPage` / `VTablePage` 平行。

### 实现落点
- `layout/VDenseOpsPage.tsx`

---

## VListDetailPage

### 功能
主从页 recipe：顶栏 + 可选 toolbar + 左列表 / 主详情 / 可选 aside，支持 layoutId 宽度记忆。

### 适用范围
- **适用**：Skills、PromptTemplates、Kernel、审查队列、Agent 工作台主从。
- **不适用**：纯运维表 → `VDenseOpsPage`；看板 rail → `VBoardWorkbenchPage`。

| 场景 | 选择 |
| --- | --- |
| 左队列右详情 | `VListDetailPage` |
| 三列 filter+list+detail | list 槽塞筛选，或未来 Filter 变体 |

### 使用方式
```tsx
import { VListDetailPage } from "@/components/vui";

<VListDetailPage
  title="技能"
  list={<SkillList />}
  detail={<SkillDetail />}
  layoutId={WORKBENCH_LAYOUT_IDS.skills}
  data-vui-domain-recipe="skills-workbench"
/>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| list / detail / aside | 列内容 | 空选中用 `VEmptyState` |
| layoutId / resize | 拖拽记忆 | 只用 registry id |
| toolbar | 列表上过滤条 | 可选 |

### 反冗余
- 禁止手写双栏宽度 localStorage。

### 实现落点
- `layout/VListDetailPage.tsx`

---

## VSettingsFormPage

### 功能
设置页 recipe：顶栏 + 可滚动表单体 + 粘性底栏（保存等）。

### 适用范围
- **适用**：Config 等配置表单。
- **不适用**：满高分栏工作台 → Workbench recipes。

| 场景 | 选择 |
| --- | --- |
| 配置保存页 | `VSettingsFormPage` |
| 运维队列 | `VDenseOpsPage` |

### 使用方式
```tsx
import { VSettingsFormPage } from "@/components/vui";

<VSettingsFormPage title="配置" footer={<VButton>保存</VButton>}>
  <VFieldRow label="...">...</VFieldRow>
</VSettingsFormPage>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| children | 滚动表单 | FieldRow 包字段 |
| footer | 粘性操作 | 主保存在 footer |

### 实现落点
- `layout/VSettingsFormPage.tsx`（内部 `VPage`）

---

## VBoardWorkbenchPage

### 功能
左 rail + 工具条 + 看板主区（可选 inspector）的工作台 recipe。

### 适用范围
- **适用**：Teams 看板；未来同类 board。
- **不适用**：主从选中列表 → `VListDetailPage`；自由画布 → `VCanvasWorkbenchPage`。

| 场景 | 选择 |
| --- | --- |
| 团队看板 | `VBoardWorkbenchPage` |
| 流程画布 | `VCanvasWorkbenchPage` |

### 使用方式
```tsx
import { VBoardWorkbenchPage } from "@/components/vui";

<VBoardWorkbenchPage
  title="团队"
  rail={<TeamList />}
  board={<Kanban />}
  layoutId={WORKBENCH_LAYOUT_IDS.teams}
  domainRecipe="teams-organization-workbench"
/>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| rail / board / aside | 列 | rail 可拖宽度 |
| domainRecipe | 域标记 | 与 page recipe 并存 |
| hideHeader | 壳已有标题时 | 少用 |

### 反冗余
- 与 ListDetail：board 强调工作台内容而非 master-detail 选中。

### 实现落点
- `layout/VBoardWorkbenchPage.tsx`

---

## VCanvasWorkbenchPage

### 功能
可选 rail + 画布主区 + inspector 的图/流程工作台 recipe。

### 适用范围
- **适用**：Teams 画布、组织图、记忆图、流程画布。
- **不适用**：看板列 → `VBoardWorkbenchPage`；禁止第三种「graph page」。

| 场景 | 选择 |
| --- | --- |
| 流程画布 | `VCanvasWorkbenchPage` |
| 看板 | `VBoardWorkbenchPage` |

### 使用方式
```tsx
import { VCanvasWorkbenchPage } from "@/components/vui";

<VCanvasWorkbenchPage
  title="流程"
  canvas={<FlowCanvas />}
  inspector={<NodeInspector />}
  layoutId={WORKBENCH_LAYOUT_IDS.researchFlow}
/>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| canvas / inspector / rail | 区域 | inspector 宽度走 layoutId |
| domainRecipe | 域标记 | 合约用 |

### 反冗余
- 与 Board 互斥选型。

### 实现落点
- `layout/VCanvasWorkbenchPage.tsx`

---

## VSessionWorkbenchPage

### 功能
会话工作台：可选路由顶栏 + **indexRail / session / statusRail** 三槽 + resize 句柄 + overlay；承载 Chat 双轨几何 host。

### 适用范围
- **适用**：Chat 会话工作台；未来同类 session 双/三栏。
- **不适用**：主从列表选中 → `VListDetailPage`；运维表 → `VDenseOpsPage`；模式轨 multi-rail → `VTrackWorkbenchPage`。

| 场景 | 选择 |
| --- | --- |
| Chat 编码/会话 | `VSessionWorkbenchPage`（经 `ChatSessionWorkbenchShell`） |
| Evolution 多轨 | `VTrackWorkbenchPage` |

### 使用方式
```tsx
import { VSessionWorkbenchPage } from "@/components/vui";

<VSessionWorkbenchPage
  hostAsRoot
  layoutRef={layoutRef}
  className={gridClassName}
  hostStyle={cssVars}
  domainRecipe="chat-session-workbench"
  layoutId={WORKBENCH_LAYOUT_IDS.chat}
  overlay={backdrop}
  statusRail={<StatusRail />}
  leftResizeHandle={<PaneCollapseHandle side="left" ... />}
  session={<CenterConversation />}
  rightResizeHandle={<PaneCollapseHandle side="right" ... />}
  indexRail={<ConversationIndex />}
>
  {dialogs}
</VSessionWorkbenchPage>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| `hostAsRoot` | 默认 true：host 即 page 根（Chat 网格） | false 时外包 `VWorkbenchPage` + 可选 header |
| `session` / `indexRail` / `statusRail` | 三主区 | 宽度记忆走 layoutId + 域 hook |
| `layoutRef` / `layoutId` | 几何 host 与持久化 id | Chat 双写仍在 `useChatWorkbenchLayout` |
| `domainRecipe` | 域标记 | 如 `chat-session-workbench` |
| children | 对话框等 host 级内容 | 勿塞业务三栏 |

### 非职责
- 不实现双写宽度 / 响应式 collapse 算法（route hook）。
- 不替代 list-detail 主从选中。

### 实现落点
- `layout/VSessionWorkbenchPage.tsx`
- Chat 适配：`routes/chat/ChatSessionWorkbenchShell.tsx`

### 反冗余
- 禁止再手写 Chat 顶层 grid host；禁止平行 `VChatPage`。

---

## VTrackWorkbenchPage

### 功能
多 track（模式轨）工作台：可选路由顶栏 + 可选 track chrome + 满高主区 body。
用于 Evolution 等「监督 / 自进化」多模式切换，主区常为 **自定义 multi-rail**（不硬塞 ListDetail / DenseOps）。

### 适用范围
- **适用**：Evolution 双轨；「模式轨 + 满高 domain 工作区」且不是标准 list-detail / dense table。
- **不适用**：运维表 → `VDenseOpsPage`；左列表右详情 → `VListDetailPage`；看板 → `VBoardWorkbenchPage`。

| 场景 | 选择 |
| --- | --- |
| Evolution 监督/自进化 | `VTrackWorkbenchPage` |
| Git/Logs 运维 | `VDenseOpsPage` |
| Skills 主从 | `VListDetailPage` |

### 使用方式
```tsx
import { VTrackWorkbenchPage, VTabs } from "@/components/vui";

<VTrackWorkbenchPage
  fill
  ariaLabel={title}
  domainRecipe="evolution-multi-rail"
  data-vui-recipe="evolution-workbench"
  data-vui-layout-id={WORKBENCH_LAYOUT_IDS.evolution}
  header={
    showHeader
      ? {
          eyebrow,
          title,
          meta,
          hideIntro: focusMode,
          actions: (
            <>
              <VTabs density="compact" value={track} onValueChange={setTrack} items={trackItems} />
              {extraControls}
            </>
          ),
        }
      : null
  }
>
  {track === "self" ? <SelfTrack /> : <SupervisedMultiRail />}
</VTrackWorkbenchPage>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| `header` | 可选；`null` 表示无顶栏 | 支持 `hideIntro` 紧凑控制条 |
| `trackChrome` | 可选；顶栏与 body 之间的轨带 | tabs 已在 header.actions 时可省略 |
| children / bodyClassName | 满高主区 | multi-rail 由域 grid + layoutId 负责 |
| `domainRecipe` | 域标记 | 与 `data-vui-recipe` 域覆盖并存 |
| ref | forwardRef → **body div** | 可挂 `usePersistedPaneResize` layoutRef（`HTMLDivElement`） |

### 非职责
- 不内建 multi-rail 列算法（collapse / 多列仍属 domain + `usePersistedPaneResize`）。
- 不替代 `VTabs`（track 切换用 VTabs 填入 header/trackChrome）。

### 实现落点
- `layout/VTrackWorkbenchPage.tsx` → 内部 `VWorkbenchPage` + `VRouteHeader`

### 反冗余
- 与 Session（拟）：track 是 **模式切换**，不是会话流。
- 禁止再为 Evolution 手写 page 根 div / 裸 `VWorkbenchPage` 堆 header。

---

## VSplitWorkspace

### 功能
底层可拖分栏（sidebar / main / aside），供 recipe 或过渡期 domain 壳组合。

### 适用范围
- **适用**：recipe 内部；Memory 等已挂 layoutId 的分栏。
- **不适用**：已有匹配 page recipe 时不要裸用代替整页。

| 场景 | 选择 |
| --- | --- |
| ListDetail 内部 | 由 recipe 封装 |
| 过渡 domain 三分栏 | `VSplitWorkspace` + layoutId |

### 使用方式
```tsx
import { VSplitWorkspace } from "@/components/vui";

<VSplitWorkspace
  sidebar={list}
  main={detail}
  resize={{
    layoutId: WORKBENCH_LAYOUT_IDS.memory,
    enabled: true,
    collapse: {
      sidebar: {
        separatorLabel: "调整列表栏宽度",
        collapseLabel: "收起列表栏",
        expandLabel: "展开列表栏",
      },
    },
  }}
/>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| sidebar / main / aside | 列 | 空列勿占宽 |
| resize.layoutId | 宽度记忆 | 仅 registry id |
| resize.collapse | 可选 sidebar / aside 收起 | 复用 `PaneCollapseHandle`；标签由消费者提供；收起不覆盖已记忆宽度 |
| columnsClassName | 固定列模板覆盖 | 默认列宽带 16rem 回退，未注入页面变量时仍保持桌面横向分栏 |

### 实现落点
- `layout/VSplitWorkspace.tsx` + `usePersistedPaneResize`
