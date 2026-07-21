"""Agent directory internal packs.

- ``profiles`` — pure persona/task normalizers (Stage 4)
- ``policies`` — tool/memory/delegation/supervision/visibility (Phase 11)
- ``lifecycle`` — archive/purge/reset helpers (Phase 11)
- ``projections`` — list/get + API hydration (Phase 12)
- ``mutations`` — create/update + avatar (Phase 12)
- ``repair_store`` — registry repair/load-save (Phase 17)
- ``ops_residual`` — inbox/workspace/ensure-session residual (Phase 17)

Public callers use ``agent_directory_service`` facade re-exports.
"""
