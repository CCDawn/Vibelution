# Desktop pet

## DesktopPetRoute

### 功能

在独立透明 Electron 窗口中，以单一卡通虚拟人聚合展示当前项目原生 Session 的运行、等待确认、异常与刚完成状态，并允许回到对应工作台对话。

### 适用范围

- 适用于 `/desktop-pet` 独立窗口、角色状态动效与展开式 Session HUD。
- 人物主体使用 4px 移动阈值区分单击与拖动：单击展开 HUD，拖动通过 Electron 窗口位移移动桌宠并沿用原有位置持久化。
- 关闭按钮只关闭桌宠窗口；系统托盘的“显示桌面宠物”是稳定恢复入口。
- 不适用于普通 `/chat`、Companion 人物会话正文或第二套 transcript；这些仍由原生 Session、Journal 与 SSE 拥有。
- 采用用户确认的 小洛 Live2D 形态；无 3D 引擎、模型导入或市场。

### 使用方式

- 页面只调用 `/api/pet/activity` 的安全投影；活动或注意状态每秒刷新，空闲时每三秒刷新。
- 角色点击使用 `VNativeButton` 展开 HUD，Session 行仍使用 `VNativeButton`；关闭使用 `VIconButton`。
- Session 点击只调用 Electron preload 的 `openConversationFromPet(sessionId)`，由主进程聚焦原工作台并复用通知打开事件。
- 角色组件只接收名称、tone 与 animation state；Live2D 只渲染活动投影，不持有会话。
- 显示模型加载与失败状态，不静默切回旧 PNG；保留小洛的作者标注。

### 非职责

- 不保存消息、不判断 Turn 权威、不创建 Companion mailbox，也不修改普通 Session admission、worker、projection 或 composer。
- 不显示用户消息、工具参数、审批 payload 或模型推理正文。

### 视觉与状态

- 窗口透明、无边框、置顶；顶部保留拖动区与极简状态胶囊。
- 状态优先级由后端投影固定为 `approval > error > running > completed > idle`。
- `prefers-reduced-motion` 下停止全部非必要角色动画。
- 复用官方 Cubism SDK 5-r.5 的眨眼、呼吸、视线与物理；九种状态为参数姿态与小洛原生摸头动作，不是九套定制动画。
- 标签页隐藏时停止渲染，关闭/卸载时取消加载并释放模型资源。
- 本机集成不代表已获公开发布许可，详见 `web/live2d/README.md`。

### 实现落点

- `web/src/routes/desktopPet/DesktopPetRoute.tsx`
- `web/src/routes/desktopPet/DesktopPetCharacter.tsx`
- `web/src/design/route-css/desktop-pet.tailwind.css`

### 反冗余

复用现有 VUI 按钮，不新增桌宠专用 primitive、浮层或第二套设计系统。HUD 是该独立产品窗口的领域组合，不对外导出通用组件。
