#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自我重构系统 (Self-Refactoring System) - Phase 8 模块

包含：
- self_refactoror.py - 自动代码重构
- refactor_validator.py - 重构验证
- evolution_tracker.py - 进化追踪

Phase 8.6 模块
"""

from __future__ import annotations

import os
import ast
import json
import hashlib
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from collections import defaultdict
import difflib


# ============================================================================
# 枚举和数据结构
# ============================================================================

class RefactorType(Enum):
    """重构类型"""
    EXTRACT_METHOD = "extract_method"
    RENAME_VARIABLE = "rename_variable"
    EXTRACT_CLASS = "extract_class"
    INLINE_METHOD = "inline_method"
    MOVE_METHOD = "move_method"
    REORDER_METHODS = "reorder_methods"
    ADD_TYPE_HINTS = "add_type_hints"
    SIMPLIFY_CONDITION = "simplify_condition"


class RefactorStatus(Enum):
    """重构状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    VALIDATED = "validated"
    APPLIED = "applied"
    REVERTED = "reverted"
    FAILED = "failed"


@dataclass
class RefactorOpportunity:
    """重构机会"""
    opportunity_id: str
    refactor_type: RefactorType
    file_path: str
    location: Tuple[int, int]  # start, end
    description: str
    original_code: str
    suggested_code: Optional[str] = None
    confidence: float = 0.8
    estimated_hours: float = 0.5


@dataclass
class RefactorPlan:
    """重构计划"""
    plan_id: str
    title: str
    description: str
    opportunities: List[RefactorOpportunity]
    total_estimated_hours: float
    risk_level: str = "medium"
    dependencies: List[str] = field(default_factory=list)


@dataclass
class RefactorResult:
    """重构结果"""
    opportunity_id: str
    status: RefactorStatus
    success: bool
    changes: List[Dict[str, Any]] = field(default_factory=list)
    validation_results: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class EvolutionRecord:
    """进化记录"""
    record_id: str
    timestamp: str
    refactor_type: RefactorType
    file_path: str
    before_metrics: Dict[str, Any]
    after_metrics: Dict[str, Any]
    improvements: List[str] = field(default_factory=list)
    regressions: List[str] = field(default_factory=list)
    success: bool = False


# ============================================================================
# 重构验证器
# ============================================================================

