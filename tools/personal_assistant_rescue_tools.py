"""Personal-assistant rescue tools: bounded Git writes and startup diagnosis.

Both tools stay inside the current project checkout. Git writes are ordinary
registered tools, so the native per-call approval path still decides whether a
commit, revert or reset runs. The diagnosis tool only reads bounded summaries;
it never returns a full stdout log body.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MAX_JSON_CHARS = 20000
_MAX_MESSAGE_CHARS = 2000
_READ_ACTIONS = frozenset({"status", "diff", "log", "show", "branch_list"})
_WRITE_ACTIONS = frozenset(
    {"commit", "stash", "checkout_path", "revert_commit", "reset_to_commit"}
)
_FORBIDDEN_ACTIONS = frozenset(
    {"push", "pull", "fetch", "remote", "clone", "submodule"}
)
_DIAGNOSIS_KEYS = ("status", "process", "runtime", "workbench", "lifecycleProof")


def _blocked(message: str, *, code: str = "BLOCKED") -> str:
    return json.dumps(
        {"ok": False, "status": "blocked", "code": code, "message": message},
        ensure_ascii=False,
    )


def _text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _bounded(text: str, limit: int = 6000) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "\n…[truncated]"


def _git(*args: str, timeout: float = 30.0) -> Any:
    from core.infrastructure.git_process import run_git

    return run_git(
        list(args),
        cwd=str(PROJECT_ROOT),
        timeout=timeout,
        capture_output=True,
        text=True,
    )


def _coerce_args(raw: str | dict | None) -> dict[str, Any]:
    if raw in (None, ""):
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        if len(raw) > _MAX_JSON_CHARS:
            raise ValueError("args_json 过长")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("args_json 必须是 JSON 对象") from exc
        if not isinstance(value, dict):
            raise TypeError("args_json 必须是 JSON 对象")
        return value
    raise ValueError("args_json 必须是 JSON 对象或对象字符串")


def _project_paths(raw: Any) -> list[str]:
    if raw in (None, ""):
        return []
    items = raw if isinstance(raw, list) else [raw]
    normalized: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        candidate = (
            Path(text).resolve()
            if Path(text).is_absolute()
            else (PROJECT_ROOT / text).resolve()
        )
        if candidate != PROJECT_ROOT and PROJECT_ROOT not in candidate.parents:
            raise ValueError("path 必须位于当前项目 checkout 内")
        if ".git" in candidate.parts:
            raise ValueError("path 不能指向 .git")
        relative = candidate.relative_to(PROJECT_ROOT).as_posix()
        normalized.append(relative or ".")
    return normalized


def _safe_paths(raw: Any) -> tuple[list[str], str]:
    try:
        return _project_paths(raw), ""
    except ValueError as exc:
        return [], str(exc)


def _result(action: str, completed: Any, *, extra: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {
        "ok": int(completed.returncode) == 0,
        "status": "ready" if int(completed.returncode) == 0 else "failed",
        "action": action,
        "exitCode": int(completed.returncode),
        "stdout": _bounded(_text(completed.stdout)),
        "stderr": _bounded(_text(completed.stderr), 3000),
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _head_short() -> str:
    return _text(_git("rev-parse", "--short", "HEAD").stdout).strip()


def _dirty_count() -> int:
    output = _text(_git("status", "--porcelain=v1").stdout)
    return len([line for line in output.splitlines() if line.strip()])


def personal_assistant_git_tool(action: str = "status", args_json: str = "") -> str:
    """Read or write the current project checkout's Git state for platform rescue.

    action: read-only `status`, `diff`, `log`, `show`, `branch_list`; write
    `commit`, `stash`, `checkout_path`, `revert_commit`, `reset_to_commit`.
    Write actions still go through the native per-call approval path.
    args_json keys: message (commit/stash), paths (commit/stash/checkout_path),
    ref (show/revert_commit/reset_to_commit), staged_only (diff), stat (diff/log),
    limit (log, max 50), mode (reset: soft|mixed, default soft).
    Push, pull, fetch, remote, clone and submodule are not supported.
    """
    normalized = str(action or "").strip().lower()
    if normalized in _FORBIDDEN_ACTIONS:
        return _blocked(f"救援工具不执行远端或子模块操作：{action}")
    if normalized not in (_READ_ACTIONS | _WRITE_ACTIONS):
        return _blocked(f"未登记的 Git 动作：{action}")
    try:
        args = _coerce_args(args_json)
    except (TypeError, ValueError) as exc:
        return _blocked(str(exc))

    if normalized == "status":
        return _result("status", _git("status", "--porcelain=v1", "-b"))

    if normalized == "diff":
        command = ["diff", "--stat" if bool(args.get("stat")) else "--patch"]
        if bool(args.get("staged_only")):
            command.insert(1, "--staged")
        paths, path_error = _safe_paths(args.get("paths"))
        if path_error:
            return _blocked(path_error)
        if paths:
            command.extend(["--", *paths])
        completed = _git(*command)
        return _result("diff", completed)

    if normalized == "log":
        try:
            limit = max(1, min(int(args.get("limit") or 10), 50))
        except (TypeError, ValueError):
            return _blocked("limit 必须是整数")
        command = ["log", "--oneline", f"-n{limit}"]
        if bool(args.get("stat")):
            command.append("--stat")
        return _result("log", _git(*command))

    if normalized == "show":
        ref = str(args.get("ref") or "").strip()
        if not ref:
            return _blocked("show 需要 ref")
        return _result("show", _git("show", "--stat", "--oneline", "--no-renames", ref))

    if normalized == "branch_list":
        completed = _git(
            "branch",
            "--list",
            "--format=%(refname:short) %(objectname:short) %(upstream:short)",
        )
        return _result("branch_list", completed)

    if normalized == "commit":
        message = str(args.get("message") or "").strip()
        if not message:
            return _blocked("commit 需要 message")
        if len(message) > _MAX_MESSAGE_CHARS:
            return _blocked("commit message 过长")
        paths, path_error = _safe_paths(args.get("paths"))
        if path_error:
            return _blocked(path_error)
        if paths:
            added = _git("add", "--", *paths)
            if int(added.returncode) != 0:
                return _result("commit", added)
        completed = _git("commit", "-m", message)
        return _result(
            "commit",
            completed,
            extra={"head": _head_short(), "dirtyCount": _dirty_count()},
        )

    if normalized == "stash":
        message = str(args.get("message") or "").strip() or "personal-assistant rescue stash"
        command = ["stash", "push", "-m", message]
        paths, path_error = _safe_paths(args.get("paths"))
        if path_error:
            return _blocked(path_error)
        if paths:
            command.extend(["--", *paths])
        return _result("stash", _git(*command))

    if normalized == "checkout_path":
        paths, path_error = _safe_paths(args.get("paths"))
        if path_error:
            return _blocked(path_error)
        if not paths:
            return _blocked("checkout_path 需要 paths")
        tracked = _git("ls-files", "--error-unmatch", "--", *paths)
        if int(tracked.returncode) != 0:
            return _result("checkout_path", tracked)
        return _result(
            "checkout_path",
            _git("checkout", "--", *paths),
            extra={"head": _head_short()},
        )

    if normalized == "revert_commit":
        ref = str(args.get("ref") or "").strip()
        if not ref:
            return _blocked("revert_commit 需要 ref")
        return _result(
            "revert_commit",
            _git("revert", "--no-edit", ref),
            extra={"head": _head_short()},
        )

    mode = str(args.get("mode") or "soft").strip().lower()
    if mode not in {"soft", "mixed"}:
        return _blocked("reset_to_commit 只允许 soft 或 mixed，禁止 hard")
    ref = str(args.get("ref") or "HEAD~1").strip()
    return _result(
        "reset_to_commit",
        _git("reset", f"--{mode}", ref),
        extra={"head": _head_short()},
    )


def personal_assistant_startup_diagnosis_tool(recent_scene_limit: int = 3) -> str:
    """Aggregate Launcher, backend and frontend startup health for platform rescue.

    Reads Launcher status, active-work guard, frontend build freshness, the
    bounded agent-log firstRead, recent runtime scenes, and Git HEAD/dirty state.
    Use this first when the workbench will not start or behaves unexpectedly.
    The result is a bounded summary; open a named evidence path only when needed.
    """
    try:
        limit = max(1, min(int(recent_scene_limit or 3), 10))
    except (TypeError, ValueError):
        return _blocked("recent_scene_limit 必须是整数")
    try:
        from core.diagnostics.agent_log_context import build_agent_log_context
        from core.launcher.frontend_build import frontend_build_status
        from core.launcher.service import (
            get_launcher_active_work_status,
            get_launcher_status,
        )

        launcher = get_launcher_status()
        active = get_launcher_active_work_status()
        build = frontend_build_status(PROJECT_ROOT)
        context = build_agent_log_context(
            PROJECT_ROOT, recent_scene_limit=limit
        )
    except Exception as exc:  # noqa: BLE001 - rescue surface must stay JSON
        return json.dumps(
            {
                "ok": False,
                "status": "failed",
                "code": "DIAGNOSIS_UNAVAILABLE",
                "message": f"{type(exc).__name__}: {exc}",
            },
            ensure_ascii=False,
        )
    proof = launcher.get("lifecycleProof") if isinstance(launcher, dict) else {}
    proof = proof if isinstance(proof, dict) else {}
    components = []
    for item in list(proof.get("components") or [])[:8]:
        if not isinstance(item, dict):
            continue
        components.append(
            {
                key: item.get(key)
                for key in ("id", "state", "ok", "detail")
                if key in item
            }
        )
    active_runs = {}
    active_proof = active.get("lifecycleProof") if isinstance(active, dict) else {}
    if isinstance(active_proof, dict):
        active_runs = active_proof.get("activeWorkRuns") or {}
    evidence = []
    for item in list(context.get("evidencePaths") or [])[:5]:
        if isinstance(item, dict):
            evidence.append(
                {
                    key: item.get(key)
                    for key in ("absolutePath", "warning", "kind")
                    if key in item
                }
            )
    return json.dumps(
        {
            "ok": True,
            "status": "ready",
            "git": {"head": _head_short(), "dirtyCount": _dirty_count()},
            "launcher": {
                "overallState": proof.get("overallState"),
                "summary": proof.get("summary"),
                "phase": proof.get("phase"),
                "verifiedAt": proof.get("verifiedAt"),
                "components": components,
            },
            "activeWork": {"activeWorkRuns": active_runs},
            "frontendBuild": {
                "current": bool(build.get("current")) if isinstance(build, dict) else False,
                "reason": _bounded(str(build.get("reason") or ""), 600),
            },
            "agentLog": {
                "conclusion": _bounded(str(context.get("conclusion") or ""), 1200),
                "nextStep": context.get("nextStep"),
                "doNotDo": context.get("doNotDo"),
                "evidencePaths": evidence,
            },
        },
        ensure_ascii=False,
    )
