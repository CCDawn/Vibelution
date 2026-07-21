# Service Optimization Phase 13 — Runtime Scene Record / Query

Date: 2026-07-21
Status: **phase13_closed**
Branch: `codex/svc-opt-p13-runtime-scene`

## Goal

Start splitting the `runtime_scene_service` god facade (largest remaining ~6.3k) into claimable packs.

## Delivered

| Pack | ~LOC | Role |
|------|------|------|
| `runtime_scene/record.py` | ~2.7k | record_* writers, delete, manifests, write-side package/summary |
| `runtime_scene/query.py` | ~1.1k | list/get/detail, evidence, prompt index, retention |

## Metrics

| Surface | Lines (approx) |
|---------|----------------|
| Facade before | ~6.3k |
| Facade after | ~2.8k |

## Verification

- structure re-export asserts
- package diagnosis / package index / projection fastpath / launcher scene
- pre-existing package_index failures unchanged on main (active launcher reference; supervised_runs path expectation)
- version: none; Launcher: not needed
