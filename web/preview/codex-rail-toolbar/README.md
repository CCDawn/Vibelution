# Codex 右栏与会话工具栏预览

仅预览，不修改正式界面。对照本机 Codex 窗口的弱化工具按钮、紧凑列表、白色圆角内容面与细分隔线。保留 Vibelution 的导航、Agent 身份与现有工具名称；桌面浏览器内可显示任务、变更和通知入口。

复用 VUI、ChatCenterTabStrip 和 ChatRightRail；样式只在 preview.css 中覆盖。空状态、工具标签、搜索、关闭／收起、会话浏览及窄屏抽屉可交互。所有数据确定性模拟；辅助会话使用 mock client，无真实消息提交。导出只展示菜单。

启动：在 web 目录使用 Vite CLI 加载 preview/codex-rail-toolbar/vite.config.ts，访问 /codex-rail-toolbar-preview.html。

实际参考：2026-10-13 的本机 Codex 窗口。不是 Codex 源码或像素级复制。

第二版：使用当前截图的双会话标题检验长标题；标签字重改为 regular；浏览会话与侧栏统一为 28px 裸图标，名称保留在 tooltip 与无障碍标签中。侧栏打开时入口不绘制白色凸起按钮。

第四版提供 `?view=compare`：A 平整标题栏（推荐）与 B 低轮廓连接标签；均复用 SessionHeader 和真实 ChatCenterTabStrip。`?variant=flat` / `?variant=attached` 可查看完整工作台。A 将标题栏和正文合成一个白色圆角面；B 保留连接轮廓并把标签高度压低。导出菜单并入同一工具行，避免额外占一行。
