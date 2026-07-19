# 对话页悬浮式 Agent 创建向导实施计划

**Date:** 2026-07-19

**Status:** implemented

**Owner:** `agent-root-agent-create-dialog`

**Claim:** `claim-7566e6911a25`

**Scope:** 对话页与 Agent 管理页的新建 Agent 入口、共享创建控制器、悬浮向导及其验证

**Replaces:** `51b54ce1` 引入的 Agent 管理页全宽创建工作区

**Implementation link:** `feat(chat): add floating Agent creation wizard`

**Validation:** 191 项聚焦组件/路由测试通过；生产 build 通过；浏览器验证确认 `/chat` 原地打开/关闭 dialog、三步切换和 option 加载。合入最新 Chat route 拆分后，补齐两处静态契约（layout 组合迁至 `useChatWorkbenchLayout.ts`、显式允许其共享 parent styles）后，完整 web suite 通过。
**Close condition:** 两个入口复用同一向导；对话页不再跳转；创建、失败、取消、成功和继续配置路径均通过验证

**Mode:** `COMPACT_PLAN`
**Risk:** `STANDARD_TASK / CHECK` — 跨路由状态与创建后缓存收敛存在回归风险，但不改后端创建协议

## 目标与可观察结果

用户在对话页点击“新建 Agent”后：

1. 当前对话页面保持不变，在其上方立即出现居中的 onboarding dialog。
2. 向导分三步完成基本信息、服务商/模型、提示词/工具配置；默认值可一键使用。
3. 选项数据未返回时先显示完整弹窗框架和局部骨架，不出现空白页或整页跳转。
4. 创建成功后刷新 Agent/会话目录并显示成功状态；用户可选择“开始对话”或“继续高级配置”。
5. 关闭向导后焦点回到原“新建 Agent”按钮，当前对话、滚动位置和输入草稿不丢失。

Agent 管理页的“新增 Agent”入口复用同一个 dialog，不再维护另一套全宽创建布局。

## 非目标与保护边界

- 不修改 `POST /api/agents` 的后端字段契约、权限校验或持久化语义。
- 不重做 Agent 高级配置页、对话目录或新建会话表单。
- 不在创建成功时自动产生会话；只有用户点击“开始对话”才显式创建，避免隐式副作用。
- 不新增全局状态管理库或通用 Modal 设计系统；先以局部、可复用的 VUI dialog 实现。
- 不把完整提示词、模型响应、工具列表或表单文本写入新日志。
- 保留 `/agents?create=1` 兼容入口，但其表现改为在 Agent 管理页上打开相同 dialog。

## 推荐架构

### 1. 共享创建领域契约

新增 `web/src/routes/agent-create/agentCreateContract.ts`，从 `AgentsRoute.tsx` 和 `AgentCreatePanel.tsx` 提取创建专用的纯类型与纯函数：

- `AgentCreateDraft`、preset/model/select option 类型；
- 默认草稿、推荐 preset、工作会话判定；
- 服务商/模型与工具包默认选择；
- 工具包 selection → tool policy 投影；
- `AgentCreateDraft` → `POST /api/agents` payload 构建；
- 创建就绪条件和摘要投影。

约束：

- payload builder 必须保持现有字段、排序和默认值完全一致；
- 纯函数不读取路由、React state 或全局缓存；
- `AgentsRoute.tsx` 不再成为新建 Agent 领域逻辑的事实源。

### 2. 共享创建控制器

`AgentCreateWizardDialog.tsx` 作为唯一共享 controller，单一管理：

- `open` 生命周期、初始 draft、当前步骤和 dirty 状态；
- 懒加载 `/api/agents/config-workspace?includeRuntime=false` 与 `/api/tools`；
- 复用 `queryKeys.agentConfigWorkspace()`、`queryKeys.agentSummary(...)` 和现有 query cache；
- 创建 mutation、pending/error/success 状态；
- `chatWorkspaceCache.afterAgentWorkspaceChanged()` 及相关 query invalidation；
- 创建成功返回精确的 `agentId`，由入口决定后续动作。

实现时没有再增加一个只被 Dialog 自身调用的 `useAgentCreateWizard.ts` 包装层：所有跨入口的领域逻辑已在纯 `agentCreateContract.ts` 中复用，而 controller 与它唯一的视图消费者保持同文件，避免引入无收益的 state forwarding。

数据加载契约：

- dialog shell 在 `open=true` 的首帧出现，不等待 query；
- 第一步名称和使用位置可立即编辑；
- 模型与工具区域分别显示局部 skeleton；
- 远端默认值只补充用户尚未编辑的字段，禁止异步结果覆盖已经输入的名称、模型、提示词或工具选择；
- 加载失败只阻塞依赖该数据的步骤，并提供局部重试；已经输入的草稿保留。

### 3. 悬浮向导 Dialog

新增：

- `web/src/routes/agent-create/AgentCreateWizardDialog.tsx`
- `web/src/routes/agent-create/AgentCreateWizardDialog.styles.ts`

