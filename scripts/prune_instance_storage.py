#!/usr/bin/env python3
"""实例存储 retention：回收项目根已不存在的实例目录。

为什么需要：实例目录按项目根路径的哈希命名（``vibelution_storage.instance_id_for_project``），
每个任务 worktree 都是独立根，因此各自产生一份完整实例存储
（``data/workspace``、``runtime/runtime-manager``、``logs``、``cache``）。
worktree 被清理后这份存储没有任何东西回收，长期累积
（2026-09 本机观测：1675 个目录 / 5.4GB）。

判定证据（默认只回收可确证的）：
- ``<instance>/runtime/runtime-manager/state.json`` 记录 ``projectRoot``；
  该路径已不存在、且没有存活的 runtime-manager 进程 → 确证死亡，可回收。
- 没有 ``projectRoot`` 记录（例如只写过 ``cache/quality_gates``）→ 不可确证，
  默认只报告；显式加 ``--include-unproven-older-than-days N`` 才按 mtime 回收。

安全边界：
- 默认 dry-run，必须 ``--apply`` 才删除；
- 只处理 ``<projects_home>/<project_id>/instances`` 的直接子目录；
- 永不碰当前 checkout 自己的实例目录；
- 跳过链接 / junction，不跟随删除。

用法示例::

    python scripts/prune_instance_storage.py                    # dry-run 报告
    python scripts/prune_instance_storage.py --json             # 机器可读
    python scripts/prune_instance_storage.py --apply            # 回收确证死亡的实例
    python scripts/prune_instance_storage.py --apply \\
        --include-unproven-older-than-days 30                   # 追加按龄回收不可确证项
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vibelution_storage import (  # noqa: E402
    instance_id_for_project,
    resolve_projects_home,
)

RUNTIME_MANAGER_STATE_RELATIVE_PATH = Path("runtime") / "runtime-manager" / "state.json"
DEAD = "dead"
UNPROVEN = "unproven"
UNPROVEN_STALE = "unproven_stale"
LIVE = "live"
DAEMON_ALIVE = "daemon_alive"
PROTECTED = "protected"


@dataclass(frozen=True)
class InstanceCandidate:
    """一个实例目录及其回收判定。"""

    project_id: str
    instance_id: str
    path: Path
    verdict: str
    project_root: str
    size_bytes: int
    last_write: float

    @property
    def reclaimable(self) -> bool:
        return self.verdict in {DEAD, UNPROVEN_STALE}


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(callable(is_junction) and is_junction())


def _path_size_bytes(path: Path) -> int:
    total = 0
    for root, _directories, file_names in os.walk(path, followlinks=False):
        for name in file_names:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def _last_write_seconds(path: Path) -> float:
    """最新文件写入时间；目录内没有文件时退回目录自身 mtime。"""

    newest = 0.0
    seen_file = False
    for root, _directories, file_names in os.walk(path, followlinks=False):
        for name in file_names:
            try:
                newest = max(newest, (Path(root) / name).stat().st_mtime)
                seen_file = True
            except OSError:
                continue
    if seen_file:
        return newest
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _read_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _process_is_runtime_manager(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        from core.runtime_manager.process_identity import is_runtime_manager_process
    except ImportError:
        return False
    try:
        return bool(is_runtime_manager_process(pid))
    except (OSError, ValueError):
        return False


def classify_instance(
    instance_dir: Path,
    *,
    project_id: str,
    protected_instance_ids: frozenset[str],
    unproven_older_than_days: int | None,
    process_alive: Callable[[int], bool] = _process_is_runtime_manager,
    now: float | None = None,
) -> InstanceCandidate:
    """判定一个实例目录该保留还是该回收。"""

    instance_id = instance_dir.name
    size_bytes = _path_size_bytes(instance_dir)
    last_write = _last_write_seconds(instance_dir)
    state = _read_state(instance_dir / RUNTIME_MANAGER_STATE_RELATIVE_PATH)
    project_root = str(state.get("projectRoot") or "").strip()

    def candidate(verdict: str) -> InstanceCandidate:
        return InstanceCandidate(
            project_id=project_id,
            instance_id=instance_id,
            path=instance_dir,
            verdict=verdict,
            project_root=project_root,
            size_bytes=size_bytes,
            last_write=last_write,
        )

    if instance_id in protected_instance_ids:
        return candidate(PROTECTED)
    if project_root:
        if Path(project_root).is_dir():
            return candidate(LIVE)
        manager_pid = int(state.get("managerPid") or 0)
        if process_alive(manager_pid):
            return candidate(DAEMON_ALIVE)
        return candidate(DEAD)
    # No recorded root: only an explicit age threshold may reclaim it.
    if unproven_older_than_days is None:
        return candidate(UNPROVEN)
    reference = now if now is not None else time.time()
    age_days = (reference - last_write) / 86_400.0
    if age_days < unproven_older_than_days:
        return candidate(UNPROVEN)
    return candidate(UNPROVEN_STALE)


def collect_candidates(
    projects_home: Path,
    *,
    project_filter: str | None = None,
    protected_instance_ids: frozenset[str] = frozenset(),
    unproven_older_than_days: int | None = None,
    process_alive: Callable[[int], bool] = _process_is_runtime_manager,
    now: float | None = None,
) -> list[InstanceCandidate]:
    """扫描 projects home 下所有实例目录并给出判定。"""

    candidates: list[InstanceCandidate] = []
    if not projects_home.is_dir():
        return candidates
    normalized_filter = str(project_filter or "").strip()
    for project_home in sorted(projects_home.iterdir()):
        if not project_home.is_dir() or _is_link_or_junction(project_home):
            continue
        if normalized_filter and project_home.name != normalized_filter:
            continue
        instances_root = project_home / "instances"
        if not instances_root.is_dir():
            continue
        for instance_dir in sorted(instances_root.iterdir()):
            if not instance_dir.is_dir() or _is_link_or_junction(instance_dir):
                continue
            candidates.append(
                classify_instance(
                    instance_dir,
                    project_id=project_home.name,
                    protected_instance_ids=protected_instance_ids,
                    unproven_older_than_days=unproven_older_than_days,
                    process_alive=process_alive,
                    now=now,
                )
            )
    return candidates


def reclaim(candidates: Iterable[InstanceCandidate], *, apply: bool) -> dict[str, Any]:
    """回收判定为可回收的候选。返回 {removed, failed, freedBytes, reclaimed}。"""

    reclaimed: list[InstanceCandidate] = []
    failed: list[dict[str, str]] = []
    freed = 0
    for item in candidates:
        if not item.reclaimable:
            continue
        freed += item.size_bytes
        if apply:
            try:
                shutil.rmtree(item.path)
            except OSError as error:
                failed.append(
                    {"instanceId": item.instance_id, "reason": type(error).__name__}
                )
                freed -= item.size_bytes
                continue
        reclaimed.append(item)
    return {
        "removed": len(reclaimed),
        "failed": failed,
        "freedBytes": freed,
        "reclaimed": reclaimed,
    }


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _summarize(candidates: Sequence[InstanceCandidate]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for item in candidates:
        bucket = summary.setdefault(item.verdict, {"count": 0, "bytes": 0})
        bucket["count"] += 1
        bucket["bytes"] += item.size_bytes
    return summary


def _print_report(
    candidates: Sequence[InstanceCandidate],
    result: dict[str, Any],
    *,
    apply: bool,
    unproven_older_than_days: int | None,
    detail_limit: int,
) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"prune_instance_storage.py [{mode}]")
    summary = _summarize(candidates)
    labels = {
        DEAD: "可回收（根已不存在）",
        UNPROVEN_STALE: "可回收（无根记录，按龄）",
        UNPROVEN: "不可确证（无根记录）",
        LIVE: "保留（根仍存在）",
        DAEMON_ALIVE: "保留（daemon 存活）",
        PROTECTED: "保留（当前 checkout）",
    }
    for verdict, label in labels.items():
        bucket = summary.get(verdict)
        if not bucket:
            continue
        print(
            f"  {verdict:<13} {bucket['count']:>5} 个"
            f"  {_human_size(bucket['bytes']):>9}  {label}"
        )
    reclaimable = [item for item in candidates if item.reclaimable]
    if reclaimable:
        reclaimable.sort(key=lambda item: item.size_bytes, reverse=True)
        shown = reclaimable[:detail_limit]
        print(f"  待回收明细（按占用降序，显示 {len(shown)}/{len(reclaimable)}）:")
        for item in shown:
            root_text = item.project_root or "(无根记录)"
            print(
                f"    {item.instance_id}  {_human_size(item.size_bytes):>9}"
                f"  age={(time.time() - item.last_write) / 86_400:.0f}d  {root_text}"
            )
    action = "已回收" if apply else "将回收"
    freed_text = _human_size(result["freedBytes"])
    print(f"total: {action} {result['removed']} 个  freed={freed_text}")
    if result["failed"]:
        print(f"failed: {len(result['failed'])} 个 {result['failed'][:5]}")
    if not apply and result["removed"]:
        print("（dry-run；加 --apply 真正执行）")
    if unproven_older_than_days is None and summary.get(UNPROVEN):
        print(
            "（不可确证项默认保留；确认无误后可加"
            " --include-unproven-older-than-days N 按龄回收）"
        )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--projects-home",
        type=Path,
        default=None,
        help="projects home（默认 %LOCALAPPDATA%%\\Vibelution\\projects）。",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="只处理指定 project id（默认全部）。",
    )
    parser.add_argument(
        "--apply", action="store_true", help="真正执行删除；默认仅 dry-run。"
    )
    parser.add_argument(
        "--include-unproven-older-than-days",
        type=int,
        default=None,
        help="同时对没有根记录、且最后写入早于 N 天的实例目录做回收。",
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读报告。")
    parser.add_argument("--detail-limit", type=int, default=10, help="明细显示条数。")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.projects_home is not None:
        projects_home = args.projects_home
    else:
        projects_home = resolve_projects_home(None)
    if not projects_home.is_dir():
        print(f"projects home 不存在：{projects_home}")
        return 0

    protected = frozenset({instance_id_for_project(REPO_ROOT)})
    candidates = collect_candidates(
        projects_home,
        project_filter=args.project_id,
        protected_instance_ids=protected,
        unproven_older_than_days=args.include_unproven_older_than_days,
    )
    result = reclaim(candidates, apply=bool(args.apply))

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "projectsHome": str(projects_home),
                    "protectedInstanceIds": sorted(protected),
                    "summary": _summarize(candidates),
                    "removed": result["removed"],
                    "freedBytes": result["freedBytes"],
                    "failed": result["failed"],
                    "reclaimable": [
                        asdict(item) | {"path": str(item.path)}
                        for item in sorted(
                            (item for item in candidates if item.reclaimable),
                            key=lambda item: item.size_bytes,
                            reverse=True,
                        )
                    ],
                },
                ensure_ascii=True,
                indent=2,
            )
        )
        return 0

    _print_report(
        candidates,
        result,
        apply=bool(args.apply),
        unproven_older_than_days=args.include_unproven_older_than_days,
        detail_limit=max(0, int(args.detail_limit)),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
