# ChatCodingRoute Phase E — Stream / Selection Split Plan

**Date:** 2026-07-19
**Owner lane:** chat frontend split (worktree `chat-coding-route-split-hooks`)
**Baseline:** `ChatCodingRoute.tsx` ≈ 5600–5800 LOC after Phase A–D

## Goal

Make session **selection** and **live stream** agent-claimable modules so parallel work no longer requires opening the god file for SSE or session switch logic. Keep one EventSource per surface.

## Non-negotiables

1. **Single session EventSource** — never open a second `/api/sessions/:id/events` controller; extract by move, not re-implement.
2. **Single group EventSource** — same rule for `/api/chat-rooms/:id/events`.
3. **RQ keys unchanged** — `queryKeys.session`, sessions/conversations index shapes stay.
4. **Apply path unchanged** — keep `routeSessionStreamEvent` + `planQueuedSessionDetail` / `planAppliedSessionDetail` / `planAppliedAssistantDeltaDrain` + `createSessionAssistantDeltaScheduler`.
5. **No dual apply queues** — one pending detail queue + one assistant-delta scheduler per connected session stream effect instance.
6. **Telemetry event codes** preserved (layout contract source asserts).
7. **No remote push** unless user asks.

## Current map (LOC approx)

| Block | Location | ~LOC | Risk |
|-------|----------|------|------|
| Stream connect decision + grace | ~927–1005 | 80 | Medium (render-time grace ref write) |
| `syncSessionDetail` | ~1146–1200 | 55 | Medium (ledger merge SSOT) |
| `selectDirectSessionMutation` + reselect ref | ~1208–1245 | 40 | Medium |
| URL / bootstrap session selection effects | ~1258–1328 | 70 | Medium |
| `sessionDetailQuery` + startup settle | ~1330–1355 | 25 | Low |
| **Session EventSource effect** | ~2124–2564 | **~440** | **HIGH** |
| Group EventSource effect | ~2566–2720+ | ~160 | Medium |
| Active-turn reconcile effects | later | varies | High coupling to stream |

Already extracted (do not re-own):

- Protocol: `chatSessionStreamProtocol.ts`
- Apply plans: `chatStreamApplyController.ts`
- Delta scheduler: `sessionAssistantDeltaScheduler.ts`
- Active turn pure: `chatActiveTurnLayer.ts`
- Composer mutations: `useChatComposerSubmit.ts`
- Layout: `useChatWorkbenchLayout.ts`

## Target modules

```
web/src/routes/chat/
  useSessionDetailStream.ts      # E1 — sole session EventSource owner
  useGroupRoomStream.ts          # E2 — sole group EventSource owner
  chatSessionStreamConnect.ts    # E1a — pure connect/grace decision helpers + constants
  useChatSessionSelection.ts     # E3 — URL/bootstrap/select mutation wiring
  README.md                      # claim map update
```

## Phase E1 — Session detail stream (do first)

**Deliverable:** `useSessionDetailStream`

**Owns:**

- `sessionStreamConnected` state
- Stream-local refs: error logged, payload error logged, apply stats (or receive them if already shared with route)
- The full `useEffect` that:
  - skips when `!sessionStreamShouldConnect`
  - opens `EventSource(/api/sessions/${id}/events?initial=light)`
  - handles `session_detail` / `session_initial` / `assistant_delta`
  - queues detail + assistant deltas
  - applies via existing pure planners
  - closes/cleanup on dispose
- Telemetry: `browser.session_stream.*` codes

**Does not own:**

- Second EventSource
- Composer submit mutations
- Group room stream
- RQ key definitions

**Inputs (from route orchestration):**

- `activeSessionId`
- `sessionStreamShouldConnect` (+ decision snapshot fields for telemetry)
- `queryClient`
- `syncSessionDetail`
- `setActiveTurnLayersBySession` / `activeTurnLayersBySessionRef`
- Desktop notifier ref
- Title fallbacks for delta notifications (`sessionDetailQuery.data?.title`, summary title)
- Constants: `SESSION_STREAM_MIN_APPLY_INTERVAL_MS`

**Returns:**

- `sessionStreamConnected`

**Verify:**

- `ChatCodingRoute.layout.test.ts` session_stream contracts pass via `routeAndStreamSource` combined `?raw`
- `npm run build`
- Grep: only one `new EventSource(\`/api/sessions/` in chat route modules

## Phase E1a — Connect decision pure helpers (with E1 or immediately before)

**Deliverable:** `chatSessionStreamConnect.ts`

- `SESSION_STREAM_MIN_APPLY_INTERVAL_MS`
- `SESSION_STREAM_ROUTE_SWITCH_GRACE_MS`
- `resolveSessionStreamRouteTargetMatches(...)`
- `resolveSessionStreamShouldConnect(...)`
- Grace window helpers (pure where possible; ref writes stay in hook/route)

Keeps grace semantics identical (route switch keeps stream briefly connected).

## Phase E2 — Group room stream

**Deliverable:** `useGroupRoomStream`

- Sole owner of chat-room EventSource
- `groupStreamConnected`
- Same “move not clone” rule

Depends on E1 pattern proven.

## Phase E3 — Session selection

**Deliverable:** `useChatSessionSelection`

**Owns:**

- `selectDirectSessionMutation` + `reselectDirectSessionRef`
- Bootstrap from `/api/sessions/active`
- URL `?session=` / `?room=` sync effects that call `setActiveSession` / `setActiveGroupRoomId`
- Optional: clear transient UI on session leave (or keep in route with injected clearer)

**Does not own:**

- Stream connection
- Index list queries (stay orchestration)
- `syncSessionDetail` can stay route-owned and injected (shared by stream + select)

**Order constraint:** selection effects may run before stream hook; stream depends on `activeSessionId` from store.

## Phase E4 — Thin route residual (later)

- Move remaining pure helpers still in `ChatCodingRoute.tsx` (labels, avatar helpers, etc.) only when a claim map row exists
- Target orchestration band: **~800–1500 LOC** (long horizon; E1–E3 alone may land ~4800–5200)

## Risk register

| Risk | Mitigation |
|------|------------|
| Double EventSource after extract | Single hook owns `new EventSource` for sessions; layout/test grep count = 1 |
| Stale apply / double queue | Move entire effect body intact; no parallel implement |
| Grace window break on switch | Preserve grace refs + tests in layout contract |
| Hooks order / early return | Call stream hook unconditionally after connect decision derived |
| Layout tests break | Combined `routeAndStreamSource` like prior phases |

## Execution order (this session)

1. Write this plan + update `web/src/routes/chat/README.md` Phase E section
2. **E1a** constants/helpers if cheap
3. **E1** `useSessionDetailStream` + wire route + fix layout tests
4. build + vitest + commit + self-merge local main
5. **E2** `useGroupRoomStream` when E1 green
6. **E3** selection when E2 green

## Success evidence

- [x] Plan checked into repo
- [x] Only one session EventSource construction path in extracted hook + route import
- [x] E1 Layout stream contracts green / build green / merged
- [x] E2 sole group EventSource (`useGroupRoomStream`)
- [ ] E3 selection extracted
- [ ] Version impact: none (refactor)
- [ ] Launcher refresh: recommended before user testing (stream path)

## Out of scope

- Changing SSE payload protocol
- Changing optimistic turn / composer submit behavior
- Remote PR/push
- Full god-file collapse to 800 LOC in one PR
