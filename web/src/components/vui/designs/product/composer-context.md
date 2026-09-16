# Composer context usage

## ComposerContextRing

### 功能

输入区的上下文用量入口，按“容量、主要来源、明细”展示最近一次上下文数据。

### 适用范围

用于会话 composer 的轻量概览。使用现有 `VButton` 和 `VPopover`，不新增另一套浮层或缓存事实源。

### 使用方式

`ComposerContextRing` 接收 `model`、`lang`、`sessionId` 和可选 `onOpenDetail`。模型由现有上下文组成与供应商用量生成；`sessionId` 改变时重置整个浮层状态。

- 主条分母为模型窗口上限，不是已用内容总量；未知上限不显示 0%。容量与分项统一读取 lastContextComposition，禁止将缓存 calibratedSegments 混入上下文来源；分段独立估算可能与总量略有差异。
- 提示、运行规范和项目规则合并为一组，历史单列，其余来源保留在其他内容中。明细仍保留每个来源的名称、数量、比例和可用预览。
- 缓存只有 `provider_usage` 且已观测时展示命中比例；`computed_hit` 等本地估算不参与该比例。供应商未返回时明确显示无数据。
- 完整缓存诊断沿用原回调，从第二层打开。组明细比例以列出内容为分母，不能解读为容量比例。
- 浮层约 324px，受视口限制；明细可滚动，深浅色使用共享语义 token，键盘、Escape、点击外部由 VPopover 负责。

### 实现落点与验证

`components/conversation/ComposerContextRing.tsx` 与 `routes/chat/composerContextModel.ts`。
回归覆盖真实 0、未知容量、估算缓存不冒充实测、来源展开及切换会话收起。
