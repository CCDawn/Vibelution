"""Shared canonical helpers for research workflow contracts.

The implementation lives in :mod:`core.infrastructure.canonical_json` so
non-ledger surfaces (agent kernel content-addressed keys, runtime-manager
command args hashes) reuse the identical canonical form; this module keeps
the ledger contract's historical import path stable.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.infrastructure.canonical_json import canonical_json, sha256_hex

__all__ = ["canonical_json", "sha256_hex"]
