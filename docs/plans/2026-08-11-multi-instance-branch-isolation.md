# 多实例架构：按分支隔离 + Launcher 多项目管理（块B）

> 状态：方向已对齐（2026-08-11），待立项
> 前置：块A（daemon 单例守卫 / orphaned 清理上限 / 粘性消息清除）已提交
> 触发背景：2026-08-11 工作台事故——单目录内两套 Launcher/daemon 实例并发，
> 后端 24808 被挤到 8002 而观察/窗口仍指向 8000，daemon 判孤儿强制关窗。

## 目标

1. 多个实例可并存：每个 (项目, 分支) 是一个独立 worktree 目录实例
2. 每个实例 = 唯一 backend + 唯一前端窗口，一对一绑定
3. Launcher 负责管理多个项目/实例：托盘 + CLI 级（第一版）
4. 后端端口自动分配，冲突时迁移而非崩溃

## 现状（已探明）

- `vibelution_launcher.py` 已支持 `--project <目录>`（含 git 根校验防跨 checkout）
- 每个目录实例已有自己的 `.runtime/runtime-manager/`（daemon/state/events）与
  `.runtime/launcher/state.json`——**目录级隔离天然成立**
- 块A1 已修"单目录内双 daemon 竞态"
- 缺口：无跨目录实例注册表；端口分配有 `preferredBackendPort` 但 URL/观察未同步
  （8002 backend + 8000 观察 = 本次事故）；无托盘/CLI 多实例入口

## 设计

### 1. 实例标识与注册表

- 实例 ID：`<project-slug>--<branch-slug>`（如 `vibelution--main`、`vibelution--chat-fix`）
- 注册表：`%LOCALAPPDATA%\Vibelution\instances.json`（全局，跨项目）
  ```json
  {
    "schemaVersion": 1,
    "instances": {
      "<instanceId>": {
        "projectRoot": "C:\\...\\Vibelution-worktrees\\chat-fix",
        "branch": "chat-fix",
        "commit": "abc123",
        "port": 8001,
        "url": "http://127.0.0.1:8001",
        "backendPid": 0,
        "browserWindowPid": 0,
        "status": "running|closed|failed",
        "startedAt": "ISO",
        "lastHealthyAt": "ISO",
        "windowBindings": { "browserWindowPid": 0, "backendPid": 0 }
      }
    }
  }
  ```
- 写者：Launcher（open/close/restart 命令时更新）；读者：daemon（观察）、托盘、CLI
- 原子写（复用 `_atomic_write_json` 模式），跨实例进程并发写同一注册表

### 2. 端口自动分配

- 基线 8000；`allocate_port()`：扫描注册表已用端口 + `netstat` 实测，
  取第一个空闲；分配后写注册表
- backend 搬迁：现有 `preferredBackendPort` 机制保留，搬迁成功后**必须回写
  注册表 url/port 并同步窗口 URL**（本次事故直接缺口）

### 3. 窗口↔后端一对一绑定

- open 流程：Launcher spawn backend（指定端口）→ 注册表写
  `bindings.backendPid` → 开窗口 → 注册表写 `bindings.browserWindowPid`
- daemon 观察：以注册表绑定对校验（backend 消失 → 提示重建/自动迁移端口，
  不直接判孤儿关窗）；孤儿判定仅保留"绑定对双方都不存在"的场景
- 意外情形：backend 搬迁后观察与 URL 不一致 → 迁移而非关闭

### 4. Launcher 托盘/CLI（第一版）

- CLI（`vibelution_launcher.py` 新子命令）：
  - `instances list`：所有实例（id/项目/分支/端口/状态/窗口 pid）
  - `instances start --instance <id> [--no-browser]`
  - `instances stop --instance <id>`
  - `instances focus --instance <id>`（窗口前置）
- 托盘：列出实例（项目/分支/端口/状态），点击聚焦；启停走既有生命周期命令
- Launcher UI 多项目页：后置（P3）

### 5. 单目录内单例（块A1 已交付）

- daemon 启动 settle 窗口 + 单例锁：同目录并发启动只有一个存活

## 阶段划分与验收

| 阶段 | 内容 | 验收 |
| --- | --- | --- |
| P1 | 注册表模块 + 端口分配 + 搬迁后 URL/观察同步 | 两个 worktree 实例同启互不干扰；8000 被占时实例 B 自动 8001 且窗口/观察一致；单测覆盖注册表并发写与端口分配 |
| P2 | CLI list/start/stop/focus + 托盘集成 | 双实例启停/聚焦全程无孤儿误判；无控制台弹窗（pythonw/CREATE_NO_WINDOW） |
| P3 | Launcher UI 多项目页 | 列表/启停/日志（后置，另行立项） |

## 风险与红线

- Windows 无控制台：所有新 spawn 走 pythonw / CREATE_NO_WINDOW（块A 未触碰）
- 注册表并发写：原子写 + 读重试；跨实例进程不共享内存
- 不改变既有单实例路径的行为（单实例 = 注册表里一个条目）
- 端口安全：仅本机回环绑定；不开放外网
- 全部改动先在任务 worktree 上做（多目录实例的集成验证需要真实 worktree）
