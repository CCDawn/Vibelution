# Layout — Structure

## VSection

### 职责
带可选标题/提示的内容分区。

### 何时使用
- 设置页卡片区、详情分段

### 反冗余
- 不要 `VCardSection` 平行

---

## VStack

### 职责
纵向 flex 堆叠。

### 非职责
- 不做表面样式（外包 `VSurface`）

---

## VHStack

### 职责
横向 flex 堆叠。

---

## VEmptyState

### 职责
空态：标题、说明、操作。

### 何时使用
- 列表无数据、未选择详情

### 视觉
- 默认居中；`align="start"` 用于工作台左对齐域

---

## VStateSurface

### 职责
加载/错误/不可用/空 的状态面（可 skeleton、facts）。

### 何时使用
- 冷加载、失败恢复、占位
- **工作台主区（board/canvas/list-detail main）加载**：必须 `fill`，避免「一行字 + 大片空白」

### `fill`
- `fill`：占满父级 flex/grid 区域（`flex-1` + 最小高度 + 居中内容）
- loading 且未指定 `skeletonLines` 时：`fill` 默认 3 条骨架，非 fill 默认 2 条
- 父级请用 `VUI_REGION_STATE_HOST_CLASS` 或已有 `flex-1 min-h-0` 链

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 仅一行错误文案 | `VErrorSummary` |
| 列表永久空 | `VEmptyState` |
| 主区加载仍用 `styles.empty` 一行字 | **禁止** — 改本组件 `fill` |

---

## VErrorSummary

### 职责
错误摘要展示（可多条）。

### 何时使用
- 表单/操作失败汇总

---

## VEntityList

### 职责
简单实体列表渲染（id/label + renderItem）。

### 何时使用
- 轻量列表；重表格用 `VDenseTable`
