# 07 · Launcher / Runtime / Workbench

## `[launcher]`

Launcher 控制面为 **Electron 主进程 IPC**（[ADR 0009](../../adr/0009-launcher-control-plane-lives-in-electron-main.md)），控制窗口不再走 `http://127.0.0.1:8765`；Python `:8765` 控制面已退役。工作台仍为 Python FastAPI + Runtime Manager（常见 `:8000`）。

生命周期命令以开发标准为准：

```text
%LOCALAPPDATA%\Vibelution\Launcher\VibelutionLauncher.exe --project "<root>" start|stop|restart
```

C# shim 在 packaged Electron 存在时把命令转发给 Electron（second-instance）；仅开发 checkout（无 `dist\desktop\win-unpacked\Vibelution.exe`）保留 legacy Python 路径与 WinForms 托盘。

或 `scripts/vibelution_launcher.ps1` / `vibelution_launcher.py`（legacy/开发）。

### 注意

- 有进行中任务时勿强行 restart（active-work guard）。
- 改 LLM/agent 代码后通常需要 restart 才能进运行时。
- Windows 禁止可见控制台弹窗路径（见开发标准 §8.0）。

## `[runtime]`

运行时能力与子系统开关。改前确认是否影响：

- Runtime Manager 队列
- 轮询间隔
- 能力开关

## `[workbench]`

```toml
[workbench]
window_mode = "windowed"     # 产品允许的枚举
window_size = "960x600"
window_position = "0,0"
```

| 字段 | 说明 |
| --- | --- |
| `window_mode` | 窗口模式 |
| `window_size` | `WxH`；过小尺寸可能被 Launcher 拒绝 |
| `window_position` | `x,y`；屏外坐标可能被拒绝 |

Workbench HTTP（常见 `:8000`）与 Electron 控制窗口（`vibelution-launcher://` app protocol）分离；控制面偏好字段（`[launcher].control_port`）保留兼容但产品路径不再使用。

## Agent 清单

- [ ] 改 workbench 窗口后是否需要重启 Launcher
- [ ] 未用 taskkill 绕过 lifecycle
- [ ] 前端 `tsc -b` 失败会导致 open_workbench preflight 失败（构建债，不是 workbench 节本身）
