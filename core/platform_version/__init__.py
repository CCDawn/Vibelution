"""Local platform-version cadence ownership.

The ledger is the authority for how far the platform has evolved locally.
``VERSION`` and ``CHANGELOG.md`` are explicit projections, never the source.
"""

from core.platform_version.ledger import (
    Cadence,
    UnreleasedEntry,
    VersionEntry,
    VersionLedger,
    advance,
    extract_unreleased,
    parse_version,
    resolve_ledger_path,
    snapshot,
)
from core.platform_version.settler import (
    VersionWatcher,
    get_watcher,
    reset_watchers_for_tests,
)

__all__ = [
    "Cadence",
    "UnreleasedEntry",
    "VersionEntry",
    "VersionLedger",
    "VersionWatcher",
    "advance",
    "extract_unreleased",
    "get_watcher",
    "parse_version",
    "reset_watchers_for_tests",
    "resolve_ledger_path",
    "snapshot",
]
