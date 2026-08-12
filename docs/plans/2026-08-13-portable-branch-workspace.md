# 便携分支工作区：仓内 `.worktrees` + Launcher 全部分支

> **状态**：草案，供继续优化。升格 ADR / 写入 `docs/standards/` 之前，**不覆盖** `AGENTS.md` 与现行协作规范。
> **日期**：2026-08-13
> **触发**：Launcher 首屏只能看见当前 checkout；「多分支管理」与「统一到一个文件夹」需要一份对**任意用户部署**成立的目录契约，而不是本机 Desktop/junction。
> **2026-08-13 校准**：监督进化发现优秀子树后，**整树晋升到现在的 `main`**；**所有流程必须在 Git 管辖内**（worktree / merge / ref / revert），禁止拷文件、换目录、junction 当晋升。
> **相关**：[2026-08-11 多实例按分支隔离](2026-08-11-multi-instance-branch-isolation.md)（P1 注册表 / P2 CLI；本文补目录契约 + Launcher 清单 + Git 晋升）。实现半成品在分支 `codex/multi-instance-branch-isolation`。

---

## 1. 要解决什么

1. Launcher 进程表只描述**当前这一个** checkout，看不到其他分支/worktree。
2. 任务 checkout 现在落在仓库**外面**的兄弟目录 `<parent>/Vibelution-worktrees/`。拷贝项目、换盘、换用户、两个仓库共用一个父目录，都会丢分支或抢同一文件夹。
3. 本机已有大量注册 worktree、本地分支、以及摘除 worktree 后的空壳目录。没有产品级清单，也无法安全地按行启停。
4. 监督进化已能把「评过的文件」拷进 `main`，但这不是 Git merge，也不是「整棵优秀子树变成 main」。

**成功时**：任何用户只要有一个项目根（clone 或安装目录），就能在同一相对布局下看到全部分支；优秀子树经 Git 合入后，集成根仍是 `main`、内容变成那棵树；换机器不必改路径。

---

## 2. 目标 / 非目标

### 目标

- 一个用户可见文件夹 = 一次 clone / 一次 `--project` / 一次安装根。
- 该根始终停在本地 `main`（集成区）。不把 `main` 再塞进子目录。
- 全部分支 checkout 进入这个根下面的唯一分支池。
- 路径只从 Git 与项目根推导，禁止用户名、Desktop、盘符常量。
- Launcher 首屏列出**全部** Git 分支实例（活 worktree、未 checkout 的本地分支），点中一行再看该实例进程。
- 监督进化（或人工）认定优秀后：**整棵子树经 Git 晋升到集成根的 `main`**，再激活运行时。
- **所有身份与切换都在 Git 管辖内**：创建用 `git worktree`，晋升用 `merge`/`ff-only`，回滚用 `revert` 或可审计的 git 操作。禁止把子树目录改名为 main、禁止拷文件当合入、禁止 junction 当契约。
- 本机迁移与其他用户的「空仓新建」走同一套规则。

### 非目标（本草案默认不做，可在第 10 节改）

- 把安装根从 `main` 改成某个子文件夹，或把优秀 worktree 的路径变成新的 `--project` 根。
- 一次性给每个远程分支建 checkout。
- 第一刀就做每行启动/停止（依赖端口隔离，见第 8 节）。
- 删除无 `.git` 的残留目录（先隔离出产品主路径，它们本来就不在 Git 管辖内）。
- 本机专用 junction / 快捷方式当契约。
- 继续用现行按文件清单拷贝再 commit 作为本流程的晋升机制（见第 7 节）。

---

## 3. 目录契约（建议稿）

```text
<project-root>/                      # clone / 安装 / --project；必须是 main
  .git/
  web/  core/  scripts/  ...
  .worktrees/                        # 唯一分支池；gitignore
    <slug>/                          # 活 git worktree
    _retired/                        # 已摘除、无 .git 的残留
```

