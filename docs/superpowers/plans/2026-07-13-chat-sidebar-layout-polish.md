# Chat Sidebar Layout Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将会话侧栏改成顶部操作、中部滚动索引、底部系统入口的稳定三段布局，并降低分组与会话行的视觉噪声。

**Architecture:** 保留现有数据模型和交互回调，只在 `ChatCodingRoute` 增加侧栏布局容器，并调整现有 Tailwind style map。列表项继续由现有组件渲染，选择状态保留 `aria-current` 和左侧强调条。

**Tech Stack:** React, TypeScript, Tailwind utility strings, VUI primitives, Vitest, Vite

## Global Constraints

- 不修改会话分类、API、查询键、后端协议或持久化数据。
- 不增加依赖，不改变 Launcher 或 package-lock。
- 群成员模式、loading、empty、error 和群聊创建流程必须继续可用。
- 只使用项目现有 VUI/Tailwind 视觉语义。

---

### Task 1: 锁定侧栏视觉契约

**Files:**
- Modify: `web/src/routes/ChatCodingRoute.layout.test.ts`

**Interfaces:**
- Consumes: `ChatCodingRoute.tsx?raw` 以及现有 style map。
- Produces: 三段布局、30px 头像列、46px 会话行、34px 分组标题、无当前徽章和无时钟图标的结构断言。

- [ ] **Step 1: 更新布局测试断言**

将旧的 `50px`、计数胶囊、`Clock3` 和 `VChip tone="accent"` 断言替换为新视觉契约，并增加 `conversationIndexLayout`、`conversationIndexScrollRegion` 与 `conversationIndexPanelBody` 断言。

- [ ] **Step 2: 运行测试确认 RED**

Run: `node node_modules/vitest/vitest.mjs run src/routes/ChatCodingRoute.layout.test.ts --reporter=dot`

Expected: FAIL，失败项指向尚未实现的新 class、尺寸或已存在的当前徽章/时钟图标。

### Task 2: 实现三段布局和轻量列表

**Files:**
- Modify: `web/src/routes/ChatCodingRoute.tsx`
- Modify: `web/src/routes/ChatCodingRoute.styles.ts`
- Modify: `web/src/routes/ConversationIndexSection.styles.ts`
- Modify: `web/src/routes/DirectSessionIndexItem.tsx`
- Modify: `web/src/routes/DirectSessionIndexItem.styles.ts`
- Modify: `web/src/routes/GroupSessionIndexItems.tsx`
- Modify: `web/src/routes/GroupSessionIndexItems.styles.ts`

**Interfaces:**
- Consumes: 现有会话树、群聊创建表单、系统入口回调和 `aria-current` 状态。
- Produces: `conversationIndexPanelBody`、`conversationIndexLayout`、`conversationIndexScrollRegion` 三个局部布局 class；其余公共接口不变。

- [ ] **Step 1: 调整 ChatCodingRoute 结构**

在会话视图分支内增加三行 grid：操作行、滚动区、系统入口。群聊创建表单放入中部滚动区，群成员分支保持现状。

- [ ] **Step 2: 调整搜索、操作和系统入口样式**

搜索框使用完整边框容器；操作按钮等宽；系统入口增加顶部分隔线；移除 `conversationTreeRootHeader` 中互相冲突的 flex/grid/overflow utility。

- [ ] **Step 3: 调整分组和会话行样式**

分组标题改为 34px 轻量行；头像和网格列统一为 30px；会话行改为 46px；角色标签改为 18px；普通状态不显示卡片边框。

- [ ] **Step 4: 简化时间和选中状态**

移除会话行重复的 `Clock3` 图标和直接会话的“当前”徽章，继续保留 `aria-current`、左侧强调条、运行状态和未读状态。

- [ ] **Step 5: 运行 GREEN 和相关回归**

Run: `node node_modules/vitest/vitest.mjs run src/routes/ConversationIndexSection.test.tsx src/routes/ConversationIndexTree.test.tsx src/routes/ChatCodingRoute.layout.test.ts --reporter=dot`

Expected: 相关测试全部通过。

- [ ] **Step 6: 生产构建和 diff 检查**

Run: `node node_modules/typescript/bin/tsc -b`

Run: `node node_modules/vite/bin/vite.js build`

Run: `git diff --check`

Expected: 三条命令退出码均为 0。
