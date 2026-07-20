# Frontend Bundle Budget P0 — Root Cause And Plan

Date: 2026-07-20
Owner: frontend optimization lane

## Measured baseline (before CSS split)

| Asset | Size | Budget | Status |
|-------|------|--------|--------|
| `index-*.css` | ~673 KiB | 170 KiB (misclassified as route css) | fail |
| `index-*.js` | ~558 KiB | 470 KiB | fail |
| `ConversationView-*.js` | ~453 KiB | 390 KiB | fail |
| `TeamsRoute-*.js` | ~434 KiB | 390 KiB | fail |
| `ChatCodingRoute-*.js` | ~434 KiB | 390 KiB | fail |

## Root causes

### 1. Shell CSS scanned every lazy route (primary CSS root cause)

`src/design/tailwind.css` previously used:

```css
@source "../routes/**/*.{ts,tsx}";
```

JS routes are lazy, but **all route `*.styles.ts` class strings still entered the shell CSS entry**.

Evidence:

- Route style sources ≈ **1.10 MB** characters across ~150 `routes/**/*.styles.ts`
- Non-route style sources ≈ **0.20 MB**
- Top route style maps: ChatCodingRoute (~136 KB), Config (~80 KB), Agents (~74 KB), Evolution (~61 KB), Teams (~60 KB), Memory (~49 KB)
- Built CSS ≈ **6.3k rule blocks**, dominated by arbitrary Tailwind utilities (`[...]`)

### 2. ConversationView is a heavy JS feature chunk

`ConversationView` chunk ≈ 453 KiB with strong markdown-related signal and large local conversation module graph (timeline, operations, codex transcript, markdown renderer).

### 3. Chat/Teams chunks still exceed JS route budget after source split

Source modularization of Chat improved claimability, but **did not by itself** bring the Chat JS chunk under 390 KiB. Teams remains a god-route (~11k LOC) with large JS output.

### 4. Budget taxonomy was misleading

`index-*.css` was matched by “route css chunks” (170 KiB). It is the **main app CSS entry**, not a lazy route CSS file.

## First cut implemented

1. Shell `tailwind.css` now sources:
   - `app/`, `agent-thread/`, `components/`
   - chat-primary route files only (`ChatCodingRoute*`, `chat/**`, session index helpers, agent-create)
2. Lazy CSS entries under `web/src/design/route-css/`:
   - `agents.tailwind.css`
   - `teams.tailwind.css`
   - `memory.tailwind.css`
   - `config.tailwind.css`
   - `evolution.tailwind.css`
   - `research.tailwind.css`
   - `workbench-secondary.tailwind.css`
3. Corresponding route modules import their CSS entry so Vite emits CSS with the lazy JS chunk.
4. Bundle budget checker:
   - `main application css entry` for `index-*.css` (360 KiB target)
   - `lazy route css chunks` for non-index CSS (220 KiB)

## Measured after first cut

| Asset | Before | After | Notes |
|-------|--------|-------|-------|
| `index-*.css` | ~673 KiB | **~260 KiB** | shell+chat only; under 360 KiB target |
| lazy CSS (agents/config/…) | n/a | 26–146 KiB each | load with route JS |
| `index-*.js` | ~559 KiB | ~559 KiB | unchanged (JS P0 next) |
| ConversationView / Chat / Teams JS | over 390 | still over 390 | unchanged by CSS split |

CSS budget class now passes for shell + lazy route CSS. Remaining failures are **JS** entry/chunks.

## Measured after ConversationView markdown secondary-lazy

`ConversationView` / streaming content now import `LazyConversationMarkdownRenderer` (`React.lazy` + `Suspense`). `react-markdown` / `remark-gfm` land in a separate async chunk.

| Asset | Before (post CSS) | After markdown split | Budget | Status |
|-------|-------------------|----------------------|--------|--------|
| `ConversationView-*.js` | ~453 KiB | **~192 KiB** | 390 KiB | **pass** |
| `ConversationMarkdownRenderer-*.js` | (inside CV) | **~154 KiB** | n/a (async) | loads on rich markdown |
| `ConversationView.styles-*.js` | shared | ~108 KiB | n/a | residual style map chunk |
| `ChatCodingRoute-*.js` | ~434 KiB | ~434 KiB | 390 KiB | still fail (see next cut) |
| `TeamsRoute-*.js` | ~440 KiB | ~440 KiB | 390 KiB | still fail |
| `index-*.js` | ~559 KiB | ~559 KiB | 470 KiB | still fail |
| `index-*.css` | ~260 KiB | ~260 KiB | 360 KiB | pass |

Test note: node `renderToStaticMarkup` never resolves `React.lazy`. Vitest uses a production-noop plugin + `LazyConversationMarkdownRenderer.sync.tsx` re-export so sanitization contracts still run in SSR tests.

