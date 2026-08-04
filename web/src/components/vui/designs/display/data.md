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
