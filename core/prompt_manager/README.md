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

## 机制地图（活跃）

| 机制 | 作用 | 触发条件 |
|---|---|---|
| 三核心 + 失败关闭 | 三份受保护核心必须存在 | 每次 `build()` |
| protected floor | 必载章节在 include/exclude 后回补 | 每次 `_select_sections` |
| frozen_core_sections | 会话快照已含三核心时跳过实时注入 | host 已种快照（Web 会话） |
| 相关性裁剪（prune） | ENV_INFO / CONFIG_AWARENESS / CODEBASE_MAP 按任务相关性保留或裁掉 | 每次 `build()`，渲染前 |
| 能力门（capability_requirements） | 章节声明依赖，如 CODEBASE_MAP→`code_context`、GIT_RULES→`git_workflow` | Prompt Assembly resolver 阶段 |
| 预算裁决 | 按 tier/总预算输出 FULL / TRUNCATED / OMITTED / BLOCKED；受保护层超预算失败关闭 | 传了 `assembly_context`（生产 turn 恒传） |
| 静态/动态边界 | 静态段进 prompt-cache 稳定前缀，动态段下移 | 存在动态段时 |
| 章节级缓存 | 静态章节只渲染一次 | 每次渲染静态章节 |

**能力门是单一权威**：运行目标包的能力由 `provider_adapters.runtime_goal_capabilities()` 投影为能力名（`code_context` / `git_workflow`），与协议能力合并进 `PromptAssemblyContext.capabilities`；章节是否放行只在 resolver 裁决，manifest 记录 `decision` 与 `decisionReason`。渲染前不再有第二处目标过滤。

## 未启用机制（保留，但生产不生效）

- **workspace 动态文件**：`IDENTITY.md` / `USER.md` / `DYNAMIC.md` 章节仅在 `PromptManager(enable_workspace=True)` 时注册；生产恒为 `False`（唯一启用点在测试）。保留为潜在能力，勿按“活跃机制”理解。

## 主要文件

| 文件 | 职责 |
|---|---|
| `core_prompt_sources.py` | 三核心来源、顺序、校验和快照元数据 |
| `sections.py` | 静态和动态提示词章节注册（含能力声明） |
| `prompt_manager.py` | 章节选择、排序、保护回补、相关性裁剪和最终装配 |
| `builder.py` | 章节渲染、静/动边界与 assembly manifest 组装 |
| `assembly_resolver.py` | 能力门与预算裁决（FULL/TRUNCATED/OMITTED/BLOCKED） |
| `assembly_contract.py` | Segment / Manifest 契约与 token 估算 |
| `provider_adapters.py` | 协议适配章节渲染 + 装配上下文与运行目标能力投影 |
| `section_cache.py` | 章节级缓存 |
| `types.py` | 数据结构定义 |
| `task_analyzer.py` | 任务分析 |
| `codebase_map_builder.py` | 代码库认知地图构建 |

## 使用

```python
from core.prompt_manager import get_prompt_manager

prompt_manager = get_prompt_manager()
system_prompt = prompt_manager.build()
```
