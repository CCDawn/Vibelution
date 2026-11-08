# ChatGPT subscription settings

## ChatGPTSubscriptionPanel

### 功能

在现有模型服务设置中连接一个 ChatGPT 账户、显示授权状态、发现该账户可用的模型，并把用户选择加入现有模型配置流程。用户已批准独立预览中的连接、授权等待、模型选择和额度提示结果。

### 适用范围

Workbench 的模型服务设置。保存后的模型由普通聊天和独立 Launcher 个人助理沿现有模型选择器使用。面板不拥有会话、记忆、工具执行、审批或 Launcher 生命周期。

### 使用方式

复用 `VSection`、`VSurface`、`VButton`、`VStatusChip`、`VCheckbox`、`VDialog` / `VConfirmDialog` 等既有产品 API；不新增 renderer 或第二套设计系统。`ConfigProviderRegistryPanel` 组合本面板，账户查询与动作由 `useChatGPTSubscription` 管理；模型加入由父页面的 `useChatGPTSubscriptionModelSetup` 经 canonical draft/apply 完成。

首屏说明使用 ChatGPT 套餐额度，主操作为 `Continue with ChatGPT`。授权在系统浏览器完成；等待时可以取消。已连接显示账户邮箱和管理用量入口，明确该状态只表示本地授权，模型可用性以实际完成的调用为准。模型列表来自当前账户，选中后加入配置，保留其它提供商、默认模型和 Agent 绑定。

### 状态与边界

- 未连接、等待授权、验证交换、已连接、授权过期、断网和额度限制具有独立文案与恢复动作；状态不依赖颜色单独传达。
- 活跃登录轮询使用同一 domain query key；取消、重新登录和断开后失效对应查询，迟到响应不能覆盖新动作。
- 页面和浏览器存储不接收 access/refresh/ID token，不提供 API Key 输入；授权地址只使用服务端生成的固定官方登录流程。
- 断开连接使用确认对话框。无法确认远端撤销时明确说明本机已退出，并提供官方连接管理入口。
- 额度不足保留已有模型选择和收到的输出，不自动更换收费提供商。模型添加失败保留配置草稿，不显示保存成功。
- 窄屏保持卡片内容自然换行、模型长名可断行、按钮可触达，不造成水平页面溢出；键盘可访问全部动作。

### 验证

专属 hook、API 和面板测试覆盖主要状态及错误；VUI 边界与 TypeScript 构建必须通过。真实官方授权与原生会话推理另做运行验收；示例预览或 HTTP 200 不代表账户额度已验证。
