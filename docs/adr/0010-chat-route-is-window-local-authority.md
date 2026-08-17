# ADR 0010 · Chat Route Is The Window-Local Active Authority

## Status

Accepted (2026-08-14).

> 编号说明：最初规划为 ADR 0009，落地时 0009 已被 Launcher Electron 控制面
> ADR 占用，本决策改编号为 0010，内容与语义不变。

## Context

The Chat workbench historically kept four competing "current session" sources:
React Router URL search params, Zustand `activeSessionId`, localStorage
last-viewed selection, and the backend `active_conversation_id` viewing pointer.
`AppShell` additionally ran a browser/router "desync recovery" that called
`window.history.replaceState` and `navigate` on window focus, `pageshow`,
`popstate`, document clicks, and visibility changes, emitting
`browser.router_location_desync.recovered`.

The result was non-user-intended session switching: a window that regained
focus, a background task that finished, a cache refresh, or a late async
response could snap the page back to an old session. A backend pointer that is
inherently project-global also cannot express two workbench windows viewing
different sessions at the same time.

## Decision

1. **Window-local authority.** The committed React Router URL is the single
   authority for the current Workbench page, direct session (`?session=<id>`),
   group room (`?room=<id>`), and Project Agent Bus
   (`?room=__project_agent_bus__`). There is no second authority: no Zustand
   active session, no component-local active room state, and no localStorage or
   server pointer that can drive navigation after a canonical URL exists.
2. **No desync recovery.** `browser.router_location_desync.recovered` and all
   recovery code are deleted. Business code never calls
   `window.history.pushState/replaceState` directly. `POP` is handled only by
   React Router. Focus, `pageshow`, `visibilitychange`, background task
   completion, SSE/polling/query invalidation, session recency, list ordering,
   and pointer writes from other windows may update data, caches, or telemetry
   only — never navigation.
3. **One route-domain writer.** All Chat route writes flow through
   `useChatRouteSelection` (`openSession`, `openRoom`, `openProjectBus`,
   `canonicalizeBareRoute`, `replaceIfStillViewing`). Async create/delete/
   archive/reset/select/handoff results must compare-and-swap: the transition
   applies only while the committed route still equals the request-start
   target; otherwise only caches are updated.
4. **Explicit invalid routes stay put.** `/chat?session=<missing>` or an
   archived session keeps its URL and renders an unavailable surface. It never
   silently opens another session.
5. **Temporary sessions live in the URL.** Optimistic `temp-session-*` ids
   enter `?session=` immediately; success replaces them with the real id only
   while the user still views the temp route; failure keeps the temp failure
   surface and never auto-restores a previous session.
6. **Preferences are bootstrap hints only.** localStorage last-viewed selection
   and the backend `active_conversation_id` participate only in the one-shot
   canonicalization of a bare `/chat` entry (once per `location.key`, only
   after the session directory is authoritative). After a canonical URL is
   committed they are written passively and never read back into navigation.
   `GET /api/sessions/active` and `POST /api/sessions/{id}/select` remain as a
   last-viewed preference API; `/select` late responses update only the target
   session cache. SQLite keeps `active_conversation_id` for compatibility;
   renaming to `lastViewedSessionId` is out of scope for this decision.
7. **No dual-mode flag.** The old and new authority models never run behind a
   feature flag; dual mode would itself be two competing authorities.

## Consequences

- Session switching is fully predictable: only user clicks, explicit deep
  links, Router `POP`, user-confirmed lifecycle transitions, and the one-shot
  bare-route canonicalization change the page.
- Backend tests `tests/test_session_viewing_pointer.py` and
  `tests/test_web_session_routes.py` continue to prove that background submits,
  child-session creation, list ordering, and `/select` never act as window
  navigation authority.
- Telemetry may keep passive `browser.route.changed` /
  `browser.history.pop_state` events; telemetry handlers have no navigation or
  selection-setter capability.
- Rollback is per-commit; there is no data migration and no schema change.
  Reintroducing a "recovery" event under any name reopens the defect.
