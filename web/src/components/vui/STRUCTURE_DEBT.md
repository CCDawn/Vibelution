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
| `TeamsRoute.tsx` | ~6.0k lines; shell recipes + SC injects + **`teamsWorkspacePanelRenderers` factory** for memory/AI-search/loop/ledger/canvas inspectors. Next: collapse remaining SC/orchestrator render glue. | keep recipes; continue module extract |
| Agents workspace | **Migrated** outer shell to `VListDetailPage` + layoutId (`AgentWorkspaceLayoutPanel`) | keep product/agent-management panels; optional inspector UX polish |
| Chat coding | Dual-pane domain math (OK); `data-vui-domain-recipe=chat-dual-pane` + `WORKBENCH_LAYOUT_IDS.chat` + height panes in `chatListHeights.ts`; session tabs soft cool select | Keep domain layout; region tags on center/status rails |
| Memory | Outer `VDenseOpsPage` + layoutId; sources/knowledge/agent-memory three-pane → `VSplitWorkspace` (`left`/`right`, `agent-list`/`agent-detail`); lists/queues on height registry | Done for main three-pane shells |
| Config settings | **Migrated** nav/main to `VSplitWorkspace` + `configSettings`; model-assets → `configModelAssets` | Done for shell width ownership |
| Research flow canvas | **Migrated** page shell → `VCanvasWorkbenchPage` | optional layoutId for inspector width |
| Evolution queues | Multi-rail widths/heights on `WORKBENCH_LAYOUT_IDS.evolution`; soft segment track; **dataset catalog → `EvolutionDatasetCatalogPanel`** | Domain multi-rail intentional; next: live launch setup / members rail extract |

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