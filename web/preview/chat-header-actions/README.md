# 会话工具栏优化预览

只优化截图中的浏览会话、侧栏和 HTML 导出入口。复用已有 ChatCenterTabStrip、VIconButton、VDropdownMenu、VDialog 与 VSplitWorkspace，不修改正式组件或共享样式。

浏览与侧栏并排，统一 28px 控件和 16px 图标；保留 tooltip、键盘焦点和打开状态。导出归入同一行的更多菜单，取消正文独立工具行。移动端增大点击区域；现有辅助对话、浏览器、CLI 等工具仍放在原右侧栏。借用已有 codex-rail-toolbar 预览的控件组织方式，但本预览只展示本次三个入口，不重做顶栏与右栏。

会话列表、导出范围和工具正文为确定性模拟；服务器拒绝所有 /api/ 请求。预览不发送消息、不执行命令、不下载文件。
