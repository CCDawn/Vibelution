# Product — 会话页签分组

## 会话页签分组

### 功能

顶栏会话页签条（`AgentSessionTabStrip`）的分组浏览能力：用户可以新建分组、重命名、
折叠/展开、删除分组，并把会话页签拖入组或拖回「未分组」。分组是**纯前端视图记忆**，
按 Agent 隔离持久化在浏览器里，不写会话数据、不改后端接口。

视觉上，每个有页签的组渲染为一个浅底圆角区块：组头（折叠按钮 + 组名 + 页签数 +
重命名/删除）+ 组内页签；「未分组」区块固定排在最后，只显示组名与数量，不可重命名、
不可删除。条尾有一个新建分组按钮（`FolderPlus`）。

### 适用范围

- **适用**：`AgentSessionTabStrip` 会话页签的横向条目。
- **不适用**：
  - 左侧会话索引/搜索结果/归档列表（仍按现有排序与筛选展示，不感知分组）；
  - 文件页签、terminal / CLI Agent 运行页签、pane dock chips（不参与分组）；
  - 后端会话元数据（`pinnedAtMs`、`archiveState`、`hiddenFromIndex` 与分组正交）。

| 场景 | 选择 |
| --- | --- |
| 用户想减少页签条噪音、按项目/话题归档已打开会话 | 用本分组（视图记忆） |
| 需要跨设备/跨实例一致，或 Agent 需要读取分组 | 升级为会话元数据（另立任务，需改 API） |
| 想永久移除会话 | 仍用 × 两段式确认删除或归档 |

### 使用方式

分组状态不抽 VUI 新组件，沿用「route 组件内部状态 + 纯函数模型」先例
（`agentSessionTabOrder.ts`）：模型与持久化在 `agentSessionTabGroups.ts`，
`AgentSessionTabStrip` 只负责渲染与拖放。

```ts
// web/src/routes/agentSessionTabGroups.ts
const STORAGE_KEY = "vibelution.agentSessionTabGroups.v1";
// Record<agentId, { groups: { id, name, collapsed }[], membership: Record<sessionId, groupId> }>
```

| API | 语义 |
| --- | --- |
| `readAgentSessionTabGroupState(agentId)` | 读取并按 agent 容错解析；损坏/缺失一律回退为空状态 |
| `writeAgentSessionTabGroupState(agentId, state)` | 写回；组清空时删除该 agent 的条目，全空时移除整个键 |
| `createAgentSessionTabGroup(state, name)` | 新建组，返回新状态与 groupId（调用方负责持久化） |
| `renameAgentSessionTabGroup` / `deleteAgentSessionTabGroup` | 重命名；删除时成员回落「未分组」 |
| `setAgentSessionTabGroupCollapsed` | 折叠开关（持久化） |
| `assignSessionToTabGroup(state, sessionId, groupId \| null)` | 文件夹式归属；未知 groupId 为空操作 |
| `pruneSessionTabGroupMembership(state, liveIds)` | 惰性清理已不存在会话的归属 |
| `resolveSessionTabGroupSections(sessions, state)` | 把已排序会话切成分区；空组不占位，未分组最后 |

拖放约定：拖拽源仍是页签上的排序把手（`SESSION_TAB_ORDER_MIME`）。
同组内落在页签上 = 排序；跨组落在页签上或落在任意组区块 = 移动归属。
落点高亮复用 `data-session-tab-group-header` 锚点，不新增第二套拖拽协议。

### 状态与数据语义

- 归属记录在 `sessionId` 上而非「当前第几个页签」：关闭页签后再打开同一会话，
  仍回到原分组。
- 空组不渲染，但组定义保留，因此重新打开成员会话时位置不丢。
- 「未分组」是固定兜底区：不可重命名/删除，成员为空时不渲染。
- 分组只影响顶栏渲染顺序，不改变 `agentSessionTabOrder` 的全局排序语义；
  排序持久化仍写全量顺序，跨组排序被判定为「移动归属」而不写顺序。
- 会话被删除/归档后，`pruneSessionTabGroupMembership` 在 effect 中清理失效归属，
  避免 localStorage 无界增长。

