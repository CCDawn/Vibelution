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
| FAST_PATCH（=Ship） | 本地快速路（现行流程，不变）；直合本地 `main` 后由集成 agent 直推 origin（身份入 branch protection bypass 名单） | 现行最小门 | 自审或跳过（现行规则） |
| STANDARD_TASK（=Show） | PR | 快门（本地 focused selector）+ commit status `ci/local-verify` 绿章 | 独立 reviewer 在 PR 上 review； blocking 意见>0 才 Request Changes |
| HIGH_RISK（=Ask） | PR | 全门（完整 selector 证据 + 合入前 rebase 最新 main 复跑快门）+ 运行时证据 | 独立 reviewer APPROVE 作 required review；用户可见暂停点 |

分级术语对齐业界 [SHIP/SHOW/ASK](https://martinfowler.com/articles/ship-show-ask.html)。

流程：worktree → 本地门禁（task_closeout 同款 selector）→ push 分支 → 开 PR（结构化证据贴附）→ 本地验证结果打 commit status（`gh api POST /repos/CCDawn/Vibelution/statuses/<sha>`，context `ci/local-verify`，零 Actions 分钟）→ 独立 reviewer `gh pr review` → 集成 agent **rebase-merge**（branch protection 锁死 allowed merge methods + Require linear history）→ 回拉同步本地 `main` → 清理。

**单一集成权威（修订，关键）**：本地 ff-only 合入与 GitHub rebase-merge 产出不同 SHA——两边同时当集成点会使本地 `main` 与 `origin/main` 永久分叉。定 GitHub 为唯一集成权威：STANDARD/HIGH 只经 PR 合入，本地只验证与回拉；FAST_PATCH 本地直合后由集成 agent（bypass 名单内）直推 `origin/main`。branch protection 不要把 "require branches up to date" 与线性历史叠加成贡献者 rebase+force-push 循环（agent 流程恒本地 rebase，无碍，但设置时注意）。

**降级路径**：GitHub 不可达时退回现行本地 closeout；网络不得成为开发单点。

## 5. 角色与职责

- **Worker**：只交本地分支与验证证据，**不操作远端**（远端操作集中授权、集中卫生检查）。
- **独立审查 agent**：在 PR 上做 review（行级评论锚定问题），APPROVE/REQUEST_CHANGES 二元裁决；保持与开发、合入权分离——2026-09-16 实战已证明独立性价值（REWORK 抓出两层契约不一致）。
- **集成 agent**：负责所有 PR 的创建/合入/同步/清理，持常设授权；**不得同时充当 reviewer**。
- Planner：不变。

## 6. 待用户拍板项（生效前置）

1. **常设授权范围**（建议：push 任务分支、建 PR、rebase-merge 合 PR、回拉同步本地 main 免请示；force push、删远端分支、发布 release 仍逐次确认）。
2. **FAST_PATCH 是否豁免 PR**（建议豁免）。
3. **单一集成权威定为 GitHub**（建议照此；FAST_PATCH 直推通道依赖 bypass 名单）。

## 7. 落地任务清单（拍板后按三角色流水线执行）

1. 仓库设置：branch protection 锁 allowed merge methods = rebase merge。
2. `task_closeout` PR 变体（或 `--remote` 模式）：push+PR+证据贴附+merge+同步+清理，复用现有 selector 门。
3. worktree-collaboration.md 三角色规范增补 PR 模式节（reviewer 产出物从 coordination checkpoint 迁至 `gh pr review`，checkpoint 可双写过渡）。
4. pre-push 推送卫生检查固定动作（secrets/路径扫描；PR 描述不贴内部坐标：claim id、本机路径）。
5. CI 自动化缓步：先"本地证据门"，稳定后再评估是否开 push/PR 触发。
6. **PR 审查自动激活与队列**（详见 §12）：`pr_review_watch.py` 常驻 watcher + 单飞队列 + 临时审查 worktree。

## 8. 门禁优化方向（讨论中）

现状痛点：证据只在本地（不持久不可见）、selector 完整性依赖 agent 自述、门禁只在 closeout 跑一次、并行会话 stale_main 重试是手工模式。

调研定稿（2026-09-17，来源见 §11）：

1. **机器门 = 本地证据 + commit status + required review 双门**：本地跑完验证给 SHA 打 `ci/local-verify` 绿章设 required check，配合独立 APPROVE 作 required review。**不用 self-hosted runner**（公共仓库 fork PR 任意代码执行，官方红线；agent 本就在开发者机器上跑，本机验证+打 status 等价且更简单）。
2. **快门=准入证、全门=准出证**（trunk-based 共识，Chromium CQ/Meta Sandcastle 可缩放版）：pre-merge 只跑 ruff fatal + focused selector（分钟级）；全量 selector 保持 workflow_dispatch 手动触发作准出门——HIGH_RISK 每次合入后必跑，STANDARD 抽样/nightly。
3. **当前规模不上 merge queue**（2-3 并发；queue 每次 merge_group 出队重跑 required checks 费分钟，min/max 组大小与等待时间是成本旋钮）。用"合入前 rebase 最新 main + 快门复跑"（stale_main 流程的自动化）作廉价同构；并发 >5 或快门 >10min 再评估 GitHub 原生 queue。
4. **分级门禁清单机器化**：FAST/STANDARD/HIGH_RISK 各自的必跑命令与证据类型固化为模板（可加 <10s 的 PR title/checklist 校验轻 action 作结构门），而非每次派发时手写。

## 9. 审查 agent 工具与提示词优化方向（讨论中）

2026-09-16 两轮实战（初裁 REWORK + 终裁 APPROVE）暴露的改进点：

1. **常设审查 rubric**（现为每次手写 8 条）：正确性/契约一致性/测试是否真实（防"测试存在但不测真东西"）/边界条件/嵌套与并发语义/卫生（scope-claim 覆盖、署名、无意外扰动）。每次派发只补任务特有的验收点。
2. **severity 分级定型**：实战自然形成了三级，应固化——BLOCKER（正确性/契约/测试造假，必须返工）/ SHOULD-FIX（琐碎但属本任务 own 文件的缺口，随返工带走）/ FOLLOW-UP（范围外，记录不阻塞）。
3. **对抗性验证强制化**：凡涉及语法/契约/解析层的改动，reviewer 必须亲手构造边界值实验（本轮 5 个占位符边界值即由此抓出 R1），不接受"只读测试文件"。
4. **返工信封格式**：问题+实测证据+建议修法+危害说明，让 worker 不需重新调研即可修。
5. **返工轮 diff 纪律**：range-diff 确认返工未意外扰动其他区域（本轮 reviewer 已实践）。
6. **PR 时代的工具升级**：行级评论锚定（gh pr review --request-changes + line comments）、审查记录平台持久化。
7. **防橡皮图章**：reviewer 与合入权分离（§5）；每论断必须带实测或 file:line 锚点。

调研定稿（2026-09-17，业界对照见 §11）：

8. **裁决三档映射**：`safe_to_merge / merge_with_caution / changes_required` ↔ PR 的 Approve / Comment / Request Changes（PR-Agent 语义）；reviewer 平时 Comment-only，仅 changes_required 升 Request Changes，合入权威归门禁与集成 agent。
9. **finding 双轴结构化**：每条 `{file, start_line-end_line, severity(blocker/should-fix/nit), category(security/logic/contract/test), confidence}`——severity 定裁决、category 定返工分工、低 confidence 强制标注"未验证假设"且不触发 REWORK（CodeRabbit 四轴思想：nit 可以是 security，critical 可以不值得修）。
10. **行级锚定与建议块**：行评论只锚 `+` 行，可修的给 ```` ```suggestion ```` 一键采纳块；nit 一律 `(non-blocking)` 装饰（Conventional Comments），REWORK 清单由机器解析 blocking 标签生成——评论与阻断解耦（reviewdog fail-level 思想：只有 blocker>0 才改裁决）。
11. **APPROVE 必附验证证据段**：固定 Evidence 段（跑过的命令+退出码+关键输出摘录；对抗性边界实验进这里），缺证据=无效审查（claude-code-action allowed_tools 白名单模式）。
12. **prompt 硬规则抄 PR-Agent**：只审本 PR 引入的问题、每条问题附具体触发场景、"prefer not reporting over guessing"、禁寒暄禁夸大。
13. **防橡皮图章用验证轨迹而非问题数量**：业界无强制"至少 N 条问题"（只会造噪音）；改为对 diff 最高风险点复述行为/做边界实验留轨迹，审查绑定具体 commit SHA，新 push 自动失效重审（Copilot approve 撤销机制）。
14. **大 diff 降维**：超阈值先输出 `can_be_split` 拆分建议（Graphite 小 PR 哲学），或非关键文件降 Lite 档只查明显 bug/安全。

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| 网络单点（国内到 GitHub 波动） | 断网降级回本地 closeout（§4）；规范已有 443/22 排查手册 |
| 周期拉长（push/PR/merge/sync 往返） | FAST_PATCH 豁免；快门/全门分层（§8.2） |
| 公共仓库发布面 | pre-push 卫生检查；不贴内部坐标；secrets 禁令沿用 |
| 审查橡皮图章化 | 独立性 + 对抗性验证强制（§9.3/§9.7） |
| 双平面权威混乱 | 明确：PR 合入后以远端为准回拉同步；合入前本地 main 为工作镜像 |
| merge 方式破坏线性历史 | branch protection 锁 rebase-merge + Require linear history（§7.1） |
| 双集成权威 SHA 分叉 | 单一权威=GitHub；FAST_PATCH 走 bypass 直推（§4） |

## 11. 调研附录（2026-09-17 两路定稿）

**门禁与合入队列**：[SHIP/SHOW/ASK](https://martinfowler.com/articles/ship-show-ask.html) · [GitHub merge queue](https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue) · [bors-ng](https://github.com/bors-ng/bors-ng) · [Mergify merge queues](https://mergify.com/blog/the-origin-story-of-merge-queues) · [Zuul gating](https://zuul-ci.org/docs/zuul/latest/gating.html) · [Chromium CQ design](https://www.chromium.org/developers/testing/commit-queue/design/) · [commit statuses API](https://docs.github.com/rest/commits/statuses) · [self-hosted runner 安全](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/about-self-hosted-runners) · [jvns：rebase 的坑](https://jvns.ca/blog/2023/11/06/rebasing-what-can-go-wrong/)

**AI code review**：[Qodo PR-Agent](https://github.com/The-PR-Agent/pr-agent)（[reviewer prompts 全公开](https://github.com/Codium-ai/pr-agent/blob/main/pr_agent/settings/pr_reviewer_prompts.toml)）· [CodeRabbit findings 四轴](https://docs.coderabbit.ai/change-stack/findings) · [Copilot code review](https://docs.github.com/en/copilot/using-github-copilot/code-review/using-copilot-code-review)（Comment-only 默认+approve 撤销）· [claude-code-action](https://github.com/anthropics/claude-code-action)（allowed_tools 可执行验证）· [reviewdog](https://github.com/reviewdog/reviewdog)（filter-mode/fail-level 评论与阻断解耦）· [Conventional Comments](https://conventionalcomments.org/) · [Google eng-practices](https://google.github.io/eng-practices/review/reviewer/standard.html) · [Graphite](https://graphite.com/docs)（小 PR/can_be_split）

## 12. PR 审查自动激活与审查队列（2026-09-17 增补）

需求：PR 一创建/更新即自动触发独立审查，无需人工派发；审查串行排队，防止多个 reviewer 并发争抢本机资源与 LLM 通道。

### 12.1 触发机制选型

| 方案 | 结论 |
|---|---|
| GitHub webhook → 本地端点 | 需内网穿透/暴露端口，安全面大，否决 |
| GitHub Actions `pull_request` 事件 | 费 Actions 分钟；云端无本地门禁上下文，语义审查仍要回到本地，否决 |
| **本地轮询 watcher（选定）** | `pythonw` 常驻、无可见控制台（遵守无控制台红线），60s 级轮询 `gh pr list --state open`，事件语义由状态差分得出 |

状态差分事件：`opened`（新 PR 出现）、`synchronize`（HEAD SHA 变化=新 push）、`ready_for_review`（draft 转正）、`closed/merged`（移除队列项）。去重键 = `(PR number, HEAD SHA)`——同 SHA 的重复触发合并为一个任务；新 push 顶替同 PR 的旧任务。

### 12.2 队列设计（防并发）

- **单飞锁**：锁文件（PID+心跳）保证同一时刻只有一个 review 在跑；并发度默认 1、可配（审查是 LLM 重载任务，本机串行最稳）。
- **任务即文件**：队列目录下一个任务一个 JSON 文件（入队时间/pr/sha/重试计数/状态）；崩溃后重启按文件恢复，锁心跳超时视为死锁可安全接管。
- **失效重审**：新 push 时自动 dismiss 该 PR 上针对旧 SHA 的 review（Copilot approve 撤销语义），重入队新 SHA。
- **重试与死信**：审查进程失败重试 N 次（指数退避），超限进 dead-letter 并在队列状态中可见。
- **全程留痕**：enqueued / started / verdict / completed / failed 每步一行结构化日志（不含 secret）。

### 12.3 审查执行隔离

- 每个任务在临时 worktree `.worktrees/pr-review-<pr>` 检出到目标 SHA 执行，结束清理；绝不碰根 `main`。
- 过滤：只认本流程的 PR（`codex/*` 分支前缀或 `show:`/`ask:` 标题前缀）；draft 默认等到 ready 再审（可配为也审）。
- watcher 保持"哑"：只做轮询、队列、机械检查（diff 统计、`ci/local-verify` status 是否已打）与结果发布；**语义审查交给 reviewer agent 子进程**（常设 rubric + Evidence 段，产出 Approve/Comment/Request Changes + Conventional Comments）。reviewer 智能来源二选一（落地时定）：headless CLI agent 子进程，或 Vibelution 产品自身 agent 会话 API。
- 与门禁协同：`ci/local-verify` 缺失时审查照跑，但意见中标注"缺本地验证证据"；merge 由 branch protection 的 required check 挡，不靠 reviewer 自觉。

### 12.4 配置默认值

轮询间隔 60s；并发度 1；重试 3 次；draft=等 ready；分支过滤 `codex/*`。均可用环境变量/配置覆盖。

## 13. 方向修订（2026-09-17）：本地集成权威 + GitHub 发布镜像

用户拍板：git 管理全部本地完成，GitHub 仅作发布存储站。本节取代 §4 的"单一集成权威=GitHub"与 §12.1 的 gh 轮询触发；SHIP/SHOW/ASK 分级（§4）、门禁分层（§8）、审查规范（§9）、队列设计（§12.2）全部保留，仅换宿主。

### 13.1 本地合并请求（Local Merge Request, LMR）

PR 的本地等价物是一份登记记录，存 `.git` common-dir 下的 ledger（进程工件，不进仓库树）：

- 字段：branch、HEAD SHA、base、标题/任务包引用、证据 manifest 路径、分级（show/ask）、状态机 `pending_review → in_review →（rework → pending_review）* → approved → merging → merged / rejected`、审查记录（verdict + findings + Evidence 段）、时间戳。
- 生命周期：Worker 本地门禁跑完 → 登记 LMR → watcher 自动入队审查 → APPROVE → 集成收口（stale_main 合并 + 快门复跑 + ff-only 合入本地 `main`，即现行 task_closeout 机制原封不动）→ 清理 → 进入待发布队列；REWORK → 返工信封回 Worker。

### 13.2 组件映射（GitHub PR → 本地）

| GitHub PR 概念 | 本地等价 |
|---|---|
| PR 对象 | LMR ledger 记录 |
| push 新 commit | branch SHA 变化 → 顶替任务 + 作废旧 verdict |
| review / 行评论 | findings（file+行号+severity+category+confidence）写入 LMR |
| required checks | closeout 门禁 + 证据 manifest（机器可验） |
| approve 撤销 | 新 SHA 自动作废旧 verdict（§12.2） |
| merge button | task_closeout ff-only 合入本地 `main`（现状机制） |
| 平台可见性 | 本地状态/汇总命令；发布后 GitHub 即镜像 |
| branch protection | 不需要（合入权在本地集成 agent + 审查门） |

### 13.3 发布（GitHub = 存储站）

- 集成完成后 `main` 进入待发布队列；发布 = `git push origin main`（策略待拍板：每任务即推 / 定量定时批推 / 手动指令）。
- 无双权威分叉：本地 `main` 唯一权威，`origin/main` 为镜像；远端默认不留任务分支。

### 13.4 剩余待拍板 / 待建

- 待拍板：①发布策略（建议：定量批推 + 手动即推并存）；②FAST_PATCH 是否豁免 LMR（建议豁免，维持本地直合）。
- 待建（三角色流水线，互相独立可并行）：①LMR ledger 与生命周期脚本（登记/查询/状态流转/作废旧 verdict）；②`pr_review_watch.py` 改监听本地 ledger（零网络，其余 §12 设计不变）；③审查 verdict 写入 LMR + 状态汇总命令；④发布队列脚本（批推 + 推送卫生检查）。
