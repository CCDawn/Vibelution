# VUI 前端统一 Wave 2：alpha 白名单、残余消费与组合搭页

**Date:** 2026-07-24
**Status:** closed-enough（2A–2E 工程项完成；2C 视觉 H 格待操作者补签；**附录 B：剩余 30 个无 recipe style map 分类已落档**）
**Owner:** `web-workbench-surface` / VUI design-system owner
**Mode:** `TASK_GRAPH`
**Risk:** `STANDARD_TASK`
**Depends on:**
- `docs/superpowers/plans/2026-07-23-shadcn-aligned-vui-design-system-migration.md`（主方案，`ADAPT`）
- Wave 1 已完成基线：`--vui-surface-*` 唯一字面量源；legacy `--surface-*` 别名已删除；约 147 个 style map 接入 `vuiSurfaceRecipes`
**Close condition:**
1. 生产代码中对 `vui-surface` 的 `color-mix` **仅允许白名单角色**；CI 契约测试失败即拦截
2. 11 个「无 recipe 但仍引用 surface」文件全部标注为 *state-only / intentional* 或已接入 recipe
3. 代表页（Chat / Agents / Config / Teams / Memory）完成深浅色 + 有/无背景图手测清单并归档证据
4. 至少 1 条高流量路径（建议 Chat 左栏或 Agents 列表）示范「VUI product + recipe，少直写 token」
5. 主方案 close condition 中「任意透明度 / 代表页验收」可勾选或明确延期项

---

## 0. 基线事实（2026-07-24）

| 指标 | 现状 |
|---|---|
| 表面字面量 | 仅 `--vui-surface-*`（`tokens.css`） |
| legacy `--surface-*` | 定义已删除；生产 `var(--surface-*)` = 0 |
| recipe 消费 | **~155 / 185** style maps（import `vuiSurfaceRecipes`） |
| 无 recipe style map | **30**（见 **附录 B** 全表；含 layout-only / state / glass） |
| 无 recipe 仍引用 surface | **5**（B1 表：state-tint / hover / glass / ring-offset） |
| 对 vui-surface 的 color-mix | 主路径已压；长尾 Evolution/近邻 % 可选 |
| shadcn 对齐 | 工程思想 `ADAPT` 已对齐；全站 composition 未完成 |
| 本地 git | `main` 相对 origin 多 commit ahead（以当时分支为准） |

**判断：** Wave 0–1（token 契约 + recipe 铺开 + 去别名）已基本完成。Wave 2 不再以「扫文件挂 recipe」为主，而以 **制度化例外、代表页验收、减少页面级拼装** 为主。

---

## 1. 目标

在不引入第二套组件 API、不 `shadcn init`、不复制官方 block 的前提下：

1. 把「结构表面必须不透明 / 可解释」写成 **可测试契约**，而不是口头约定。
2. 让状态层（selected / danger / accent）走 **有限状态配方**，而不是每次手写任意 alpha。
3. 用 1–2 个代表路径验证：页面 = **布局 + VUI product + recipe**，而不是 500 字 Tailwind 墙。
4. 手测闭环，避免「测试全绿、肉眼仍花」。

---

## 2. 非目标

- 不重做 AppShell 信息架构。
- 不把所有 domain shell 抽成通用 primitive。
- 不强制 Chat 中心区/composer 立刻改为 100% 不透明（须经手测决策）。
- 不新增 `class-variance-authority` / 平行 `components/ui`。
- 不在本 Wave 做 Base UI 迁移。

---

## 3. 工作流分层

```
Wave 2A  契约：color-mix 白名单 + 残余 11 文件分类
Wave 2B  状态 recipe：selected / danger / accent 可复用类
Wave 2C  代表页手测验收清单 + 证据归档
Wave 2D  示范路径 composition（Chat 左栏 或 Agents 列表）
Wave 2E  （可选）高流量 color-mix 热点压缩：Research / Tools
```

每层单独 PR/提交；层内可并行读，**2A 必须先于 2B/2E 合入**（契约先落地）。

---

## 4. Wave 2A — color-mix 白名单与残余分类

### 4.1 允许的 surface color-mix 角色（白名单）

| 角色 ID | 允许条件 | 示例 |
|---|---|---|
| `state-tint` | `color-mix` 第一操作数为 **accent / state-***，第二操作数为 surface | `accent-cool 10% + surface-row` |
| `chat-wallpaper-soft` | 仅限 Chat 中心软层 / composer 软层（文件+key 白名单） | centerSurface 6%、composer 74% |
| `glass-overlay` | 仅限浮层、handle、popover 类（glass 或 workspace overlay） | PaneCollapseHandle、session menu |
| `forbidden` | **surface + transparent 作结构板** | `surface-row 58% + transparent` |

