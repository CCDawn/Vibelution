# Service Optimization Phase 14 — Runtime Scene Diagnosis

Date: 2026-07-21
Status: **phase14_closed**
Branch: `codex/svc-opt-p14-runtime-scene-diagnosis`

## Goal

Finish the main claimable surface of `runtime_scene_service` by extracting diagnosis/issue/work-run helpers left after Phase 13 record/query.

## Delivered

| Pack | ~LOC | Role |
|------|------|------|
| `runtime_scene/diagnosis.py` | ~2.3k | package diagnosis, issues, agent brief, startup/browser signals, work-run |

## Metrics

| Surface | Lines (approx) |
|---------|----------------|
| Facade before | ~2.8k |
| Facade after | ~0.7k |
| Residual functions on facade | 3 (package-index sidecar glue) |

## Verification

- structure re-export asserts (record/query/diagnosis)
- package diagnosis / index / projection fastpath / launcher scene
- pre-existing package_index failures unchanged
- version: none; Launcher: not needed
