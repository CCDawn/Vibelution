# Product — 项目工具右栏

> 产品组合：AppShell 顶栏入口 + Chat 右栏；项目级工具沿用会话右栏 renderer。
> 这里登记的是领域组合，不是新的公共 `V*` 导出。

## ProjectUtilityRightRail

### 功能

顶栏「任务」打开下拉，列出进行中的会话，以及还没有并进这些会话的运行任务。变更和通知仍打开工作区右侧工具栏。在 Chat 会话中，这个右栏与辅助对话、浏览器、CLI 终端等会话工具共用同一组标签和同一位置。

### 适用范围

- **适用**：顶栏任务下拉；跨页面可打开的仓库变更和项目通知；普通 Chat 会话中与会话级右栏工具并列切换。
- **不适用**：应用设置、导航和用量等全局入口（保留在顶栏设置 `VPopover`）；完整任务中心、Git 历史或项目广播中心仍由各自的完整页面承载。

| 场景 | 选择 |
| --- | --- |
| 顶栏「任务」查看进行中的会话和未并入的运行任务 | 打开顶栏任务下拉 |
| 顶栏「变更 / 通知」查看项目上下文 | 打开本右栏对应标签 |
| Chat 中继续看辅助对话、浏览器或 CLI，同时查看项目工具 | 复用 Chat 的同一右栏标签栏 |
| 更改主题、打开设置页、查看用量或日志、刷新工作台 | 使用顶栏设置 `VPopover`，按需前往既有页面 |
| 浏览完整任务历史或 Git 提交/分支操作 | 从右栏对应的完整视图入口打开既有任务中心或 Git 页面 |

### 使用方式

顶栏「变更」和「通知」各选择一个项目工具；相同入口再次点击会收起当前工具，点击另一个入口会切换到对应标签。顶栏「任务」不打开这条右栏：

```ts
openProjectUtilityRail("project_git");   // "project_notices"
```

普通 Chat 会话用 `useProjectAwareRightRail(activeSessionId)` 合并项目标签与当前会话的标签，只在展示模型中合并；会话工具状态仍按会话隔离。壳层 fallback 由 `ShellProjectUtilities` 使用同一个 `ChatRightRail` renderer，只开放项目工具：

| 顶栏入口 | 右栏标签 | 面板内容与后续动作 |
| --- | --- | --- |
| 任务 | 顶栏下拉 | 进行中的会话，以及计数里多出来的运行任务；有会话地址时可打开该会话。右栏里的 `project_tasks` 面板仍给侧栏自己的任务标签使用，顶栏按钮不再打开它 |
| 变更 | `project_git` | 仓库分支、变更文件和 diff；完整提交记录、分支与同步前往既有 Git 页面 |
| 通知 | `project_notices` | 项目通知时间线；可打开关联会话、发送项目广播或进入完整广播视图 |

Chat 的同一标签栏继续承载辅助对话、浏览器、CLI 终端，以及现有审查和上下文工具。标签可选择、拖动排序、搜索、关闭并从最近关闭列表重开；项目工具标签各保留一个。关闭标签只关闭当前展示标签，不等同于停止任务或 CLI 会话。停止活动 CLI 运行由独立运行操作处理，并在结束终端前确认。

项目通知仅在时间线请求成功且最新事件已提交显示后标为已读。加载中、失败或空列表不能提前清除未读状态。任务、仓库和通知分别保留自己的加载、空和错误状态；刷新与重试留在当前面板。

### 非职责

- 不新增独立的任务、变更或通知专用页面，也不复制 Chat 右栏 renderer。
- 不替代顶栏设置 `VPopover`、全局导航或完整任务/Git/广播页面。
- 不把项目工具状态写入 Session transcript；项目工具标签属于工作台 UI 状态，会话辅助对话仍走原生 Session 语义。
- 关闭右栏标签只改变展示状态；停止任务、停止 CLI 和发送广播各自保留明确动作及其确认/结果反馈。

### 视觉与状态

- 右栏顶部统一展示可切换标签、搜索、打开工具和收起操作；项目工具与辅助对话、浏览器、终端沿用同一层级和密度，不为顶栏入口另外画一套卡片式页面壳。
- 当前标签有清晰选中态；任务数、仓库变更和通知未读以顶栏入口的轻量提示表达，不把状态摘要扩成独立仪表盘。
- 面板内容区使用既有 VUI 面板、按钮、标签、空态、加载态和错误态。通知在数据成功显示后才更新已读提示；任务停止和广播发送反馈留在各自操作附近。
- Chat 右栏宽度由 Chat 工作台共享布局状态管理。壳层 fallback 使用 `WORKBENCH_LAYOUT_IDS.projectUtilities` 的 shared pane persistence；窄屏及无 Chat 右栏宿主的 compact 场景用 overlay 呈现同一个 renderer，不另设计窄屏页面。

### 实现落点

- 顶栏触发、壳层 fallback 与设置入口：`web/src/app/AppShell.tsx`
- 项目工具标签状态与入口：`web/src/app/projectUtilityRail.ts`、`web/src/app/ShellProjectUtilities.tsx`
- Chat 右栏和项目/会话标签组合：`web/src/routes/chat/ChatRightRail.tsx`、`web/src/routes/chat/chatRightRailModel.ts`、`web/src/routes/chat/useProjectAwareRightRail.ts`
- 面板分发：`web/src/routes/chat/ProjectUtilityPanel.tsx`
- 面板内容：`RuntimeTasksPanel`、`ProjectGitPanel`、`ProjectNotificationsPanel`
- 布局：`WORKBENCH_LAYOUT_IDS.projectUtilities`；Chat 会话右栏继续由 Chat 工作台宽度状态管理。
- Renderer：复用现有 `ChatRightRail` 和 VUI 产品 API，不新增 renderer 或公共 `V*` 控件。

### 反冗余

- 项目任务、变更和通知统一通过本右栏组合进入；禁止为每个顶栏按钮新建平行页面壳或第二个工具栏。
- Chat 右栏是会话工具与项目工具共享的 renderer。新增会话工具时扩展既有 tab kind 与 panel dispatch；新增项目工具时扩展项目工具映射，不另造 rail。
- 设置导航仍用既有 `VPopover`；需要完整工作流时链接到已有页面，不把完整页面嵌入右栏或复制业务逻辑。