class RefactorValidator:
    """
    重构验证器

    验证重构后的代码是否正确
    """

    def __init__(self, project_root: Optional[str] = None):
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        self.project_root = Path(project_root)

    def validate_syntax(self, code: str) -> Tuple[bool, Optional[str]]:
        """
        验证语法正确性

        Returns:
            (is_valid, error_message)
        """
        try:
            ast.parse(code)
            return True, None
        except SyntaxError as e:
            return False, str(e)

    def validate_imports(self, file_path: str) -> Tuple[bool, List[str]]:
        """
        验证导入是否正确

        Returns:
            (is_valid, error_imports)
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            tree = ast.parse(content)
            imports = []

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module)

            # 检查是否有未使用的导入
            errors = []
            for imp in imports:
                if not self._check_import_available(imp):
                    errors.append(imp)

            return len(errors) == 0, errors

        except Exception as e:
            return False, [str(e)]

    def validate_semantics(
        self,
        original_code: str,
        new_code: str,
    ) -> Tuple[bool, List[str]]:
        """
        验证语义一致性

        Returns:
            (is_equivalent, differences)
        """
        differences = []

        try:
            orig_tree = ast.parse(original_code)
            new_tree = ast.parse(new_code)

            # 比较 AST 结构
            if not self._compare_ast(orig_tree, new_tree):
                differences.append("AST structure differs")

            return len(differences) == 0, differences

        except Exception as e:
            return False, [str(e)]

    def validate_tests(self, file_path: str) -> Tuple[bool, Dict[str, Any]]:
        """
        运行相关测试

        Returns:
            (all_passed, test_results)
        """
        results = {
            "ran": False,
            "passed": 0,
            "failed": 0,
            "errors": [],
        }

        try:
            # 查找测试文件
            test_file = self._find_test_file(file_path)
            if not test_file:
                return True, results

            # 运行测试
            test_results = subprocess.run(
                ["python", "-m", "pytest", str(test_file), "-v"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=60,
            )

            results["ran"] = True
            results["passed"] = test_results.returncode == 0
            results["output"] = test_results.stdout[:500]

            return test_results.returncode == 0, results

        except Exception as e:
            results["errors"].append(str(e))
            return False, results

    def _check_import_available(self, module_name: str) -> bool:
        """检查模块是否可用"""
        try:
            __import__(module_name)
            return True
        except ImportError:
            return False

    def _compare_ast(self, tree1: ast.AST, tree2: ast.AST) -> bool:
        """比较两个 AST"""
        return ast.dump(tree1) == ast.dump(tree2)

    def _find_test_file(self, source_file: str) -> Optional[Path]:
        """查找对应的测试文件"""
        source_path = Path(source_file)
        test_dir = self.project_root / "tests"

        if not test_dir.exists():
            return None

        module_name = source_path.stem
        test_patterns = [
            f"test_{module_name}.py",
            f"{module_name}_test.py",
        ]

        for pattern in test_patterns:
            test_file = test_dir / pattern
            if test_file.exists():
                return test_file

        return None


# ============================================================================
# 自我重构器
# ============================================================================

class SelfRefactoror:
    """
    自我重构器

    自动识别和应用代码重构
    """

    def __init__(
        self,
        project_root: Optional[str] = None,
        validator: Optional[RefactorValidator] = None,
    ):
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        self.project_root = Path(project_root)
        self.validator = validator or RefactorValidator(str(self.project_root))
        self._refactor_counter = 0

    def find_opportunities(self) -> List[RefactorOpportunity]:
        """发现重构机会"""
        opportunities = []

        for py_file in self.project_root.rglob("*.py"):
            if self._should_ignore(py_file):
                continue

            try:
                file_opps = self._find_in_file(py_file)
                opportunities.extend(file_opps)
            except Exception:
                continue

        return opportunities

    def _find_in_file(self, file_path: Path) -> List[RefactorOpportunity]:
        """在单个文件中发现重构机会"""
        opportunities = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            tree = ast.parse(content)

            for node in ast.walk(tree):
                # 检测过长函数
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.end_lineno and node.lineno:
                        func_length = node.end_lineno - node.lineno + 1
                        if func_length > 100:
                            self._refactor_counter += 1
                            opportunities.append(RefactorOpportunity(
                                opportunity_id=f"ref_{self._refactor_counter}",
                                refactor_type=RefactorType.EXTRACT_METHOD,
                                file_path=str(file_path),
                                location=(node.lineno, node.end_lineno),
                                description=f"函数 '{node.name}' 过长 ({func_length} 行)",
                                original_code=content.split('\n')[node.lineno-1:node.end_lineno],
                                confidence=0.9,
                                estimated_hours=2.0,
                            ))

                # 检测重复代码块
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.end_lineno and node.lineno:
                        func_lines = content.split('\n')[node.lineno-1:node.end_lineno]
                        func_code = '\n'.join(func_lines)

                        # 简单重复检测：检查是否有相似代码
                        if self._has_similar_code(func_code, content):
                            self._refactor_counter += 1
                            opportunities.append(RefactorOpportunity(
                                opportunity_id=f"ref_{self._refactor_counter}",
                                refactor_type=RefactorType.EXTRACT_METHOD,
                                file_path=str(file_path),
                                location=(node.lineno, node.end_lineno),
                                description=f"函数 '{node.name}' 可能有重复代码",
                                original_code=func_code,
                                confidence=0.7,
                                estimated_hours=1.0,
                            ))

        except Exception:
            pass

        return opportunities

    def _has_similar_code(self, code1: str, full_content: str) -> bool:
        """检查是否有相似代码"""
        lines1 = [l.strip() for l in code1.split('\n') if l.strip() and not l.strip().startswith('#')]
        if len(lines1) < 3:
            return False

        # 简单检查：计算行重叠
        content_lines = full_content.split('\n')
        for i in range(len(content_lines) - 2):
            check_lines = [l.strip() for l in content_lines[i:i+3] if l.strip() and not l.strip().startswith('#')]
            if len(check_lines) >= 2 and self._lines_similar(lines1[:2], check_lines):
                return True

        return False

    def _lines_similar(self, lines1: List[str], lines2: List[str]) -> bool:
        """检查两行列表是否相似"""
        if len(lines1) < 2 or len(lines2) < 2:
            return False

        ratio = difflib.SequenceMatcher(None, lines1[0], lines2[0]).ratio()
        return ratio > 0.9

    def apply_refactor(
        self,
        opportunity: RefactorOpportunity,
        dry_run: bool = False,
    ) -> RefactorResult:
        """
        应用重构

        Args:
            opportunity: 重构机会
            dry_run: 是否只预览不实际应用

        Returns:
            RefactorResult: 重构结果
        """
        result = RefactorResult(
            opportunity_id=opportunity.opportunity_id,
            status=RefactorStatus.IN_PROGRESS,
            success=False,
        )

        try:
            # 读取文件
            with open(opportunity.file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # 获取原始代码
            start, end = opportunity.location
            original_lines = lines[start-1:end]

            # 验证语法
            is_valid, error = self.validator.validate_syntax(''.join(original_lines))
            if not is_valid:
                result.status = RefactorStatus.FAILED
                result.error = f"语法错误: {error}"
                return result

            # 生成新的代码（这里简化处理）
            if opportunity.suggested_code:
                new_code = opportunity.suggested_code
            else:
                new_code = self._generate_refactored_code(
                    opportunity,
                    original_lines,
                )

            if dry_run:
                result.success = True
                result.status = RefactorStatus.VALIDATED
                result.changes.append({
                    "type": "preview",
                    "original": ''.join(original_lines),
                    "suggested": new_code,
                })
                return result

            # 应用修改
            lines[start-1:end] = [new_code]

            # 验证修改后的代码
            new_content = ''.join(lines)
            is_valid, error = self.validator.validate_syntax(new_content)
            if not is_valid:
                result.status = RefactorStatus.FAILED
                result.error = f"重构后语法错误: {error}"
                return result

            # 写入文件
            with open(opportunity.file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            result.success = True
            result.status = RefactorStatus.APPLIED
            result.changes.append({
                "type": "replace",
                "lines": f"{start}-{end}",
            })

        except Exception as e:
            result.status = RefactorStatus.FAILED
            result.error = str(e)

        return result

    def _generate_refactored_code(
        self,
        opportunity: RefactorOpportunity,
        original_lines: List[str],
    ) -> str:
        """生成重构后的代码"""
        # 这里简化处理，实际应该根据重构类型生成不同的代码
        # 目前只是返回原始代码
        return ''.join(original_lines)

    def _should_ignore(self, file_path: Path) -> bool:
        """检查是否应该忽略"""
        ignore_patterns = [
            '__pycache__', '.pytest_cache', 'venv',
            '.git', 'backups', 'temp', 'tests',
        ]
        path_str = str(file_path)
        return any(pattern in path_str for pattern in ignore_patterns)


# ============================================================================
# 进化追踪器
# ============================================================================

class EvolutionTracker:
    """
    进化追踪器

    追踪代码进化历史和指标变化
    """

    def __init__(self, storage_path: Optional[str] = None):
        if storage_path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            storage_path = os.path.join(project_root, "workspace", "evolution", "records.json")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        self._records: List[EvolutionRecord] = []
        self._load()

    def record_refactor(
        self,
        refactor_type: RefactorType,
        file_path: str,
        before_metrics: Dict[str, Any],
        after_metrics: Dict[str, Any],
        success: bool,
    ) -> str:
        """
        记录重构

        Args:
            refactor_type: 重构类型
            file_path: 文件路径
            before_metrics: 重构前指标
            after_metrics: 重构后指标
            success: 是否成功

        Returns:
            记录 ID
        """
        record_id = hashlib.md5(
            f"{file_path}{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]

        # 计算改进和退化
        improvements = []
        regressions = []

        for key in before_metrics:
            if key in after_metrics:
                delta = after_metrics[key] - before_metrics[key]
                # 假设越小越好的指标
                if delta < 0:
                    improvements.append(f"{key} 降低了 {abs(delta):.2f}")
                elif delta > 0:
                    regressions.append(f"{key} 增加了 {delta:.2f}")

        record = EvolutionRecord(
            record_id=record_id,
            timestamp=datetime.now().isoformat(),
            refactor_type=refactor_type,
            file_path=file_path,
            before_metrics=before_metrics,
            after_metrics=after_metrics,
            improvements=improvements,
            regressions=regressions,
            success=success,
        )

        self._records.append(record)
        self._save()

        return record_id

    def get_history(
        self,
        limit: int = 50,
        refactor_type: Optional[RefactorType] = None,
    ) -> List[EvolutionRecord]:
        """获取进化历史"""
        records = self._records

        if refactor_type:
            records = [r for r in records if r.refactor_type == refactor_type]

        return records[-limit:]

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        total = len(self._records)
        successful = sum(1 for r in self._records if r.success)
        failed = total - successful

        by_type: Dict[str, int] = defaultdict(int)
        for r in self._records:
            by_type[r.refactor_type.value] += 1

        return {
            "total_refactors": total,
            "successful": successful,
            "failed": failed,
            "success_rate": successful / total if total > 0 else 0,
            "by_type": dict(by_type),
        }

    def _load(self) -> None:
        """从文件加载"""
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for record_data in data.get("records", []):
                try:
                    record = EvolutionRecord(
                        record_id=record_data["record_id"],
                        timestamp=record_data["timestamp"],
                        refactor_type=RefactorType(record_data["refactor_type"]),
                        file_path=record_data["file_path"],
                        before_metrics=record_data.get("before_metrics", {}),
                        after_metrics=record_data.get("after_metrics", {}),
                        improvements=record_data.get("improvements", []),
                        regressions=record_data.get("regressions", []),
                        success=record_data.get("success", False),
                    )
                    self._records.append(record)
                except Exception:
                    continue
        except Exception:
            pass

    def _save(self) -> None:
        """保存到文件"""
        data = {
            "version": "1.0",
            "updated_at": datetime.now().isoformat(),
            "records": [
                {
                    "record_id": r.record_id,
                    "timestamp": r.timestamp,
                    "refactor_type": r.refactor_type.value,
                    "file_path": r.file_path,
                    "before_metrics": r.before_metrics,
                    "after_metrics": r.after_metrics,
                    "improvements": r.improvements,
                    "regressions": r.regressions,
                    "success": r.success,
                }
                for r in self._records
            ],
        }

        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================================
# 单例和工具函数
# ============================================================================

_refactoror_instance: Optional[SelfRefactoror] = None
_validator_instance: Optional[RefactorValidator] = None
_tracker_instance: Optional[EvolutionTracker] = None


def get_refactoror() -> SelfRefactoror:
    """获取重构器单例"""
    global _refactoror_instance
    if _refactoror_instance is None:
        _refactoror_instance = SelfRefactoror()
    return _refactoror_instance


def get_validator() -> RefactorValidator:
    """获取验证器单例"""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = RefactorValidator()
    return _validator_instance


def get_tracker() -> EvolutionTracker:
    """获取追踪器单例"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = EvolutionTracker()
    return _tracker_instance


def reset_refactor_modules() -> None:
    """重置所有单例"""
    global _refactoror_instance, _validator_instance, _tracker_instance
    _refactoror_instance = None
    _validator_instance = None
    _tracker_instance = None
