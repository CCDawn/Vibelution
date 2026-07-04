# Task 4 Report: Frontend Types, Query Keys, And User Content Panel

## Status

- DONE
- Branch: `codex/user-markdown-space-memory`
- Base: `870c5548`
- Claim: `claim-3fae1f5b3254` (reactivated for this continuation)

## Scope Delivered

- Added user Markdown DTO coverage in `web/src/api/types.ts` for list, import preview/import, page list/detail, and search payloads.
- Added user Markdown React Query keys in `web/src/api/queryKeys.ts`.
- Added a new route-level child panel at `web/src/routes/MemoryUserContentPanel.tsx` with local styles in `web/src/routes/MemoryUserContentPanel.styles.ts`.
- Narrowly mounted the new panel inside `MemoryRoute` without broader route state refactors.
- Extended `web/src/routes/MemoryRoute.layout.test.ts` with a static contract test for the new panel/query-key wiring using raw imports from the route root.

## Implementation Notes

- Followed the local `web/src/routes/*Panel.tsx` pattern: the new panel owns its own query/mutation/local state and does not import `MemoryRoute.styles`.
- Kept `MemoryRoute.tsx` edits narrow: one import plus one mount.
- The panel supports:
  - managed-copy import preview via `POST /api/user-content/markdown-spaces/import-preview`
  - managed-copy import via `POST /api/user-content/markdown-spaces/import`
  - space browse via `GET /api/user-content/markdown-spaces`
  - page browse via `GET /api/user-content/markdown-spaces/{spaceId}/pages`
  - page read via `GET /api/user-content/markdown-spaces/{spaceId}/pages/{pageId}`
  - read-only reference search via `GET /api/user-content/markdown-spaces/search`
- Frontend normalization fills missing legacy fields from current backend payloads so the UI can consume the briefed DTO shape without forcing backend edits in this task.

## Files Changed

- `web/src/api/types.ts`
- `web/src/api/queryKeys.ts`
- `web/src/routes/MemoryUserContentPanel.tsx`
- `web/src/routes/MemoryUserContentPanel.styles.ts`
- `web/src/routes/MemoryRoute.tsx`
- `web/src/routes/MemoryRoute.layout.test.ts`

## Validation

1. `npm --prefix web run test -- MemoryRoute.layout.test.ts`
   - PASS (`40 passed`)
2. `npm --prefix web run build`
   - PASS
3. `git diff --check`
   - PASS

## Logging Decision

- No new runtime logging added in this task.
- Reason: Task 4 is a frontend-only projection and interaction surface over already-existing backend endpoints; no backend lifecycle/state-transition behavior was changed here.

## Launcher Refresh Decision

- `recommended before user testing`
- Reason: this changes frontend build inputs and visible Memory UI, but runtime verification was not requested in this task.

## Version Impact

- No version-file edit performed in this task worktree.
- Recommendation: no standalone version bump for Task 4 alone; evaluate version impact at the full feature integration/merge round.

## Concerns / Residual Risk

- Backend `list/search/page` payloads currently expose a sparser space summary than the briefed frontend DTO contract; the panel compensates with local normalization.
- Search and page filtering intentionally share the same `searchQuery` in this first slice to keep the route integration narrow.

## Commit Readiness

- Ready to stage only the owned frontend files above plus this report file.

## Task 4 Fix Report

- Status: DONE
- Files changed:
  - `web/src/api/types.ts`
  - `web/src/routes/MemoryUserContentPanel.tsx`
  - `web/src/routes/MemoryUserContentPanel.styles.ts`
  - `web/src/routes/MemoryRoute.layout.test.ts`
- Reviewer findings fixed:
  - Shared DTO truthfulness: `UserMarkdownSpaceSummary` now matches the real sparse API contract with required `spaceId`, `spaceName`, `canonicalPagesRoot`, `indexRoot`, `pageCount`, and `updatedAt`, while richer fields (`userId`, `sourceRef`, `counts`) are explicitly optional. The panel now declares its own normalized rendering shape and performs compatibility normalization locally instead of pretending the API already returns the enriched payload.
  - Bounded text/path/source display: long managed-root paths, canonical roots, relative paths, ignored-file summaries, and source-ref previews now render through bounded wrapping styles with `overflow-wrap:anywhere`, `break-all`, and multi-line code wrapping so Windows paths do not force horizontal panel overflow.
- Validation:
  - `npm --prefix web run test -- MemoryRoute.layout.test.ts` -> PASS
  - `npm --prefix web run build` -> PASS
  - `git diff --check` -> PASS
- Commit SHA: `412099a05ae580aae650efb0b0a847c27703115e`