| 角色 | 路径 | 说明 |
| --- | --- | --- |
| 集成根 | `<project-root>` | `git rev-parse --show-toplevel` 且分支为 `main` |
| 分支池 | `<integration-root>/.worktrees` | 所有用户同一相对路径 |
| 任务实例 | `.worktrees/<slug>` | slug 与今日任务分支对应 |
| 退役 | `.worktrees/_retired/<slug>` | 列表可见，默认不可启动、不可晋升 |
| 未打开分支 | 仅 Git ref | 列表一行，状态 `not_checked_out` |

旧路径 `<integration-root 的父目录>/Vibelution-worktrees` 只作只读兼容：发现则提示迁移，不再作为新 worktree 的写入目标。

---

## 4. 解析算法（唯一权威，建议实现）

输入：当前进程所在 checkout（`PROJECT_ROOT` 或 `--project`）。

```text
1. git -C <checkout> rev-parse --git-common-dir
2. common-dir 的上级（剥掉 .git 或 .git/worktrees/<id>）→ integration_root
3. branch_pool = integration_root / ".worktrees"
4. 若 checkout == integration_root → 角色 = main
   若 checkout 位于 branch_pool 下且不是 _retired → 角色 = task
   若 checkout 位于旧兄弟目录 Vibelution-worktrees → 角色 = legacy_task（兼容）
5. 清单扫描：
   - git worktree list --porcelain
   - git for-each-ref refs/heads
   - branch_pool 与 legacy 兄弟目录的一级子目录（无 .git 的只标 retired）
   - 每个 checkout 的 .runtime/launcher/state.json（有则填端口/PID/observedState）
```

禁止：`Path.home()`、`Desktop`、硬编码用户目录、硬编码仓库名当父路径。

现有写入点需改到此函数（升格后）：

- `core/launcher/developer_mode.py` 的 `_worktrees_root`
- `docs/agents/worktree-collaboration.md` / `docs/standards/development-standard.md` 的 worktree 命令
- `scripts/vibelution_launcher.py` 里旧 worktrees 路径文案
- 质量门 / Agent 创建 worktree 的脚本说明

---

## 5. 清单数据（Launcher 看到什么）

| 字段 | 来源 |
| --- | --- |
| `id` | 稳定 id：`main` / `worktree:<slug>` / `branch:<name>` / `retired:<slug>` |
| `kind` | `main` / `worktree` / `local_branch` / `retired` |
| `branch` | 当前分支或 ref 名；detached 标 `detached` |
| `path` | 绝对路径（运行用）+ 相对集成根的展示路径 |
| `head` | 短 SHA |
| `alive` | 该目录 `.runtime` 观察：backend/window 是否活 |
| `port` / `pids` | 有 state 才填 |
| `legacy` | 是否仍在旧兄弟目录 |
| `promotable` | 是否满足第 7 节门禁（Git worktree、有 commit、非 dirty） |

**「全部分支」定义（草案）**：本地 `refs/heads/*` + `git worktree list` 中的全部 checkout。这才是 Git 管辖内的全集。
无 `.git` 的残留目录不是分支，只进 `_retired` / 高级清理，不能晋升。不含未 fetch 的纯远程分支，除非第 10 节改为包含。

---

## 6. Launcher 首屏（P3 草案）

```text
[顶栏] 生命周期 · 启动/停止/打开          ← 只作用于「当前选中实例」，默认 main
[分支实例] 表格：分支 · 状态 · 端口 · 路径
           当前选中行高亮
[进程监控] 选中实例的子进程 / 残留进程
[启动设置] 窗口 / 档位 / 端口
[高级]     维护 / 沙盒 / 诊断
```

第一刀只读：列表 + 选中展开进程。不在未完成端口隔离时提供「启动该分支」。

选中优秀子树后的主操作是 **晋升到 main**（第 7 节），不是把 Launcher 的 `--project` 指到那棵子树。

---

## 7. Git 管辖与整树晋升（已校准）

用户可见效果：监督进化（或操作者）发现优秀子树，然后切换到它。
磁盘与 Git 上的含义：集成根路径不变，分支名仍是 `main`，`main` 的树变成那棵子树的树。

