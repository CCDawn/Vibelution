# VUI 前端统一 Wave 2：alpha 白名单、残余消费与组合搭页

**Date:** 2026-07-24
**Status:** closed-enough（2A–2E 工程项完成；2C 视觉 H 格待操作者补签）
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
| recipe 消费 | ~147 / ~185 style maps |
| 无 recipe 仍引用 surface | **11**（状态 tint / hover / ring-offset 为主） |
| 对 vui-surface 的 color-mix | 约 **100+**；集中于 Research*、Tools、Conversation、状态条 |
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

### 4.3 11 文件分类（基线）

| 文件 | 建议角色 | Wave 2 动作 |
|---|---|---|
| `AgentConversationDirectory.styles.ts` | state-tint | 登记；可选 `vuiStateTintSelectedClass` |
| `ChatFileWorkspaceTabs.styles.ts` | state-tint | 登记 |
| `MemoryKnowledgeModeTabs.styles.ts` | state-tint | 登记 |
| `TeamSourceCollectionFindingDetailsPanel.styles.ts` | state-tint | 登记 |
| `AgentReturnBannerPanel.styles.ts` | state-tint (accent banner) | 登记 |
| `AgentConfigPrimaryPanePanel.styles.ts` | state-tint (danger zone) | 登记 |
| `AgentUserContentSectionView.styles.ts` | state-tint (user bubble) | 登记；勿强行 opaque panel |
| `AgentResponseSectionView.styles.ts` | ring-offset only | 登记为 non-mix 或 ignore |
| `ConversationIndexSection.styles.ts` | hover fill | 登记 hover 角色 |
| `SupervisedWorkspaceControls.styles.ts` | hover only | 登记 |
| `PaneCollapseHandle.styles.ts` | glass-overlay | 登记 glass 白名单 |

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
- [ ] 11 文件均有角色标注或已 recipe 化（2A 附录已分类，注释标注可选）
- [ ] 5 代表页手测矩阵完成
- [ ] 至少一条示范路径结构表面零内联 mix
- [ ] `npm --prefix web run build` 通过
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

**范围：**
1. `vuiSurfaceAlphaPolicy.ts` + test
2. 为 Chat center/composer、状态 tint 登记初始白名单
3. 不改视觉（若扫描已绿）或仅修扫描失败的违例

**验证：** `vitest` policy + foundation；无需 Launcher（纯契约）除非顺带修视觉。
