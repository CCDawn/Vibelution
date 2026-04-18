# CodebaseMap 重构方案 —— 从工具调用改为提示词拼接

> **状态：已完成** | **完成时间：2026-04-18**

---

## 目标

将 `record_codebase_insight_tool` / `get_global_codebase_map_tool`（LLM 工具调用模式）重构为 **PromptManager 内部动态 AST 扫描**：每次 build() 时自动扫描代码库结构、更新 `workspace/prompts/codebase_map.md`、按需拼入提示词。

## 架构设计

```
PromptManager.build(include=["CODEBASE_MAP"])
    │
    ├─ _load_codebase_map() [已改造]
    │     ├─ 检测: 是否需要重新扫描（时间戳 / 文件变更）
    │     ├─ AST 扫描 tools/、core/、tests/ 目录
    │     ├─ 生成 Markdown 结构树
    │     └─ 写入 workspace/prompts/codebase_map.md
    │
    └─ 读取 workspace/prompts/codebase_map.md → 拼入提示词
```

## 变更文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/capabilities/codebase_map_builder.py` | 新建 | AST 扫描 + 地图生成器 |
| `core/capabilities/prompt_manager.py` | 修改 | `_load_codebase_map()` 改调新建模块 |
| `tools/memory_tools.py` | 修改 | 两工具标注 `@deprecated` |
| `core/core_prompt/AGENTS.md` | 无需修改 | 废弃工具未在速查表中 |

## 缓存策略

- `codebase_map.md` TTL = 24 小时（避免每次启动都全量扫描）
- `codebase_map.md` 文件变更时自动失效
- `build(include=["CODEBASE_MAP"], force_refresh=True)` 可强制刷新（通过 `get_codebase_map(force_refresh=True)`）

## 新增 API

```python
from core.capabilities.codebase_map_builder import (
    get_codebase_map,      # 获取地图（自动缓存）
    scan_and_build_codebase_map,  # 强制重新扫描
    should_rescan,         # 检查是否需要扫描
)
```

## 废弃工具

| 工具名 | 状态 | 替代方案 |
|--------|------|----------|
| `record_codebase_insight_tool` | `@deprecated` | 自动 AST 扫描 |
| `get_global_codebase_map_tool` | `@deprecated` | PromptManager CODEBASE_MAP 组件 |

> 工具仍保留导出（不破坏现有注册），仅从文档移除引用。

## 测试计划

1. `python -c "from core.capabilities.codebase_map_builder import get_codebase_map; print(get_codebase_map()[:500])"`
2. `from core.capabilities.prompt_manager import get_prompt_manager; pm = get_prompt_manager(); p = pm.build(include=["CODEBASE_MAP"])`
3. 验证 `workspace/prompts/codebase_map.md` 已生成
