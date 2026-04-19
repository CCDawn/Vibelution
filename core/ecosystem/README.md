# Ecosystem Module

**工具生态系统模块** - 工具生态与重启管理

## Modules

| File | Description |
|------|-------------|
| `tool_ecosystem.py` | 工具生态系统 |
| `skill_registry.py` | 技能注册表 |
| `skill_loader.py` | 技能加载器 |
| `skill_tools.py` | 技能工具 |
| `restarter.py` | 重启管理器 |

## Usage

```python
from core.ecosystem.tool_ecosystem import ToolEcosystem
from core.ecosystem.skill_registry import SkillRegistry
```

## Key Classes

- `ToolEcosystem` - 工具生态管理器
- `SkillRegistry` - 技能注册与发现
- `SkillLoader` - 动态技能加载
- `Restarter` - Agent 重启管理

## 功能

- 工具生态系统管理
- 动态技能加载
- 技能注册与发现
- 自动重启触发
- 代码更新热加载
