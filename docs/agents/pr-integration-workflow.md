# PR 集成工作流提案（草案，未生效）

> **状态**：提案。在用户拍板 §6 两项授权决定之前，本文件不改变任何现行流程；现行权威仍是 [development-standard.md](../standards/development-standard.md) 与 [worktree-collaboration.md](worktree-collaboration.md)。生效后本文件收缩为其 PR 模式扩展节并回写规范。
>
> 2026-09-16 可行性审查定稿；门禁与审查 agent 优化两节为进行中的讨论（§8/§9），调研结论待补。

## 1. 背景与目标

当前主流程为本地集成：任务 worktree（`codex/<task-slug>` 分支）→ 本地完整门禁（task_closeout）→ 独立审查 APPROVE → ff-only 合入本地 `main`。远端 push/PR 属逐次授权操作。

目标：把 **STANDARD_TASK / HIGH_RISK** 的主要流程迁到 GitHub PR 平台，获得持久可审计的审查记录、用户可随时查看/驳回的集成面，与集中授权的远端操作；同时不引入网络单点、不稀释质量门、不破坏线性历史铁律。

## 2. 可行性结论

**可行，成熟度高于预期，但采用"PR 作为审查与集成的权威平面"的混合模式，而非把全部质量门搬上 PR。** 三个前置缺口：CI 手动触发（PR 无自动门禁）、task_closeout 零远端感知（需 PR 变体）、公共仓库的常设发布面（需授权边界与推送卫生）。

## 3. 事实底座（2026-09-16 核验）

- 远端 `origin = github.com/CCDawn/Vibelution.git`（**公共仓库**）；本地 `main` 领先 12 提交、零落后——远端已在被持续同步，无大迁移启动成本。
- `gh` CLI 2.96 已认证（repo+workflow 权限）；SSH 写钥匙 `vibelution_write_ed25519` 已备案（development-standard.md §14）。
- 规范已有完整 **remote sync gate**（development-standard.md §14：clean worktree / 范围已审 / 验证新鲜 / 目标确认 / 版本影响已判 / 无破坏性操作），push/PR 本就是门后允许项——本提案改变的是默认授权值，不是门结构。
- CI（`.github/workflows/ci.yml`）为 `workflow_dispatch` 手动触发（为省 Actions 分钟关闭了自动触发）：ruff fatal + Windows Python 测试矩阵。
- 历史 8 个 PR（2026-08，cursor/feat 分支），模式与工具链已验证。

## 4. 设计：混合分层模式

| 分级 | 通道 | 门禁 | 审查 |
|---|---|---|---|
| FAST_PATCH | 本地快速路（现行流程，不变） | 现行最小门 | 自审或跳过（现行规则） |
| STANDARD_TASK | PR | 本地完整门禁证据贴附 PR | 独立 reviewer 在 PR 上 APPROVE |
| HIGH_RISK | PR | 本地完整门禁 + 运行时证据 | 独立 reviewer + 用户可见暂停点 |

流程：worktree → 本地门禁（task_closeout 同款 selector）→ push 分支 → 开 PR（结构化证据贴附）→ 独立 reviewer `gh pr review` → 集成 agent **rebase-merge**（锁死方式，保线性历史）→ 回拉同步本地 `main` → 清理。

**降级路径**：GitHub 不可达时退回现行本地 closeout；网络不得成为开发单点。

## 5. 角色与职责

- **Worker**：只交本地分支与验证证据，**不操作远端**（远端操作集中授权、集中卫生检查）。
- **独立审查 agent**：在 PR 上做 review（行级评论锚定问题），APPROVE/REQUEST_CHANGES 二元裁决；保持与开发、合入权分离——2026-09-16 实战已证明独立性价值（REWORK 抓出两层契约不一致）。
- **集成 agent**：负责所有 PR 的创建/合入/同步/清理，持常设授权；**不得同时充当 reviewer**。
- Planner：不变。

## 6. 待用户拍板项（生效前置）

1. **常设授权范围**（建议：push 任务分支、建 PR、rebase-merge 合 PR、回拉同步本地 main 免请示；force push、删远端分支、发布 release 仍逐次确认）。
2. **FAST_PATCH 是否豁免 PR**（建议豁免）。

