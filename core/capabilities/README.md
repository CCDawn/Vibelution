# Capabilities Module

**能力系统模块** - 技能画像与任务管理

## Modules

| File | Description |
|------|-------------|
| `prompt_manager.py` | 提示词管理器 |
| `prompt_builder.py` | 提示词构建器 |
| `task_analyzer.py` | 任务分析器 |
| `task_manager.py` | 任务管理器 |
| `skills_profiler.py` | 技能画像 |
| `pattern_library.py` | 模式库 |

## Usage

```python
from core.capabilities.prompt_manager import get_prompt_manager
from core.capabilities.task_analyzer import TaskAnalyzer
```

## Key Classes

- `PromptManager` - 提示词动态拼接管理
- `PromptBuilder` - 构建系统提示词
- `TaskAnalyzer` - 分析用户任务
- `TaskManager` - 管理任务状态
- `SkillsProfiler` - 技能能力画像
- `PatternLibrary` - 常用模式库

## 功能

- 提示词双轨加载 (core_prompt + workspace/prompts)
- 动态提示词组件拼装
- 任务分析与分解
- 技能能力评估
- 模式复用库
