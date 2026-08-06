# VUI Structure Debt Backlog

> Prep document for cleanup. Not a second design system. Authority: root `AGENTS.md` + `docs/standards/development-standard.md` §9.1 + this folder’s `README.md`.

## Goals

- New pages start from a **page recipe**, not a custom flex shell.
- Visual coordination comes from **tokens + `pageRecipeClasses`**, not one-off CSS.
- Fat routes become **orchestrators**; domain logic lives in sibling modules.
- Workbench main **loading/empty** uses `VStateSurface` with `fill` (or panel-local skeleton) — never a one-line `styles.empty` above a empty floor.
- Sweep status (4 rounds): workbench/main panels largely on `VStateSurface`; Chat index/workspace keep geometry skeleton shells (`ChatLoadingShell`). Residual: form helper microcopy, button pending labels, membership hints.

## Inventory (current hotspots)

| Surface | Symptom | Target recipe |
| --- | --- | --- |
| `TeamsRoute.tsx` | Thick orchestrator; shell recipes + SC/canvas extracts in progress (other owner). | keep recipes; continue module extract |
| Agents workspace | **Migrated** outer shell to `VListDetailPage` + layoutId (`AgentWorkspaceLayoutPanel`) | optional inspector UX polish |
| Chat coding | **`VSessionWorkbenchPage` + `ChatSessionWorkbenchShell` + `useChatWorkbenchLayout`**; dual-pane math in hook | Done for page recipe + slots; keep dual-write domain math |
| Memory | Outer `VDenseOpsPage` + layoutId; sources/knowledge/agent-memory → `VSplitWorkspace` | Done for three-pane shells |
| Config settings | **Migrated** nav/main + model-assets to `VSplitWorkspace` layoutIds | Done for shell width ownership |
| Research flow canvas | **Migrated** `VCanvasWorkbenchPage` + **`WORKBENCH_LAYOUT_IDS.researchFlow`** inspector resize | Done for inspector width memory |
| Evolution queues | Outer **`VTrackWorkbenchPage`** + multi-rail domain recipe; panels extracted incl. **case-trace / conversation evidence** | Done for page host; keep multi-rail resize exception |
| Panel titles residual | Module bar = nav chrome (`data-vui=agent-management-module-bar`); chat bubbles use route-local `ChatMessageChromeHeader` | Promote chat chrome to vui/product only with second consumer |
| Git / Tools / Logs / Launcher | Shared `usePersistedPaneResize` + **`PaneCollapseHandle`** (collapse-to-zero; not VSplit) | Keep hook+collapse pattern; gate documents exception |

## Cleanup playbook (per surface)

1. Identify shell vs domain logic vs styles.
2. Replace shell with a recipe (`fill` + `layoutId`).
3. Move domain blocks into `routes/<domain>/` or `vui/product/`.
4. Delete dead style keys and private resize handlers.
5. Run: `vuiShadcnRouteContract`, route layout tests, `npm --prefix web run build`.

## Non-goals

- Do not reintroduce HeroUI.
- Do not put business logic in `renderers/shadcn`.
- Do not add a second page-template folder outside VUI.
