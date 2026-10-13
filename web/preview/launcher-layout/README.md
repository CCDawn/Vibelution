# Launcher 分支列表与详情隔离预览

范围：仅 `web/preview/launcher-layout/`；正式 Launcher route、共享组件和设计 token 未修改。

复用 VUI 的 `VSplitWorkspace`、`VDenseOpsPage`、`VButton`、`VTabs`、`VChip`、`VInput`、`VDropdownMenu` 与 `VConfirmDialog`。组件只在预览内组合，不新增产品组件。

```powershell
node web/node_modules/vite/bin/vite.js --config web/preview/launcher-layout/vite.config.ts
```

默认列表：`http://127.0.0.1:5198/`；详情：`http://127.0.0.1:5198/?view=detail`。

全部数据为确定性 mock；路径使用 Example 用户。启动、打开、停止、版本状态均为模拟，没有真实 IPC、API、日志或写入；复制仅写入模拟路径。诊断、维护与设置仅提示范围，不模拟这些页面。强制停止需要真实进程存活证据，因此本预览不虚构该动作。

覆盖：列表搜索/筛选/无结果、详情返回、概览/启动信息、运行/停止/启动中/失败、停止确认与取消、长分支名/完整路径、浅色/深色、桌面与窄屏。

当前阶段：等待用户审阅预览；批准后才将界面组合落地到正式组件，保留现有生命周期判断、权限与反馈语义。

用户修订方向：对齐 Workbench 主页面，并保留圆角。已只读核对当前主页面：灰色 canvas/rail、白色内容面、12px 主内容圆角；内部 VSurface 使用共享 8px panel token，按钮与页签使用 5px control token；主按钮直接沿用 VUI 原生 face/border/shadow。取消上一版自定义蓝色和直角分栏，保留现有列表、详情和模拟交互。
