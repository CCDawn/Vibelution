# 07 · Launcher / Runtime / Workbench

## `[launcher]`

Launcher 控制面（默认 `http://127.0.0.1:8765`）相关偏好。
生命周期命令以开发标准为准：

```text
%LOCALAPPDATA%\Vibelution\Launcher\VibelutionLauncher.exe --project "<root>" start|stop|restart
```

或 `scripts/vibelution_launcher.ps1` / `vibelution_launcher.py`。

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

Workbench HTTP 与 Launcher 控制面分离（常见 8000 vs 8765，以实际配置为准）。

## Agent 清单

- [ ] 改 workbench 窗口后是否需要重启 Launcher
- [ ] 未用 taskkill 绕过 lifecycle
- [ ] 前端 `tsc -b` 失败会导致 open_workbench preflight 失败（构建债，不是 workbench 节本身）
