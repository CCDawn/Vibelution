# VSelectionToolbar

## VSelectionToolbar

### 功能与边界
基于选区视口坐标的非模态操作条。用于引用、复制和打开侧边对话；动作由调用方的 `VButton` 与回调提供，不接管草稿、会话或 transcript。

### 适用范围
用于会话文本选区的紧凑操作。不用于阻塞确认、设置表单或通用右键菜单；这些场景继续使用 `VDialog`、`VPopover` 和 `VDropdownMenu`。

### API 与定位
`anchorRect` 提供选区矩形；`ariaLabel` 标识操作条；`children` 提供按钮；`className` 补业务标记。默认位于选区上方，空间不足时置于下方，并保留 12px 视口边距。尺寸变化与窗口 resize 重新定位。

### 交互与实现
保持 `role="toolbar"`，鼠标按下阻止默认聚焦，保留选区直到按钮 click 进入原有回调。Portal、测量和定位由 shadcn renderer 负责；业务组件不得直接调用 `createPortal`。不自动抢焦点，不新增阻塞层。

### 视觉与验收
延续现有控制圆角、细边线、面板背景和轻阴影。组件预览提供可打开的选区操作条；定位沿用既有选区测试，另验证 portal、选区保留和动作回调。

### 使用方式
业务在选区有效时挂载组件，提供 `anchorRect`、`ariaLabel` 和原有动作按钮。取消选区或动作结束时由宿主卸载；renderer 清理尺寸观察与窗口事件。保留 `data-conversation-selection-menu` 以兼容会话的选区事件边界。
