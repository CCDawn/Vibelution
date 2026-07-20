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

## Follow-up backlog (ordered)

### P0 remaining

1. **ConversationView JS**: secondary-lazy markdown/codex/tool-detail panels; measure again.
2. **Chat JS chunk**: ensure CliAgentRunTerminalPanel stays lazy (already); audit remaining eager imports from ChatCodingRoute.
3. **Teams JS**: apply Chat-style claim map + panel split (source + chunk).

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
