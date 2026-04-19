# Core Prompt Module

**核心提示词模块** - 系统提示词双轨加载

## Structure

```
core_prompt/
├── SOUL.md       # 使命定义 (只读)
└── AGENTS.md    # Agent 行为规则 (只读)
```

## 双轨加载机制

| 轨道 | 路径 | 优先级 | 说明 |
|------|------|--------|------|
| 静态 | `core/core_prompt/` | 低 | 内置只读模板 |
| 动态 | `workspace/prompts/` | 高 | 用户可编辑覆盖层 |

## Usage

```python
from core.capabilities.prompt_manager import get_prompt_manager
pm = get_prompt_manager()
system_prompt, components = pm.build()
```

## 文件说明

- `SOUL.md` - 使命定义，包含核心价值观和行为准则
- `AGENTS.md` - Agent 行为规则，定义工具使用规范

## 加载流程

1. 优先从 `workspace/prompts/` 加载用户覆盖版本
2. 如果不存在，加载 `core/core_prompt/` 内置版本
3. 动态提示词组件可由 Agent 运行时修改
