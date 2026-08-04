# Aesthetic — Dense workbench atoms

> 这些是 **工作台美学原子**，不是第二套 primitive。
> 交互仍优先 `VButton`/`VNative*`；此处补边框底色与行密度。

## VDenseToolbar

### 职责
带边框/底色的密集工具条外观。

### 何时使用
- 需要「条带」视觉的过滤工具条

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 只要 role=toolbar 容器 | `VToolbar` |

---

## VDenseRow

### 职责
密集列表行容器。

---

## VEmbeddedPanel

### 职责
嵌在主面板内的浅表面块。

### 反冗余
- 优先 `VSurface tone="row"`；本组件保留美学预设

---

## VMetricChip

### 职责
label+value 的指标胶囊。

### 反冗余
- 与 `VChip`：本组件强调键值；Chip 强调标签

---

## VStateRow

### 职责
带 tone 的状态行。

---

## VStatusChip

### 职责
工作台状态小片（tone 映射）。

### 反冗余
- 与 `VChip`：状态语义优先本组件
