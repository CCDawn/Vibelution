# 会话左栏团队管理

## TeamContextMenu

### 功能
团队标题整行右键或 Shift+F10 打开 VDropdownMenu，提供重命名、管理团队、打开团队工作台、隐藏和归档。

### 适用范围
会话左栏真实 Team 分组。会话 Agent、特殊 Agent 与历史群聊标题不挂团队菜单。

### 使用方式
沿用 AgentContextMenu 的 VUI 菜单样式和 Radix 定位；右键不展开分组、不切换会话。外部点击、滚动、Esc 或选择菜单项关闭。
系统团队只读策略沿用 TeamSettingsDialog：禁用改名与归档并给出原因，允许查看设置、进入工作台和隐藏。

## TeamDirectoryManagementOverlay

### 功能
以 VDialog + VNativeInput + VButton 重命名，以现有 TeamSettingsDialog 管理完整配置，以 VConfirmDialog 二次确认归档。

### 适用范围
TeamDirectoryManagementOverlay 为延迟挂载的会话左栏 dialog host。打开设置时才加载完整团队和 Agent 配置；加载失败显示重试，不能用摘要名单覆盖完整成员。

### 使用方式
复用 useTeamSettingsActions 的写入、日志和 query invalidation。改名只 PATCH name，不提交成员；失败保持弹窗与输入并显示错误。归档说明团队只读及关联群聊删除，失败保留原列表。

## 隐藏与恢复

### 功能
VButton 打开“已隐藏团队”VDialog，每个团队有恢复按钮。

### 适用范围
当前浏览器的会话左栏显示偏好，localStorage 为唯一持久权威。隐藏分组及其成员行，不删除 Team、Agent、Session 或群聊，不将成员重分类为孤立 Agent。

### 使用方式
保留原完整目录分组数据，仅过滤显示的团队块。当前会话继续显示；重新加载仍隐藏；恢复后使用原折叠状态。隐藏记录不改变布局宽高持久化或服务器生命周期。
