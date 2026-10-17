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

### 工作台外壳（用户批准的 A）

AppShell 内的顶级 VUI page / recipe 和已有域壳统一由 `design/workbench-frame.css` 承载外框：灰色 shell 底色、桌面左右与底部 4px 留白（700px 以下 2px）、白色对话表面、12px 外圆角和弱边界。外壳不改变页面内部列表、画布、表单、导航或宽度记忆；内部滚动继续归各 recipe 所有，简单页与用量页保留根滚动。

分栏页的页面根保持灰色，最外层 VSplitWorkspace 的 main / aside 各自使用白色 12px 圆角，sidebar 与顶栏同灰；不得将所有列圈进第二个白色大框。页面分栏显式声明 chrome=workbench，嵌套编辑器使用 embedded，不重复套框。窄屏设置页保留根滚动以容纳竖向排列的表单。

圆角衔接由外层 pane 独占：同尺寸的 Board/Canvas/Agent pane-root 不重复画 8px 内框；灰 sidebar 的 recipe 根不保留矩形边框。页级标题不再套第二张圆角卡片；分栏页的页级工具条与外框同灰，白 pane 内的工具条继续与正文相连；Dense 页的页头和正文共用同一白色基底。共享拖动线使用正文色，贴左右 pane 边界且上下各避开 12px 弧段；保留原命中区、键盘和宽度记忆。

壳的唯一入口是 AppShell / LauncherShell 中常驻的 `VWorkbenchFrame`。页根由 `data-vui-page="surface|workspace|session"` 显式声明；公共页框不再根据域名或 `:has()` 推断内部布局。`VWorkbenchPage` / `VPage` 自动登记，少量已有自定义根使用相同标记。简单滚动页和窄屏设置通过 `data-vui-page-scroll="true"` 保留根滚动。

窗口 pane 的圆角使用 `--vui-workbench-radius`（12px），与内部卡片的 `--vui-radius-panel-soft`（8px）分开；不要修改卡片 token 来对齐窗口。`VSplitWorkspace chrome="workbench"` 绘制公共栏位，默认 `embedded` 保留内层编辑器/画布语义。List/Board/Canvas recipes 自动采用公共栏位；自定义尺寸控制器可用 `VUI_WORKBENCH_PANE_CLASS` / `VUI_WORKBENCH_RAIL_CLASS` / `VUI_WORKBENCH_TOOLBAR_CLASS`，不得为复用外观增加第二个 resize hook。颜色、圆角、边框、裁切和拖杆规则唯一落在 `design/workbench-frame.css`。

`VBoardWorkbenchPage chrome="embedded"` 用于外层仅提供内容宿主、内层 Canvas 自己拥有栏位的场景（科研流程）。内层 recipe 负责白色主区与检查器的独立圆角，外层不截断它们或绘制额外白框。

## VWorkbenchFrame

### 功能

持久的窗口内容宿主（`data-vui="workbench-frame"`），位于 Outlet 和其 Suspense 外。AppShell 与 LauncherShell 是两个实际消费者。children 是路由正文，不缓存、不保留已离开的业务页面，不管理 Session、查询或尺寸持久化。

### 适用范围

用于窗口级路由内容区。内部编辑器与画布沿用所属 recipe，不再增加第二个 Frame。

### 使用方式

| Prop | 说明 |
| --- | --- |
| children | 内容页、加载态或错误态，均沿用相同宿主 |
| flush | 会话 recipe 自己拥有 4px inset 时使用；不重复增加边距 |

Frame 用 memo，消费者提供稳定的 Outlet 元素，以隔离全局状态轮询引起的父级更新；React Router context 和正文自己的状态更新仍正常传播。验证必须同时证明无关父级更新不重绘正文、导航仍切页、正文状态仍更新以及 frame DOM 节点保留。

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
| `toolbar` / `toolbarSlot` | 过滤条 / 指标条 | 已是 strip 用 toolbarSlot。顶栏与工具条包在同一 chrome 行，避免 `header-body` 两行网格把正文挤到页面底部 |
| children / empty / isEmpty | 主区 | 默认 fill；是 `VWorkbenchPage` 的第二行（1fr），从上往下铺内容 |

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
| `hideHeader` | 不渲染重复顶栏 | 外层已命名时使用，不用 CSS 隐藏顶栏；工具条仍保留 |
| toolbar | 列表上过滤条 | 与顶栏包在同一 chrome 行；正文独占第二行，避免按钮被列表覆盖 |

### 几何契约
- `list-detail-chrome` 统一承载顶栏和工具条，`list-detail-body` 承载满高分栏。
- `hideHeader` 且无工具条时复用 `VWorkbenchPage` 的 `stack` 满高布局；不保留空标题行。

### 反冗余
- 禁止手写双栏宽度 localStorage。

### 实现落点
- `layout/VListDetailPage.tsx`

---

## VSettingsFormPage

设置工作台采用已批准的分类直达导航：桌面固定窄 rail，移动端原生分类选择，不出现边界悬浮折叠按钮。右侧统一设置行，文本和数字直接编辑为草稿；仅有未保存内容时显示 footer 保存与取消。选择/开关、语言专用接口、本机主题和字号保持各自的即时生效语义，取消草稿不得撤销已生效值。专业编辑器、动态未知字段和迁移确认仍可达。


