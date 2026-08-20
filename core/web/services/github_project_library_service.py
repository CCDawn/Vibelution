"""Persistent GitHub OSS project library under project memory.

§2.2 ranking (locked alignment):
- Local: `skill_library_service` registry + generated INDEX — ADAPT.
- Local: `no_console_git.run_git` for windowless clone/fetch — REUSE.
- Local: public catalog mixed-read (metadata, then open locator) — ADAPT.
- External: Hugging Face hub cache naming (`owner__name`) — naming only.
Not borrowed: Zoekt/Sourcegraph engines; dumping clone bodies into RAG.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

import httpx

from core.chat.chat_task_types import trim_lines
from core.infrastructure.no_console_git import run_git
from vibelution_storage import resolve_project_memory_home

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = 1
LIBRARY_DIRNAME = "github-projects"
REGISTRY_NAME = "registry.json"
INDEX_NAME = "INDEX.md"
REPOS_DIRNAME = "repos"
MAX_PROJECTS = 20
MAX_REPO_SIZE_KB = 1_048_576  # GitHub `size` is KiB; ~1 GiB
CLONE_TIMEOUT_SECONDS = 600.0
FETCH_TIMEOUT_SECONDS = 180.0
GITHUB_API_TIMEOUT_SECONDS = 15.0
USER_AGENT = "Vibelution-GithubProjectLibrary/1.0"
VISIBLE_STATUSES = {"ready", "failed", "cloning"}
_LOCK = RLock()
_GITHUB_SPEC_RE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_SAFE_TOKEN_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class GithubProjectLibraryError(ValueError):
    """Raised when a GitHub project library request is invalid."""


def github_project_library_root(*, project_root: Path | None = None) -> Path:
    return resolve_project_memory_home(project_root or PROJECT_ROOT) / LIBRARY_DIRNAME


def initialize_github_project_library(*, project_root: Path | None = None) -> dict[str, Any]:
    root = github_project_library_root(project_root=project_root)
    (root / REPOS_DIRNAME).mkdir(parents=True, exist_ok=True)
    registry = _read_registry(root)
    _write_registry(root, registry)
    _write_index(root, registry)
    return _library_payload(root, registry)


def list_github_projects(*, query: str = "", project_root: Path | None = None, include_archived: bool = False) -> dict[str, Any]:
    root = github_project_library_root(project_root=project_root)
    initialize_github_project_library(project_root=project_root or PROJECT_ROOT)
    registry = _read_registry(root)
    projects = [
        project
        for project in list(registry.get("projects") or [])
        if isinstance(project, dict) and (include_archived or str(project.get("status") or "") != "archived")
    ]
    needle = trim_lines(str(query or ""), max_lines=2).strip().lower()
    if needle:
        projects = [project for project in projects if _project_matches(project, needle)]
    payload = _library_payload(root, {"projects": projects, "updatedAt": registry.get("updatedAt") or ""})
    payload["request"] = {"query": needle, "includeArchived": bool(include_archived)}
    return payload


def search_github_project_cards(*, query: str, limit: int = 8, project_root: Path | None = None) -> list[dict[str, Any]]:
    """Mixed-read discovery cards: name/description only, locator is the local clone."""

    if not str(query or "").strip():
        return []
    payload = list_github_projects(query=query, project_root=project_root)
    results: list[dict[str, Any]] = []
    for index, project in enumerate(list(payload.get("projects") or [])[: max(1, min(int(limit or 8), 25))]):
        if str(project.get("status") or "") != "ready":
            continue
        results.append(
            {
                "resultId": f"github-project:{project.get('projectId')}:{index + 1}",
                "resultType": "github_project_card",
                "title": str(project.get("name") or project.get("fullName") or "").strip(),
                "score": 1.0,
                "rank": index + 1,
                "searchBackend": "github_project_library",
                "matchReason": "local_github_project_index",
                "metadata": {
                    "fullName": str(project.get("fullName") or "").strip(),
                    "description": str(project.get("description") or "").strip(),
                    "githubUrl": str(project.get("githubUrl") or "").strip(),
                    "localPath": str(project.get("localPath") or "").strip(),
                    "absolutePath": str(project.get("absolutePath") or "").strip(),
                    "headSha": str(project.get("headSha") or "").strip(),
                    "license": str(project.get("license") or "").strip(),
                    "status": str(project.get("status") or "").strip(),
                },
            }
        )
    return results


def clone_github_project(
    spec: str,
    *,
    confirm: bool = False,
    project_root: Path | None = None,
) -> dict[str, Any]:
    owner, repo = parse_github_spec(spec)
    root = github_project_library_root(project_root=project_root)
    initialize_github_project_library(project_root=project_root or PROJECT_ROOT)
    project_id = _project_id(owner, repo)
    with _LOCK:
        registry = _read_registry(root)
        existing = _find_project(registry, project_id)
        if existing and str(existing.get("status") or "") == "ready" and _repo_dir(root, project_id).is_dir():
            return {
                "ok": True,
                "status": "already_present",
                "message": "本地记忆库已有该项目，直接使用本地仓调研。",
                "project": _project_api(root, existing),
                "library": _library_payload(root, registry),
            }
        metadata = fetch_github_repo_metadata(owner, repo)
        if bool(metadata.get("private")):
            raise GithubProjectLibraryError("Only public GitHub repositories can be cloned into the memory library.")
        size_kb = int(metadata.get("sizeKb") or 0)
        visible_count = _visible_project_count(registry, exclude_id=project_id)
        needs_confirm = (visible_count >= MAX_PROJECTS) or (size_kb > MAX_REPO_SIZE_KB)
        if needs_confirm and not confirm:
            reason = "repo_count_limit" if visible_count >= MAX_PROJECTS else "repo_size_limit"
            return {
                "ok": False,
                "status": "confirmation_required",
                "reason": reason,
                "message": _confirmation_message(reason, metadata, visible_count),
                "metadata": metadata,
                "library": _library_payload(root, registry),
            }
        dest = _repo_dir(root, project_id)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        record = _project_record(metadata, status="cloning")
        _upsert_project(registry, record)
        _write_registry(root, registry)
        _write_index(root, registry)
        clone_url = str(metadata.get("cloneUrl") or f"https://github.com/{owner}/{repo}.git")
        try:
            completed = run_git(
                ["clone", "--no-recurse-submodules", clone_url, str(dest)],
                cwd=root / REPOS_DIRNAME,
                timeout=CLONE_TIMEOUT_SECONDS,
            )
            if getattr(completed, "returncode", 1) != 0:
                stderr = trim_lines(str(getattr(completed, "stderr", "") or ""), max_lines=6).strip()
                raise GithubProjectLibraryError(stderr or "git clone failed.")
            inspected = _inspect_clone(dest, metadata)
            record.update(inspected)
            record["status"] = "ready"
            record["clonedAt"] = record.get("clonedAt") or _utc_now_iso()
            record["updatedAt"] = _utc_now_iso()
        except Exception as exc:
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            record["status"] = "failed"
            record["error"] = trim_lines(str(exc), max_lines=4).strip()[:400]
            record["updatedAt"] = _utc_now_iso()
            _upsert_project(registry, record)
            _write_registry(root, registry)
            _write_index(root, registry)
            raise GithubProjectLibraryError(record["error"]) from exc
        _upsert_project(registry, record)
        _write_registry(root, registry)
        _write_index(root, registry)
        return {
            "ok": True,
            "status": "cloned",
            "message": "已全量克隆到记忆库。后续调研请读本地路径，不要把网页当结论。",
            "project": _project_api(root, record),
            "library": _library_payload(root, registry),
        }


def fetch_github_project(project_id: str, *, project_root: Path | None = None) -> dict[str, Any]:
    normalized = str(project_id or "").strip()
    if not normalized:
        raise GithubProjectLibraryError("projectId is required.")
    try:
        owner, repo = parse_github_spec(normalized)
        normalized = _project_id(owner, repo)
    except GithubProjectLibraryError:
        normalized = _SAFE_TOKEN_RE.sub("_", normalized) or normalized
    root = github_project_library_root(project_root=project_root)
    initialize_github_project_library(project_root=project_root or PROJECT_ROOT)
    with _LOCK:
        registry = _read_registry(root)
        existing = _find_project(registry, normalized)
        if not existing:
            raise GithubProjectLibraryError(f"Unknown GitHub project: {normalized}")
        dest = _repo_dir(root, normalized)
        if not dest.is_dir():
            raise GithubProjectLibraryError("Local clone is missing; clone the project again.")
        completed = run_git(["fetch", "--no-recurse-submodules", "origin"], cwd=dest, timeout=FETCH_TIMEOUT_SECONDS)
        if getattr(completed, "returncode", 1) != 0:
            stderr = trim_lines(str(getattr(completed, "stderr", "") or ""), max_lines=6).strip()
            raise GithubProjectLibraryError(stderr or "git fetch failed.")
        inspected = _inspect_clone(dest, existing)
        existing.update(inspected)
        existing["status"] = "ready"
        existing["updatedAt"] = _utc_now_iso()
        _upsert_project(registry, existing)
        _write_registry(root, registry)
        _write_index(root, registry)
        return {
            "ok": True,
            "status": "updated",
            "message": "已 fetch 远程并刷新索引 SHA。",
            "project": _project_api(root, existing),
            "library": _library_payload(root, registry),
        }


def parse_github_spec(spec: str) -> tuple[str, str]:
    text = trim_lines(str(spec or ""), max_lines=1).strip()
    if text.lower().startswith("github.com/"):
        text = f"https://{text}"
    matched = _GITHUB_SPEC_RE.match(text)
    if not matched:
        raise GithubProjectLibraryError("Provide a public GitHub URL or owner/repo.")
    owner = matched.group(1)
    repo = matched.group(2)
    if owner.lower() in {"http:", "https:"} or not owner or not repo:
        raise GithubProjectLibraryError("Provide a public GitHub URL or owner/repo.")
    return owner, repo


def fetch_github_repo_metadata(owner: str, repo: str) -> dict[str, Any]:
    url = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        with httpx.Client(timeout=GITHUB_API_TIMEOUT_SECONDS) as client:
            response = client.get(url, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        raise GithubProjectLibraryError(f"GitHub metadata lookup failed: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise GithubProjectLibraryError("GitHub metadata lookup returned an unexpected payload.")
    license_payload = payload.get("license") if isinstance(payload.get("license"), dict) else {}
    html_url = str(payload.get("html_url") or f"https://github.com/{owner}/{repo}").strip()
    return {
        "projectId": _project_id(owner, repo),
        "name": str(payload.get("name") or repo).strip(),
        "fullName": str(payload.get("full_name") or f"{owner}/{repo}").strip(),
        "description": trim_lines(str(payload.get("description") or ""), max_lines=4).strip()[:400],
        "githubUrl": html_url,
        "cloneUrl": str(payload.get("clone_url") or f"{html_url}.git").strip(),
        "defaultBranch": str(payload.get("default_branch") or "main").strip() or "main",
        "license": str(license_payload.get("spdx_id") or license_payload.get("name") or "").strip(),
        "language": str(payload.get("language") or "").strip(),
        "stars": int(payload.get("stargazers_count") or 0),
        "sizeKb": int(payload.get("size") or 0),
        "private": bool(payload.get("private")),
        "visibility": str(payload.get("visibility") or ("private" if payload.get("private") else "public")).strip(),
    }


def _library_payload(root: Path, registry: dict[str, Any]) -> dict[str, Any]:
    projects = [_project_api(root, item) for item in list(registry.get("projects") or []) if isinstance(item, dict)]
    ready_count = sum(1 for item in projects if item.get("status") == "ready")
    archived_count = sum(1 for item in projects if item.get("status") == "archived")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "root": str(root),
        "indexPath": str(root / INDEX_NAME),
        "registryPath": str(root / REGISTRY_NAME),
        "reposPath": str(root / REPOS_DIRNAME),
        "summary": {
            "projectCount": len([item for item in projects if item.get("status") != "archived"]),
            "readyCount": ready_count,
            "archivedCount": archived_count,
            "maxProjects": MAX_PROJECTS,
            "maxRepoSizeKb": MAX_REPO_SIZE_KB,
        },
        "projects": projects,
        "updatedAt": str(registry.get("updatedAt") or ""),
    }


def _project_api(root: Path, project: dict[str, Any]) -> dict[str, Any]:
    project_id = str(project.get("projectId") or "").strip()
    dest = _repo_dir(root, project_id) if project_id else root / REPOS_DIRNAME
    return {
        "projectId": project_id,
        "name": str(project.get("name") or "").strip(),
        "fullName": str(project.get("fullName") or "").strip(),
        "description": str(project.get("description") or "").strip(),
        "githubUrl": str(project.get("githubUrl") or "").strip(),
        "localPath": f"{REPOS_DIRNAME}/{project_id}" if project_id else "",
        "absolutePath": str(dest) if project_id else "",
        "defaultBranch": str(project.get("defaultBranch") or "").strip(),
        "headSha": str(project.get("headSha") or "").strip(),
        "license": str(project.get("license") or "").strip(),
        "language": str(project.get("language") or "").strip(),
        "stars": int(project.get("stars") or 0),
        "hasSubmodules": bool(project.get("hasSubmodules")),
        "status": str(project.get("status") or "").strip(),
        "clonedAt": str(project.get("clonedAt") or "").strip(),
        "updatedAt": str(project.get("updatedAt") or "").strip(),
        "error": str(project.get("error") or "").strip(),
    }


def _project_record(metadata: dict[str, Any], *, status: str) -> dict[str, Any]:
    now = _utc_now_iso()
    return {
        "projectId": str(metadata.get("projectId") or "").strip(),
        "name": str(metadata.get("name") or "").strip(),
        "fullName": str(metadata.get("fullName") or "").strip(),
        "description": str(metadata.get("description") or "").strip(),
        "githubUrl": str(metadata.get("githubUrl") or "").strip(),
        "defaultBranch": str(metadata.get("defaultBranch") or "main").strip(),
        "headSha": "",
        "license": str(metadata.get("license") or "").strip(),
        "language": str(metadata.get("language") or "").strip(),
        "stars": int(metadata.get("stars") or 0),
        "hasSubmodules": False,
        "status": status,
        "clonedAt": now if status == "ready" else "",
        "updatedAt": now,
        "error": "",
    }


def _inspect_clone(dest: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    head = _git_text(["rev-parse", "HEAD"], dest)
    branch = _git_text(["rev-parse", "--abbrev-ref", "HEAD"], dest) or str(metadata.get("defaultBranch") or "main")
    return {
        "headSha": head,
        "defaultBranch": branch,
        "hasSubmodules": (dest / ".gitmodules").is_file(),
    }


def _git_text(args: list[str], cwd: Path) -> str:
    completed = run_git(args, cwd=cwd, timeout=30.0)
    if getattr(completed, "returncode", 1) != 0:
        return ""
    return str(getattr(completed, "stdout", "") or "").strip()


def _read_registry(root: Path) -> dict[str, Any]:
    path = root / REGISTRY_NAME
    if not path.exists():
        return {"schemaVersion": SCHEMA_VERSION, "updatedAt": "", "projects": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": SCHEMA_VERSION, "updatedAt": "", "projects": []}
    if not isinstance(payload, dict):
        return {"schemaVersion": SCHEMA_VERSION, "updatedAt": "", "projects": []}
    projects = [item for item in list(payload.get("projects") or []) if isinstance(item, dict)]
    return {
        "schemaVersion": int(payload.get("schemaVersion") or SCHEMA_VERSION),
        "updatedAt": str(payload.get("updatedAt") or ""),
        "projects": projects,
    }


def _write_registry(root: Path, registry: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / REPOS_DIRNAME).mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "updatedAt": _utc_now_iso(),
        "projects": [item for item in list(registry.get("projects") or []) if isinstance(item, dict)],
    }
    (root / REGISTRY_NAME).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    registry["updatedAt"] = payload["updatedAt"]
    registry["projects"] = payload["projects"]


def _write_index(root: Path, registry: dict[str, Any]) -> None:
    rows = [
        "| 名字 | 描述 | GitHub | 本地路径 | HEAD | 许可 | 子模块 | 状态 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for project in list(registry.get("projects") or []):
        if not isinstance(project, dict) or str(project.get("status") or "") == "archived":
            continue
        name = _md_cell(project.get("name") or project.get("fullName") or "")
        description = _md_cell(project.get("description") or "")
        url = _md_cell(project.get("githubUrl") or "")
        local_path = _md_cell(f"{REPOS_DIRNAME}/{project.get('projectId') or ''}")
        head = _md_cell(str(project.get("headSha") or "")[:12])
        license_id = _md_cell(project.get("license") or "")
        submodules = "yes" if bool(project.get("hasSubmodules")) else "no"
        status = _md_cell(project.get("status") or "")
        rows.append(
            f"| {name} | {description} | {url} | {local_path} | {head} | {license_id} | {submodules} | {status} |"
        )
    if len(rows) == 2:
        rows.append("| （空） | 还没有落盘的开源项目 |  |  |  |  |  |  |")
    body = "\n".join(
        [
            "# 开源项目索引",
            "",
            "借鉴外部 GitHub 项目时：先查本表 → 未命中则全量克隆到本目录 → 再对本地仓调研。",
            "不要把整仓正文写入正式知识库或 RAG。子模块默认不拉。",
            "",
            "路径解析：`python scripts/migrate_project_storage.py inventory` 的 `activePaths.memory/github-projects/`。",
            "",
            *rows,
            "",
        ]
    )
    (root / INDEX_NAME).write_text(body, encoding="utf-8")


def _find_project(registry: dict[str, Any], project_id: str) -> dict[str, Any] | None:
    for item in list(registry.get("projects") or []):
        if isinstance(item, dict) and str(item.get("projectId") or "") == project_id:
            return item
    return None


def _upsert_project(registry: dict[str, Any], project: dict[str, Any]) -> None:
    projects = [item for item in list(registry.get("projects") or []) if isinstance(item, dict)]
    project_id = str(project.get("projectId") or "")
    replaced = False
    for index, item in enumerate(projects):
        if str(item.get("projectId") or "") == project_id:
            projects[index] = project
            replaced = True
            break
    if not replaced:
        projects.append(project)
    registry["projects"] = projects


def _visible_project_count(registry: dict[str, Any], *, exclude_id: str = "") -> int:
    count = 0
    for item in list(registry.get("projects") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("projectId") or "") == exclude_id:
            continue
        if str(item.get("status") or "") in VISIBLE_STATUSES:
            count += 1
    return count


def _repo_dir(root: Path, project_id: str) -> Path:
    token = _SAFE_TOKEN_RE.sub("_", str(project_id or "").strip()) or "repo"
    dest = (root / REPOS_DIRNAME / token).resolve()
    repos_root = (root / REPOS_DIRNAME).resolve()
    if dest != repos_root and repos_root not in dest.parents:
        raise GithubProjectLibraryError("Refusing to write a clone outside the GitHub project library.")
    return dest


def _project_id(owner: str, repo: str) -> str:
    return f"{owner}__{repo}"


def _project_matches(project: dict[str, Any], needle: str) -> bool:
    haystack = " ".join(
        [
            str(project.get("name") or ""),
            str(project.get("fullName") or ""),
            str(project.get("description") or ""),
            str(project.get("githubUrl") or ""),
            str(project.get("language") or ""),
            str(project.get("license") or ""),
        ]
    ).lower()
    return needle in haystack


def _confirmation_message(reason: str, metadata: dict[str, Any], visible_count: int) -> str:
    full_name = str(metadata.get("fullName") or "").strip()
    if reason == "repo_count_limit":
        return f"记忆库已有 {visible_count} 个开源项目（上限 {MAX_PROJECTS}）。确认后再克隆 {full_name}。"
    size_kb = int(metadata.get("sizeKb") or 0)
    return f"{full_name} 约 {size_kb} KiB，超过单仓约 1GB 上限。确认后再全量克隆。"


def _md_cell(value: Any) -> str:
    return str(value or "").replace("|", "/").replace("\n", " ").strip() or " "


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
