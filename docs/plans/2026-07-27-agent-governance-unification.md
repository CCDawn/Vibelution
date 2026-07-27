# Agent 规范权威统一迁移计划

> Status: implemented
> Baseline: `f8be120d4425`
> Branch: `codex/agent-governance-unification`
> Owner: `agent-runtime-core`

## 1. 目标

让外部开发 Agent（包括 Codex、Grok Build 等）与 Vibelution 项目自身 Agent 共享同一个根入口 `AGENTS.md`，并把所有跨模块详细规范统一收敛到 `docs/`。

最终稳定基础只有三项：

1. `core/core_prompt/COMMON.md`：通用执行纪律；
2. `core/core_prompt/SOUL.md`：稳定身份与价值倾向；
3. 根目录 `AGENTS.md`：项目最高规则、红线和文档路由中枢。

`COMMON.md`、`SOUL.md` 是运行时 Prompt 资产，`AGENTS.md` 是跨 Agent 自动发现入口；它们是“详细规范统一进入 docs”规则的三个明确例外。

## 2. 非目标

- 不改变 Agent 人格、工具权限、LLM 路由或用户可见产品行为。
- 不重写历史计划、历史测试报告和归档文档中的旧路径。
- 不把 `.docs/project-memory/` 迁入 `docs/`；前者是运行状态与协作数据，不是规范。
- 不把模块内 README 全部搬走；模块 README 只保留实现地图，不得声明跨项目 canonical 规则。
- 不借本轮重构业务代码、前端组件或后端服务。

## 3. 权威层级

发生冲突时按以下顺序处理：

1. 用户当前明确要求与授权边界；
2. 根目录 `AGENTS.md` 的全局红线和路由规则；
3. `docs/standards/README.md` 指向的单一专项规范；
4. ADR 和模块 README 中的架构原因、实现地图；
5. 历史计划、报告和归档材料。

`COMMON.md` 与 `SOUL.md` 提供身份和通用纪律，但不扩大权限，也不覆盖项目级规则。

## 4. 目标目录

```text
AGENTS.md

core/core_prompt/
├── COMMON.md
└── SOUL.md

docs/
├── README.md
├── standards/
│   ├── README.md
│   ├── development-workflow.md
│   ├── architecture.md
│   ├── frontend.md
│   ├── backend-fullstack.md
│   ├── testing-evidence.md
│   └── runtime-release.md
├── agents/
│   ├── domain.md
│   ├── worktree-collaboration.md
│   ├── tool-authorization-entrypoints.md
│   ├── issue-tracker.md
│   └── triage-labels.md
└── adr/
```

## 5. 文件迁移映射

| 当前来源 | 目标 | 动作 | 最终状态 |
| --- | --- | --- | --- |
| `AGENTS.md` | `AGENTS.md` | 缩减为身份、优先级、红线、任务路由、最小完成证据 | 根目录唯一规范入口 |
| `DEVELOPMENT_STANDARD.md` §0–5 | `docs/standards/development-workflow.md`、`testing-evidence.md` | 按责任拆分并去除重复 | 删除根目录原文件 |
| `DEVELOPMENT_STANDARD.md` §6–7、§13–19 | `docs/agents/worktree-collaboration.md`、`runtime-release.md` | 复用现有 worktree 文档，Git/发布规则归入 runtime-release | 一个规则只保留一个正文 |
| `DEVELOPMENT_STANDARD.md` §8、§23 | `docs/standards/architecture.md` | 保留来源权威、结构、Agent/工具/记忆边界 | 跨层架构唯一规范 |
| `DEVELOPMENT_STANDARD.md` §9、§23.6、§23.10 | `docs/standards/frontend.md` | 统一为 Tailwind + VUI + shadcn/Radix | 清除 HeroUI 现行描述 |
| `DEVELOPMENT_STANDARD.md` §24 | `docs/standards/backend-fullstack.md` | 保留 Route/Service/DTO/cache/contract 路径 | 全栈契约唯一规范 |
| `DEVELOPMENT_STANDARD.md` §11、§21–22 | `docs/standards/testing-evidence.md` | 测试、日志、验收和报告收敛 | 证据规范唯一正文 |
| `DEVELOPMENT_STANDARD.md` §10、§12、§14–16、§20 | `docs/standards/runtime-release.md` | Launcher、Bun、GitHub、版本、集成、生成站点 | 运行发布唯一规范 |
| `CONTEXT.md` | `docs/agents/domain.md` | 用当前完整词汇替换现有指针页 | 删除根目录原文件 |
| `core/core_prompt/SPEC.md` | 各专项规范、`core/prompt_manager/README.md` | 迁移仍有效的独有规则，移除核心 Prompt 身份 | 删除，不再参与当前工具/测试契约 |
| `docs/README.md` | `docs/README.md` | 改为统一导航并标注权威/历史/实现地图 | docs 总入口 |
| 根 `README.md`、`INDEX.md` | 新路径 | 更新导航，不复制规范正文 | 项目介绍与结构索引 |
| 服务包 README | 新专项规范 | 只更新链接，保留局部 ownership map | 非全局权威 |
| `core/launcher/developer_mode.py` | `docs/standards/` | 更新受保护规范路径 | 清理保护不失效 |
| `scripts/integration_audit.py` | 新规范路径 | 更新 hot-file 判定 | 治理审计不失效 |
| Prompt/remote/lifecycle tests | 三核心与新路径 | 删除旧 SPEC 假设，增加链接/权威守卫 | 防止规范回漂 |

