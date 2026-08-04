# Display — Data

## VDenseTable

### 职责
密集数据表。

### 非职责
- 不做服务端分页引擎（调用方）

### 何时使用
- 工具列表、日志行、运维表

### 反冗余
- 禁止再引入第三方 DataGrid 作为默认表

---

## VMetricStrip

### 职责
横向指标条（多 metric）。

### 何时使用
- 页头摘要数字

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 单枚 pill 指标 | `VMetricChip` |
| 极轻状态 | `VStatusStrip` |

---

## VLoadingValue

### 职责
加载中占位值（spinner + label）。

### 何时使用
- 指标未就绪、单元格加载

### 反冗余
- 不要 `VSpinnerText` 平行

---

## VSkeleton

### 职责
shadcn 风格脉冲骨架块（线/块/圆），用于**原位**占位，不替换整块工作台布局。

### 非职责
- 不负责整页 recipe 壳（用 page recipe + 域内 region shell）
- 不负责 spinner 数值位（用 `VLoadingValue`）
- 不替代 settled 后的 empty/error（用 `VStateSurface` / `VEmptyState`）

### 何时使用
- 列表行、卡片体、指标值、按钮槽等几何固定后的数据槽
- 与 `ProgressiveRegionSkeleton` 等 region 壳组合

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 指标单元格转圈 | `VLoadingValue` |
| 无结构的主区冷启动（极少） | `VStateSurface` fill loading |
| 整页路由首次壳 | `RouteLoadingShell` / Chat loading shell |

### API 要点
- `shape`: `line` | `block` | `circle`
- 几何用调用方 `className`（宽高）控制

### 视觉与状态
- `animate-pulse` + 边框色混合填充；`prefers-reduced-motion` 停动画

### 实现落点
- `display/VSkeleton.tsx`

### 反冗余
- 禁止路由再发明第二套 `animate-pulse` 骨架 token；扩展本组件 shape 即可
