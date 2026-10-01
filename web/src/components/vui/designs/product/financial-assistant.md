# 智能体菜单与金融助手入口

## SpecialistAgentMenu

### 功能
替代顶栏原“虚拟人”直达按钮，向下显示“炒股智能体”和“虚拟人智能体”。

### 适用范围
桌面顶栏及移动导航共用；仅聚合入口，不改变人物大厅和会话链路。

### 使用方式
组合现有 `VDropdownMenu` + `VButton`，`side="bottom"`；`onNavigate` 交回壳层原导航与遥测。
pathname 决定当前项及按钮高亮。Radix 管理键盘、Esc、外点和焦点；路由变化关闭菜单。
原 `/companions` 和 Companion 深链保留。禁用 chat 域时菜单不可用。

## FinanceRoute

### 功能
独立金融身份入口：显式创建/恢复未完成初始化，进入原生聊天、打开原身份模型配置及财报库。

### 适用范围
本地项目单一金融专家，第一阶段只读研究。不是行情终端、自动交易或个人账户账本。

### 使用方式
复用 `VDenseOpsPage`、`VStateSurface`、`VButton`、`VRouteLinkButton`。
GET 无自动创建；POST 幂等且并发串行。异步创建只刷新缓存，不自动导航，避免完成时抢走新页面。
只打开服务端验证 Agent/Session 绑定后返回的 sessionId，经 `useChatRouteSelection.openSession`。
未配置/连接未验证、已归档、初始化失败、权限不足、服务未接入均可见；不假装有数据。
公开新闻复用既有 `news_search_tool`，只在本会话作参考；助手判断真伪，不写入财报库，不开启跨团队委派。

### 非职责与反冗余
不新增 VUI primitive、第二套身份/配置存储、聊天组件、transcript、SSE 或后台调度。
金融建议与工具沿原生 Agent 权限；未来行情图仍需成熟图表库和独立来源验证。
