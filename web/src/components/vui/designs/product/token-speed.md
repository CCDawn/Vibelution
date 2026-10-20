# 当前会话实时生成速度

## ConversationTokenSpeedIndicator

### 功能
在会话顶栏右侧用小型半圆速度表和 `≈42.3 tok/s` 显示当前可见输出的估算速度，不显示模型名字。

### 适用范围
普通原生会话及个人助理内嵌会话；不聚合后台 Agent。历史调用统计仍用 ComposerContextRing。Companion、群聊与通知流不接入。

### 使用方式
由 ChatTokenSpeedIndicator 订阅当前 session 的 active-turn store，传入 `tokensPerSecond: number | null` 和 `lang: "zh" | "en"`。
展示组件组合 VTooltip 与只读 SVG，无展开面板。键盘可聚焦阅读估算说明，不添加高频 aria-live。

### 视觉与状态
28px 高，数字等宽；使用现有语义颜色。半圆刻度 0–200 tok/s，指针封顶但数值不截断；不以颜色表示速度优劣。无数据、等待首字、执行工具、暂停或完成均显示 `— tok/s`。不添加动效。

### 数据边界
仅统计正在运行的原生 Turn 中 reasoning / agent_message 的可见文本，按中文字符与其他非空白字符估算。首次快照仅作基线，只有同一文本项前缀追加才计速；不累加历史全文、工具输入输出、状态或 usage 终值。
使用最近 2 秒的有界采样，至少 250ms；1500ms 无新 token 后置空，每 500ms 检查。turn、文本项、模型配置、会话、已知断连/重连、重试、工具与非追加文本均重新采样。
当前投影不含真实 token 增量或请求 ID；未识别的服务端回放与隐式路由变化无法精确计量，数值始终以 ≈ 标识。

### 实现落点
`components/conversation/ConversationTokenSpeedIndicator.tsx` 与 `.styles.ts`；`routes/chat/ChatTokenSpeedIndicator.tsx`；`routes/chatTokenSpeed.ts`。不修改 Session、SSE、worker 或 transcript 权威。

### 非职责与反冗余
不承担模型切换、请求耗时、计费、性能诊断或历史统计；复用 VTooltip 和现有 active-turn store，不创建第二 SSE、状态仓库或公共 VUI primitive。