### 4.2 实现任务

| # | 任务 | 产出 | 验证 |
|---|---|---|---|
| A1 | 新增 `web/src/design/vuiSurfaceAlphaPolicy.ts`（或测试内 policy 表）列出 allowed path+pattern | policy 模块 | unit |
| A2 | `vuiSurfaceAlphaPolicy.test.ts`：扫描 `web/src/**/*.styles.ts` 中 `color-mix(...vui-surface...)`，非白名单即 fail | 契约测试 | vitest |
| A3 | 11 个无 recipe 文件分类表写入本计划附录；状态-only 标注 `// surface-role: state-tint` 或 policy 登记 | 清单 | 人工 review |
| A4 | 若扫描发现仍存在 `surface + transparent` 结构洗，优先改不透明 recipe，**禁止**扩白名单 | 补丁 | A2 绿 |

### 4.3 无 recipe 文件分类

**基线 11 文件（2A）** 多数已在 2B 接入 recipe（selected / banner / danger 等）。
**现行全量：30 个** 无 `vuiSurfaceRecipes` import 的 `*.styles.ts`，完整表见 **附录 B**。

**决策规则（写死）：**

| 角色 | 是否必须挂 recipe | 说明 |
|---|---|---|
| `layout-only` | 否 | 无 surface token / 无 mix，纯几何 |
| `state-tint` / `hover-fill` | 可选 | 可继续手写或吸收进状态 recipe；禁止 surface+transparent 结构洗 |
| `glass-overlay` | 否（policy 放行） | 仅浮层/handle；勿改成 opaque panel |
| `message-bubble` | 否 | 用户气泡等 domain 材质；勿强行 opaque row |
| `ring-offset` | 否 | 仅 focus ring-offset 引用 surface |
| `mix-no-surface` | 否 | accent/state mix 不落 surface 时不强制 recipe |
| `needs-recipe` | 是 | 结构板仍自造 border+bg 时再迁 |

---

## 5. Wave 2B — 状态 recipe（减少任意 tint 拼写）

**状态：已落地（2026-07-24）**

在 `vuiSurfaceRecipes.ts` 增加 **有限** 状态类（固定配方，不允许路由自造 %）：

| Recipe | 语义 | 实现 |
|---|---|---|
| `vuiStateSelectedRowClass` | 列表选中 / active chip | border cool 34% + row 10% + cool text |
| `vuiStateCoolSoftClass` | 软 cool chip（透明 wash） | border 38% + bg 11% transparent |
| `vuiStateCoolInfoClass` | 更轻 info pill | border 28% + bg 8% transparent |
| `vuiStateDangerPanelClass` | 危险区底板 | error 22% border + 4% panel |
| `vuiStateWarningPanelClass` | 警告区 | warning 42% border + 8% panel |
| `vuiStateAccentBannerClass` | 返回条/提示条 | cool 28% border + 6% panel |
| `vuiStateDangerSoftClass` / `Success` / `Warm` | 状态 soft chip | 固定 transparent wash |

**已做：**
- 迁移脚本 `web/scripts/migrate_vui_state_recipes.py` 折叠 double-stack / 高频 soft chip
- ~43 个 style map 热点消费状态 recipe（AppShell / Chat / Memory / Research / Teams / Tools 等）
- foundation 导出契约已扩；alpha policy 仍允许 style map 内 residual state-tint（结构 wash 仍禁）

**规则：** 新代码应引用状态 recipe，禁止自造任意 alpha。残余近邻变体（border 40%/42%、arbitrary `[background:…]`）在 2E 分批压缩。

**验证：**
- foundation 测试导出符号
- alpha policy：recipes 文件为 token-definition；style map 禁止 structure wash

---

## 6. Wave 2C — 代表页手测验收

**状态：部分完成（2026-07-24）** — 自动化矩阵与清单见
`docs/superpowers/evidence/2026-07-24-vui-wave2/CHECKLIST.md`。
深/浅色 + 背景图 **视觉格** 仍需操作者 Launcher 刷新后补签。

### 6.1 页面与矩阵

| 页面 | 深色 | 浅色 | 无背景图 | 有背景图 | 窄视口 ≤860 |
|---|---|---|---|---|---|
| Chat | A | H | A | H | A |
| Agents | A | H | A | H | A |
| Config | A | H | A | H | H |
| Teams | A | H | A | H | A |
| Memory | A | H | A | H | A |