## 6. 兼容策略

- 同一分支内先创建新规范、更新所有当前引用和守卫，最后删除根 `DEVELOPMENT_STANDARD.md`、`CONTEXT.md` 与旧 `SPEC.md`。
- 不保留长期根目录 compatibility stub；全部当前消费者迁移后，Git 历史已足以定位旧文档。
- 历史归档中的旧链接不批量改写，避免篡改历史证据；`docs/README.md` 明确历史材料不具备现行权威。
- 现有旧 worktree 保留其分叉时的规则副本；只有 rebase/merge 新 main 后才采用新入口，不对并行任务做跨 worktree 覆盖。

## 7. 任务图

### Task 1：切换规范权威与文档结构

- Owner/Boundary：文档治理；`AGENTS.md`、`docs/standards/**`、`docs/agents/domain.md`、导航链接。
- Dependency：本计划。
- Mode：SIMPLE。
- Verification/Stop：所有新链接可解析；每类规则只有一个 canonical 正文；没有改变规则语义的意外分叉。

### Task 2：清理旧入口和代码依赖

- Owner/Boundary：Prompt 与治理兼容；旧根文档、`SPEC.md`、Launcher、Integration Audit、相关测试。
- Dependency：Task 1 的目标路径稳定。
- Mode：BDD_TDD；先把守卫断言切到三核心和新规范路径，再删除旧入口。
- Verification/Stop：当前代码、脚本和测试不再把 `SPEC.md` 或根 `DEVELOPMENT_STANDARD.md` 当作现行权威。

### Task 3：统一验证与真实 Prompt 证据

- Owner/Boundary：验证与收口。
- Dependency：Task 1、Task 2。
- Mode：SIMPLE。
- Verification/Stop：聚焦测试通过；链接、固定用户名和旧 HeroUI 检查通过；真实会话快照只包含 `COMMON / SOUL / AGENTS` 且 `AGENTS` hash 与仓库一致。

Critical Path：Task 1 → Task 2 → Task 3。共享规范与测试路径均串行修改，不并行写入。

当前执行状态：

- Task 1：implemented and integrated；
- Task 2：implemented and integrated；
- Task 3：focused verification and live Prompt snapshot passed。

验收会话：`session-20260727-163103-480703`。运行时快照的核心来源严格为 `COMMON / SOUL / AGENTS`，其中 `AGENTS` hash 为 `sha256:c7662acad28b4958c92bcdc6652dce53fcd6b76f7a68f1becc5d7b82e7073f37`。

## 8. 风险与回滚

| 风险 | 失败信号 | 保护措施 | 回滚 |
| --- | --- | --- | --- |
| 外部 Agent 找不到规则 | `AGENTS.md` 链接失效或需要两跳以上 | 链接守卫与一跳路由表 | 恢复上一版 AGENTS 路由 |
| 项目自身 Agent 丢失核心 Prompt | Prompt bundle 缺项、snapshot reason=`missing_core_prompt` | 保持三核心源路径不变并跑 Prompt 测试 | 回退本分支 Prompt 相关提交 |
| Developer Mode/审计漏保护规范 | 清理计划允许删除新规范，或 hot-file 审计不命中 | 同步更新保护集合和审计测试 | 恢复旧保护项并修正新路径 |
| 规则拆分造成语义遗漏 | 原章节没有目标归属或多个目标保留正文 | 迁移映射逐节核对，正文单写、其他位置只链接 | 从 Git 基线恢复遗漏章节 |
| 历史证据被错误改写 | archive/旧报告出现大面积机械 diff | 排除历史目录 | 撤销历史目录改动 |

## 9. 验证契约

1. 文档和路径：
   - `AGENTS.md` 中所有仓库内链接存在；
   - `docs/standards/README.md` 覆盖全部现行全局规范；
   - 当前文件不再引用根 `DEVELOPMENT_STANDARD.md` 或核心 `SPEC.md`；
   - 当前规范不含 `C:\Users\<固定用户名>`；
   - 当前 docs 索引不含 HeroUI 现行指导。
2. Python：
   - Prompt source/template/session snapshot 测试；
   - PromptManager 旧 SPEC 迁移测试；
   - Developer Mode 清理保护测试；
   - Integration Audit hot-file 测试；
   - remote runner/lifecycle prompt contract 测试。
3. 运行时：
   - Launcher 刷新后创建独立会话；
   - snapshot `corePrompts[].name == ["COMMON", "SOUL", "AGENTS"]`；
   - snapshot `AGENTS.contentHash` 与当前文件一致；
   - 不输出完整 Prompt 内容到日志。
4. 交付：
   - `git diff --check`；
   - scoped status/diff；
   - version impact 评估；
   - claim 释放和项目记忆同步决策。

## 10. 完成定义

- 外部 Agent 和 Vibelution Agent 从同一个根 `AGENTS.md` 起步；
- 所有详细全局规范位于 `docs/`；
- `COMMON`、`SOUL`、`AGENTS` 是唯一核心 Prompt 基础；
- 没有旧 `SPEC.md`、根大规范、固定用户名或过期前端栈继续竞争权威；
- 代码保护、审计、测试和真实 Prompt 快照共同证明迁移完成。
