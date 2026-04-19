# Evolution 模块 - 进化引擎组件
from core.evolution.evolution_engine import (
    EvolutionEngine, EvolutionPhase, EvolutionResult,
    get_evolution_engine
)
from core.evolution.self_analyzer import (
    SelfAnalyzer, CapabilityDimension, get_self_analyzer
)
from core.evolution.refactoring_planner import (
    RefactoringPlanner, RefactoringOpportunity, RefactoringPlan,
    get_refactoring_planner
)
from core.evolution.code_generator import (
    CodeGenerator, CodeTemplate, get_code_generator
)
from core.evolution.self_refactoror import (
    SelfRefactoror, get_refactoror
)
from core.evolution.evolution_gate import (
    run_evolution_gate,
    check_evolution_gate,
)
