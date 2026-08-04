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

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 仅一行错误文案 | `VErrorSummary` |
| 列表永久空 | `VEmptyState` |

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