`A` = 自动化 layout/policy 已绿；`H` = 待真人视觉。

### 6.2 验收问题（每格回答 pass/fail + 截图路径）

1. 主卡片/列表行是否 **不透出花背景**（除非白名单软层）？
2. 浮层（dialog/menu）是否可读且层级清晰？
3. 选中/危险状态是否可辨且不过度发光？
4. 控件高度/圆角是否与邻页大体一致？
5. 有无布局溢出或双重边框（recipe 叠 class 常见病）？

### 6.3 刷新

- 用户可见验证前：**Launcher 刷新**（遵守项目 Launcher 规范，不直跑闪窗脚本）。
- 证据：短笔记 + 截图目录（如 `docs/superpowers/evidence/2026-07-xx-vui-wave2/`），不入库大图亦可放本地路径记录。

---

## 7. Wave 2D — 示范路径 composition

**状态：已落地（2026-07-24）** — D1 + D2 均完成。

### D1：Agents 列表行

- `agentRow` → `vuiDenseRowClass`
- `agentRowActive` → `vuiStateSelectedWarmRowClass`
- `agentRowBulkSelected` → `vuiStateSelectedRowFillClass`
- 契约：`vuiWave2CompositionContract.test.ts` + `AgentsRoute.layout.test.ts`

### D2：Chat 会话索引行

- `sessionItem` → `vuiDenseRowClass`
- `sessionItemActive` → `vuiStateSelectedRowClass`
- 契约：同上 composition test

**成功标准：** 示范路径状态/结构表面走 recipe；无 structure-wash。

---

## 8. Wave 2E — 热点 color-mix 压缩（可选、可拆）

**状态：主路径已落地（2026-07-24）**

| 优先级 | 文件 | 结果 |
|---|---|---|
| P0 | `ResearchRoute.styles.ts` | 结构 opaque + cool/state soft recipe；残余极少 |
| P0 | `ResearchFlowCanvasRoute.styles.ts` | 同上 |
| P1 | `ToolsRoute.styles.ts` | 本地 panel/row/tone 别名接 recipe |
| P1 | Teams / Config / Chat / Logs / Git / Agents 热点 | 脚本批量折叠 |
| P2 | `ConversationView.styles.ts` | 非白名单可折叠项已压；composer 软层保留 |

脚本：`web/scripts/migrate_vui_wave2e_hotspots.py`。
长尾（Evolution 任意属性语法、近邻 %）不阻塞 close。

---

## 9. 测试与 CI

| 类型 | 内容 |
|---|---|
| 新增 | `vuiSurfaceAlphaPolicy.test.ts`（或等价扫描） |
| 扩展 | foundation：shell recipes + 禁止 tokens 再出现 `--surface-` |
| 回归 | Agents / Chat / Config / Teams / Research layout 相关套件 |
| 构建 | `npm --prefix web run build` |
| 禁止 | 为过测试而扩大白名单到「任意 color-mix」 |

---

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| Chat 软层改不透明导致「死板」 | 2C 先拍板；默认保留白名单软层 |
| 状态 recipe 固定 % 与现网视觉差 | recipe 从现网最高频配方取样；手测 2C |
| 扫描误报 | policy 支持 path+regex 精确放行 |
| 脏树 / Launcher clean-main | 小提交；刷新走 Launcher |

---

## 11. 建议排期（单 Agent 串行）

| 顺序 | 工作量（约） | 产出 |
|---|---|---|
| 2A | 0.5–1d | alpha policy + 测试 + 11 文件登记 |
| 2B | 0.5–1d | 3–4 个状态 recipe + 热点 1 文件示范替换 |
| 2C | 0.5d | 手测清单填完（可与 2B 交错） |
| 2D | 0.5–1d | 一条示范路径 composition 干净 |
| 2E | 1–2d | Research/Tools 压缩（可并行多人） |

**总建议：** 先合 **2A+2B+2C**，再开 2D/2E。不要同时改 token 字面量与大批路由布局。

---

## 12. 与 shadcn 思想的关系（Wave 2 定位）

| shadcn 思想 | Wave 2 动作 |
|---|---|
| Semantic theming | 已完成字面量源；Wave 2 约束「页面乱 mix」 |
| Composition | 2D 示范 product+recipe 搭页 |
| Progressive migration | 分 Wave、分文件、契约先于大改 |
| 有限 variant | 2B 状态 recipe = 有限状态，不是无限 alpha |
| 不照搬 block | 仍不引入官方 dashboard |

