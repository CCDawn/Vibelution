# Chat Workspace Efficiency Baseline - 2026-05-29

Evidence package: `logs/runtime_scenes/20260529T112138Z__cfc1652fcea0`

## Frontend Query State

- Route: `/chat`
- Browser telemetry samples repeatedly reported `queryCount=18`.
- Browser telemetry samples repeatedly reported `activeQueryCount=17`.

## Session List Latency

Source: `logs/runtime_scenes/20260529T112138Z__cfc1652fcea0/events/conversation.jsonl`

- `session.list.loaded` count: 68
- min: 9ms
- max: 1090ms
- avg: 420ms

The package was still active while measured, so counts may continue to increase. The useful baseline is that a simple `/chat` workbench run can repeatedly reload the lightweight session list despite `readOnly=true` and `hydrateAgent=false`.

## Bundle Baseline

Source: `web/dist/assets`

- main JS: `index-6kCOTXA3.js`, 2,020,513 bytes
- CSS: `index-C_eZjHMN.css`, 472,171 bytes

Source: `logs/runtime_scenes/20260529T112138Z__cfc1652fcea0/raw/frontend.build.log`

- Build succeeded in 1.49s.
- Vite reported `INEFFECTIVE_DYNAMIC_IMPORT` because `FilePreview.tsx` is dynamically imported by `ChatCodingRoute.tsx` but statically imported by `LogsRoute.tsx` and `RuntimeScenesPane.tsx`.

## Optimization Targets

- Centralize chat workspace cache refresh recipes behind a deeper Module.
- Reduce direct route-level query invalidation fanout.
- Make file preview lazy loading effective by avoiding mixed static/dynamic imports.
- Recompare runtime scene query and session-list metrics after implementation.
