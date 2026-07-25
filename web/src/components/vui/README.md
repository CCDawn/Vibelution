# VUI — product design system

> **VUI is the stable product API.**
> **shadcn-style + Radix is the preferred implementation backend.**
> Routes and product pages must not import `@heroui/react` or `renderers/shadcn/*` directly.
> `@heroui/react` is **removed** from dependencies.

## Ownership

| Layer | Path | Owns |
| --- | --- | --- |
| Product API | `primitives/`, `forms/`, `layout/`, `display/`, `index.ts` | `VButton`, `VInput`, … — stable names for routes |
| Page recipes | `layout/VListDetailPage`, `VSettingsFormPage`, `VDenseOpsPage` | Prefer for new pages instead of inventing layout |
| Product domain | `product/` | Agent / Team composition (not a generic UI kit) |
| Renderers | `renderers/shadcn/` | shadcn-style native + Radix implementations |
| Shared tokens | `renderers/shared/` | density, tone, button slots (renderer-agnostic) |
| Root provider | `VuiProvider.tsx` | `data-vui-provider="shadcn"` app boundary |

## Rules (efficiency)

1. **No new `V*` primitive** unless at least two call sites already need it. Prefer composing existing primitives **or a page recipe**.
2. **Routes import only** from `components/vui` (or `…/vui/product/…`). Never from `renderers/`.
3. **New interactive controls** go through a `V*` facade; put Radix/shadcn code under `renderers/shadcn/`.
4. **HeroUI is gone.** Do not re-add `@heroui/react`. Prefer extending the shadcn renderer.
5. **Domain shells** (Agent three-pane, Chat rails) stay in routes/product — shadcn does not replace them.

## Renderer map (interactive primitives)

| Product API | Implementation | Notes |
| --- | --- | --- |
| `VButton` | `ShadcnButton` | density + variant; HeroUI-era `onPress` / `isDisabled` kept |
| `VIconButton` | via `VButton` | square geometry |
| `VChip` | `ShadcnChip` | tone map |
| `VTooltip` | `ShadcnTooltip` (Radix) | `isOpen` alias retained |
| `VDialog` / `VConfirmDialog` | `ShadcnDialog` (Radix) | Prefer over hand-rolled `fixed inset-0` overlays |
| `VInput` | `ShadcnInput` | |
| `VTextarea` | `ShadcnTextarea` | |
| `VSelect` | `ShadcnSelect` | `selectedKey` / `onSelectionChange` retained |
| `VCheckbox` | `ShadcnCheckbox` | |
| `VNativeButton` / `VNativeInput` / `VNativeSelect` / `VNativeTextarea` | native | Prefer for dense ops / zero-float paths |
| Layout / display (`VPage`, `VSurface`, strips, …) | Tailwind composition | Not shadcn primitives; keep project-owned |

## Page recipes (prefer for new pages)

| Recipe | Use when |
| --- | --- |
| `VListDetailPage` | Left list / filter + main detail (+ optional aside); pass `layoutId` so sidebars are **draggable with permanent width memory** (`localStorage` key `vibelution.pane-layouts.v1`) |
| `VSettingsFormPage` | Settings/config form with sticky save footer |
| `VDenseOpsPage` | Dense toolbar + body; use `toolbar` (VToolbar) or `toolbarSlot` (bare strip like metrics) |
| `VSplitWorkspace` | Low-level split; `resize={{ layoutId }}` enables left/right drag + persistence (used by list-detail recipe) |

## Rail resize / collapse (Wave 4B)

| Piece | Path | Contract |
| --- | --- | --- |
| Resize only | `components/layout/PaneResizeHandle` | `role=separator`, `aria-valuenow/min/max`, hover-lit 1px rule, Home/End + arrows via `usePersistedPaneResize` |
| Collapse + resize | `components/layout/PaneCollapseHandle` | Same visual contract + centered toggle; routes pass **placement** class only |
| Keyboard helper | `components/layout/paneResizeKeyboard` | Shared Arrow/Home/End resolution for Chat/Logs/custom drag |
| Persistence | `pane-layouts.v1[layoutId]` | Wave 4A store; do not invent new width keys |

## Workbench layoutIds (Wave 4C)

Canonical ids live in `components/layout/workbenchLayoutIds.ts` (`WORKBENCH_LAYOUT_IDS`).

| Prefer | Avoid |
| --- | --- |
| `layoutId={WORKBENCH_LAYOUT_IDS.skills}` on `VListDetailPage` / `VSplitWorkspace` | New ad-hoc `localStorage` width keys |
| `usePersistedPaneResize({ layoutId: WORKBENCH_LAYOUT_IDS.logs, panes })` for custom shells | Copy-pasted drag/keyboard handlers per route |
| `data-vui-layout-id` on the shell root | Hard-coded string literals outside the registry |

New list-detail pages should start from a page recipe + registry `layoutId`. Domain shells (Chat dual-write via `shellStore`, Agents flex) still use the same registry ids.

**Evolution / Runtime scenes:** multi-column Evolution width rails and Logs nested `RuntimeScenesPane` sidebar use `usePersistedPaneResize` + registry ids (`evolution`, `logs-runtime-scenes`). Self-evolution sidebar uses the same hook (`evolution-self`).

