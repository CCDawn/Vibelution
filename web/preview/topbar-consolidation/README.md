# 顶栏收拢交互预览

任务、变更、通知直达同一个可收起的辅助区；辅助对话、浏览器、CLI、文件、子 Agent、计划等沿用同一标签条，设置保留菜单。此目录只用于预审，未修改正式 AppShell、ChatRightRail 或共享设计事实源。

沿用 VUI 的 VButton、VTabs、VPopover、VDialog、VConfirmDialog、VSplitWorkspace、VSurface 与原生表单 API，不新增 V* 组件。宽度记忆复用 WORKBENCH_LAYOUT_IDS.chat，预览 origin 与产品隔离。

WorkspaceTools 直接复用 chatRightRailModel 的打开、关闭、恢复、新建辅助对话、草稿更新与浏览器地址校验函数。会话工具模型按 session 保存，项目工具标签独立保存，仅共用显示位置。辅助对话可以多开；标签超过可用宽度时横向滚动，并可从标签列表直接定位或恢复。关闭 CLI 标签只收起视图，模拟输出仍可恢复。

所有任务、差异、通知、辅助消息、浏览器正文、CLI 输出与停止操作均为确定性 mock。开发服务器拒绝 /api/ 请求，不代理产品运行时；浏览器不访问输入地址，CLI 不执行真实 Shell。桌面使用分栏，1050px 以下使用 VDialog 覆盖式辅助区。完整配置和广播以独立对话框示意入口。

参考研究：OpenCode b155b15694db 的 session-side-panel；VS Code custom-layout 与 notifications 官方文档；Zed Git Panel 官方文档。只参考交互层次，不复制外部组件或引入第二套设计系统。
