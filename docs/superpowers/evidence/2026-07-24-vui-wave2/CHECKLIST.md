# VUI Wave 2 验收证据 — 2026-07-24

**Owner:** web-workbench-surface
**Scope:** Wave 2A–2E
**Runtime refresh:** 用户肉眼验收前 **recommended**（Launcher 刷新）；本轮 Agent 未强制刷新。

---

## 1. 自动化证据（本轮可重复）

| 套件 | 结果 | 命令 |
|---|---|---|
| Alpha policy + foundation | pass | `node ./node_modules/vitest/vitest.mjs run src/design/vuiSurfaceAlphaPolicy.test.ts src/components/vui/vuiThemeFoundation.test.tsx` |
| Composition contract (2D) | pass | `node ./node_modules/vitest/vitest.mjs run src/design/vuiWave2CompositionContract.test.ts` |
| Aesthetic contract | pass | `… routeAestheticContract.test.ts` |
| AppShell / Chat / Agents / Teams / Memory layout | pass | 见提交前 vitest 记录 |
| Structure wash 扫描 | 0 forbidden | policy 全量 style map 扫描 |

**color-mix 含 vui-surface 的 style map 命中（Wave 2E 后粗计）：** Research=0 / Tools≈1；全库长尾仍存（Evolution 任意属性、近邻 %）。主路径热点已压。

---

## 2. 代表页手测矩阵（2C）

图例：`A` = 自动化已绿（layout/policy）；`H` = 需真人视觉；`—` = 本轮未跑。

| 页面 | 深色 | 浅色 | 无背景图 | 有背景图 | 窄视口 ≤860 |
|---|---|---|---|---|---|
| Chat | A / H | H | A / H | H | A / H |
| Agents | A / H | H | A / H | H | A / H |
| Config | A / H | H | A / H | H | H |
| Teams | A / H | H | A / H | H | A / H |
| Memory | A / H | H | A / H | H | A / H |

### 验收问题（自动化可答部分）

1. **主卡片/列表行是否不透出花背景？**
   - 结构板已强制 opaque recipe；Chat centerSurface/composer 保留白名单软层。
   - **自动：pass**（forbidden structure-wash = 0）。
   - **视觉：pending**（有背景图时由操作者确认）。

2. **浮层是否可读？**
   - glass recipe + VUI dialog 路径；**视觉 pending**。

3. **选中/危险状态是否可辨？**
   - 2B 固定 selected/danger/warning recipe；Agents 行 = warm selected + bulk cool fill。
   - **自动：pass**（composition contract）；**视觉 pending**。

4. **控件高度/圆角一致？**
   - layout 测试覆盖代表页；**视觉 pending**。

5. **双重边框 / 溢出？**
   - composition 示范路径已去 double-stack；**视觉 pending**。

### 操作者手测步骤（补 H 格）

1. Launcher 刷新本仓库。
2. 切换深/浅色主题。
3. 开关背景图（若产品有入口）。
4. 将视口压到 ≤860。
5. 走 Chat 索引选中、Agents 列表选中/多选、Config 主工作台、Teams 卡片、Memory 列表。
6. 将截图放本地 `docs/superpowers/evidence/2026-07-24-vui-wave2/shots/`（可不入库大图），在本文件下方追加路径。

**手测签署：** _pending human_
**日期：**

---

## 3. Wave 2D composition 示范

| 路径 | 实现 |
|---|---|
| D1 Agents 列表行 | `agentRow` = `vuiDenseRowClass`；`agentRowActive` = `vuiStateSelectedWarmRowClass`；`agentRowBulkSelected` = `vuiStateSelectedRowFillClass` |
| D2 Chat 会话索引 | `sessionItem` = `vuiDenseRowClass`；`sessionItemActive` = `vuiStateSelectedRowClass` |

契约测试：`web/src/design/vuiWave2CompositionContract.test.ts`。

---

## 4. Wave 2E 压缩摘要

| 热点 | 动作 |
|---|---|
| Research* / Tools / Teams / Config / Chat / Logs / Git | 结构 soft-border panel → opaque/row recipe；state chip → soft recipes |
| Research 残余 selected/theme | 手改进 cool soft / selected |
| ConversationView | 保留 chat soft 白名单；其余可折叠的已进 recipe |
| 残余 | Evolution 等任意属性语法、近邻 % — 不阻塞 close；后续可继续扫 |

脚本：`web/scripts/migrate_vui_wave2e_hotspots.py`。

---

## 5. Close 判断

| 条件 | 状态 |
|---|---|
| color-mix 白名单可测 | **done** (2A) |
| 状态 recipe + 热点消费 | **done** (2B) |
| 代表页手测矩阵归档 | **partial**（A 格 done；H 格待操作者） |
| composition 示范路径 | **done** (2D) |
| 热点 color-mix 压缩 | **done** 主路径；长尾可选 |
