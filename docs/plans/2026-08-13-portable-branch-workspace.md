# 便携分支工作区：仓内 `.worktrees` + Launcher 全部分支

> **状态**：草案，供继续优化。升格 ADR / 写入 `docs/standards/` 之前，**不覆盖** `AGENTS.md` 与现行协作规范。
> **日期**：2026-08-13
> **触发**：Launcher 首屏只能看见当前 checkout；「多分支管理」与「统一到一个文件夹」需要一份对**任意用户部署**成立的目录契约，而不是本机 Desktop/junction。
> **相关**：[2026-08-11 多实例按分支隔离](2026-08-11-multi-instance-branch-isolation.md)（P1 注册表 / P2 CLI；本文补目录契约 + Launcher P3 清单）。实现半成品在分支 `codex/multi-instance-branch-isolation`。

---

## 1. 要解决什么

1. Launcher 进程表只描述**当前这一个** checkout，看不到其他分支/worktree。
2. 任务 checkout 现在落在仓库**外面**的兄弟目录 `<parent>/Vibelution-worktrees/`。拷贝项目、换盘、换用户、两个仓库共用一个父目录，都会丢分支或抢同一文件夹。
3. 本机已有 24 个注册 worktree、26 个本地分支、61 个兄弟子目录（其中约 38 个是摘除 worktree 后的空壳）。没有产品级清单，也无法安全地按行启停。

**成功时**：任何用户只要有一个项目根（clone 或安装目录），就能在同一相对布局下看到并管理全部分支；换机器不必改路径。

---

## 2. 目标 / 非目标

### 目标

- 一个用户可见文件夹 = 一次 clone / 一次 `--project` / 一次安装根。
- 该根始终停在本地 `main`（集成区）。不把 `main` 再塞进子目录。
- 全部分支 checkout 进入这个根下面的唯一分支池。
- 路径只从 Git 与项目根推导，禁止用户名、Desktop、盘符常量。
- Launcher 首屏列出**全部**分支实例（活 worktree、未 checkout 的本地分支、已退役残留），点中一行再看该实例进程。
- 本机迁移与其他用户的「空仓新建」走同一套规则。

### 非目标（本草案默认不做，可在 §9 改）

- 把安装根从 `main` 改成某个子文件夹。
- 一次性给每个远程分支建 checkout。
- 第一刀就做每行启动/停止（依赖端口隔离，见 §7）。
- 删除退役目录（先隔离）。
- 本机专用 junction / 快捷方式当契约。

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
| 任务实例 | `.worktrees/<slug>` | slug 与今日 `codex/<task-slug>` 对应，目录名不含 `codex/` 前缀（可优化，见 §9） |
| 退役 | `.worktrees/_retired/<slug>` | 列表可见，默认不可启动 |
| 未打开分支 | 仅 Git ref | 列表一行，状态 `not_checked_out` |

旧路径 `<integration-root 的父目录>/Vibelution-worktrees` 只作**只读兼容**：发现则提示迁移，不再作为新 worktree 的写入目标。

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
   - branch_pool 与 legacy 兄弟目录的一级子目录
   - 每个 checkout 的 .runtime/launcher/state.json（有则填端口/PID/observedState）
