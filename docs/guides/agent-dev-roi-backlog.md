# Agent 开发便利度 · ROI 改造清单

**读者：coding Agent / 排期 Owner。**
**目标：提高「定位 → 安全改 → 验证 → 收束」吞吐，不是产品功能清单。**
**评分口径：** Impact 1–5（省上下文/降错改/加速验证）· Effort 1–5（人日量级感）· ROI ≈ Impact/Effort。
**状态：** `todo` | `doing` | `done` | `blocked`
**生成：** 2026-08-05 · 依据便利度评估（综合约 3.7/5）。

---

## 使用方式

```text
1. 每轮只认领 1 个 P0 或 1–2 个 P1（同域）
2. 开工前：route.md 定域 + claim 热文件
3. 完成：改 Status + 在完成报告写「Agent 便利变化」一句
4. 禁止：为清单再写长文而不改代码/门禁
```

**不要做：** 再批量堆 archive 式计划；把标准全文再抄进 guides。

---

## P0 — 高 ROI / 先做（阻塞日常 Agent 吞吐）

| ID | 项 | Impact | Effort | ROI | 范围 | 完成定义（DoD） | 验证 | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **R01** | **ChatCodingRoute 继续削入口** | 5 | 3 | 1.7 | `web/src/routes/ChatCodingRoute.tsx` + chat/* | 入口文件 **≤800 行**（或 re-export + 明确 shell）；逻辑在 `chat/` 模块；README 30 秒表更新 | chat contract / layout tests 绿 | **done** (thin re-export; body → `ChatCodingRouteWorkbench.tsx`) |
| **R01b** | **FE 统一门禁：按钮+壳标记** | 4 | 2 | 2.0 | `vuiShadcnRouteContract` + guides | Teams 薄入口对齐；routes 禁裸 button；Chat/Agents recipe 标记；button-selection 文档 | `vuiShadcnRouteContract` 全绿 | **done** |
| **R02** | **SC presentation 去 `@ts-nocheck`** | 5 | 3 | 1.7 | `useSourceCollectionPresentationCore.ts` 等 | 去掉 nocheck；关键 bag **显式类型**；不扩大 any 逃逸 | teams contract + `tsc -b` | **done** |
| **R03** | **agent.py 再抽一层 orchestration 边界** | 5 | 4 | 1.3 | `agent.py` → `core/orchestration` / 现有 core | 入口 **净减少 ≥20% 行** 或职责表写清「禁止新业务进 agent.py」且新逻辑 0 新增业务 | 相关 agent/turn pytest；无行为回归 | todo |
| **R04** | **services 索引防腐门禁** | 4 | 1 | 4.0 | `scripts/_gen_services_readme.py` + test | CI/pytest：**磁盘 `*_service.py` 集合 ⊆ README 表**；缺行 fail | `tests/test_service_structure_guards.py::test_services_readme_indexes_every_facade` | **done** |
| **R05** | **select_tests / matrix 对齐热路径** | 4 | 2 | 2.0 | `tests/test_matrix.yaml` + `select_tests.py` | 至少覆盖：`session/*`、`team_workflow/*`、`core/llm/*`、`ChatCoding*`、`agent.py` 的 focused 命令可复制且跑得动 | `select_tests --changed-file … --commands-only` 抽样 5 条 | **done** |

**P0 建议顺序：** ~~R04 → R05 → R02 → R01~~（入口薄 re-export 已完成）→ R03；后续再拆 workbench 体量。

---

## P1 — 中高 ROI（降冷门域瞎改率）

| ID | 项 | Impact | Effort | ROI | 范围 | DoD | 验证 | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **R10** | **迷你 README 批 1：config 族** | 3 | 2 | 1.5 | `config_service` / `provider_config` / `model_reference` 等 | 1 个 `config_services.md` 或目录 README：**编辑表 + 禁止 + 主测** | Agent 不读源码能答「改 provider 挂哪」 | todo |
| **R11** | **迷你 README 批 2：evolution 族** | 3 | 2 | 1.5 | self/supervised/evolution facades | 同上：控制面 vs payload vs worktree 边界 | 聚焦 evolution 测试路径写进表 | todo |
| **R12** | **迷你 README 批 3：memory/RAG** | 3 | 2 | 1.5 | memory_* / rag_* / unified_knowledge | SSOT：谁写删除/索引；只读边界 | memory/rag 相关 pytest 列名 | todo |
| **R13** | **迷你 README 批 4：launcher/runtime** | 4 | 2 | 2.0 | launcher / runtime / runtime_manager_control / reset | 生命周期 + **无控制台** 检查点 + 禁止 taskkill | launcher/runtime 测试名 | todo |
| **R14** | **tools 全量索引（仿 services）** | 3 | 2 | 1.5 | `tools/*_tools.py` | `tools/README.md`：工具名 → 文件 → 授权入口 → 主测 | 与 tool-authorization 文档互链 | todo |
| **R15** | **session facade 再瘦到 re-export only** | 4 | 3 | 1.3 | `session_service.py` | facade **无新业务函数体**（仅 re-export/常量）；逻辑全在 `session/` | session 测试全绿；facade LOC 显著下降 | todo |
| **R16** | **team_workflow facade 再瘦** | 4 | 3 | 1.3 | `team_workflow_orchestration_service.py` | 同上 | team_workflow 合同 + 域测试 | todo |

**P1 建议顺序：** R13 → R10 → R11 → R12 → R14；R15/R16 与功能任务搭车。

---

## P2 — 中 ROI（体验与防呆）

| ID | 项 | Impact | Effort | ROI | 范围 | DoD | 验证 | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **R20** | **guides 加载 token 预算注释** | 2 | 1 | 2.0 | `docs/guides/README.md` | 每文件标注「约 N 行 / 何时跳过」 | 人工扫 | todo |
| **R21** | **development-standard 章节跳转卡** | 3 | 2 | 1.5 | `docs/standards/README.md` 或 standards 头 | Agent 只开 § 索引即可定位，不必全文 | 任务类型→§ 表完整 | todo |
| **R22** | **route.md 与 services 索引交叉链** | 2 | 1 | 2.0 | `docs/guides/route.md` | 后端行显式链 `services/README` domain 锚点（若可） | 链接有效 | todo |
| **R23** | **诊断命令卡片集中** | 3 | 1 | 3.0 | `docs/guides/loop.md` 或 `playbook.md` | runtime_scenes / diagnose_session / doctor 三行可复制 | 命令存在 | todo |
| **R24** | **FE 非 chat/teams 路由迷你表** | 3 | 2 | 1.5 | `web/src/routes/` | `routes/README.md`：Route 文件 → 域 → api 模块 | 新 Agent 能指到 Config/Git/Logs | todo |
| **R25** | **VUI 新建失败模式速查** | 2 | 1 | 2.0 | vui README 或 guides | 5 条「错 import / 未登记 designs」→ 修法 | contract 名列出 | todo |

---

## P3 — 低 ROI 或延后（ enticing 但贵）

| ID | 项 | 为何延后 |
| --- | --- | --- |
| R30 | 给 63 个 facade **各写长 README** | 维护成本 > 索引 + 迷你批 |
| R31 | 全仓「理想 &lt;500 行」运动 | 无产品目标时的大爆炸；应跟功能搭车 |
| R32 | archive 内部链接全量重写 | Agent 不应依赖 archive |
| R33 | 把 standards 拆成十几个专题文件 | 仅当链接守卫与引用全绿后再做（标准已声明） |
| R34 | 自动禁止打开 `docs/archive` 的工具层 | 需改 Agent 运行时；非本仓必做 |

---

## 与热文件 / claim 的绑定

| 项 | 建议 claim scope |
| --- | --- |
| R01 | `web/src/routes/chat/**` · ChatCodingRoute |
| R02 | `web/src/routes/teams/**` presentation |
| R03 | `agent.py` · `core/orchestration/**` |
| R04–R05 | `tests/**` · `scripts/_gen_services_readme.py` · services README |
| R15 | `core/web/services/session/**` |
| R16 | `core/web/services/team_workflow/**` |

并行：**禁止** R01+R03+R15 同一 Agent 无协调同时啃（热文件冲突）。

---

## 里程碑（建议）

| 里程碑 | 包含 | 成功信号（Agent 侧） |
| --- | --- | --- |
| **M1 防腐** | R04 + R05 + R23 | 索引不漏 facade；热路径 selector 命令可信；诊断三命令固定 |
| **M2 前端可导航** | R01 + R02 + R24 | Chat 入口薄；SC 可类型检查；非主路由可查表 |
| **M3 热后端** | R15 + R16 +（可选 R03 一段） | facade 薄；pack README 仍准 |
| **M4 冷域覆盖** | R10–R14 | config/evolution/memory/launcher/tools 可 30 秒定位 |
| **M5 文档 UX** | R20–R22 + R25 | guides/standards 打开成本下降 |

---

## 每项完成时的固定输出（粘贴到任务报告）

```text
ROI-ID: Rxx
Agent 便利变化: <一句话，如「Chat 入口从 3.5k→700，contract 仍绿」>
未做: <边界>
验证: <命令与结果>
Refresh: not needed | recommended | required
```

---

## 明确不在本清单

- 产品功能（新 Teams 能力、新模型厂商等）除非直接降低 Agent 改错率
- 单纯美化用户 UI
- 无 DoD 的「整体重构」

---

## 相关

| 文档 | 用途 |
| --- | --- |
| [README.md](README.md) | guides 入口 |
| [route.md](route.md) | 任务路由 |
| [ownership.md](ownership.md) | 落点 |
| [loop.md](loop.md) | 验证/完成 |
| `core/web/services/README.md` | backend 全表 |
| `docs/standards/development-standard.md` §8.3 | 体量意识 |
