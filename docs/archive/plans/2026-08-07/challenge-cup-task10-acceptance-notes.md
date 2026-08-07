# Task 10 · Acceptance notes (in progress)

Branch: `codex/challenge-workflow-impl`
Date: 2026-08-07

## Machine evidence (focused)

| Gate | Result |
| --- | --- |
| Backend Task0–3/6 graph/runtime/rollback pytest | **16+ passed** (focused suite) |
| Frontend research-workflow + retired route contracts | **69 passed** (focused suite) |
| Legacy execute sole writer | default **disabled**; rollback via `VIBELUTION_LEGACY_FLOW_CANVAS_EXECUTE=1` |
| ResearchFlowCanvasRoute / ResearchRoute | **redirect shells** (no independent page) |
| LangGraph full topology | **15 nodes** + human interrupts |
| Challenge Cup primary surface | `ResearchProcessWorkspace` + `VWorkflowCanvas` |

## Closed in later commits

| Item | Status |
| --- | --- |
| Full `npx tsc -b` | **green** |
| Canonical internal links (`teamWorkspaceRoute` / stage routes) | **workflow + node** |
| Challenge progress surface | mounts `ResearchProcessWorkspace` only |
| URL matrix (pure resolver) | `researchWorkflowUrlMatrix.test.ts` |

## Not yet closed

| Item | Status |
| --- | --- |
| `npm run build` | see latest CI/local run |
| Desktop browser full URL matrix | **not run** (resolver matrix automated) |
| Launcher restart + real HITL + SSE reconnect | **not run** |
| Physical delete of ChallengeCupOperationsWorkspace sources | **kept** (no longer mounted as primary) |
| Merge to main | **not authorized** |

## Rollback

1. Before deleting more surfaces: set `VIBELUTION_LEGACY_FLOW_CANVAS_EXECUTE=1` only for emergency legacy execute.
2. After redirect retirement: rollback is **git version revert** of this branch commits, not partial page resurrection.

## Next for full MERGE_READY

1. Full tsc + web build green
2. Browser navigate disposition table URLs
3. Optional: stop mounting ChallengeCupOperationsWorkspace from stage launcher when challenge cup (secondary)
4. Claim release + local merge authorization
