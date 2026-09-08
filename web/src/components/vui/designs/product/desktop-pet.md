# Desktop pet

## DesktopPetRoute

### 功能

在独立透明 Electron 窗口中，以单一卡通虚拟人聚合展示当前项目原生 Session 的运行、等待确认、异常与刚完成状态，并允许回到对应工作台对话。

### 适用范围

- 适用于 `/desktop-pet` 独立窗口、角色状态动效与展开式 Session HUD。
- 人物主体使用 4px 移动阈值区分单击与拖动：单击展开 HUD，拖动通过 Electron 窗口位移移动桌宠并沿用原有位置持久化。
- 关闭按钮只关闭桌宠窗口；系统托盘的“显示桌面宠物”是稳定恢复入口。
- 不适用于普通 `/chat`、Companion 人物会话正文或第二套 transcript；这些仍由原生 Session、Journal 与 SSE 拥有。
- 不作为 3D 引擎。未来 Blender 资产由 `DesktopPetCharacter` 的 renderer 边界接入，不改变活动投影和 HUD。

### 使用方式

- 页面只调用 `/api/pet/activity` 的安全投影；活动或注意状态每秒刷新，空闲时每三秒刷新。
- 角色点击使用 `VNativeButton` 展开 HUD，Session 行仍使用 `VNativeButton`；关闭使用 `VIconButton`。
- Session 点击只调用 Electron preload 的 `openConversationFromPet(sessionId)`，由主进程聚焦原工作台并复用通知打开事件。
- 角色组件只接收图片、名称、tone 与 animation state。2D PNG 和未来 glTF/GLB renderer 必须遵循这一输入边界。

### 非职责

- 不保存消息、不判断 Turn 权威、不创建 Companion mailbox，也不修改普通 Session admission、worker、projection 或 composer。
- 不显示用户消息、工具参数、审批 payload 或模型推理正文。

### 视觉与状态

- 窗口透明、无边框、置顶；顶部保留拖动区与极简状态胶囊。
- 状态优先级由后端投影固定为 `approval > error > running > completed > idle`。
- `prefers-reduced-motion` 下停止全部非必要角色动画。

### 实现落点

- `web/src/routes/desktopPet/DesktopPetRoute.tsx`
- `web/src/routes/desktopPet/DesktopPetCharacter.tsx`
- `web/src/design/route-css/desktop-pet.tailwind.css`

### 反冗余

复用现有 VUI 按钮，不新增桌宠专用 primitive、浮层或第二套设计系统。HUD 是该独立产品窗口的领域组合，不对外导出通用组件。