## Measured after Chat secondary-lazy dialogs

Chat route secondary-lazy (same pattern as CLI terminal):

- `AgentCreateWizardDialog` — mount only when wizard open
- `CacheDetailDialog` — mount only when cache detail open
- `SessionContextMenu` — mount only when context menu open
- `LlmPayloadTracePanel` — lazy from `ChatStatusRail` when trace present

| Asset | Before | After | Budget | Status |
|-------|--------|-------|--------|--------|
| `ChatCodingRoute-*.js` | ~434 KiB | **~287 KiB** | 390 KiB | **pass** |
| `AgentCreateWizardDialog-*.js` | (in Chat) | ~38 KiB | async | open-to-create |
| `CacheDetailDialog-*.js` | (in Chat) | ~14 KiB | async | open cache |
| `ChatCodingRoute.styles-*.js` | (in Chat) | ~128 KiB | shared style map chunk | pulled by dialog + route |
| `TeamsRoute-*.js` | ~440 KiB | ~441 KiB | 390 KiB | still fail |
| `index-*.js` | ~559 KiB | ~559 KiB | 470 KiB | still fail (see next cut) |

## Measured after index vendor split + lazy VTooltip

Root cause of `index-*.js` bloat (sourcemap / rendered module sizes):

- `react-dom` ~180 KiB min, `react-router` ~95 KiB, `@tanstack/query` ~40 KiB, Radix/floating-ui overlay ~72 KiB
- App-owned shell (`AppShell` + styles + systemStatus) is smaller than the framework graph

Cuts:

1. Vite `manualChunks` → `vendor-react-dom` / `vendor-react-router` / `vendor-query` / `vendor-overlay`
2. `VButton` loads `VTooltip` via `React.lazy` so Radix is not forced into every VButton consumer graph
3. AppShell / RouteErrorBoundary import VButton via direct primitive paths (no VUI barrel)

| Asset | Before | After | Budget | Status |
|-------|--------|-------|--------|--------|
| `index-*.js` | ~559 KiB | **~186 KiB** | 470 KiB | **pass** |
| `vendor-react-dom-*.js` | (in index) | ~174 KiB | 480 KiB vendor | pass |
| `vendor-react-router-*.js` | (in index) | ~93 KiB | 480 KiB vendor | pass |
| `vendor-overlay-*.js` | (in index) | ~71 KiB | 480 KiB vendor | pass |
| `vendor-query-*.js` | (in index) | ~39 KiB | 480 KiB vendor | pass |
| `TeamsRoute-*.js` | ~441 KiB | ~441 KiB | 390 KiB | still fail (see next cut) |

## Measured after Teams secondary panel pack

Structure-first Teams cut (claim map + one async UI pack):

- `web/src/routes/teams/README.md` — ownership map
- `teamSecondaryPanels.ts` — single secondary barrel for panel components
- `lazyTeamPanel.tsx` — shared `createLazyNamedTeamPanel` helper
- `TeamWorkflowGraphLayout.ts` — pure layout math stays in shell; SVG view stays secondary

| Asset | Before | After | Budget | Status |
|-------|--------|-------|--------|--------|
| `TeamsRoute-*.js` | ~441 KiB | **~305 KiB** | 390 KiB | **pass** |
| `teamSecondaryPanels-*.js` | (in Teams) | **~123 KiB** | 390 KiB | pass (async UI pack) |
| other P0 assets | pass | pass | — | pass |

## Follow-up backlog (ordered)

### P0 remaining

1. ~~**ConversationView JS**: secondary-lazy markdown~~ **done** (~453 → ~192 KiB).
2. ~~**Chat JS chunk**: secondary-lazy wizard/cache/menu/LLM trace~~ **done** (~434 → ~287 KiB).
3. ~~**index.js**: vendor split + lazy tooltip~~ **done** (~559 → ~186 KiB).
4. ~~**Teams JS**: claim map + secondary panel pack~~ **done** (~441 → ~305 KiB).
5. Optional: further extract pure helpers/mutations from `TeamsRoute.tsx` (claimability; not required for budget).
6. Optional: further split `ConversationView.styles` if CV residual needs more headroom.

### P1

4. Deduplicate long arbitrary utilities in top `*.styles.ts` (shared class tokens / smaller surface classes).
5. Consider CSS `@source not` refinements if chat-primary shell is still too large.
6. Optional total-transfer budget (sum of all CSS) to watch duplication across lazy CSS entries.

## How to verify

```bash
npm --prefix web run build
node web/scripts/checkBundleBudget.mjs
npm --prefix web test -- --run src/components/vui/vuiPrimitives.test.tsx src/agent-thread/AgentThreadView.test.tsx
```

Success for this cut:

- shell `index-*.css` drops substantially vs 673 KiB baseline
- non-chat route styles no longer force-load on first paint
- budget classification matches architecture
