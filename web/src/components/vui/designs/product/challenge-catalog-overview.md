# Product — Challenge catalog overview

## ChallengeCatalogOverview

### 功能

在挑战杯 Program 总览中提供 GitHub Checks 式 125 题批次列表：一屏看总进度与失败项，失败行展开显示服务端 blocker 文案，单行继续/重试只调用已有 DEV fixture 命令。

### 适用范围

- **适用**：`ChallengeMvpProgressPanel` 内的 125 题批量总览。
- **不适用**：DEV readiness 门禁控制面、单题详情、提交包检查。

### 使用方式

- 页面壳使用 `VListDetailPage`，状态用 `VStatusChip`，计数用 `VMetricStrip`，列表用 `VDenseTable`。
- 排序：失败置顶，进行中次之，其余按题号；可用 `VSelect` 按状态过滤。
- 阻塞原因只渲染服务端 `blocker.message` / `remediationLabel`，禁止按 `code` 猜测文案。
- 单行重试调用既有 `runChallengeCupDevBatch(planId, { retryFailed: true })`，不新开批量启动语义。
