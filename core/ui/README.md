# UI Module

**用户界面模块** - 终端 UI 与交互

## Modules

| File | Description |
|------|-------------|
| `cli_ui.py` | CLI UI 管理器 (Rich Live 显示) |
| `interactive_cli.py` | 交互式 CLI |
| `ascii_art.py` | ASCII Art 艺术 |
| `theme.py` | 主题系统 |

## Usage

```python
from core.ui.cli_ui import get_ui, UIManager
from core.ui.ascii_art import get_avatar_manager
```

## Key Classes

- `UIManager` - Rich Live 三段式布局管理器
  - 顶部状态栏（Baby Claw 状态）
  - 中间内容区（工具输出、思考过程）
  - 底部日志栏（最近日志）
- `XuebaInteractiveCLI` - 交互式 CLI 界面
- `AvatarManager` - ASCII Art 角色管理
- `LobsterTheme` - 龙虾主题

## 布局结构

```
+-------------------------------- 虾宝状态 --------------------------------+
| (\ /)  Lv.1 (0岁)                                                           |
|   ( ^.^)  IDLE  TURN #0                                                     |
+-----------------------------------------------------------------------------+
+---------------------------- 内容输出 (N 条) -----------------------------+
+-----------------------------------------------------------------------------+
+-------------------------------- 日志 (N) --------------------------------+
```

## 功能

- Claude Code 风格三段式终端布局
- 龙虾宝宝主题 UI
- 动态状态刷新
- 工具执行结果显示
