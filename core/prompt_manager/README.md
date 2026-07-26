# Prompt Manager

Vibelution Agent 的系统提示词装配模块。

## 三核心基座

所有 Agent 都以以下三份受保护的核心提示词为基础，顺序固定：

1. `core/core_prompt/COMMON.md`：通用认知、证据和执行纪律。
2. `core/core_prompt/SOUL.md`：稳定身份、价值倾向和自我进化动力。
3. 根目录 `AGENTS.md`：项目级规则、中枢路由和开发红线。

`core_prompt_sources.py` 是三核心名称、顺序、路径、版本和内容哈希的唯一代码定义。核心文件缺失或为空时应失败关闭，不能静默降级。

## 装配与快照

- 普通运行由 `PromptManager` 注入三核心，再组合运行目标、记忆和其他动态章节。
- 会话 Agent 创建提示词快照时，冻结“三核心 + 会话公共提示词（若适用）+ 角色提示词”。
- 有效会话快照已经承载三核心时，`PromptManager` 跳过实时三核心，避免重复注入。
- `ContextEngine` 不再单独抽取或注入 `AGENTS.md`；它只负责运行时上下文。
- 新格式会话快照记录核心 schema、整体哈希和逐文件元数据，但公开会话 DTO 不暴露完整提示词内容。

三核心内容变更只影响新建快照；已有有效会话继续使用原快照。旧格式快照因缺少核心 schema 会升级一次。

## 主要文件

| 文件 | 职责 |
|---|---|
| `core_prompt_sources.py` | 三核心来源、顺序、校验和快照元数据 |
| `sections.py` | 注册静态和动态提示词章节 |
| `prompt_manager.py` | 章节选择、排序、缓存和最终装配 |
| `prompt_builder.py` | 系统提示词渲染 |
| `task_analyzer.py` | 任务分析 |
| `task_manager.py` | 任务状态管理 |

## 使用

```python
from core.prompt_manager import get_prompt_manager

prompt_manager = get_prompt_manager()
system_prompt = prompt_manager.build()
```
