# Launcher 权限选择局部预览

只展示现有对话区与输入框下方的权限选择，不重画 Launcher 外壳或导航。复用 ConversationView、LauncherAssistantModelControl、ChatComposerPlusMenu 与 VUI 弹层。权限菜单沿用 AgentPermissionPresetControl 的选项、图标与样式，以预览局部适配替换团队管理说明，不修改正式组件。

所有数据、保存和按钮均为模拟；fetch 拒绝网络请求，不安装原生 bridge，不访问真实审批/项目/文件接口。三档默认选择“替我审批”，切到完全访问前展示一次范围说明与确认。草稿与原有模型、附件、发送位置保留。

参考 Claude Code Desktop 的 prompt-box 下方模式选择行，以及 Cline 的权限分类与自动审批边界；只借交互思路，不引入代码或依赖。

- https://code.claude.com/docs/en/desktop#choose-a-permission-mode
- https://docs.cline.bot/features/auto-approve

初步预览已由用户批准。原入口 `/preview/launcher-permission-levels/` 保留批准时布局；`?state=error`、`pending`、`unavailable` 用于检查原模拟状态。

正式组件隔离验收入口：`/preview/launcher-permission-levels/runtime.html`。它直接挂载 LauncherAssistantEmbeddedRoute 与正式权限 hook/控件，仅 IPC 为模拟，拒绝所有 HTTP 与未列出的操作。`?state=error` 检查503恢复重试，`old-host` 检查旧版本禁用，`busy` 检查运行中仍可切档。此入口不构成真实产品运行验收。
