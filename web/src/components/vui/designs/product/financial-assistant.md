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
`/finance` 是炒股智能体自己的页面。菜单点“炒股智能体”进入这一页，不进入普通聊天的 Agent 列表。还没有助手时，这一下创建身份、空财报库和会话，然后只显示这个助手的对话，对话占满页面。打不开时只留一句原因和重试。

### 适用范围
本地项目单一金融专家，第一阶段只读研究。不是行情终端、自动交易或个人账户账本。

### 使用方式
复用 `VDenseOpsPage`、`VStateSurface`、`VButton`。
GET 无自动创建；菜单或 `/finance` 这一下才会 POST。POST 幂等且并发串行。
只打开服务端验证 Agent/Session 绑定后返回的 sessionId，经 `useChatRouteSelection.openSession`。
离开入口后，晚到的结果不导航。已归档或身份已改不另建。
公开新闻复用既有 `news_search_tool`，只在本会话作参考；助手判断真伪，不写入财报库，不开启跨团队委派。

## 对话说明与连接状态

### 功能
炒股智能体的对话开头用一条 `VStateSurface` 放能力边界，并链到原身份配置和财报库。会话菜单增加“财报知识库”。模型、外部财报服务和财报库是否绑上，写在身份配置页和财报库页，用白话，不展示内部状态词。

### 适用范围
只在该助手自己的会话、配置和财报库出现。普通会话、其他 Agent 和虚拟人会话不出现。

### 使用方式
复用 `VStateSurface` 与 `VRouteLinkButton`。列表查询失败时说明不出现，不挡住对话。

### 非职责与反冗余
不新增 VUI primitive、第二套身份/配置存储、聊天组件、transcript、SSE 或后台调度。
金融建议与工具沿原生 Agent 权限；未来行情图仍需成熟图表库和独立来源验证。
