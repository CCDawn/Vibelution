#!/usr/bin/env python3
"""本地日志与运行态产物 retention 脚本。

策略：对每个目标目录，按 mtime 降序保留最新 N 份文件 / 子目录，
其余移除。默认 --dry-run，必须显式加 --apply 才会真正删除。

只看用户指定的目标顶层（不递归到子目录里删文件），避免误清正在使用的
lifecycle 包内部结构。`log_info/` 和 `.runtime/` 都是顶层平铺的运行
产物，本策略足够。

用法示例:
    python scripts/prune_logs.py                              # dry-run，默认目标 + 默认配额
    python scripts/prune_logs.py --apply                      # 真正执行
    python scripts/prune_logs.py --target log_info --keep 80  # 单目标 + 自定义配额
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class PruneTarget:
    """单个清理目标。

    name: 目标显示名
    path: 相对仓库根的目录路径
    keep: 默认保留份数
    glob: 顶层匹配模式（None = 所有文件/目录）
    """

    name: str
    path: Path
    keep: int
    glob: str | None = None


DEFAULT_TARGETS: tuple[PruneTarget, ...] = (
    PruneTarget("log_info", REPO_ROOT / "log_info", keep=80, glob="debug_*.log"),
    PruneTarget("logs", REPO_ROOT / "logs", keep=40),
    PruneTarget(".runtime", REPO_ROOT / ".runtime", keep=40),
    PruneTarget("backups", REPO_ROOT / "backups", keep=5, glob="backup_*.zip"),
)


def _iter_candidates(target: PruneTarget) -> list[Path]:
    if not target.path.exists():
        return []
    if target.glob:
        return list(target.path.glob(target.glob))
    return [p for p in target.path.iterdir() if not p.name.startswith(".")]


def _sort_newest_first(paths: Iterable[Path]) -> list[Path]:
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


def _human_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}{units[-1]}"


def _path_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def _remove(path: Path) -> None:
    if path.is_file() or path.is_symlink():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def prune(target: PruneTarget, keep: int, apply: bool) -> tuple[int, int]:
    """对单个目标执行清理。返回 (deleted_count, freed_bytes)。"""

    candidates = _sort_newest_first(_iter_candidates(target))
    if len(candidates) <= keep:
        print(f"  [skip] {target.name}: {len(candidates)} 份 <= keep={keep}")
        return 0, 0

    keep_paths = candidates[:keep]
    drop_paths = candidates[keep:]
    freed = 0
    for path in drop_paths:
        size = _path_size(path)
        freed += size
        if apply:
            _remove(path)

    action = "removed" if apply else "would remove"
    newest_kept = keep_paths[-1]
    oldest_kept_mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(newest_kept.stat().st_mtime))
    print(
        f"  [{target.name}] {action} {len(drop_paths)} / {len(candidates)}"
        f"  freed={_human_size(freed)}  oldest-kept={newest_kept.name} @ {oldest_kept_mtime}"
    )
    return len(drop_paths), freed


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--target",
        action="append",
        choices=[t.name for t in DEFAULT_TARGETS],
        help="只处理指定目标（可重复）。默认全部。",
    )
    parser.add_argument("--keep", type=int, default=None, help="覆盖所有目标的保留份数。")
    parser.add_argument("--apply", action="store_true", help="真正执行删除；默认仅 dry-run。")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    selected_names = set(args.target) if args.target else {t.name for t in DEFAULT_TARGETS}
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"prune_logs.py [{mode}] repo={REPO_ROOT}")
    total_dropped = 0
    total_freed = 0
    for target in DEFAULT_TARGETS:
        if target.name not in selected_names:
            continue
        keep = args.keep if args.keep is not None else target.keep
        dropped, freed = prune(target, keep=keep, apply=args.apply)
        total_dropped += dropped
        total_freed += freed
    print(f"total: {total_dropped} 份  freed={_human_size(total_freed)}")
    if not args.apply and total_dropped:
        print("（dry-run；加 --apply 真正执行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