### 7.1 为什么必须在 Git 里

| 做法 | 是否 Git 管辖 | 本草案 |
| --- | --- | --- |
| `git worktree add/move/remove` | 是 | 创建/迁移/退役 |
| `git merge --ff-only` 或受控 merge 到 `main` | 是 | 默认晋升 |
| `git revert` 晋升提交 | 是 | 回滚 |
| 现行按 `changed_files` 拷到 main 再 commit | 提交在 Git，内容不经 merge | 本流程弃用 |
| 把 worktree 目录改成新的项目根 / 对调文件夹 | 否 | 禁止 |
| junction 当权威 | 否 | 禁止 |
| `%LOCALAPPDATA%\instances.json` | 否（运行观察） | 只记端口/PID，不决定谁是 main |

`main` 是 ref，不是文件夹名字。别的用户 clone 到任何路径，拉到同一个 `main` 就是同一棵树。

### 7.2 晋升算法（建议）

前置（全部失败则停，不写 main）：

- 集成根当前分支是 `main`
- 集成根工作区干净
- 无活动任务，或先收口再晋升
- 候选是已注册 git worktree（或至少有可解析的 commit），不是 `_retired`、不是无 `.git` 空壳
- 候选工作区干净：未提交改动不在 Git 里，不能晋升
- 候选 HEAD 仍等于评测/审批冻结的 commit（或明确再授权）
- 监督进化：审批/Judge 已通过（沿用现有 run 快照）

Git 步骤（只在集成根上操作）：

```text
1. 记录 old_main = git rev-parse main
2. 候选未提交的已跟踪/已评改动先在子树 commit（不写 main）
3. fetch 候选 HEAD 进集成根 refs/vibelution/supervised-promote
4. 优先：git merge --ff-only <candidate>
   不能快进：commit-tree(候选树, -p old_main -p candidate) 再 ff 该 merge
   结果树必须等于候选 HEAD 树；main 上独有提交不保留
   失败：中止，不在 main 上留下冲突文件；回子树修完再晋升
5. 禁止：git reset --hard <candidate> 作为日常路径
6. 禁止：checkout 任务分支到集成根
7. 新 HEAD 记入 run / Launcher 证据；再排队 runtime 激活
8. 候选 worktree：默认保留对照；或 git worktree remove
```

回滚：对晋升产生的 merge/ff 提交做 `git revert`，不要 `reset --hard` 公共 main。

### 7.3 和现行监督合入的差

现行 `integrate_candidate`：干净 main + HEAD 等于 checkpoint → 拷清单文件 → 一条 evolve 提交。

本流程要换成：同一门禁，晋升机制改为 Git merge 整棵树。

- 子树里所有已提交内容都上 main，不依赖 changed_files 是否写全
- 历史可 log / revert，证据在对象库里
- 未提交改动不能晋升（先在子树 commit，或拒绝）

若某次监督运行仍然只想合入评过的文件子集，那是另一条显式「补丁晋升」通道，默认不走。

### 7.4 入口

- 监督进化审批通过 → 同一整树晋升服务（owner：监督合入 facade，不在 route 里写 git）
- Launcher 分支列表：优秀/可晋升行给「晋升到 main」（需确认）；普通任务 worktree 不自动晋升
- 晋升不是「启动该分支当第二套 main」

---

## 8. 与多实例启停的关系

[08-11 方案](2026-08-11-multi-instance-branch-isolation.md) 已定端口注册表与 CLI。

- `%LOCALAPPDATA%\Vibelution\instances.json` 只协调端口，不决定谁是 main
- 第 3–6 节不依赖该分支合入
- 按行启停必须先有端口隔离
- Operator config 仍按 ADR0003 留在 Documents，不进 `.worktrees`

---

## 9. 迁移程序（可重复，不绑本机）