## 7. 落地任务清单（拍板后按三角色流水线执行）

1. 仓库设置：branch protection 锁 allowed merge methods = rebase merge。
2. `task_closeout` PR 变体（或 `--remote` 模式）：push+PR+证据贴附+merge+同步+清理，复用现有 selector 门。
3. worktree-collaboration.md 三角色规范增补 PR 模式节（reviewer 产出物从 coordination checkpoint 迁至 `gh pr review`，checkpoint 可双写过渡）。
4. pre-push 推送卫生检查固定动作（secrets/路径扫描；PR 描述不贴内部坐标：claim id、本机路径）。
5. CI 自动化缓步：先"本地证据门"，稳定后再评估是否开 push/PR 触发。

## 8. 门禁优化方向（讨论中）

现状痛点：证据只在本地（不持久不可见）、selector 完整性依赖 agent 自述、门禁只在 closeout 跑一次、并行会话 stale_main 重试是手工模式。

候选方向（调研结论待补，见 §11）：

1. **证据机器可验证**：closeout manifest（JSON）结构化贴 PR，合入工具校验 schema，杜绝"口头全绿"。
2. **快门/全门分层**：pre-merge 快门（ruff fatal + focused selector）+ 周期全量门（现有 CI 手动/定时触发）。
3. **合入串行化**：当前 2-3 并发规模用"rebase + 快门复跑"（stale_main 的自动化）即可；merge queue（GitHub 原生/bors）在并发上去后再评估，其依赖 per-dequeue required checks 的 Actions 成本。
4. **分级门禁清单机器化**：FAST/STANDARD/HIGH_RISK 各自的必跑命令与证据类型固化为模板，而非每次派发时手写。

## 9. 审查 agent 工具与提示词优化方向（讨论中）

2026-09-16 两轮实战（初裁 REWORK + 终裁 APPROVE）暴露的改进点：

1. **常设审查 rubric**（现为每次手写 8 条）：正确性/契约一致性/测试是否真实（防"测试存在但不测真东西"）/边界条件/嵌套与并发语义/卫生（scope-claim 覆盖、署名、无意外扰动）。每次派发只补任务特有的验收点。
2. **severity 分级定型**：实战自然形成了三级，应固化——BLOCKER（正确性/契约/测试造假，必须返工）/ SHOULD-FIX（琐碎但属本任务 own 文件的缺口，随返工带走）/ FOLLOW-UP（范围外，记录不阻塞）。
3. **对抗性验证强制化**：凡涉及语法/契约/解析层的改动，reviewer 必须亲手构造边界值实验（本轮 5 个占位符边界值即由此抓出 R1），不接受"只读测试文件"。
4. **返工信封格式**：问题+实测证据+建议修法+危害说明，让 worker 不需重新调研即可修。
5. **返工轮 diff 纪律**：range-diff 确认返工未意外扰动其他区域（本轮 reviewer 已实践）。
6. **PR 时代的工具升级**：行级评论锚定（gh pr review --request-changes + line comments）、审查记录平台持久化。
7. **防橡皮图章**：reviewer 与合入权分离（§5）；每论断必须带实测或 file:line 锚点。

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| 网络单点（国内到 GitHub 波动） | 断网降级回本地 closeout（§4）；规范已有 443/22 排查手册 |
| 周期拉长（push/PR/merge/sync 往返） | FAST_PATCH 豁免；快门/全门分层（§8.2） |
| 公共仓库发布面 | pre-push 卫生检查；不贴内部坐标；secrets 禁令沿用 |
| 审查橡皮图章化 | 独立性 + 对抗性验证强制（§9.3/§9.7） |
| 双平面权威混乱 | 明确：PR 合入后以远端为准回拉同步；合入前本地 main 为工作镜像 |
| merge 方式破坏线性历史 | branch protection 锁 rebase-merge（§7.1） |

## 11. 调研附录（待补）

- AI code review 成熟方案（Qodo PR-Agent / CodeRabbit / Copilot review / reviewdog / danger 等）的 rubric、工具接口、裁决语义、防橡皮图章机制 → 对 §9 的可抄清单。
- 门禁与 merge queue 方案（GitHub merge queue / bors / Mergify / 分层 CI / SHIP-SHOW-ASK 等）→ 对 §8 的机制选型。
