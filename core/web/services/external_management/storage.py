"""Resolve one project-bound management store across supported runtime cutovers."""
import json
from pathlib import Path

from core.assistant_runtime.migration_io import check_path


def management_home(project_root: Path) -> Path:
    from vibelution_storage import resolve_active_project_storage_paths, resolve_project_storage_paths

    canonical = resolve_project_storage_paths(project_root)
    active = resolve_active_project_storage_paths(project_root)
    # The legacy-to-canonical transition is performed by the existing
    # quiesced, verified storage migration, including management receipts.
    runtime = active.runtime if active.runtime == project_root / ".runtime" else canonical.runtime
    path = runtime / "external_management"
    try:
        path.lstat()
    except FileNotFoundError:
        return path
    check_path(path)
    if not path.is_dir():
        raise ValueError("Invalid management store")
    return path


def migrated_management_subject_exists(paths, subject_path: Path) -> bool:
    """Verify that this subject's file was in the completed storage transfer.

    The current file may legitimately have newer reductions or upgrades. Its
    native proof chain remains authoritative and is validated by the caller.
    """
    from vibelution_storage import storage_migration_state_path

    try:
        marker = json.loads(storage_migration_state_path(paths).read_text(encoding="utf-8"))
        manifest = Path(marker["manifestPath"])
        if manifest.parent != paths.instance_home / "migrations" or manifest.suffix != ".jsonl":
            return False
        check_path(manifest)
        relative = subject_path.relative_to(paths.runtime)
        source = paths.project_root / ".runtime" / relative
        with manifest.open(encoding="utf-8") as stream:
            for line in stream:
                entry = json.loads(line)
                if (entry.get("category") == "runtime"
                        and entry.get("relative_path") == relative.as_posix()
                        and Path(entry["source"]) == source
                        and Path(entry["destination"]) == subject_path):
                    return True
    except (OSError, ValueError, TypeError, KeyError):
        return False
    return False