Wave 2 **不追求**「长得像 shadcn 官网」，只追求 **像 shadcn 一样可治理**。

---

## 13. 验收勾选（Wave 2 完成时）

- [x] alpha policy 测试（`web/src/design/vuiSurfaceAlphaPolicy.test.ts`）
- [x] style map 扫描：无 `forbidden-structure-wash`（surface+transparent 结构洗）
- [x] 无 recipe 残余文件均有角色分类（**附录 B**；30 文件，2026-07-24 重盘）
- [ ] 5 代表页手测矩阵完成（A 格已绿；H 格待操作者）
- [x] 至少一条示范路径 composition（Agents 列表 + Chat 会话索引）
- [x] `npm --prefix web run build` 通过（recipe CSS 扫描修复后本地已验）
- [ ] 主方案文档 §0 状态更新为「Wave 2 done / Wave 3 pending」

### 2A 已交付（2026-07-24）

- `web/src/design/vuiSurfaceAlphaPolicy.ts`：角色分类 + 白名单
- 扫描契约：`.styles.ts` 禁止 structure wash
- 修复 Research/Tools/Teams/Memory 等残余 surface+transparent
- 保留：Chat soft layer、状态 tint、VUI component soft、token 定义

---

## 14. Wave 3 预告（本计划不实施）

- 控件几何：页面少覆盖 height/radius，统一走 VUI size/density
- 更多 product shell（dense ops / list-detail）替换重复 page chrome
- Reference Lab 与生产 token 的「已批准映射」文档化
- 若第二仓库出现再评估 internal registry

---

## 附录 A — 推荐立即开工的第一 PR

**标题建议：** `test(web): enforce vui-surface color-mix whitelist`
**状态：** 已完成（2A 合入）。

---

## 附录 B — 无 recipe style map 全表（2026-07-24 重盘）

**统计：** `web/src/**/*.styles.ts` 共 **185**；import `vuiSurfaceRecipes` **155**；**未 import 30**。
**扫描方式：** 无 recipe import 即入表（不要求必须含 surface）。
**维护：** 迁入 recipe 后从本表删除；新增无 recipe 文件须补角色。

### B0. 角色汇总

| 角色 | 数量 | 默认动作 |
|---|---|---|
| `layout-only` | 17 | **keep** — 无 surface 契约压力 |
| `mix-no-surface` | 8 | **keep** — accent/state mix，不强制 recipe |
| `state-tint` / `hover-fill` | 3 | **optional** — 可挂状态 recipe |
| `message-bubble` | 1 | **keep** — 勿 opaque 化用户气泡 |
| `ring-offset` | 1 | **keep** |
| `glass-overlay` | 1 | **keep** — policy glass 角色 |
| **合计** | **30** | 无 `needs-recipe` 阻塞项 |

### B1. 仍引用 `--vui-surface-*`（5）

| 文件 | 角色 | 说明 | 动作 |
|---|---|---|---|
| `components/conversation/AgentResponseSectionView.styles.ts` | `ring-offset` | `ring-offset-[var(--vui-surface-panel)]`；正文 `bg-transparent` | keep |
| `components/conversation/AgentUserContentSectionView.styles.ts` | `message-bubble` | cool 6% + panel 用户气泡 | keep；可选未来 soft bubble recipe |
| `components/layout/PaneCollapseHandle.styles.ts` | `glass-overlay` | glass 58% + transparent；policy 放行 | keep |
| `routes/ConversationIndexSection.styles.ts` | `hover-fill` | `hover:!bg-[var(--vui-surface-card)]` | optional dense/hover |
| `routes/SupervisedWorkspaceControls.styles.ts` | `hover-fill` | `hover:!bg-[var(--vui-surface-row-hover)]` + warm soft active | optional |

### B2. `mix-no-surface`（8）— 有 color-mix，无 surface 结构义务

| 文件 | 说明 | 动作 |
|---|---|---|
| `components/conversation/ConversationOperationDetails.styles.ts` | 操作详情状态色 | keep |
| `routes/AgentArchiveZonePanel.styles.ts` | 归档区 tint | keep / optional state soft |
| `routes/AgentManagementNav.styles.ts` | 导航 hover cool border | keep |
| `routes/chat/ChatToolApprovalDialog.styles.ts` | 审批对话框 overlay-ish | keep |
| `routes/MemoryGraphCanvas.styles.ts` | 图谱节点/边色 | keep |
| `routes/MemoryWarningStrip.styles.ts` | 警告条 | optional `vuiStateWarningSoftClass` |
| `routes/TeamSourceCollectionPhaseCloseGatePanel.styles.ts` | 阶段门禁状态 | keep |
| `routes/TeamSourceCollectionRunSwitcherPanel.styles.ts` | run 切换 tint | keep |