设置工作台采用“功能列表 → 原有详情编辑器”导航：主页按分组一项一行展示 VNativeButton，整行可点击；详情保留现有字段、校验和保存语义。配置 URL 的 page/focus 支持深链、浏览器返回和搜索定位，返回列表不丢失父级草稿。模型连接继续复用完整 Provider 工作区，Agent 模型选择不移入设置。全局设置入口保持左下角，不随页内布局迁移。

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

- `chrome` defaults to `workbench`; use `embedded` when a domain composition owns the rail, canvas and inspector panel surfaces. It forwards to VSplitWorkspace, matching VBoardWorkbenchPage, without changing drawer behavior or layout persistence.

侧栏抽屉锚定视口边缘，覆盖居中 Dialog 的位移动画；抽屉内容填满可用高度，长详情在面板内滚动，不得因居中 transform 移出视口。

记忆图谱可设置 `responsive.inspector.narrowPlacement="bottom"`：窄屏阅读栏从底部展开，最高占 64dvh；复用 VDialog 的 Escape、焦点约束与返回焦点。默认仍是侧栏，不改变其他画布页。

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
| canvas / inspector / rail | 区域 | inspector 宽度走 layoutId；科研流程右栏保持挂载，不因空选中拆列 |
| toolbar | 画布顶栏 | 叠在画布之上（`z-20`）；分栏吃剩余高度，不用 `h-full` 盖住顶栏 |
| `responsive` | 可选响应式抽屉能力 | 默认关闭；`enabled` 后 `>=1280` 保持三栏，`900–1279` 保留 rail、Inspector 进入抽屉，`<900` 两侧均为独立抽屉 |
| `responsive.rail` / `responsive.inspector` | 抽屉标题、受控/非受控开关与变更回调 | 抽屉使用 `role="dialog"` + `aria-modal="true"`；打开时焦点进入，Escape/关闭后焦点返回触发按钮，并锁定背景滚动 |
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

个人记忆阅读页组合两层分栏：Agent rail → 记忆文件列表 → 正文阅读。
列表搜索与记录类型筛选共用一行，阅读区只保留「正文 / 来源与变化 / 对话使用记录」。
沿用 `WORKBENCH_LAYOUT_IDS.memory`，pane ids 为 `agent-list` 和 `private-memory-list`；窄屏先列表、点选后阅读并可返回。
正文复用现有安全文本转换，初始化文件明确标识；来源历史及使用证据未提供时展示不可用状态，不从文件时间推断。

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
| resize.collapse | 可选 sidebar / aside 收起 | `placement` 缺省为 `rail`，复用 `PaneCollapseHandle`；标签由消费者提供；收起不覆盖已记忆宽度 |
| `resize.collapse.*.placement` | `rail` / `header`，缺省为 `rail` | `header` 时由页面使用现有 `VIconButton` 并提供受控折叠状态；展开时分隔轨只保留 `PaneResizeHandle`，折叠时移除轨道和侧栏，宽度仍复用 `layoutId` 记忆 |
| `resize.collapse.*.restoreInRail` | 可选 boolean，缺省 false | 配合 `header` 时，展开仅保留调宽分隔线，收起保留 36px 窄轨，展开按钮置于轨道顶部；草稿保持挂载，宽度记忆不变 |
| `resize.collapse.*.collapsed` / `onCollapsedChange` | 受控折叠值与回调必须一起提供；`header` placement 必须受控 | 响应式策略归页面；`rail` 未提供时保持内部手动切换。撤销受控值时沿用 owner 最后接受的状态，不采用尚未接受的点击请求。收起只隐藏列、不卸载草稿；点击请求 owner 更新，不另建宽度记忆 |
| columnsClassName | 固定列模板覆盖 | 默认列宽带 16rem 回退，未注入页面变量时仍保持桌面横向分栏 |

### 共享拖动线的边界对齐

`PaneResizeHandle` 与 `PaneCollapseHandle` 继续共用 1px 可见线和 12px 隐形命中区。布局可设置 `--pane-resize-rule-offset`，同时移动可见线和命中区；`--pane-resize-rule-top` / `--pane-resize-rule-bottom` 将可见线限制在圆角面板边框的直线段，默认均为 0px。外层可用 `--pane-resize-rule-color` 设置中性线色；未设置时保留现有 hover/focus/active 强调色。页面不重新绘制分隔线，也不改变共享键盘、拖动或持久化协议。

栏级收起按钮统一使用 `VIconButton variant="ghost"`，放在所属栏顶栏 actions 的最右端。自定义布局的 `PaneCollapseHandle` 使用 `togglePlacement="header"`：展开时不在分隔条重复渲染收起按钮，收起后的恢复入口置顶并占用独立窄轨；grid 容器须让此轨道随内容宽度分配空间。窄屏隐藏分隔轨时，顶栏收起入口同步隐藏，或由页面提供始终可用的展开入口。正文、树节点和分组的折叠不受此约定影响。

### 实现落点
- `layout/VSplitWorkspace.tsx` + `usePersistedPaneResize`
