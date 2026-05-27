# -*- coding: utf-8 -*-
"""
Python 结构感知与静态检查工具。

目标：
- 用 Jedi 提供接近语言服务器的定义 / 引用 / 悬浮信息
- 用 Ruff 提供快速、只读的 Python lint 诊断
- 依赖缺失时结构化降级，而不是直接报异常
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_path(file_path: str) -> Path:
    path = Path(file_path)
    if path.is_absolute():
        return path
    return (_project_root() / path).resolve()


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _missing_dependency_message(dep: str, capability: str) -> str:
    payload = {
        "status": "unavailable",
        "capability": capability,
        "missing_dependency": dep,
        "message": f"当前环境未安装 {dep}，暂时无法执行 {capability}。",
        "suggested_action": f"在项目环境中安装 `{dep}` 后再重试。",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _safe_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(_project_root()).as_posix()
    except Exception:
        return path.as_posix()


def _iter_python_files(scope: str = "", file_path: str = "") -> List[Path]:
    if file_path:
        path = _resolve_path(file_path)
        return [path] if path.exists() and path.suffix == ".py" else []
    root = _resolve_path(scope or ".")
    if root.is_file():
        return [root] if root.suffix == ".py" else []
    if not root.exists():
        return []
    ignored_parts = {".git", ".venv", "__pycache__", "node_modules", "dist", "build"}
    files: List[Path] = []
    for item in root.rglob("*.py"):
        if any(part in ignored_parts for part in item.parts):
            continue
        files.append(item)
        if len(files) >= 1200:
            break
    return files


def _entity_matches_symbol(entity: Dict[str, Any], symbol: str) -> bool:
    name = str(entity.get("name") or "")
    class_name = str(entity.get("class_name") or "")
    return name == symbol or (class_name and f"{class_name}.{name}" == symbol)


def _definition_results(symbol: str, *, scope: str = "", file_path: str = "", max_results: int = 20) -> List[Dict[str, Any]]:
    from tools.code_analysis_tools import get_file_entities

    results: List[Dict[str, Any]] = []
    for path in _iter_python_files(scope=scope, file_path=file_path):
        entities = get_file_entities(str(path))
        for kind in ("class", "function", "async_function"):
            for entity in entities.get(kind, []):
                if _entity_matches_symbol(entity, symbol):
                    results.append(
                        {
                            "path": _safe_rel(path),
                            "kind": kind,
                            "symbol": entity.get("name"),
                            "qualified_symbol": entity.get("name"),
                            "line": entity.get("lineno"),
                            "end_line": entity.get("end_lineno"),
                        }
                    )
        for class_entity in entities.get("class", []):
            for method in class_entity.get("methods", []):
                if _entity_matches_symbol(method, symbol):
                    results.append(
                        {
                            "path": _safe_rel(path),
                            "kind": "method",
                            "symbol": method.get("name"),
                            "qualified_symbol": f"{class_entity.get('name')}.{method.get('name')}",
                            "line": method.get("lineno"),
                            "end_line": method.get("end_lineno"),
                        }
                    )
        if len(results) >= max_results:
            return results[:max_results]
    return results[:max_results]


def _reference_results(symbol: str, *, scope: str = "", file_path: str = "", max_results: int = 20) -> List[Dict[str, Any]]:
    pattern = re.compile(rf"\b{re.escape(symbol)}\b")
    results: List[Dict[str, Any]] = []
    for path in _iter_python_files(scope=scope, file_path=file_path):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for idx, line in enumerate(lines, start=1):
            if not pattern.search(line):
                continue
            results.append(
                {
                    "path": _safe_rel(path),
                    "line": idx,
                    "preview": line.strip()[:240],
                }
            )
            if len(results) >= max_results:
                return results
    return results


def code_symbol_tool(
    mode: str,
    file_path: str = "",
    symbol: str = "",
    entity_name: str = "",
    line: int = 0,
    column: int = 0,
    scope: str = ".",
    max_results: int = 20,
) -> str:
    """Unified code navigation tool for outlines, entities, definitions, and references."""

    normalized_mode = str(mode or "").strip().lower()
    target_symbol = str(entity_name or symbol or "").strip()
    try:
        max_results = max(1, min(int(max_results or 20), 100))
    except (TypeError, ValueError):
        max_results = 20

    if normalized_mode == "outline":
        if not file_path:
            return json.dumps(
                {
                    "status": "error",
                    "mode": normalized_mode,
                    "message": "outline 模式需要 file_path。",
                    "example": {"mode": "outline", "file_path": "core/web/services/session_service.py"},
                },
                ensure_ascii=False,
                indent=2,
            )
        from tools.code_analysis_tools import list_file_entities

        return list_file_entities(file_path=file_path, entity_type="all")

    if normalized_mode == "entity":
        if not file_path or not target_symbol:
            return json.dumps(
                {
                    "status": "error",
                    "mode": normalized_mode,
                    "message": "entity 模式需要 file_path 和 symbol 或 entity_name。",
                    "example": {
                        "mode": "entity",
                        "file_path": "core/web/services/session_service.py",
                        "symbol": "_run_session_continuation_loop",
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        from tools.code_analysis_tools import get_code_entity

        return get_code_entity(file_path=file_path, entity_name=target_symbol)

    if normalized_mode in {"definition", "references", "hover"}:
        if file_path and line:
            return python_symbol_query(
                file_path=file_path,
                line=int(line),
                column=int(column or 0),
                action=normalized_mode,
                max_results=max_results,
            )
        if not target_symbol:
            return json.dumps(
                {
                    "status": "error",
                    "mode": normalized_mode,
                    "message": f"{normalized_mode} 模式需要 symbol，或提供 file_path + line + column。",
                    "example": {"mode": normalized_mode, "symbol": "ToolExecutor", "scope": "core"},
                },
                ensure_ascii=False,
                indent=2,
            )
        if normalized_mode == "hover":
            return json.dumps(
                {
                    "status": "error",
                    "mode": normalized_mode,
                    "message": "hover 模式需要 file_path + line + column。",
                    "example": {
                        "mode": "hover",
                        "file_path": "core/infrastructure/tool_executor.py",
                        "line": 1,
                        "column": 0,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        results = (
            _definition_results(target_symbol, scope=scope, file_path=file_path, max_results=max_results)
            if normalized_mode == "definition"
            else _reference_results(target_symbol, scope=scope, file_path=file_path, max_results=max_results)
        )
        return json.dumps(
            {
                "status": "ok",
                "mode": normalized_mode,
                "symbol": target_symbol,
                "scope": scope,
                "file_path": file_path,
                "count": len(results),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )

    return json.dumps(
        {
            "status": "error",
            "mode": normalized_mode,
            "message": "不支持的 mode。",
            "supported_modes": ["outline", "entity", "definition", "references", "hover"],
            "example": {"mode": "outline", "file_path": "agent.py"},
        },
        ensure_ascii=False,
        indent=2,
    )


def python_symbol_query(
    file_path: str,
    line: int,
    column: int,
    action: str = "definition",
    max_results: int = 20,
) -> str:
    """
    Python 符号工具：definition / references / hover。

    Args:
        file_path: Python 文件路径
        line: 1-based 行号
        column: 0-based 列号（与 Jedi 保持一致）
        action: definition / references / hover
        max_results: 最大结果数

    Returns:
        JSON 字符串
    """
    if action not in {"definition", "references", "hover"}:
        return json.dumps(
            {
                "status": "error",
                "message": f"不支持的 action: {action}",
                "supported_actions": ["definition", "references", "hover"],
            },
            ensure_ascii=False,
            indent=2,
        )

    if not _module_available("jedi"):
        return _missing_dependency_message("jedi", f"python_symbol:{action}")

    path = _resolve_path(file_path)
    if not path.exists():
        return json.dumps(
            {"status": "error", "message": f"文件不存在: {file_path}"},
            ensure_ascii=False,
            indent=2,
        )

    try:
        import jedi  # type: ignore

        script = jedi.Script(path=str(path))
        if action == "definition":
            symbols = script.goto(line=line, column=column, follow_imports=True)
        elif action == "references":
            symbols = script.get_references(line=line, column=column, include_builtins=False)
        else:
            symbols = script.infer(line=line, column=column)

        results: List[Dict[str, Any]] = []
        for symbol in symbols[:max_results]:
            module_path = getattr(symbol, "module_path", None)
            rel_path = _safe_rel(Path(module_path)) if module_path else None
            item = {
                "name": getattr(symbol, "name", ""),
                "type": getattr(symbol, "type", ""),
                "description": getattr(symbol, "description", ""),
                "module_name": getattr(symbol, "module_name", ""),
                "path": rel_path,
                "line": getattr(symbol, "line", None),
                "column": getattr(symbol, "column", None),
            }
            if action == "hover":
                doc = ""
                try:
                    doc = symbol.docstring()
                except Exception:
                    doc = ""
                item["docstring"] = doc[:1200]
            results.append(item)

        return json.dumps(
            {
                "status": "ok",
                "action": action,
                "query": {
                    "file_path": _safe_rel(path),
                    "line": line,
                    "column": column,
                },
                "count": len(results),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as exc:
        return json.dumps(
            {
                "status": "error",
                "action": action,
                "message": f"Jedi 分析失败: {type(exc).__name__}: {exc}",
            },
            ensure_ascii=False,
            indent=2,
        )


def python_lint_tool(target: str = ".", max_issues: int = 100) -> str:
    """
    Python lint 检查（Ruff）。

    Args:
        target: 文件或目录
        max_issues: 最多返回多少条问题

    Returns:
        JSON 字符串
    """
    if not _module_available("ruff"):
        return _missing_dependency_message("ruff", "python_lint")

    resolved = _resolve_path(target)
    command = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        str(resolved),
        "--output-format",
        "json",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=str(_project_root()),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as exc:
        return json.dumps(
            {
                "status": "error",
                "message": f"Ruff 执行失败: {type(exc).__name__}: {exc}",
                "command": command,
            },
            ensure_ascii=False,
            indent=2,
        )

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    raw_items: List[Dict[str, Any]] = []
    if stdout:
        try:
            raw_items = json.loads(stdout)
        except json.JSONDecodeError:
            return json.dumps(
                {
                    "status": "error",
                    "message": "Ruff 输出不是合法 JSON",
                    "stdout": stdout[:2000],
                    "stderr": stderr[:1000],
                },
                ensure_ascii=False,
                indent=2,
            )

    issues = []
    for item in raw_items[:max_issues]:
        filename = item.get("filename", "")
        issues.append(
            {
                "path": _safe_rel(Path(filename)) if filename else filename,
                "code": item.get("code"),
                "message": item.get("message"),
                "line": (item.get("location") or {}).get("row"),
                "column": (item.get("location") or {}).get("column"),
                "end_line": (item.get("end_location") or {}).get("row"),
                "end_column": (item.get("end_location") or {}).get("column"),
            }
        )

    status = "ok" if result.returncode in (0, 1) else "error"
    return json.dumps(
        {
            "status": status,
            "tool": "ruff",
            "target": _safe_rel(resolved),
            "issue_count": len(raw_items),
            "returned_issue_count": len(issues),
            "issues": issues,
            "stderr": stderr[:1000] if stderr else "",
        },
        ensure_ascii=False,
        indent=2,
    )


__all__ = [
    "code_symbol_tool",
    "python_symbol_query",
    "python_lint_tool",
]
