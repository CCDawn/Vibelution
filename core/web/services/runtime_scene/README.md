# Runtime scene modules (`core/web/services/runtime_scene`)

Ownership map for structured runtime scene bundles.
`runtime_scene_service.py` remains the **public import facade**.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| `record_*` writers / manifests / delete | `record.py` | diagnosis residual |
| list/get/detail / evidence / prompt index / retention | `query.py` | record append path |
| diagnosis / issue / work-run residual helpers | facade (later `diagnosis.py`) | package write |

## Extraction progress

| Pack | Status | Notes |
|------|--------|--------|
| `record.py` | done | Phase 13 write path |
| `query.py` | done | Phase 13 query path |
| diagnosis residual | deferred | next runtime_scene cut |

## Related

- Routes / consumers: session events, launcher, web diagnostics
- Structure plan family: `docs/plans/2026-07-21-service-optimization-phase*.md`
