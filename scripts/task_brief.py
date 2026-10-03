# -*- coding: utf-8 -*-
"""Task kickoff brief: one command that aggregates what a development agent
would otherwise re-derive by hand at the start of every task.

聚合五段::

    1. 域定位与测试建议   --files 匹配 tests/test_matrix.yaml 的 rules.paths
    2. claim 冲突预检     活跃 claims 的 scopes vs 目标文件/域
    3. 修复历史           fix_ledger 按任务关键词与文件检索
    4. 文档指引           命中面 → ownership/README 链接
    5. 本地开源参考       任务与 owning surface → 固定版本项目卡片

用法::

    python scripts/task_brief.py --task "修复会话流断线重连" --files core/llm/client.py
    python scripts/task_brief.py --task "config 面板保存失败"

只读；coordination 或 ledger 不可用时对应段降级标注，不阻断其余段。
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fix_ledger  # noqa: E402
from agent_session_status import active_claims, claims_touching, read_coordination_status, scope_covers  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 命中面（路径或矩阵 rule 关键词）→ 指引文档。小而稳定；新增域时补一行。
DOC_GUIDES: tuple[tuple[str, str], ...] = (
    ("web/src/routes/chat", "web/src/routes/chat/README.md"),
    ("web/src/routes/teams", "web/src/routes/teams/README.md"),
    ("web/src/routes", "web/src/routes/README.md"),
    ("web/src/components/vui", "web/src/components/vui/README.md"),
    ("web/src/api", "docs/guides/ownership.md (FE API 行)"),
    ("core/web/services/team_workflow", "core/web/services/README.md"),
    ("core/web/services", "core/web/services/README.md"),
    ("core/web/routes", "docs/guides/ownership.md"),
    ("core/llm", "core/llm/PROTOCOL.md"),
    ("core/infrastructure", "docs/standards/development-standard.md §8"),
    ("config", "core/web/services/config_services.md"),
    ("desktop/electron", "core/web/services/launcher_runtime.md"),
    ("tools", "tools/README.md"),
    ("tests", "tests/README.md"),
)

_STOPWORDS = frozenset({
    "修复", "修", "改", "添加", "新增", "删除", "调整", "优化", "问题", "失败", "异常",
    "the", "a", "an", "fix", "add", "refactor", "update", "and", "for", "with", "of",
})


def extract_keywords(task: str, limit: int = 6) -> list[str]:
    tokens = re.split(r"[\s,，。:：;；/\\()\[\]{}]+", str(task or ""))
    keywords: list[str] = []
    for token in tokens:
        cleaned = token.strip()
        if len(cleaned) >= 2 and cleaned.lower() not in _STOPWORDS:
            keywords.append(cleaned.lower())
        if len(keywords) >= limit:
            break
    return keywords


def load_matrix_rules(matrix_path: Path) -> list[dict[str, Any]]:
    """Load test_matrix.yaml rules; falls back to an empty rule set."""

    if not matrix_path.is_file():
        return []
    try:
        import yaml  # type: ignore[import-not-found]

        payload = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rules = payload.get("rules") if isinstance(payload, dict) else None
    if not isinstance(rules, list):
        return []
    return [rule for rule in rules if isinstance(rule, dict)]


def match_rules(files: Sequence[str], rules: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for rule in rules:
        patterns = [str(p) for p in rule.get("paths") or [] if isinstance(p, str)]
        if not patterns:
            continue
        for path in files:
            normalized = str(path).replace("\\", "/").lstrip("/")
            if any(fnmatch.fnmatch(normalized, pattern.replace("\\", "/")) for pattern in patterns):
                matched.append(rule)
                break
    return matched


def guide_for(surface: str) -> str | None:
    normalized = str(surface).replace("\\", "/")
    for prefix, doc in DOC_GUIDES:
        if normalized.startswith(prefix) or prefix in normalized:
            return doc
    return None


def github_projects_for_task(main_root: Path, task: str, files: Sequence[str]) -> dict[str, Any]:
    """Discover bounded local pointers; never clone, execute or write sources."""
    queries = [str(task).strip()[:240]]
    paths = [str(path).replace("\\", "/").lower() for path in files]
    if any(path.startswith("web/") for path in paths):
        queries.append("前端治理")
    if any(path.startswith(("core/", "tools/")) or path == "agent.py" for path in paths):
        queries.append("后端治理")
    queries = list(dict.fromkeys(query for query in queries if query))
    cards: dict[str, dict[str, Any]] = {}
    ranked_queries: list[list[dict[str, Any]]] = []
    error = ""
    try:
        from core.web.services.github_project_library_service import search_github_project_cards

        for query in queries:
            ranked = search_github_project_cards(query=query, limit=5, project_root=main_root)
            ranked_queries.append(ranked)
            for card in ranked:
                identity = str((card.get("metadata") or {}).get("fullName") or card.get("resultId") or "")
                if identity not in cards or float(card.get("score") or 0) > float(cards[identity].get("score") or 0):
                    cards[identity] = card
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        error = type(exc).__name__
    # Keep both owning surfaces visible when a task spans frontend and backend.
    ordered: dict[str, dict[str, Any]] = {}
    for rank in range(5):
        for ranked in ranked_queries:
            if rank >= len(ranked):
                continue
            card = ranked[rank]
            identity = str((card.get("metadata") or {}).get("fullName") or card.get("resultId") or "")
            if identity not in ordered and len(ordered) < 5:
                ordered[identity] = cards[identity]
    return {
        "githubProjects": list(ordered.values()),
        "githubProjectQueries": queries,
        "githubProjectsError": error,
    }


def build_brief(
    main_root: Path,
    *,
    task: str,
    files: Sequence[str],
) -> dict[str, Any]:
    keywords = extract_keywords(task)
    rules = load_matrix_rules(main_root / "tests" / "test_matrix.yaml")
    matched_rules = match_rules(files, rules)

    status = read_coordination_status(main_root)
    claims = active_claims(status)
    surface_paths = list(files) + [str(p) for rule in matched_rules for p in rule.get("paths") or []][:12]
    conflicts = claims_touching(claims, surface_paths) if surface_paths else []

    ledger_entries: list[dict[str, Any]] = []
    ledger_error = ""
    try:
        # 双路查询合并：关键词路可命中未标注文件的条目，文件路可命中措辞
        # 不同的条目；按 id 去重后截断。
        by_keyword = fix_ledger.query_entries(main_root, keywords=keywords, limit=5)
        by_file = fix_ledger.query_entries(main_root, files=list(files), limit=5)
        seen_ids: set[str] = set()
        for entry in by_keyword + by_file:
            entry_id = str(entry.get("id") or "")
            if entry_id in seen_ids:
                continue
            seen_ids.add(entry_id)
            ledger_entries.append(entry)
        ledger_entries = ledger_entries[:5]
    except fix_ledger.FixLedgerError as error:
        ledger_error = str(error)

    guides = sorted({doc for doc in (guide_for(f) for f in files) if doc})

    return {
        "task": task,
        "keywords": keywords,
        "matchedRules": [
            {
                "id": str(rule.get("id") or ""),
                "description": str(rule.get("description") or ""),
                "commands": [str(c) for c in rule.get("commands") or []][:3],
            }
            for rule in matched_rules
        ],
        "claimConflicts": [
            {
                "agentId": str(claim.get("agentId") or ""),
                "branch": str(claim.get("branch") or ""),
                "claimId": str(claim.get("id") or ""),
                "scopes": [str(s) for s in claim.get("scopes") or [] if isinstance(s, str)][:6],
            }
            for claim in conflicts
        ],
        "fixHistory": ledger_entries,
        "fixHistoryError": ledger_error,
        "docGuides": guides,
        **github_projects_for_task(main_root, task, files),
    }


def render_text(brief: dict[str, Any]) -> str:
    lines: list[str] = [f"== 任务简报: {brief.get('task')} =="]
    lines.append(f"关键词: {', '.join(brief.get('keywords') or []) or '(none)'}")
    lines.append("")
    lines.append("-- 域定位与测试建议 --")
    rules = brief.get("matchedRules") or []
    if not rules:
        lines.append("  (未命中 test_matrix 规则；无 --files 时建议先补目标文件再跑一次)")
    for rule in rules:
        lines.append(f"  [{rule.get('id')}] {rule.get('description')}")
        for command in rule.get("commands") or []:
            lines.append(f"    $ {command}")
    lines.append("")
    lines.append("-- claim 冲突预检 --")
    conflicts = brief.get("claimConflicts") or []
    if not conflicts:
        lines.append("  无活跃 claim 触碰目标面。")
    for conflict in conflicts:
        lines.append(
            f"  ⚠ {conflict.get('agentId')} @ {conflict.get('branch')} → {', '.join(conflict.get('scopes') or [])}"
        )
    lines.append("")
    lines.append("-- 相关修复历史 --")
    history = brief.get("fixHistory") or []
    if brief.get("fixHistoryError"):
        lines.append(f"  (ledger 不可用: {brief.get('fixHistoryError')})")
    elif not history:
        lines.append("  (无匹配条目)")
    for entry in history:
        lines.append(fix_ledger.render_entry(entry))
    lines.append("")
    lines.append("-- 文档指引 --")
    guides = brief.get("docGuides") or []
    if not guides:
        lines.append("  (见 docs/guides/route.md 全量路由)")
    for doc in guides:
        lines.append(f"  → {doc}")
    lines.append("")
    lines.append("-- 本地开源参考 --")
    if brief.get("githubProjectsError"):
        lines.append(f"  (本地索引不可用: {brief['githubProjectsError']})")
    elif not brief.get("githubProjects"):
        lines.append("  (无匹配项目；索引空或查询未命中不表示没有成熟方案)")
    for card in brief.get("githubProjects") or []:
        metadata = card.get("metadata") or {}
        review = metadata.get("governanceReview") or {}
        lines.append(f"  → {metadata.get('fullName')}: {review.get('status') or '未审查'} · {metadata.get('localPath')}")
        if review.get("borrowedSlice"):
            lines.append(f"    借鉴点: {review['borrowedSlice']}")
        if review.get("reuseBoundary"):
            lines.append(f"    边界: {review['reuseBoundary']}")
        for ref in review.get("evidenceRefs") or []:
            lines.append(f"    证据: {ref.get('absolutePath')}:{ref.get('line')}")
    lines.append("  卡片只用于发现候选；先读固定 HEAD 的具体源码。静态审查不代表运行验证或代码复用许可。")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Task kickoff brief (read-only aggregation).")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--task", required=True, help="One-line task description.")
    parser.add_argument("--files", nargs="*", default=[], help="Target files (git-relative).")
    parser.add_argument("--json", action="store_true", help="Print the bounded kickoff brief as JSON.")
    arguments = parser.parse_args(argv)

    main_root = Path(arguments.project_root).resolve()
    brief = build_brief(main_root, task=arguments.task, files=arguments.files)
    if arguments.json:
        print(json.dumps({"ok": True, **brief}, ensure_ascii=False, indent=2))
    else:
        print(render_text(brief))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