```

禁止：`Path.home()`、`Desktop`、`C:\Users\...`、硬编码仓库名当父路径。

现有写入点需改到此函数（升格后）：

- `core/launcher/developer_mode.py` 的 `_worktrees_root`
- `docs/agents/worktree-collaboration.md` / `docs/standards/development-standard.md` 的 worktree 命令
- `scripts/vibelution_launcher.py` 里 `--project ...\Vibelution-worktrees\<slug>` 文案
- 质量门 / Agent 创建 worktree 的脚本说明

---

## 5. 清单数据（Launcher 看到什么）

每行建议字段（可增减）：

| 字段 | 来源 |
| --- | --- |
| `id` | 稳定 id：`main` / `worktree:<slug>` / `branch:<name>` / `retired:<slug>` |
| `kind` | `main` \| `worktree` \| `local_branch` \| `retired` |
| `branch` | `git branch --show-current` 或 ref 名；detached 标 `detached` |
| `path` | 绝对路径（运行用）+ 相对集成根的展示路径 |
| `head` | 短 SHA |
| `alive` | 该目录 `.runtime` 观察：backend/window 是否活 |
| `port` / `pids` | 有 state 才填 |
| `legacy` | 是否仍在旧兄弟目录 |

本机量级参考（2026-08-13 探测，会变）：注册 worktree 24；本地分支 26（5 个无对应 worktree，其中 3 个目录仍在但是 detached）；兄弟目录 61，约 38 个无 `.git`。

**「全部分支」定义（草案）**：本地 `refs/heads/*` + 所有已注册 worktree + 分支池/旧池里无 git 的残留。不含未 fetch 的纯远程分支，除非 §9 改为包含。

---

## 6. Launcher 首屏（P3 草案）

```text
[顶栏] 生命周期 · 启动/停止/打开          ← 只作用于「当前选中实例」，默认 main
[分支实例] 表格：分支 · 状态 · 端口 · 路径
           当前选中行高亮
[进程监控] 选中实例的子进程 / 残留进程
[启动设置] 窗口 / 档位 / 端口（当前选中或仅 main，见 §9）
[高级]     维护 / 沙盒 / 诊断
```

第一刀只读：列表 + 选中展开进程。不在未完成端口隔离时提供「启动该分支」。

---

## 7. 与多实例启停的关系

[08-11 方案](2026-08-11-multi-instance-branch-isolation.md) 已定：

- 实例 id：`<project-slug>--<branch-slug>`
- 全局注册表：`%LOCALAPPDATA%\Vibelution\instances.json`（跨项目端口协调，**这个**放用户目录是对的，和仓内 checkout 不是一回事）
- P1 注册表 + 端口分配、P2 CLI 已在 `codex/multi-instance-branch-isolation`，未合入 `main`
- 原 P3「Launcher 多项目页」= 本文 §6

建议依赖：§3–§6 不依赖该分支合入；**按行启停**必须先合入或重做 P1 端口隔离，否则多用户部署一样会抢 8000/8765。

Operator config 仍按 ADR0003 留在 `%USERPROFILE%\Documents\Vibelution\config\`，不进 `.worktrees`。

---

## 8. 迁移程序（可重复，不绑本机）

对**任意**已有仓库执行同一脚本/清单：

1. 解析 `integration_root` 与 `branch_pool`。
2. 对 `git worktree list` 中、路径在旧兄弟目录下的**活** worktree：`git worktree move <old> <branch_pool>/<slug>`。正在跑的实例先停再迁。
3. 旧兄弟目录里无 `.git` 的一级子目录：移到 `branch_pool/_retired/<slug>`（不删）。
4. 已在 `branch_pool` 内的不动。
5. `main` 不 `worktree move`。
6. `.gitignore` 增加 `.worktrees/`。
7. 迁移后扫描：若旧 `Vibelution-worktrees` 已空，只留 README 提示「已迁到仓内 .worktrees」或保留空目录一版兼容。

本机只是该程序的一个输入，不是另一套规则。

---

## 9. 开放优化点

改草案时优先改这一节，并回写上面各节。

1. **目录名**：`.worktrees`（隐藏）vs `worktrees`（可见）vs 保留产品名 `Vibelution-worktrees` 但改为仓内子目录。
2. **slug**：目录用 `agent-session-...` 还是保留 `codex/` 层级（Windows 允许，工具链是否讨厌）。
3. **清单是否含 `origin/*` 未 fetch 本地的远程分支**。
4. **启动设置**绑选中实例还是永远只改 `main` 的 operator/workbench 配置。
5. **退役保留多久**、要不要在高级里提供「删除 _retired 中某一项」。
6. **P1 注册表合入策略**：变基 08-11 分支 vs 按新路径重写一份更小的注册表。
7. **旧兄弟目录兼容多久**：一个大版本 / 直到扫描为零。
8. **嵌套 worktree / 非 `codex/` 分支**（如 `test/slot-supervisor-s1s8-b`）是否与任务 worktree 同等展示。
9. **便携安装（无 Git）**：最终用户只有 `main`、没有 `.worktrees` 时，列表是否只显示一行 `main`（建议：是）。

---

## 10. 建议实施阶段

| 阶段 | 内容 | 可单独验收 |
| --- | --- | --- |
| A | 解析函数 + 单测（含「checkout 在 worktree 内也能找到池」） | 路径不依赖用户名 |
| B | `GET` 清单 API + Launcher 首屏列表（全部分支） | 条数对得上 §5 |
| C | 迁移程序 + `.gitignore`；本机跑一遍 | 活 worktree 都在仓内池 |
| D | 兼容扫描旧兄弟目录并提示 | 新 `worktree add` 不再写外面 |
| E | 文档升格：协作规范 / 开发标准 / Launcher 文案 | 与实现一致后再改规范 |
| F | 合入或重做端口隔离后，按行启停/聚焦 | 双实例不同端口 |

A→B 即可让「多分支管理」在 UI 上成立。C 是「统一到一个文件夹」。F 单独授权。

---

## 11. 风险与红线

- Windows 无控制台：新 spawn 仍走 `pythonw` / `CREATE_NO_WINDOW`。
- 不在规范升格前让 Agent 按本文改默认 worktree 落点（避免双源）。
- 迁移时跳过正在跑的 checkout（本机曾有 `slot-supervisor-registry` Electron）。
- `_retired` 可能含未提交文件，隔离 ≠ 删除。
- 注册表在 `%LOCALAPPDATA%` 是跨项目端口协调，不是 checkout 权威。

---

## 12. 验证（草案，实施时再收成测试）

- 解析：集成根、池内 worktree、旧兄弟路径三种输入，得到同一 `branch_pool`。
- 清单：`worktree` 行数 = `git worktree list`；`local_branch` 含无 checkout 的 ref；残留在 `retired`。
- 便携：在临时目录 `git clone` + 空 `.worktrees`，列表只有 `main`，池路径为 `<clone>/.worktrees`。
- 迁移：假兄弟目录里一个活 worktree + 一个无 git 文件夹，跑完分别在池内与 `_retired`。
- UI：选中非当前行时进程表跟该行 path 走，而不是死盯 Launcher 自己的 checkout。

---

## 13. 权威关系

```text
用户当前要求
  → 本文（优化中的草案）
  → 升格后：ADR（布局决策）+ standards / worktree-collaboration（操作命令）
  → 08-11 多实例方案（端口/注册表/启停）
```

在升格完成前：Agent 创建任务 worktree 仍按现行 `AGENTS.md` / `worktree-collaboration.md`（兄弟目录 `Vibelution-worktrees`）。
