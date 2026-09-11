# 实例存储 retention

**用途：** 回收项目根已不存在的实例目录，控制 `%LOCALAPPDATA%\Vibelution\projects\` 的长期占用。
**工具：** [`scripts/prune_instance_storage.py`](../../scripts/prune_instance_storage.py)（默认 dry-run）。

---

## 为什么会有这些目录

实例存储按**项目根路径**的哈希命名：

```text
%LOCALAPPDATA%\Vibelution\projects\<projectId>\instances\<instanceId>\
├── data\      # workspace：agents / chat / memory / prompts / research / agent_brain.db
├── runtime\   # runtime-manager：state.json、事件、hot-restart/stable-backups（每实例保留 3 份）
├── logs\      # 会话日志等
└── cache\     # quality_gates 等
```

每个任务 worktree 都是独立根，因此各自产生**一份完整实例存储**。worktree 被 `git worktree remove`
或 `task_closeout.py` 清理后，Git 侧没有残留，但这块存储没有任何东西回收——它不在仓库内，
`branch_instance_cleanup.py` 只清分支实例的 worktree/分支/注册表条目，不删实例存储。

2026-09-11 本机观测：1675 个实例目录 / 5.4GB，其中约 78 个是当天新增。

---

## 判定证据（默认只回收可确证的）

| 判定 | 依据 | 默认动作 |
| --- | --- | --- |
| `dead` | `runtime\runtime-manager\state.json` 记录的 `projectRoot` 已不存在，且无存活 runtime-manager 进程 | **回收** |
| `unproven_stale` | 无根记录，最后写入早于 `--include-unproven-older-than-days N` | 仅显式加参数才回收 |
| `unproven` | 无根记录（例如只写过 `cache\quality_gates`） | 保留并报告 |
| `live` | 记录的 `projectRoot` 仍存在 | 保留 |
| `daemon_alive` | 根已不存在，但记录的 `managerPid` 仍是存活的 runtime-manager 进程 | 保留 |
| `protected` | 等于脚本运行所在 checkout 自己的实例目录 | 永不触碰 |

---

## 用法

```powershell
# 1) 先看报告（默认 dry-run，不删任何东西）
.\.venv\Scripts\python.exe scripts\prune_instance_storage.py

# 2) 机器可读（JSON 为 ASCII，便于脚本消费）
.\.venv\Scripts\python.exe scripts\prune_instance_storage.py --json

# 3) 回收确证死亡的实例
.\.venv\Scripts\python.exe scripts\prune_instance_storage.py --apply

# 4) 追加按龄回收不可确证项（确认报告无误后再用）
.\.venv\Scripts\python.exe scripts\prune_instance_storage.py --apply --include-unproven-older-than-days 30

# 只看某个项目
.\.venv\Scripts\python.exe scripts\prune_instance_storage.py --project-id ccdawn-vibelution
```

**边界与注意事项**

- 默认只处理 `<projects_home>/<项目>/instances` 的直接子目录；跳过链接 / junction，不跟随删除。
- `dead` 判定依赖根路径「不存在」。若根位于可移动盘或网络盘，**执行 `--apply` 前先确认盘已挂载**，
  否则该盘上的实例会被误判为可回收（dry-run 报告会逐条列出根路径，供核对）。
- `--apply` 是破坏性操作：删除的是实例的 workspace 数据、运行日志与 hot-restart 备份，不可恢复。
  先 dry-run 核对，再执行。
- 迁移前备份目录（如 `<instance>.pre-legacy-apply-backup-<date>`）不在本工具命名空间内，
  需要时单独确认后清理。

---

## 关联

- 存储路径契约：[`vibelution_storage.py`](../../vibelution_storage.py)
- 分支实例清理（worktree/分支/注册表）：[`core/launcher/branch_instance_cleanup.py`](../../core/launcher/branch_instance_cleanup.py)
- 日志与运行态 retention 先例：[`scripts/prune_logs.py`](../../scripts/prune_logs.py)
- 任务 worktree 协作与残留处理：[`../agents/worktree-collaboration.md`](../agents/worktree-collaboration.md)
