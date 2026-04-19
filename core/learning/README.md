# Learning Module (Phase 5)

**持续学习模块** - 反馈循环与策略学习

## Modules

| File | Description |
|------|-------------|
| `learning_engine.py` | 学习引擎核心 |
| `feedback_loop.py` | 反馈循环处理 |
| `insight_tracker.py` | 洞察追踪记录 |
| `strategy_learner.py` | 策略学习器 |
| `agent_core.py` | Agent 抽象基类 |

## Usage

```python
from core.learning.learning_engine import LearningEngine
from core.learning.feedback_loop import FeedbackLoop
```

## Key Classes

- `LearningEngine` - 主学习引擎
- `FeedbackLoop` - 处理执行反馈，优化策略
- `InsightTracker` - 追踪重要洞察和发现
- `StrategyLearner` - 从历史经验学习策略
- `AgentCore` - Agent 抽象基类

## 功能

- 从执行结果中学习
- 策略优化调整
- 洞察积累传承
- 经验压缩存储
