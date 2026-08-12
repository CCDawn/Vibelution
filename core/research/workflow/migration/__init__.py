"""One-shot Workflow Ledger migration (spec §14 / T8).

Old JSON Run files are read-only input. The importer never writes JSON and
never falls back to the JSON store after activation.
"""

from .importer import apply_migration
from .inventory import build_inventory
from .manifest import (
    MANIFEST_NAME,
    ManifestStatus,
    load_manifest,
    write_manifest,
)
from .validator import CLASSIFICATIONS, unknown_entries
from .verifier import verify_migration

__all__ = [
    "CLASSIFICATIONS",
    "MANIFEST_NAME",
    "ManifestStatus",
    "apply_migration",
    "build_inventory",
    "load_manifest",
    "unknown_entries",
    "verify_migration",
    "write_manifest",
]