继续复用或重构现有 `AgentCreatePanel` 的字段内容，但 dialog 自己拥有外壳、步骤导航和交互状态。

#### 视觉契约

- 使用 portal 渲染至应用顶层，固定覆盖当前 route，不改变路由画布。
- overlay：`position: fixed; inset: 0; z-index >= 80`，背景使用约 45% 遮罩与 4–6px blur。
- dialog：`width: min(880px, calc(100vw - 32px))`，`max-height: calc(100dvh - 64px)`。
- 面板使用接近实色的 `var(--vui-surface-panel)`、细边框和 floating shadow；不得透出复杂城市背景。
- 布局固定为 `header / body / footer` 三行；仅 body 滚动。
- ≥ 760px：左侧 164–180px 纵向步骤 rail，右侧主内容。
- < 760px：步骤 rail 变为顶部横向进度，dialog 接近全屏且 footer 保持可达。
- preset 只在第一步显示；默认突出“推荐配置”，代码开发与研究协作为次选卡。
- 第三步工具包使用两列紧凑卡片，窄视口一列；最终摘要放在主内容末尾，不再形成横向宽屏条带。

#### 信息层级

Header：

- 标题“创建会话 Agent”；
- 副标题“3 步完成，创建后仍可继续调整”；
- 当前步骤计数；
- 明确的关闭按钮。

Steps：

1. 基本信息：推荐 preset、功能名、使用位置。
2. 服务商与模型：Provider、模型、兼容/推理能力说明。
3. 提示词与工具：提示词模板、工具包、创建摘要。

Footer：

- 左侧显示 dirty/loading/error 的短状态；
- 右侧依次为“取消 / 上一步 / 下一步”；
- 最后一步主操作改为“创建 Agent”；
- mutation pending 时锁定重复提交并显示进行中状态。

Success：

- 不直接离开对话页；
- 显示新 Agent 名称与当前模型摘要；
- 主操作“开始对话”；
- 次操作“继续高级配置”；
- 保留“完成并关闭”。

### 4. 对话页集成

修改 `web/src/routes/ChatCodingRoute.tsx`：

- 将 `handleCreateAgent()` 的 `navigate("/agents?create=1")` 替换为打开本地 wizard。
- 将 `AgentCreateWizardDialog` 放在 `ChatCodingRoute` 顶层布局末尾，避免受左右栏 overflow/stacking context 裁切。
- 保存触发按钮 ref；关闭后恢复焦点。
- 创建成功后先刷新 Agent/会话索引并选中新 Agent。
- “开始对话”必须直接把返回的 `agentId` 传给现有 create-session mutation，不能依赖异步 `setSelectedChatAgentId` 后再读取 state。
- “继续高级配置”导航到 `/agents?agent=<agentId>&pane=config&returnTo=/chat`。

对话保护：

- wizard 开关不得重建 `ConversationView`、清空 composer、改变 active session 或重置消息滚动。
- dialog 打开期间背景 route 不可交互，但仍保持 mounted。

### 5. Agent 管理页复用与旧布局清理

修改 `web/src/routes/AgentsRoute.tsx`：

- 删除创建专用的 draft/query/mutation/payload 重复逻辑，改用共享 controller。
- `requestedCreate` 继续支持 `/agents?create=1`，但只控制 dialog open。
- 创建成功后默认显示成功页；选择“继续高级配置”时再选中 Agent 并切换 config pane。

修改：

- `web/src/routes/AgentWorkspaceLayoutPanel.tsx`
- `web/src/routes/AgentWorkspaceLayoutPanel.styles.ts`
- `web/src/routes/AgentCreatePanel.tsx`
- `web/src/routes/AgentCreatePanel.styles.ts`

清理内容：

- 删除 `createWorkspace`、`workspaceCreating` 与创建态提前返回；
- Agent 管理页恢复稳定的目录/详情双栏；
- 删除全宽 1180px 创建容器和为整页布局增加的 sticky footer/summary 特例；
- 保留真正被 dialog 内容使用的字段、preset、step 和工具卡样式。

## 交互与无障碍契约

- dialog 使用 `role="dialog"`、`aria-modal="true"`、`aria-labelledby` 和必要的 `aria-describedby`。
- 打开后聚焦首个可编辑字段；步骤切换后把焦点移动到步骤标题或首字段。
- Tab/Shift+Tab 被限制在 dialog 内；关闭后恢复触发按钮焦点。
- ESC：
  - pristine draft 直接关闭；
  - dirty draft 显示“放弃本次填写？”确认；
  - mutation pending 时不关闭。
- 点击 backdrop 遵循与 ESC 相同的 dirty/pending 规则。
- loading、error、success 使用 `aria-live="polite"`；提交失败时焦点移动到错误摘要。
- 步骤状态不能只依靠颜色，必须同时使用序号、完成图标和文本。
- 所有按钮和 checkbox 保持至少 36px 可点击高度，窄视口不发生裁切或横向溢出。

## 状态机与失败处理