### 可访问性与测试锚点

| 锚点 | 用途 |
| --- | --- |
| `data-session-tab-group="<groupId>"` | 分组区块，兼容测试与拖放落点识别 |
| `data-session-tab-group-ungrouped="true"` | 未分组兜底区标记 |
| `data-session-tab-group-header="<groupId>"` | 组头（折叠/重命名/删除控件所在行） |
| `data-session-tab-group-collapsed="true"` | 折叠态标记 |

组头控件均为 `VIconButton` ghost 变体，带 zh/en `title` 与 `aria-label`；
重命名输入使用 `VNativeInput`，Enter 提交、Escape 取消、失焦提交（空值视为取消）。

### 已知边界（v1 不做）

分组颜色、组内/组间拖拽排序、一个会话多组（标签式）、自动规则分组、跨设备同步。

## 分组颜色

### 功能

每个分组可选一个固定色板色（灰/蓝/绿/黄/橙紫/玫红，共 6 色）。颜色只作强调：
染分组区块左侧 3px 色条 + 浮层色点，不改页签选中环、状态点与文字主色，
避免和 VUI 的选中/状态语义打架。

### 使用方式

色点在组头的悬浮浮层里选，同一浮层兼顾「看成员」和「换颜色」，不额外占顶栏宽度。
再点当前色即清除颜色（回到默认强调色）。

```ts
export const TAB_GROUP_COLORS = ["gray", "blue", "green", "amber", "violet", "rose"] as const;
export type AgentSessionTabGroupColor = (typeof TAB_GROUP_COLORS)[number];

setAgentSessionTabGroupColor(state, groupId, color | null); // null = 清除
sessionTabGroupColorFor(state, groupId); // 渲染读取，未知组回落 null
```

读取时未知颜色降级为默认色而不是报错，所以色板后续增删不会让旧存档失效。
色条与合并高亮写在 `AgentSessionTabStrip.groups.css`：颜色由 `data-group-color`
属性驱动，Tailwind 无法为 data 属性生成配色，故走属性选择器。

## 悬浮下拉预览

### 功能

鼠标停在组名上弹出浮层：上半部是色板，下半部是该组会话列表（标题可点击跳转），
底部一行提示「把页签拖到另一个页签中间即可合并成新分组」。折叠组同样可用浮层预览成员，
不必先展开。

### 使用方式

复用 VUI 既有 `VHoverCard`（Radix hover-card 封装），不新增依赖、不引入第二套浮层协议：

```tsx
<VHoverCard side="bottom" align="start" openDelay={180} closeDelay={140} width="wide"
  content={renderGroupPeek(section)}>
  <span className={styles.agentSessionTabGroupName}>{sectionTitle}</span>
</VHoverCard>
```

浮层内控件仍是 VUI 元素（`VButton`），点击不关闭浮层，允许连续换色。
「未分组」区块没有色板，只列成员。

## 拖拽合并成组

### 功能

把一个页签拖到另一个页签的中间三分之一区域，两者立即合成为一个新分组
（自动命名「分组 N」，可再重命名）。落在左右两侧三分之一仍是排序，
落在组区块任意位置仍是移组。

### 使用方式

落点判定在既有排序判定上加一段中带（dnd-kit 与 Chrome 标签条的经典三区间做法），
不引入拖拽库：

```tsx
const ratio = (event.clientX - bounds.left) / Math.max(1, bounds.width);
if (ratio > 1 / 3 && ratio < 2 / 3) {
  commitMergeDrop(session.id); // 合并：源会话 + 目标会话 -> 新组
  return;
}
// 两侧：沿用 commitTabOrderDrop(session.id, position)
```

```ts
mergeSessionsIntoTabGroup(state, [sourceId, targetId], name); // 少于两个会话为 no-op
```

合并总是新建分组，不扩展目标所在的组——文件夹式语义下一个会话只能属于一个组；
源会话原本所在的组若因此变空，只是不再渲染，组定义保留。
落点反馈用 `data-session-tab-merge-target="true"` + 虚线描边，与排序插入线区分。
