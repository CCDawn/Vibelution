# Runtime scene modules (`core/web/services/runtime_scene`)

Ownership map for structured runtime scene bundles.
`runtime_scene_service.py` remains the **public import facade**.

## 30-second routing (edit here first)

| You are changing… | Open first |
|-------------------|------------|
| `record_*` writers / manifests / delete | `record.py` |
| list / get detail / evidence / prompt index / retention | `query.py` |
| diagnosis / issue / work-run / startup signals | `diagnosis.py` |
| package_index sidecar stale detect/sync | `package_index.py` |
| Public import surface | `../runtime_scene_service.py` (re-export shell) |

Structure awareness (soft): `DEVELOPMENT_STANDARD.md` §8.3.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| `record_*` writers / manifests / delete | `record.py` | diagnosis residual |
| list/get/detail / evidence / prompt index / retention | `query.py` | record append path |
| diagnosis / issue / work-run / startup signals | `diagnosis.py` | package write |
| package_index sidecar sync | `package_index.py` | record append path |

## Extraction progress

| Pack | Status | Notes |
|------|--------|--------|
| `record.py` | done | Phase 13 write path |
| `query.py` | done | Phase 13 query path |
| `diagnosis.py` | done | Phase 14 diagnosis/issue/work-run |
| `package_index.py` | done | Phase 19 package_index sidecar |
| facade residual | re-exports only | 0 function defs |

## Related

- Structure plans: `docs/plans/2026-07-21-service-optimization-phase13-runtime-scene.md`, phase14 plan
