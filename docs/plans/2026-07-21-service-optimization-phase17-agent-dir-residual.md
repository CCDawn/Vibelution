# Service Optimization Phase 17 — Agent Directory Repair / Ops Residual

Date: 2026-07-21
Status: **phase17_closed**
Branch: `codex/svc-opt-p17-agent-dir-residual`

## Goal

Drain remaining agent_directory facade surface after Phase 11–12, leaving lifecycle serializers.

## Delivered

| Pack | ~LOC | Role |
|------|------|------|
| `agent_directory/repair_store.py` | ~2.1k | repair_agent_directory, load/save, normalize, LLM binding repair |
| `agent_directory/ops_residual.py` | ~1.7k | inbox, workspace, ensure/reactivate session, profile defaults |

## Metrics

| Surface | Lines (approx) |
|---------|----------------|
| Facade before | ~4.3k |
| Facade after | ~0.9k |
| Residual functions | 3 lifecycle serializers |

## Verification

- structure + directory/lifecycle/purge/archive/tool-policy
- version: none; Launcher: not needed
