# -*- coding: utf-8 -*-
"""Parallel-session situational awareness for development agents.

一条命令回答三件事：现在谁在干什么、main 处于什么状态、此刻能不能合入。
数据源全部只读：coordination claim 表（复用 task_closeout 的同一脚本）、
``git worktree list``、main 最近合入、根 main 脏文件。

用法::

    python scripts/agent_session_status.py                     # 人类可读简报
    python scripts/agent_session_status.py --json              # 机读
    python scripts/agent_session_status.py --check-merge --files a.py b.py
        # 额外输出：给定目标文件的合入时机判断（干净门 + claim 冲突预检）

设计取舍：不 import local_quality_gate（它顶层拉起 validation_toolchain
整链），脚本候选列表与 scope 匹配逻辑在此内联并保持与
``scripts/local_quality_gate.py`` 的 GUARD_SCRIPT_CANDIDATES / scope_covers
一致；两边若变更需同步。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

# 与 scripts/local_quality_gate.GUARD_SCRIPT_CANDIDATES 保持一致（勿单侧变更）。
GUARD_SCRIPT_CANDIDATES: tuple[Path, ...] = (
    Path.home() / ".codex" / "skills" / "briefbound-project-memory" / "scripts" / "agent_coordination.py",
    Path.home() / ".codex" / "skills" / "ccdawn-dawn-agent-html-memory" / "scripts" / "agent_work_guard.py",
)


def _run_git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return ""
    # 只去首尾换行，保留行内/行首空白（porcelain 的状态列依赖前导空格）。
    return completed.stdout.strip("\r\n")


def scope_covers(scope: str, changed_path: str) -> bool:
    """Path-prefix scope matching, mirroring local_quality_gate.scope_covers."""

    normalized_scope = str(scope or "").strip().strip("/\\").replace("\\", "/")
    normalized_path = str(changed_path or "").strip().strip("/\\").replace("\\", "/")
    if not normalized_scope or not normalized_path:
        return False
    if normalized_scope == "." or normalized_scope == "*":
        return True
    return normalized_path == normalized_scope or normalized_path.startswith(
        f"{normalized_scope}/"
    )


def find_coordination_script() -> Path | None:
    for candidate in GUARD_SCRIPT_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def read_coordination_status(main_root: Path) -> dict[str, Any] | None:
    script = find_coordination_script()
    if script is None:
        return None
    completed = subprocess.run(
        [sys.executable, str(script), str(main_root), "status", "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def active_claims(status: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not status:
        return []
    claims = status.get("claims") if isinstance(status.get("claims"), list) else []
    return [
        claim
        for claim in claims
        if isinstance(claim, dict) and str(claim.get("status") or "") in {"active", "ready", "yielded"}
    ]


def claims_touching(claims: Sequence[dict[str, Any]], paths: Sequence[str]) -> list[dict[str, Any]]:
    touched: list[dict[str, Any]] = []
    for claim in claims:
        scopes = claim.get("scopes") if isinstance(claim.get("scopes"), list) else []
        normalized = [str(scope) for scope in scopes if isinstance(scope, str)]
        if any(scope_covers(scope, path) for scope in normalized for path in paths):
            touched.append(claim)
    return touched


def dirty_paths(main_root: Path) -> list[str]:
    lines = _run_git(main_root, "status", "--porcelain").splitlines()
    paths: list[str] = []
    for line in lines:
        entry = line.rstrip("\r\n")
        if len(entry) <= 3:
            continue
        # porcelain v1: "XY <path>"（前缀固定 2 状态列 + 1 空格；不能先 strip，
        # 否则 " M path" 的前导空格被剥掉导致列错位）。rename 形态取 -> 后的新路径。
        payload = entry[3:]
        if "->" in payload:
            payload = payload.split("->")[-1].strip()
        path = payload.strip().strip('"')
        if path:
            paths.append(path)
    return paths


def recent_merges(main_root: Path, limit: int = 5) -> list[str]:
    log = _run_git(main_root, "log", "--oneline", f"-{limit}")
    return [line for line in log.splitlines() if line.strip()]


def worktree_rows(main_root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in _run_git(main_root, "worktree", "list", "--porcelain").split("\n\n"):
        entry: dict[str, str] = {}
        for part in line.splitlines():
            if part.startswith("worktree "):
                entry["path"] = part[len("worktree "):]
            elif part.startswith("branch "):
                entry["branch"] = part[len("branch "):]
            elif part.startswith("HEAD "):
                entry["head"] = part[len("HEAD "):][:9]
        if entry.get("path"):
            rows.append(entry)
    return rows


def build_report(main_root: Path, merge_check_files: Sequence[str]) -> dict[str, Any]:
    status = read_coordination_status(main_root)
    claims = active_claims(status)
    dirty = dirty_paths(main_root)
    dirty_owners: list[dict[str, str]] = []
    if dirty:
        for claim in claims_touching(claims, dirty):
            dirty_owners.append(
                {
                    "agentId": str(claim.get("agentId") or ""),
                    "branch": str(claim.get("branch") or ""),
                    "claimId": str(claim.get("id") or ""),
                }
            )
    merge_assessment: dict[str, Any] = {}
    if merge_check_files:
        touching = claims_touching(claims, merge_check_files)
        merge_assessment = {
            "targetFiles": list(merge_check_files),
            "mainDirty": bool(dirty),
            "claimsTouchingTarget": [
                {
                    "agentId": str(claim.get("agentId") or ""),
                    "branch": str(claim.get("branch") or ""),
                    "claimId": str(claim.get("id") or ""),
                }
                for claim in touching
            ],
            "readyToMerge": not dirty and not touching,
        }
    return {
        "coordinationAvailable": status is not None,
        "activeClaims": [
            {
                "claimId": str(claim.get("id") or ""),
                "agentId": str(claim.get("agentId") or ""),
                "branch": str(claim.get("branch") or ""),
                "status": str(claim.get("status") or ""),
                "scopes": [str(s) for s in (claim.get("scopes") or []) if isinstance(s, str)][:8],
            }
            for claim in claims
        ],
        "worktrees": worktree_rows(main_root),
        "recentMainMerges": recent_merges(main_root),
        "mainDirtyPaths": dirty,
        "mainDirtySuspectedOwners": dirty_owners,
        "mergeAssessment": merge_assessment,
    }


def render_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    claims = report.get("activeClaims") or []
    lines.append("== 并行会话态势 ==")
    lines.append(
        f"coordination: {'可用' if report.get('coordinationAvailable') else '不可用（降级为 git-only）'} · 活跃 claim: {len(claims)}"
    )
    for claim in claims:
        scopes = ", ".join(claim.get("scopes") or []) or "(全仓库)"
        lines.append(
            f"  - [{claim.get('status')}] {claim.get('agentId')} @ {claim.get('branch')} → {scopes}"
        )
    lines.append("")
    lines.append("== 活跃 worktree ==")
    main_path = ""
    for row in report.get("worktrees") or []:
        lines.append(f"  - {row.get('path')} [{row.get('branch') or 'detached'}]")
        if not main_path:
            main_path = row.get("path") or ""
    lines.append("")
    lines.append("== main 最近合入 ==")
    for entry in report.get("recentMainMerges") or []:
        lines.append(f"  {entry}")
    dirty = report.get("mainDirtyPaths") or []
    lines.append("")
    lines.append(f"== 根 main 工作区: {'干净' if not dirty else f'{len(dirty)} 个未提交路径'} ==")
    for path in dirty[:10]:
        lines.append(f"  M {path}")
    owners = report.get("mainDirtySuspectedOwners") or []
    if owners:
        owner_text = "; ".join(
            f"{o.get('agentId')} @ {o.get('branch')}" for o in owners
        )
        lines.append(f"  疑似 owner: {owner_text}")
    assessment = report.get("mergeAssessment") or {}
    if assessment:
        lines.append("")
        lines.append("== 合入时机判断 ==")
        ready = assessment.get("readyToMerge")
        if ready:
            lines.append("  READY: main 干净且无活跃 claim 触碰目标文件，可走 closeout 合入。")
        else:
            reasons = []
            if assessment.get("mainDirty"):
                reasons.append("main 有未提交改动（closeout 干净门会拒绝）")
            for claim in assessment.get("claimsTouchingTarget") or []:
                reasons.append(
                    f"claim 冲突: {claim.get('agentId')} @ {claim.get('branch')}"
                )
            lines.append("  BLOCKED: " + "；".join(reasons))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parallel-session situational awareness (read-only).")
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output.")
    parser.add_argument(
        "--check-merge",
        action="store_true",
        help="Assess merge timing for the files passed via --files.",
    )
    parser.add_argument("--files", nargs="*", default=[], help="Target files for --check-merge.")
    arguments = parser.parse_args(argv)

    main_root = Path(arguments.project_root).resolve()
    if not (main_root / ".git").exists():
        print(json.dumps({"ok": False, "error": f"not a git repository: {main_root}"}))
        return 2

    report = build_report(main_root, arguments.files if arguments.check_merge else [])
    if arguments.json:
        print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
