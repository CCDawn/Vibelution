# First conversation: start with one Agent

This short path needs one Agent and one regular conversation. You do not need to create a team first.

## Set up a model

1. Follow the installation guide for [Windows](install-windows.md), [macOS](install-macos.md), or [Linux](install-linux.md). Windows uses the desktop workbench; macOS / Linux use the browser workbench.
2. Check the external config file. Its default path is `%USERPROFILE%\Documents\Vibelution\config\config.toml` on Windows and `~/Documents/Vibelution/config/config.toml` on macOS / Linux. The first Windows Launcher startup will usually create a starter file. After editing the config, restart the workbench as described in your platform guide.
3. Configure a provider, model, and dialogue profile in that file. Use `credential_ref` to reference an environment variable as described in the config docs, and store the real API key in that variable. Do not commit the key to the repository. See [config paths](../ops/config/01-authority-and-paths.md), [providers](../ops/config/02-llm-provider.md), [models and profiles](../ops/config/03-llm-model-and-profile.md), and [provider recipes](../ops/config/05-llm-vendor-recipes.md).

## Create an Agent and chat

1. On Windows, open Vibelution Launcher. On macOS / Linux, start and open the browser workbench as described in the installation guide. Open `Chat` in the workbench.
2. In the creation menu in the left conversation rail, choose `New Agent`, or select an existing Agent. For a new Agent, fill in the required `Name` and `Role key`, select a configured provider and model, and finish the wizard.
3. Select that Agent and click the `+` beside its session tabs. The tooltip says `New session for current Agent`. You can also choose `New session` from the Agent actions menu.
4. Send a text-only question in the message box, for example: `Based only on this conversation, introduce yourself and what you can help me with in three sentences. Do not use tools, access files, or browse the web.`

## What success looks like and where to troubleshoot

You should see your message and the Agent's text reply in the current conversation. You do not need to create a team or group chat for this first test.

If session creation fails, retry `New session`; the draft is retained. If the model is unavailable or its connectivity probe fails, check the config file, model, key environment variable, and network. If the workbench does not open, use your platform guide's troubleshooting section: [Windows](install-windows.en.md#troubleshooting), [macOS](install-macos.md), or [Linux](install-linux.md).

## Sources

- Installation, config path, and troubleshooting: [Windows](install-windows.md) · [macOS](install-macos.md) · [Linux](install-linux.md) · [external config paths](../ops/config/01-authority-and-paths.md)
- Provider, model, credential reference, and profile: [02 Provider](../ops/config/02-llm-provider.md) · [03 Models and profiles](../ops/config/03-llm-model-and-profile.md) · [05 Provider recipes](../ops/config/05-llm-vendor-recipes.md)
- Chat menu, Agent fields, and model selection: [ChatConversationIndexRail.tsx](../../web/src/routes/chat/ChatConversationIndexRail.tsx#L243) · [AgentCreateWizardDialog.tsx](../../web/src/routes/agent-create/AgentCreateWizardDialog.tsx#L66) · [AgentCreatePanel.tsx](../../web/src/routes/AgentCreatePanel.tsx#L324) · [model selection](../../web/src/routes/AgentCreatePanel.tsx#L365)
- Session and message controls, retry hint: [AgentSessionTabStrip.tsx](../../web/src/routes/AgentSessionTabStrip.tsx#L617) · [AgentContextMenu.tsx](../../web/src/routes/AgentContextMenu.tsx#L117) · [ConversationView.tsx](../../web/src/components/conversation/ConversationView.tsx#L7243) · [sessionCreateAttempt.ts](../../web/src/routes/chat/sessionCreateAttempt.ts#L39)