### B3. `layout-only`（17）— 无 surface token、无 recipe 压力

| 文件 | 说明 | 动作 |
|---|---|---|
| `app/LauncherShell.styles.ts` | Launcher 壳几何 | keep |
| `components/conversation/AgentMessageTurnView.styles.ts` | 回合布局 | keep |
| `components/conversation/conversationInlineMarkdown.styles.ts` | markdown 内联 | keep |
| `components/conversation/ConversationMarkdownRenderer.styles.ts` | markdown 布局 | keep |
| `components/conversation/ConversationStreamingResponseContent.styles.ts` | 流式块布局 | keep |
| `components/conversation/ConversationTurnAvatarContent.styles.ts` | 头像槽 | keep |
| `components/conversation/LazyConversationMarkdownRenderer.styles.ts` | lazy 壳 | keep |
| `components/editor/LazyJsonCodeMirror.styles.ts` | 编辑器壳 | keep |
| `routes/AgentBulkOperationsPanel.styles.ts` | bulk 布局 | keep |
| `routes/AgentDetailWorkspacePanel.styles.ts` | detail 工作区几何 | keep |
| `routes/AgentListWorkspacePanel.styles.ts` | list 工作区几何 | keep |
| `routes/ConversationIndexTree.styles.ts` | 索引树布局 | keep |
| `routes/TeamSourceCollectionManualWritebackPanel.styles.ts` | 回写表单布局 | keep |
| `routes/TeamSourceCollectionMemoryPanel.styles.ts` | 记忆子面板布局 | keep |
| `routes/TeamSourceCollectionRunSettingsPanel.styles.ts` | run 设置布局 | keep |
| `routes/TeamSourceCollectionScreeningPanel.styles.ts` | 筛选布局 | keep |
| `routes/TeamSourceCollectionStandaloneStagePanel.styles.ts` | 独立阶段布局 | keep |

### B4. 2A 原 11 文件 disposition（对照）

| 原文件 | 现行 |
|---|---|
| `AgentConversationDirectory.styles.ts` | **已 recipe**（selected） |
| `ChatFileWorkspaceTabs.styles.ts` | **已 recipe** |
| `MemoryKnowledgeModeTabs.styles.ts` | **已 recipe** |
| `TeamSourceCollectionFindingDetailsPanel.styles.ts` | **已 recipe** |
| `AgentReturnBannerPanel.styles.ts` | **已 recipe**（accent banner） |
| `AgentConfigPrimaryPanePanel.styles.ts` | **已 recipe**（danger panel） |
| `AgentUserContentSectionView.styles.ts` | 仍无 recipe → B1 `message-bubble` |
| `AgentResponseSectionView.styles.ts` | 仍无 recipe → B1 `ring-offset` |
| `ConversationIndexSection.styles.ts` | 仍无 recipe → B1 `hover-fill` |
| `SupervisedWorkspaceControls.styles.ts` | 仍无 recipe → B1 `hover-fill` |
| `PaneCollapseHandle.styles.ts` | 仍无 recipe → B1 `glass-overlay` |

### B5. 后续可选工单（非 Wave 2 阻塞）

1. `MemoryWarningStrip` → `vuiStateWarningSoftClass`（小）
2. `ConversationIndexSection` hover → 文档化或 `hover:bg-vui-surface-card` 主题类
3. 用户气泡若多处复制再抽 `vuiStateUserBubbleClass`
4. 盘点脚本（可复用）：对 `*.styles.ts` 检查 `vuiSurfaceRecipes` import

**结论：** 剩余 30 个 **无「必须立刻挂 recipe」的结构板**；统一工作不因这 30 个阻塞 close。

---

## 附录 C — 相关修复备忘（透底）

| 问题 | 根因 | 修复 |
|---|---|---|
| Chat 侧栏/中区透壁纸 | recipe 未进 Tailwind `@source`；fill 类无 CSS | `@source vuiSurfaceRecipes.ts` + `!bg-vui-surface-*` |
| Chat centerSurface 透 | 6% soft wash | 改为 `vuiChatFillClass` 实色 |
| Teams 右侧透 | `inspector` 无背景 | `vuiRailFillClass` + workspace fill |
