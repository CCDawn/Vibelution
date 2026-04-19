# Evolution Module (Phase 3)

**进化引擎模块** - 8阶段自我进化能力

## Modules

| File | Description |
|------|-------------|
| `evolution_engine.py` | 8阶段进化引擎核心 |
| `self_analyzer.py` | 自我分析与代码审查 |
| `refactoring_planner.py` | 重构规划器 |
| `code_generator.py` | 代码生成器 |
| `self_refactoror.py` | 自我重构执行器 |

## Usage

```python
from core.evolution.evolution_engine import EvolutionEngine
from core.evolution.self_analyzer import SelfAnalyzer
```

## Key Classes

- `EvolutionEngine` - 主进化引擎，执行8阶段循环
- `SelfAnalyzer` - 分析自身代码质量和改进点
- `RefactoringPlanner` - 制定重构计划
- `CodeGenerator` - 生成改进代码
- `SelfRefactoror` - 执行重构操作

## 8阶段进化流程

1. **自我分析** - 分析当前代码状态
2. **目标设定** - 确定改进目标
3. **计划制定** - 制定详细执行计划
4. **代码生成** - 生成新代码
5. **验证测试** - 运行测试验证
6. **重构应用** - 应用改进
7. **效果评估** - 评估改进效果
8. **记忆传承** - 保存经验到记忆