1. 解析 `integration_root` 与 `branch_pool`。
2. 对 `git worktree list` 中、路径在旧兄弟目录下的活 worktree：`git worktree move` 进池。正在跑的实例先停再迁。
3. 旧兄弟目录里无 `.git` 的一级子目录：移到 `branch_pool/_retired/<slug>`（不删，不能晋升）。
4. 已在池内的不动。`main` 不 move。
5. `.gitignore` 增加 `.worktrees/`。
6. 旧兄弟目录清空后只留兼容提示。

---

## 10. 开放优化点

1. 目录名：`.worktrees` vs `worktrees` vs 仓内 `Vibelution-worktrees`。
2. slug 是否保留 `codex/` 层级。
3. 清单是否含未 fetch 的远程分支。
4. 启动设置绑选中实例还是只改 main。
5. 退役保留多久、可否删除 `_retired` 单项。
6. P1 注册表：变基旧分支 vs 重写。
7. 旧兄弟目录兼容多久。
8. 非 `codex/` 分支是否同等展示。
9. 无 Git 的最终用户是否只显示一行 main（建议：是）。
10. 不能快进时：**已定 merge 优先** — 先 `merge --ff-only`，否则以候选树做 merge commit（不 rebase）。
11. 无 Git 残留是否出现在主列表（建议：只在高级/退役）。

---

## 11. 建议实施阶段

| 阶段 | 内容 | 可单独验收 |
| --- | --- | --- |
| A | 解析函数 + 单测 | 路径不依赖用户名。已落地：`core/infrastructure/branch_workspace.py` |
| B | 清单 API + Launcher 首屏列表 | 条数对得上 worktree list + 本地 ref。已落地：`GET /api/launcher/branch-instances` |
| C | `git worktree move` 迁移 + gitignore | 活 worktree 都在仓内池。已落地：`migrate_legacy_branch_workspaces`，`.gitignore` 含 `.worktrees/` |
| D | 兼容扫描旧兄弟目录 | 新 worktree add 不再写外面。已落地：产品写入点改仓内池，旧兄弟只读兼容 |
| E | 整树晋升服务（替换本流程的拷文件合入） | merge 后 main 树等于候选 HEAD；可 revert |
| F | 文档升格 | 与实现一致后再改规范 |
| G | 端口隔离后的按行启停 | 双实例不同端口 |

A 到 B 让多分支看得见。C 是文件夹统一。E 是优秀子树变成 main。G 单独授权。

---

## 12. 风险与红线

- Windows 无控制台：新 spawn 仍走 `pythonw` / `CREATE_NO_WINDOW`。
- 不在规范升格前让 Agent 按本文改默认 worktree 落点。
- 迁移时跳过正在跑的 checkout。
- `_retired` 隔离不等于删除；不能晋升。
- 注册表只协调端口，main 是 Git ref。
- 晋升禁止 `reset --hard` 公共 main、禁止在集成根 checkout 任务分支、禁止脏子树晋升。
- 冲突必须停在子树里解决，不把冲突工作区留在 main。

---

## 13. 验证（草案）

- 解析：三种输入得到同一 `branch_pool`。
- 清单：worktree 行数等于 `git worktree list`。
- 便携：临时 clone 只有 main，池路径为 `<clone>/.worktrees`。
- 迁移：活 worktree 进池，无 git 文件夹进 `_retired`。
- UI：选中非当前行时进程表跟该行 path 走。
- 晋升：子树独有提交 merge 后出现在 main，且为 ancestor；revert 后离开 main。
- 负例：脏 main、脏子树、无 commit、无 `.git`，晋升失败且 main HEAD 不变。

---

## 14. 权威关系

```text
用户当前要求
  → 本文（优化中的草案）
  → 升格后：ADR（布局决策 + Git 晋升）+ standards / worktree-collaboration
  → 08-11 多实例方案（端口/注册表/启停）
```

在升格完成前：Agent 创建任务 worktree 仍按现行 `AGENTS.md` / `worktree-collaboration.md`。监督进化合入仍走现行拷文件合入，直到阶段 E 落地。
