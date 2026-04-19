# Orchestration Module (Phase 7)

**模块化重构模块** - LLM协调与记忆管理

## Modules

| File | Description |
|------|-------------|
| `llm_orchestrator.py` | LLM 协调器 |
| `memory_manager.py` | 记忆管理器 |
| `task_planner.py` | 任务规划器 |
| `compression_persister.py` | 压缩持久化 |
| `semantic_retriever.py` | 语义检索器 |
| `forgetting_engine.py` | 遗忘引擎 |
| `response_parser.py` | 响应解析器 |

## Usage

```python
from core.orchestration.llm_orchestrator import LLMOrchestrator
from core.orchestration.memory_manager import MemoryManager
from core.orchestration.response_parser import parse_llm_response
```

## Key Classes

- `LLMOrchestrator` - 多模型 LLM 协调
- `MemoryManager` - 统一记忆管理
- `TaskPlanner` - 复杂任务分解规划
- `CompressionPersister` - 记忆压缩存储
- `SemanticRetriever` - 基于语义的记忆检索
- `ForgettingEngine` - 智能遗忘不重要记忆
- `ResponseParser` - LLM 响应解析

## 功能

- 多模型 LLM 调用协调
- 统一记忆管理系统
- 复杂任务自动分解
- 记忆压缩与检索
- 智能遗忘低价值记忆