```text
closed
  -> opening
  -> editing(step 1..3)
  -> submitting
  -> success

opening/editing
  -> partial_load_error -> retry -> editing
editing
  -> dirty_close_confirm -> editing | closed
submitting
  -> submit_error -> editing
success
  -> create_session -> closed/chat
  -> advanced_config -> closed/agents
  -> closed
```

保护规则：

- 每次打开生成新的 controller instance；关闭后释放临时 draft。
- 同一次打开只允许一个 create mutation。
- submit error 不重置步骤和 draft。
- create 已成功但 session 创建失败时，Agent 仍保留；显示“Agent 已创建，会话创建失败”，允许重试会话创建，禁止再次 POST Agent。

## 测试策略

### 确定性契约测试

新增：

- `web/src/routes/agent-create/agentCreateContract.test.ts`
  - 默认 draft/preset；
  - 工作会话与团队 Agent 分支；
  - model/tool bundle 选择；
  - payload 与现有创建字段完全对齐；
  - preferred tools 必须是 allowed tools 子集。

- `web/src/routes/agent-create/AgentCreateWizardDialog.test.tsx`
  - dialog 语义、初始焦点和焦点恢复；
  - 三步导航、禁用条件和默认值；
  - 首帧 shell + 局部 skeleton；
  - late query 不覆盖用户输入；
  - dirty close、ESC、backdrop 和 pending 锁；
  - submit error 保留草稿；
  - success 三个出口；
  - session 创建失败不重复创建 Agent。

更新：

- `web/src/routes/ChatCodingRoute.agentSessionHierarchy.test.ts`
  - 不再断言 `navigate("/agents?create=1")`；
  - 断言对话页打开共享 dialog；
  - 断言成功 Agent ID 直接进入 create-session mutation。

- `web/src/routes/ChatCodingRoute.layout.test.ts`
  - dialog 位于顶层而非可裁切滚动容器；
  - 背景 route 保持 mounted。

- `web/src/routes/AgentsRoute.layout.test.ts`
  - `/agents?create=1` 打开共享 dialog；
  - 旧 `workspaceCreating/createWorkspace` 契约被删除；
  - Agent 管理正常双栏不被创建态替换。

### 验证命令

```powershell
npm --prefix web run test -- --run `
  src/routes/agent-create/agentCreateContract.test.ts `
  src/routes/agent-create/AgentCreateWizardDialog.test.tsx `
  src/routes/ChatCodingRoute.agentSessionHierarchy.test.ts `
  src/routes/ChatCodingRoute.layout.test.ts `
  src/routes/AgentsRoute.layout.test.ts

npm --prefix web run test
npm --prefix web run build
git diff --check
```

### 浏览器验收

Launcher 刷新后至少覆盖：

1. 2560×1440：对话页打开、三步填写、创建成功、开始对话。
2. 1366×768：dialog 高度、body 滚动和固定 footer。
3. 768px 左右窄视口：单列步骤、无横向溢出、按钮可达。
4. 模型/工具慢加载：shell 立即出现，局部 skeleton 正确。
5. 一个 query 失败和 POST 失败：错误位置、重试与草稿保留。
6. ESC、backdrop、Tab 顺序、焦点恢复。
7. console 无错误；创建 Agent 只产生一次 POST。

## 实施顺序

单一 frontend owner 串行执行，避免 `ChatCodingRoute.tsx` 与 `AgentsRoute.tsx` 双向漂移：

1. 申请覆盖 shared contract、dialog、两个 route 和相关 tests 的窄 claim，从最新 local `main` 创建任务 worktree。
2. 先建立 payload/defaults 的确定性测试，再提取 `agentCreateContract.ts`。
3. 实现 controller 与 dialog 的 loading/error/dirty/success 契约。
4. 集成 Chat route，先证明不导航、不丢对话状态，再接成功后的 session 动作。
5. 集成 Agents route 并删除旧全宽创建路径。
6. 运行聚焦测试、完整 web suite 和 build。
7. 按最新 main 重新 closeout，ff-only 合入。
8. 释放 claim、删除任务 branch/worktree。
9. 通过原生 Launcher 刷新并完成真实浏览器验收。

## 日志、版本与回滚

- 日志决策：不新增表单内容日志；复用现有 `POST /api/agents`、会话创建和 runtime-scene 证据。若需要 UI 事件，只允许记录 open/close/succeeded/failed 枚举与耗时，不记录名称、提示词、模型响应或工具明细。
- Version impact：patch。
- Runtime refresh：required before user acceptance。
- 回滚：该改造保持后端契约不变，可整体回滚 frontend commit；`/agents?create=1` 的兼容入口仍可恢复旧表现。
- 若 shared controller 提取引发大范围 Agent 管理回归，先保留纯 contract/payload builder，暂时让两个入口各自持有薄 controller；不得复制 payload 构建规则。
- 轻量 create-options API 属于 Deferred，只有真实加载测量证明现有两个 query 明显拖慢 dialog 可用性时再独立设计。
