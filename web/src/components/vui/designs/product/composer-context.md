# Composer context usage

## ComposerCacheIndicator

### 功能

输入框旁以图标与百分比显示本会话累计缓存命中率；点开只显示「本会话」「最近一次」两行。

### 适用范围

普通聊天和 Launcher 个人助理共用同一组件。普通聊天读取当前 Session 的 usage summary；个人助理通过固定身份原生桥读取自己的隔离账本。Companion 和金融专用 composer 沿用既有入口边界。

### 使用方式

传入 `sessionId`、`lang` 与 `ComposerCacheUsageModel`。`useComposerCacheUsage` 根据现有 detail 的调用时间与状态变化刷新，不增加独立轮询。切换 Session 时重置浮层；查询按来源、Agent、Session 隔离，过期读取不可投影到新身份。

- 累计比例为账本中的缓存读取总量 ÷ 已上报缓存明细的输入总量；不平均每次调用的比例，缓存写入不计入命中。
- 最近一次只认供应商明确上报的实际用量。真实零显示 `0%`，未上报或未调用显示 `—`，不以估算补齐。
- 正常状态不展示说明段落或 Token 分解。部分上报保留短提示与覆盖次数，读取失败和生成中仅显示必要状态。
- 入口使用 `VButton`，浮层使用 `VPopover` 与共享主题。浮层约 224px，限制到视口可用高度；键盘可打开，一次 Escape 关闭并返回入口焦点，Session 改变时关闭。
- 打开详情时停用入口 tooltip，避免 tooltip 先消费 Escape。触屏入口及关闭按钮至少 44px。

### 实现落点与验证

`components/conversation/ComposerCacheIndicator.tsx`、`composerCacheUsageModel.ts` 与 `routes/chat/useComposerCacheUsage.ts`。覆盖加权统计、0/未知/部分上报、身份隔离、延迟读取、现有调用更新、两处入口和窄屏键盘操作。

## ComposerContextRing

### 功能

输入区的上下文用量入口，按“容量、主要来源、明细”展示最近一次上下文数据。

### 适用范围

用于会话 composer 的轻量概览。使用现有 `VButton` 和 `VPopover`，不新增另一套浮层或缓存事实源。

### 使用方式

`ComposerContextRing` 接收 `model`、`lang`、`sessionId` 和可选 `onOpenDetail`。模型由现有上下文组成与供应商用量生成；`sessionId` 改变时重置整个浮层状态。

- 主条分母为模型窗口上限，不是已用内容总量；未知上限不显示 0%。容量与分项统一读取 lastContextComposition，禁止将缓存 calibratedSegments 混入上下文来源；分段独立估算可能与总量略有差异。
- 提示、运行规范和项目规则合并为一组，历史单列，其余来源保留在其他内容中。明细仍保留每个来源的名称、数量、比例和可用预览。
- 缓存只有 `provider_usage` 且已观测时展示命中比例，并同时给出绝对 cached tokens（如 `63% · 55.6K tokens`）；`computed_hit` 等本地估算不参与该比例。供应商未返回缓存数据时显示 `—`（fail-open），不猜测。
- 自动压缩指示器（Claude Code 范式）：阈值只读自后端 `contextCompression.strategy.levels` 最低档 `thresholdTokens`，禁止前端硬编码；仅在「距自动压缩剩余 <40%」时出现，同时给出剩余百分比与绝对 tokens（如 `38%（≈38K tokens）`），并注明「基于上次调用估算」与压缩行为说明（摘要保留要点、完整历史仍在）。剩余充足或压缩关闭时不渲染，避免常驻噪音。
- 生成速度：优先展示后端投递的 `llmUsage.tokensPerSecond`（厂商 usage + 最终调用耗时推导），悬停注明口径为上次调用；后端未能量测（provider 未回 usage）时显示 `—`，不再回落到前端文本估算冒充实测。
- 完整缓存诊断沿用原回调，从第二层打开。组明细比例以列出内容为分母，不能解读为容量比例。
- 浮层约 324px，受视口限制；明细可滚动，深浅色使用共享语义 token，键盘、Escape、点击外部由 VPopover 负责。

### 实现落点与验证

`components/conversation/ComposerContextRing.tsx` 与 `routes/chat/composerContextModel.ts`。
回归覆盖真实 0、未知容量、估算缓存不冒充实测、来源展开及切换会话收起；新增覆盖剩余 39%/40%/41% 阈值边界、`usageStats`/`tokensPerSecond` 缺失降级为 `—`、observed 缓存绝对 tokens。
