# Product — Challenge token usage

## ChallengeTokenUsageStrip

### 功能

在挑战杯总览和单题详情展示只读 token/调用次数聚合，无可信单价时固定显示「token 计」，不渲染臆造金额。

### 适用范围

- **适用**：Program 总览指标条、单题详情折叠区。
- **不适用**：计费对账、套餐价格、usage ledger 全局页。

### 使用方式

- 使用 `VMetricStrip` 展示 token 数与调用次数。
- `priced !== true` 时禁止渲染金额字段。
- 异常黄条只渲染服务端 `anomaly.message`；数据不足时服务端不给 anomaly，前端保持静默。
