# 第一次对话：从一个 Agent 开始

这条最短路径只需要一个 Agent 和一条普通会话；无需先建团队。

## 准备模型

1. 按对应平台指南安装 Vibelution：[Windows](install-windows.md)、[macOS](install-macos.md)、[Linux](install-linux.md)。Windows 使用桌面工作台，macOS / Linux 使用浏览器工作台。
2. 检查外置配置文件：Windows 默认是 `%USERPROFILE%\Documents\Vibelution\config\config.toml`，macOS / Linux 默认是 `~/Documents/Vibelution/config/config.toml`。Windows 首次启动 Launcher 通常会生成 starter 文件；填写配置后按对应安装指南重新启动工作台。
3. 在该文件中配置服务商、模型和对话 Profile。`credential_ref` 按配置文档引用环境变量，真实 API key 放在对应环境变量中，不要提交到仓库。见[配置路径](../ops/config/01-authority-and-paths.md)、[Provider](../ops/config/02-llm-provider.md)、[模型与 Profile](../ops/config/03-llm-model-and-profile.md)和[服务商示例](../ops/config/05-llm-vendor-recipes.md)。

## 创建 Agent 并开始聊天

1. Windows 打开 Vibelution Launcher；macOS / Linux 按安装指南启动并打开浏览器工作台。进入「对话」（英文界面为 `Chat`）。
2. 在左侧会话栏的创建菜单中选「新建 Agent」；也可以直接选择已有 Agent。创建时填写必填的「功能名」和「角色键」，选择已配置的服务商与模型，并按向导完成创建。
3. 选中该 Agent，在它的会话页签旁点击 `+`（提示为「在当前 Agent 下新建会话」）。也可以从 Agent 操作菜单选择「新建会话」。
4. 在消息框发送一条纯文字问题，例如：`请只根据当前对话，用三句话介绍你自己和你能帮我做什么；不要调用工具、访问文件或联网。`

## 成功后与排查

你应在当前会话中看到自己发出的消息和 Agent 的文字回复。首次试聊不需要创建团队或群聊。

如果创建会话失败，按提示重试「新建会话」，草稿会保留。若模型不可用或连通性探测失败，核对配置文件、模型、密钥环境变量和网络；工作台打不开时，查看对应安装指南的故障排查：[Windows](install-windows.md#失败时看哪里)、[macOS](install-macos.md)、[Linux](install-linux.md)。

## 来源

- 安装、配置路径与故障入口：[Windows](install-windows.md) · [macOS](install-macos.md) · [Linux](install-linux.md) · [外置配置路径](../ops/config/01-authority-and-paths.md)
- Provider、模型、密钥引用与 Profile：[02 Provider](../ops/config/02-llm-provider.md) · [03 模型与 Profile](../ops/config/03-llm-model-and-profile.md) · [05 服务商示例](../ops/config/05-llm-vendor-recipes.md)
- Chat 菜单、Agent 必填项与模型选择：[ChatConversationIndexRail.tsx](../../web/src/routes/chat/ChatConversationIndexRail.tsx#L243) · [AgentCreateWizardDialog.tsx](../../web/src/routes/agent-create/AgentCreateWizardDialog.tsx#L66) · [AgentCreatePanel.tsx](../../web/src/routes/AgentCreatePanel.tsx#L324) · [模型选择](../../web/src/routes/AgentCreatePanel.tsx#L365)
- 会话与消息入口、重试提示：[AgentSessionTabStrip.tsx](../../web/src/routes/AgentSessionTabStrip.tsx#L617) · [AgentContextMenu.tsx](../../web/src/routes/AgentContextMenu.tsx#L117) · [ConversationView.tsx](../../web/src/components/conversation/ConversationView.tsx#L7243) · [sessionCreateAttempt.ts](../../web/src/routes/chat/sessionCreateAttempt.ts#L39)
