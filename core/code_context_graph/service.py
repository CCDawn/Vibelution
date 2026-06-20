# -*- coding: utf-8 -*-
"""Local project code context graph service.

This module provides a CodeGraph-style project index for Vibelution's native
agent tools. It is intentionally local, deterministic, and cache-backed.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from config.paths import resolve_workspace_home

SCHEMA_VERSION = 1
INDEX_REL_PATH = Path("code_context_graph") / "index.json"

INCLUDED_ROOTS = {
    "core",
    "tools",
    "tests",
    "web",
    "config",
    "docs",
    "workspace/prompts",
}
ROOT_FILES = {
    "agent.py",
    "AGENTS.md",
    "CHANGELOG.md",
    "PROJECT_MEMORY.html",
    "README.md",
    "config.toml",
    "config.example.toml",
}
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    "dist",
    "build",
    ".turbo",
    ".vite",
}
EXCLUDED_PREFIXES = {
    "workspace/chat/",
    "workspace/supervised_evolution/",
    "workspace/evaluation/",
    "workspace/agents/",
    "workspace/code_context_graph/",
    "web/dist/",
    "web/node_modules/",
}
INDEX_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".css",
    ".md",
    ".json",
    ".toml",
    ".ps1",
    ".vbs",
    ".html",
    ".txt",
}

TEXT_EXTENSIONS = INDEX_EXTENSIONS
MAX_FILE_BYTES = 512_000
MAX_SNIPPET_CHARS = 900

TS_IMPORT_RE = re.compile(r"\bfrom\s+['\"]([^'\"]+)['\"]|import\s+['\"]([^'\"]+)['\"]")
TS_SYMBOL_PATTERNS = [
    ("class", re.compile(r"\bexport\s+class\s+([A-Za-z_$][\w$]*)|\bclass\s+([A-Za-z_$][\w$]*)")),
    ("function", re.compile(r"\bexport\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)")),
    ("component", re.compile(r"\bexport\s+const\s+([A-Z][A-Za-z0-9_$]*)\s*=\s*(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>|\bconst\s+([A-Z][A-Za-z0-9_$]*)\s*=\s*(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")),
    ("hook", re.compile(r"\bexport\s+function\s+(use[A-Z][A-Za-z0-9_$]*)|\bfunction\s+(use[A-Z][A-Za-z0-9_$]*)|\bconst\s+(use[A-Z][A-Za-z0-9_$]*)\s*=")),
    ("export", re.compile(r"\bexport\s+(?:const|let|var|type|interface|enum)\s+([A-Za-z_$][\w$]*)")),
]


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def index_path(root: Path | None = None) -> Path:
    if root is None:
        return resolve_workspace_home() / INDEX_REL_PATH
    base = Path(root).resolve()
    if base == project_root():
        return resolve_workspace_home() / INDEX_REL_PATH
    workspace_root = base if base.name.lower() == "workspace" else base / "workspace"
    return workspace_root / INDEX_REL_PATH


def code_context_graph_tool(
    *,
    mode: str,
    query: str = "",
    file_path: str = "",
    symbol: str = "",
    max_results: int = 20,
    refresh: bool = False,
) -> dict[str, Any]:
    """Execute a project code graph query."""

    normalized_mode = str(mode or "").strip().lower()
    max_results = _clamp(max_results, 1, 100, default=20)

    if normalized_mode == "index":
        return build_index(force=True)

    if normalized_mode == "status":
        graph = load_or_build_index(refresh=refresh)
        return {
            "status": "ok",
            "mode": "status",
            "index": graph.get("index", {}),
            "summary": graph.get("summary", {}),
            "policy": graph.get("policy", {}),
        }

    graph = load_or_build_index(refresh=refresh)
    if normalized_mode == "files":
        return files_view(graph, query=query, max_results=max_results)
    if normalized_mode == "search":
        return search_graph(graph, query=query or symbol or file_path, max_results=max_results)
    if normalized_mode == "explore":
        return explore_graph(graph, query=query or symbol or file_path, max_results=max_results)
    if normalized_mode == "inspect":
        return inspect_graph(graph, file_path=file_path, symbol=symbol or query, max_results=max_results)
    if normalized_mode == "references":
        return references_graph(graph, query=query or symbol or file_path, file_path=file_path, symbol=symbol, max_results=max_results)
    if normalized_mode == "impact":
        return impact_graph(graph, query=query or symbol or file_path, file_path=file_path, symbol=symbol, max_results=max_results)
    if normalized_mode == "affected_tests":
        return affected_tests_graph(graph, query=query or file_path or symbol, file_path=file_path, symbol=symbol, max_results=max_results)

    return {
        "status": "error",
        "error": "unsupported_mode",
        "mode": normalized_mode,
        "message": "code_symbol_tool v2 不支持该 mode。",
        "supported_modes": ["status", "index", "search", "explore", "inspect", "references", "impact", "affected_tests", "files"],
    }


def build_index(*, force: bool = False) -> dict[str, Any]:
    root = project_root()
    out_path = index_path(root)
    if out_path.exists() and not force:
        existing = _read_json(out_path)
        if existing:
            return existing

    started = time.monotonic()
    files: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    file_hashes: dict[str, str] = {}

    for path in iter_indexable_files(root):
        rel = _rel(path, root)
        text = _read_text(path)
        if text is None:
            continue
        digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()
        file_hashes[rel] = digest
        language = _language_for_path(path)
        file_node = {
            "id": _file_id(rel),
            "path": rel,
            "language": language,
            "extension": path.suffix.lower(),
            "lineCount": len(text.splitlines()),
            "sizeBytes": path.stat().st_size,
            "hash": digest,
            "summary": _file_summary(path, text, language),
            "headings": _markdown_headings(text) if path.suffix.lower() == ".md" else [],
        }
        files.append(file_node)

        extracted_symbols, extracted_edges = _extract_file_graph(path, rel, text, language, root)
        symbols.extend(extracted_symbols)
        edges.extend(extracted_edges)
        for item in extracted_symbols:
            edges.append({"source": item["id"], "target": file_node["id"], "type": "symbol_defined_in"})

    edges.extend(_build_test_edges(files))
    summary = {
        "fileCount": len(files),
        "symbolCount": len(symbols),
        "edgeCount": len(edges),
        "languageCounts": dict(Counter(file["language"] for file in files)),
        "extensionCounts": dict(Counter(file["extension"] for file in files)),
        "durationMs": int((time.monotonic() - started) * 1000),
    }
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "ok",
        "mode": "index",
        "index": {
            "path": _rel(out_path, root),
            "updatedAt": _utc_like_now(),
            "root": str(root),
            "fresh": True,
        },
        "policy": {
            "provider": "vibelution_native",
            "mcp": False,
            "mutatesSource": False,
            "cacheOnlyWrite": True,
            "includedRoots": sorted(INCLUDED_ROOTS),
            "excludedPrefixes": sorted(EXCLUDED_PREFIXES),
        },
        "summary": summary,
        "files": files,
        "symbols": symbols,
        "edges": edges,
        "fileHashes": file_hashes,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_or_build_index(*, refresh: bool = False) -> dict[str, Any]:
    path = index_path()
    if refresh or not path.exists():
        return build_index(force=True)
    payload = _read_json(path)
    if not payload:
        return build_index(force=True)
    payload.setdefault("index", {})["fresh"] = _is_index_fresh(payload)
    return payload


def iter_indexable_files(root: Path) -> list[Path]:
    result: list[Path] = []
    for current_root, dirnames, filenames in os.walk(root):
        current = Path(current_root)
        rel_dir = _rel(current, root)
        dirnames[:] = [
            name for name in dirnames
            if _should_descend_dir(_normalize_rel(f"{rel_dir}/{name}" if rel_dir != "." else name))
        ]
        for filename in filenames:
            path = current / filename
            rel = _rel(path, root)
            if not _is_included(rel):
                continue
            if not _is_supported_file(path):
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            result.append(path)
    return sorted(result, key=lambda item: _rel(item, root))


def search_graph(graph: dict[str, Any], *, query: str, max_results: int = 20) -> dict[str, Any]:
    terms = _terms(query)
    if not terms:
        return _query_error("search", "query_required", "search 模式需要 query、symbol 或 file_path。")
    scored: list[tuple[int, dict[str, Any]]] = []
    for file in graph.get("files", []):
        score = _score_text(terms, " ".join([file.get("path", ""), file.get("summary", ""), " ".join(file.get("headings", []))]))
        if score:
            scored.append((score, {"kind": "file", **_public_file(file)}))
    for symbol in graph.get("symbols", []):
        score = _score_text(terms, " ".join([symbol.get("name", ""), symbol.get("qualifiedName", ""), symbol.get("path", ""), symbol.get("kind", ""), symbol.get("preview", "")]))
        if score:
            scored.append((score + 2, {"kind": "symbol", **_public_symbol(symbol)}))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("path", "")), str(item[1].get("name", ""))))
    results = [{**item, "score": score} for score, item in scored[:max_results]]
    return {"status": "ok", "mode": "search", "query": query, "count": len(results), "results": results}


def explore_graph(graph: dict[str, Any], *, query: str, max_results: int = 20) -> dict[str, Any]:
    search = search_graph(graph, query=query, max_results=max_results)
    if search.get("status") != "ok":
        return search
    files_by_path = _files_by_path(graph)
    symbols_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for symbol in graph.get("symbols", []):
        symbols_by_path[str(symbol.get("path") or "")].append(symbol)

    seen_paths: list[str] = []
    for item in search.get("results", []):
        path = str(item.get("path") or "")
        if path and path not in seen_paths:
            seen_paths.append(path)
    contexts = []
    for rel in seen_paths[: min(max_results, 8)]:
        file = files_by_path.get(rel)
        if not file:
            continue
        contexts.append(
            {
                "path": rel,
                "language": file.get("language"),
                "summary": file.get("summary"),
                "symbols": [_public_symbol(item) for item in symbols_by_path.get(rel, [])[:8]],
                "snippet": _snippet_for_file(rel),
            }
        )
    return {
        "status": "ok",
        "mode": "explore",
        "query": query,
        "summary": {"resultCount": len(search.get("results", [])), "contextCount": len(contexts)},
        "results": search.get("results", [])[:max_results],
        "contexts": contexts,
        "relationshipMap": _relationship_map(graph, seen_paths[:8]),
    }


def inspect_graph(graph: dict[str, Any], *, file_path: str = "", symbol: str = "", max_results: int = 20) -> dict[str, Any]:
    rel = _normalize_rel(file_path)
    files_by_path = _files_by_path(graph)
    if rel and rel in files_by_path:
        symbols = [_public_symbol(item) for item in graph.get("symbols", []) if item.get("path") == rel][:max_results]
        return {
            "status": "ok",
            "mode": "inspect",
            "target": {"filePath": rel},
            "file": _public_file(files_by_path[rel]),
            "symbols": symbols,
            "snippet": _snippet_for_file(rel, max_chars=MAX_SNIPPET_CHARS),
        }
    if symbol:
        matches = [
            item for item in graph.get("symbols", [])
            if _symbol_matches(item, symbol)
        ][:max_results]
        return {
            "status": "ok",
            "mode": "inspect",
            "target": {"symbol": symbol},
            "count": len(matches),
            "symbols": [_public_symbol(item) for item in matches],
            "snippets": [_snippet_for_symbol(item) for item in matches[:5]],
        }
    return _query_error("inspect", "target_required", "inspect 模式需要 file_path 或 symbol/query。")


def references_graph(
    graph: dict[str, Any],
    *,
    query: str = "",
    file_path: str = "",
    symbol: str = "",
    max_results: int = 20,
) -> dict[str, Any]:
    target = symbol or query or Path(file_path).stem
    rel = _normalize_rel(file_path)
    if not target and not rel:
        return _query_error("references", "target_required", "references 模式需要 symbol、query 或 file_path。")
    terms = _terms(target) if target else []
    results = []
    for file in graph.get("files", []):
        path = str(file.get("path") or "")
        if rel and path == rel:
            continue
        text = _read_indexed_text(path)
        if text is None:
            continue
        if terms and not all(term.lower() in text.lower() or term.lower() in path.lower() for term in terms[:3]):
            continue
        line_matches = _line_matches(text, terms or [Path(rel).stem], max_per_file=3)
        if line_matches:
            results.append({"path": path, "language": file.get("language"), "matches": line_matches})
        if len(results) >= max_results:
            break
    return {"status": "ok", "mode": "references", "target": {"query": target, "filePath": rel}, "count": len(results), "results": results}


def impact_graph(
    graph: dict[str, Any],
    *,
    query: str = "",
    file_path: str = "",
    symbol: str = "",
    max_results: int = 20,
) -> dict[str, Any]:
    rel = _normalize_rel(file_path)
    if not rel and symbol:
        matches = [item for item in graph.get("symbols", []) if _symbol_matches(item, symbol)]
        rel = str(matches[0].get("path") or "") if matches else ""
    if not rel and query:
        search = search_graph(graph, query=query, max_results=1)
        first = (search.get("results") or [{}])[0]
        rel = str(first.get("path") or "")
    if not rel:
        return _query_error("impact", "target_required", "impact 模式需要 file_path、symbol 或 query。")

    reverse = _reverse_imports(graph)
    direct = sorted(reverse.get(rel, set()))
    tests = _affected_tests_for_paths(graph, [rel] + direct, max_results=max_results)
    return {
        "status": "ok",
        "mode": "impact",
        "target": {"filePath": rel, "symbol": symbol},
        "directDependents": direct[:max_results],
        "affectedTests": tests,
        "relationshipMap": _relationship_map(graph, [rel] + direct[:8]),
    }


def affected_tests_graph(
    graph: dict[str, Any],
    *,
    query: str = "",
    file_path: str = "",
    symbol: str = "",
    max_results: int = 20,
) -> dict[str, Any]:
    rel = _normalize_rel(file_path)
    paths = []
    if rel:
        paths.append(rel)
    elif symbol:
        paths.extend(str(item.get("path") or "") for item in graph.get("symbols", []) if _symbol_matches(item, symbol))
    elif query:
        search = search_graph(graph, query=query, max_results=5)
        paths.extend(str(item.get("path") or "") for item in search.get("results", []) if item.get("path"))
    paths = list(dict.fromkeys(path for path in paths if path))
    tests = _affected_tests_for_paths(graph, paths, max_results=max_results)
    return {"status": "ok", "mode": "affected_tests", "target": {"paths": paths, "query": query, "symbol": symbol}, "count": len(tests), "tests": tests}


def files_view(graph: dict[str, Any], *, query: str = "", max_results: int = 20) -> dict[str, Any]:
    terms = _terms(query)
    items = []
    for file in graph.get("files", []):
        if terms and not _score_text(terms, " ".join([file.get("path", ""), file.get("language", ""), file.get("summary", "")])):
            continue
        items.append(_public_file(file))
    return {"status": "ok", "mode": "files", "query": query, "count": len(items[:max_results]), "files": items[:max_results]}


def _extract_file_graph(path: Path, rel: str, text: str, language: str, root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if language == "python":
        return _extract_python(path, rel, text, root)
    if language in {"typescript", "javascript"}:
        return _extract_typescript(path, rel, text, root)
    if language == "markdown":
        return _extract_markdown(rel, text), []
    return [], _extract_text_references(rel, text)


def _extract_python(path: Path, rel: str, text: str, root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    symbols: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return symbols, edges
    lines = text.splitlines()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            symbols.append(_symbol_node(rel, node.name, node.name, kind, getattr(node, "lineno", 1), getattr(node, "end_lineno", getattr(node, "lineno", 1)), lines))
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        qn = f"{node.name}.{child.name}"
                        symbols.append(_symbol_node(rel, child.name, qn, "method", getattr(child, "lineno", 1), getattr(child, "end_lineno", getattr(child, "lineno", 1)), lines))
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = _resolve_python_import(alias.name, root)
                edges.append({"source": _file_id(rel), "target": _file_id(target) if target else alias.name, "type": "imports", "metadata": {"module": alias.name}})
        elif isinstance(node, ast.ImportFrom) and node.module:
            target = _resolve_python_import(node.module, root)
            edges.append({"source": _file_id(rel), "target": _file_id(target) if target else node.module, "type": "imports", "metadata": {"module": node.module}})
    return symbols, edges


def _extract_typescript(path: Path, rel: str, text: str, root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    symbols: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    lines = text.splitlines()
    for kind, pattern in TS_SYMBOL_PATTERNS:
        for match in pattern.finditer(text):
            name = next((group for group in match.groups() if group), "")
            if not name:
                continue
            line = text.count("\n", 0, match.start()) + 1
            symbols.append(_symbol_node(rel, name, name, kind, line, line, lines))
    for match in TS_IMPORT_RE.finditer(text):
        specifier = match.group(1) or match.group(2) or ""
        target = _resolve_ts_import(path, specifier, root)
        edges.append({"source": _file_id(rel), "target": _file_id(target) if target else specifier, "type": "imports", "metadata": {"module": specifier}})
    edges.extend(_extract_text_references(rel, text))
    return symbols, edges


def _extract_markdown(rel: str, text: str) -> list[dict[str, Any]]:
    symbols = []
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            if title:
                symbols.append(_symbol_node(rel, title, title, "heading", idx, idx, lines))
    return symbols


def _extract_text_references(rel: str, text: str) -> list[dict[str, Any]]:
    edges = []
    for match in re.finditer(r"[\w./-]+\.(?:py|ts|tsx|md|json|toml|css)", text):
        target = _normalize_rel(match.group(0))
        if target:
            edges.append({"source": _file_id(rel), "target": _file_id(target), "type": "mentions_path"})
    return edges[:80]


def _build_test_edges(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paths = {str(file.get("path") or "") for file in files}
    edges = []
    for path in sorted(paths):
        if path.startswith("tests/") or "/test_" in path or Path(path).name.startswith("test_"):
            continue
        for candidate in _candidate_tests(path):
            if candidate in paths:
                edges.append({"source": _file_id(path), "target": _file_id(candidate), "type": "likely_tested_by"})
    return edges


def _affected_tests_for_paths(graph: dict[str, Any], paths: list[str], *, max_results: int) -> list[dict[str, Any]]:
    files = _files_by_path(graph)
    test_paths = {path for path in files if path.startswith("tests/") or "/test_" in path or Path(path).name.startswith("test_")}
    candidates: Counter[str] = Counter()
    for path in paths:
        for candidate in _candidate_tests(path):
            if candidate in files:
                candidates[candidate] += 5
        stem = Path(path).stem.replace("_", "").lower()
        parent = Path(path).parent.name.lower()
        for test in test_paths:
            compact = test.replace("_", "").lower()
            if stem and stem in compact:
                candidates[test] += 3
            if parent and parent in compact:
                candidates[test] += 1
    return [
        {"path": path, "score": score, "exists": path in files}
        for path, score in candidates.most_common(max_results)
    ]


def _relationship_map(graph: dict[str, Any], paths: list[str]) -> dict[str, Any]:
    ids = {_file_id(path) for path in paths}
    edges = [
        edge for edge in graph.get("edges", [])
        if str(edge.get("source")) in ids or str(edge.get("target")) in ids
    ][:120]
    return {
        "nodes": [_public_file(file) for file in graph.get("files", []) if _file_id(str(file.get("path") or "")) in ids],
        "edges": edges,
    }


def _reverse_imports(graph: dict[str, Any]) -> dict[str, set[str]]:
    reverse: dict[str, set[str]] = defaultdict(set)
    id_to_path = {_file_id(str(file.get("path") or "")): str(file.get("path") or "") for file in graph.get("files", [])}
    for edge in graph.get("edges", []):
        if edge.get("type") not in {"imports", "mentions_path"}:
            continue
        source = id_to_path.get(str(edge.get("source")))
        target = id_to_path.get(str(edge.get("target")))
        if source and target:
            reverse[target].add(source)
    return reverse


def _symbol_node(rel: str, name: str, qualified_name: str, kind: str, line: int, end_line: int, lines: list[str]) -> dict[str, Any]:
    preview = ""
    if 1 <= line <= len(lines):
        preview = lines[line - 1].strip()[:240]
    return {
        "id": _symbol_id(rel, qualified_name, line),
        "name": name,
        "qualifiedName": qualified_name,
        "kind": kind,
        "path": rel,
        "line": line,
        "endLine": end_line,
        "preview": preview,
    }


def _file_summary(path: Path, text: str, language: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if language == "python":
        try:
            doc = ast.get_docstring(ast.parse(text))
            if doc:
                return doc.splitlines()[0].strip()[:240]
        except SyntaxError:
            pass
    if path.suffix.lower() == ".md":
        for line in lines:
            if line.startswith("#"):
                return line.lstrip("#").strip()[:240]
    for line in lines[:20]:
        if not line.startswith(("#", "//", "/*", "*", "import ", "from ")):
            return line[:240]
    return Path(path).name


def _candidate_tests(path: str) -> list[str]:
    rel = _normalize_rel(path)
    p = Path(rel)
    if rel.startswith("tests/"):
        return [rel]
    stem = p.stem
    parent = p.parent.name
    candidates = [
        f"tests/test_{stem}.py",
        f"tests/test_{stem.replace('_', '')}.py",
        f"tests/{parent}/test_{stem}.py" if parent else "",
    ]
    if rel.startswith("web/src/"):
        web_rel = rel.replace("web/src/", "web/src/")
        candidates.extend([
            str(Path(web_rel).with_suffix(".test.ts")).replace("\\", "/"),
            str(Path(web_rel).with_suffix(".test.tsx")).replace("\\", "/"),
            str(Path(web_rel).with_name(f"{p.stem}.test.ts")).replace("\\", "/"),
            str(Path(web_rel).with_name(f"{p.stem}.test.tsx")).replace("\\", "/"),
        ])
    return list(dict.fromkeys(item for item in candidates if item))


def _resolve_python_import(module: str, root: Path) -> str:
    rel = module.replace(".", "/")
    file_path = root / f"{rel}.py"
    init_path = root / rel / "__init__.py"
    if file_path.exists():
        return _rel(file_path, root)
    if init_path.exists():
        return _rel(init_path, root)
    return ""


def _resolve_ts_import(source_path: Path, specifier: str, root: Path) -> str:
    if not specifier.startswith("."):
        return ""
    base = (source_path.parent / specifier).resolve()
    candidates = []
    for suffix in (".ts", ".tsx", ".js", ".jsx", ".json", ".css"):
        candidates.append(base.with_suffix(suffix))
    candidates.extend(base / f"index{suffix}" for suffix in (".ts", ".tsx", ".js", ".jsx"))
    for candidate in candidates:
        if candidate.exists():
            return _rel(candidate, root)
    return ""


def _is_index_fresh(payload: dict[str, Any]) -> bool:
    root = project_root()
    hashes = payload.get("fileHashes") if isinstance(payload.get("fileHashes"), dict) else {}
    current_files = iter_indexable_files(root)
    if len(current_files) != len(hashes):
        return False
    for path in current_files:
        rel = _rel(path, root)
        text = _read_text(path)
        if text is None:
            return False
        digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()
        if hashes.get(rel) != digest:
            return False
    return True


def _is_included(rel: str) -> bool:
    normalized = _normalize_rel(rel)
    if not normalized:
        return False
    if any(part in EXCLUDED_PARTS for part in normalized.split("/")):
        return False
    if any(normalized.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    if normalized in ROOT_FILES:
        return True
    return any(normalized == root or normalized.startswith(f"{root}/") for root in INCLUDED_ROOTS)


def _should_descend_dir(rel_dir: str) -> bool:
    normalized = _normalize_rel(rel_dir)
    if not normalized or normalized == ".":
        return True
    if any(part in EXCLUDED_PARTS for part in normalized.split("/")):
        return False
    prefix = f"{normalized.rstrip('/')}/"
    if normalized in INCLUDED_ROOTS or normalized in {root.split("/")[0] for root in INCLUDED_ROOTS}:
        return True
    if any(root.startswith(prefix) for root in INCLUDED_ROOTS):
        return True
    if any(prefix.startswith(excluded) for excluded in EXCLUDED_PREFIXES):
        return False
    return any(prefix.startswith(f"{root}/") for root in INCLUDED_ROOTS) or normalized in {Path(item).parent.as_posix() for item in ROOT_FILES if "/" in item}


def _is_supported_file(path: Path) -> bool:
    if path.suffix.lower() not in INDEX_EXTENSIONS:
        return False
    if path.name.endswith((".min.js", ".map")):
        return False
    return True


def _language_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".ts", ".tsx"}:
        return "typescript"
    if suffix in {".js", ".jsx"}:
        return "javascript"
    if suffix == ".md":
        return "markdown"
    if suffix == ".css":
        return "css"
    if suffix in {".json", ".toml", ".ini"}:
        return "config"
    if suffix in {".ps1", ".vbs"}:
        return "script"
    if suffix == ".html":
        return "html"
    return suffix.lstrip(".") or "text"


def _markdown_headings(text: str) -> list[str]:
    return [line.lstrip("#").strip() for line in text.splitlines() if line.startswith("#") and line.lstrip("#").strip()][:30]


def _public_file(file: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": file.get("path"),
        "language": file.get("language"),
        "lineCount": file.get("lineCount"),
        "summary": file.get("summary"),
    }


def _public_symbol(symbol: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": symbol.get("name"),
        "qualifiedName": symbol.get("qualifiedName"),
        "kind": symbol.get("kind"),
        "path": symbol.get("path"),
        "line": symbol.get("line"),
        "endLine": symbol.get("endLine"),
        "preview": symbol.get("preview"),
    }


def _symbol_matches(symbol: dict[str, Any], query: str) -> bool:
    q = str(query or "").strip().lower()
    if not q:
        return False
    values = [symbol.get("name"), symbol.get("qualifiedName"), symbol.get("path")]
    return any(q == str(value or "").lower() or q in str(value or "").lower() for value in values)


def _score_text(terms: list[str], text: str) -> int:
    haystack = str(text or "").lower()
    score = 0
    for term in terms:
        lowered = term.lower()
        if lowered in haystack:
            score += 5 if "/" in lowered or "." in lowered else 2
    return score


def _line_matches(text: str, terms: list[str], *, max_per_file: int) -> list[dict[str, Any]]:
    results = []
    lowered_terms = [term.lower() for term in terms if term]
    for idx, line in enumerate(text.splitlines(), start=1):
        lowered = line.lower()
        if any(term in lowered for term in lowered_terms):
            results.append({"line": idx, "preview": line.strip()[:260]})
            if len(results) >= max_per_file:
                break
    return results


def _snippet_for_file(rel: str, *, max_chars: int = MAX_SNIPPET_CHARS) -> str:
    text = _read_indexed_text(rel)
    if not text:
        return ""
    return text[:max_chars].rstrip()


def _snippet_for_symbol(symbol: dict[str, Any]) -> dict[str, Any]:
    rel = str(symbol.get("path") or "")
    text = _read_indexed_text(rel)
    if text is None:
        return {"path": rel, "symbol": symbol.get("qualifiedName"), "text": ""}
    lines = text.splitlines()
    start = max(1, int(symbol.get("line") or 1))
    end = min(len(lines), int(symbol.get("endLine") or start))
    excerpt = "\n".join(lines[start - 1:end])[:MAX_SNIPPET_CHARS]
    return {"path": rel, "symbol": symbol.get("qualifiedName"), "line": start, "endLine": end, "text": excerpt}


def _read_indexed_text(rel: str) -> str | None:
    path = project_root() / _normalize_rel(rel)
    if not path.exists() or not _is_supported_file(path):
        return None
    return _read_text(path)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            return None
    except OSError:
        return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _files_by_path(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(file.get("path") or ""): file for file in graph.get("files", [])}


def _terms(query: str) -> list[str]:
    raw = str(query or "").strip()
    if not raw:
        return []
    terms = re.findall(r"[\w./:-]+|[\u4e00-\u9fff]{2,}", raw)
    return [term for term in terms if len(term.strip()) >= 2][:12]


def _normalize_rel(path: str | Path) -> str:
    raw = str(path or "").replace("\\", "/").strip()
    if not raw:
        return ""
    try:
        p = Path(raw)
        if p.is_absolute():
            return _rel(p, project_root())
    except OSError:
        return raw.strip("/")
    return raw.strip("./")


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path).replace("\\", "/")


def _file_id(rel: str) -> str:
    return f"file:{_normalize_rel(rel)}"


def _symbol_id(rel: str, qualified_name: str, line: int) -> str:
    return f"symbol:{_normalize_rel(rel)}:{qualified_name}:{line}"


def _query_error(mode: str, error: str, message: str) -> dict[str, Any]:
    return {"status": "error", "mode": mode, "error": error, "message": message}


def _clamp(value: Any, minimum: int, maximum: int, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _utc_like_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
