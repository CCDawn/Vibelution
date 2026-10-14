# Conversation process presentation

## ConversationToolActivity

### 功能

用紧凑、无卡片背景的过程行展示工具动作。普通工具名使用正常字重和次要灰阶；最终回复保留正文层级。单条、批次和类别分组都不显示右侧尖括号。失败、超时和需要关注的状态紧跟动作名称，位于命令摘要或分组数量之前；详情中保留完整错误。

### 适用范围

普通对话的原生工具活动及共用 ConversationToolActivityPills 的旧时间线。只改变呈现，不改变 Session、工具结果、展开持久化和轮次状态。

### 使用方式

继续使用 ConversationToolActivity 的现有 activity、language 和 renderToolDetails 输入。整行 summary 可鼠标点击或键盘展开；状态文字沿用 VTooltip，展开详情保留复制操作。运行中动作文字沿用既有动效与 reduced-motion 支持。

### 思考行与验证

原生 reasoning header 与旧 timeline thought header 继续复用 VButton，显式清除默认及 hover 的背景图片，避免按钮渐变残留为灰色横条。保留焦点轮廓、原有展开行为和耗时摘要。用工具交互测试、过程样式契约、VUI 合约和桌面/窄屏浏览器验证。
