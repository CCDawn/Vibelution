# Codex 右栏与会话工具栏预览

仅预览，不修改正式界面。对照本机 Codex 窗口的弱化工具按钮、紧凑列表、白色圆角内容面与细分隔线。保留 Vibelution 的导航、Agent 身份与五个工具名称。

复用 VUI、ChatCenterTabStrip 和 ChatRightRail；样式只在 preview.css 中覆盖。空状态、工具标签、搜索、关闭／收起、会话浏览及窄屏抽屉可交互。所有数据确定性模拟；辅助会话使用 mock client，无真实消息提交。导出只展示菜单。

启动：在 web 目录使用 Vite CLI 加载 preview/codex-rail-toolbar/vite.config.ts，访问 /codex-rail-toolbar-preview.html。

实际参考：2026-10-13 的本机 Codex 窗口。不是 Codex 源码或像素级复制。