**Heights:** vertical splitters use `vibelution.pane-heights.v1` (`paneHeightPersistence.ts`), same layoutId namespace as widths. Prefer `usePersistedPaneHeight` + `PaneHeightResizeHandle`. Evolution CASE IO is `evolution` / `live-io` (legacy key migrated once).

## Wave 5 shell rules

| Prefer | Avoid |
| --- | --- |
| `attachAxisResizeSession` for window-level drag body cursor | Copy-pasted pointermove/up listeners per route |
| `usePersistedPaneResize` / `usePersistedPaneHeight` | New `vibelution.*-width` / `*-height` localStorage keys |
| `WORKBENCH_LAYOUT_IDS.*` + `data-vui-layout-id` | Hard-coded layout id strings |
| Chat dual-write via `setChatPanelWidths` (shellStore + pane-layouts) | Direct Chat width keys outside shellStore |

Gate: `components/layout/workbenchLayoutGate.test.ts` blocks new ad-hoc width/height keys under `routes/`.

## Wave 6A style-map compression

| Prefer | Avoid |
| --- | --- |
| Route `resizeHandle` / `*Resizer` classes = **placement + breakpoint hide only** | Re-painting lit rules, `cursor-col-resize`, or `before:` chrome on route style maps |
| `PaneResizeHandle` / `PaneCollapseHandle` / `PaneHeightResizeHandle` for visual contract | Private handle markup or dead `resizablePane` helpers |
| Drop unused Config `sidebarResize*` keys once rails use shared handles | Leaving orphan style-map keys that reintroduce dual chrome |

Gate also asserts sample route handle keys stay free of private col/row-resize chrome.

## Wave 6B domain recipe + height reuse

| Prefer | Avoid |
| --- | --- |
| Domain recipe on Agents/Teams/Memory shells (`agents-management-workbench`, `teams-organization-workbench`, `memory-knowledge-workbench`) | Anonymous multi-pane shells with only style class names |
| `data-vui-region` for directory/detail/inspector (or canvas/inspector, graph filters/canvas) | Unmarked major rails that break composition contracts |
| `usePersistedPaneHeight` + `PaneHeightResizeHandle` for any new vertical splitter (Evolution CASE IO, Memory graph node list) | Private row-resize handlers / height localStorage keys |
| Page recipe (`dense-ops-page`) + `data-vui-domain-recipe` when domain chrome sits on `VDenseOpsPage` | Overwriting the page recipe without a domain marker |

Gate: `workbenchLayoutGate` + `design/vuiDomainWorkbenchCompositionContract.test.ts`.

## Wave 6C more height split reuse

| Surface | layoutId | pane id | Notes |
| --- | --- | --- | --- |
| Evolution CASE IO | `evolution` | `live-io` | First height consumer (Wave 5) |
| Memory graph node list | `memory` | `graph-node-list` | Wave 6B |
| Logs package file picker | `logs` | `package-files` | Replaces fixed `max-h-[min(190px,24vh)]` |
| Launcher diagnostics body | `launcher` | `diagnostics-body` | Replaces fixed `max-h-[min(42vh,420px)]` |
| Memory project memory queue | `memory` | `project-memory-queue` | Wave 6D; replaces fixed `max-h-[min(220px,28vh)]` |

Prefer these shared APIs for any new vertical splitter; do not reintroduce private max-height-only strips that users would need to resize.

## Wave 6D Chat shell boundary + more height reuse

| Surface | Contract |
| --- | --- |
| Chat session workbench | Domain recipe `chat-session-workbench`; **not** `VListDetailPage`. Width dual-writes `shellStore.setChatPanelWidths` → `pane-layouts.v1[chat]`. Coupled dual-pane bounds stay Chat-owned. |
| Memory project memory queue | `memory` / `project-memory-queue` via `usePersistedPaneHeight` (replaces fixed `max-h-[min(220px,28vh)]`) |

**Chat prefer / avoid**

| Prefer | Avoid |
| --- | --- |
| `attachAxisResizeSession` + `paneResizeKeyboard` + `PaneCollapseHandle` | Private pointermove listeners or lit-rule chrome on Chat style maps |
| `setChatPanelWidths` dual-write | New Chat-only width localStorage keys |
| Document Chat-owned center-track coupling | Forcing Chat onto `usePersistedPaneResize` (breaks coupled dual-pane math) |

Gate: Chat dual-write + layout id stay in `workbenchLayoutGate`; height consumers include project-memory-queue.

Each sets `data-vui-recipe="…"` on the page root for contracts and debugging.

## Adding a control (checklist)

1. Search existing `V*` and product components.
2. If missing: add `renderers/shadcn/ShadcnX.tsx` + thin `V*` wrapper + export from `index.ts`.
3. Map product tone/density through `renderers/shared/*`, not raw shadcn class dumps in routes.
4. Add a focused test under `vui*.test.tsx` or the consuming panel’s layout contract.

## Migration stance

“Borrow shadcn to optimize VUI” means:

- finish making **shadcn/Radix the only interactive backend**;
- keep **V\*** as the steering wheel for app code;
- stop growing a second ad-hoc primitive layer;
- use **page recipes** so new routes do not reinvent headers/splits/footers.

It does **not** mean rewriting Agent/Chat shells or deleting the VUI facade.
