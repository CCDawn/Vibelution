# 团队与群聊隔离预览

从 `web` 目录运行：`node node_modules/vite/bin/vite.js --config preview/team-chat/vite.config.ts`。
入口为 `http://127.0.0.1:5192/preview/team-chat/index.html`。
URL 参数 `view=team|chat` 切换页面，`scene=running|completed|error|empty` 切换状态。

此预览借用现有 VUI 产品 API、页面 recipe 和项目设计 token，独立维护模拟状态。
没有引入聊天依赖，没有修改正式路由、会话存储或共享组件。
成员、任务详情、产出、过程、停止、重试、新建和发送仅用于设计评审；API 请求不转发至产品后端。
组织结构按需打开；连续同作者发言合并署名；长正文截短后可展开；过程默认折叠。

类型检查、VUI 契约、桌面与 390px/320px 视口及主要模拟交互已验证。
真实任务数据、流式输出、附件上传和生产会话行为须在设计获批后的正式实现中单独验收。
