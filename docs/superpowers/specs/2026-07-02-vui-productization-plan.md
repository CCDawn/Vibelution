# VUI Productization Plan — Explicit Style Baseline + Full Route Componentization

> Date: 2026-07-02
> Scope: project-level frontend architecture; supersedes and replaces `2026-06-29-vui-foundation-heroui-renderer-plan.md`
> Status: user-approved direction (alignment session 2026-07-02)
> Visual language source: `2026-06-26-frontend-style-system-design.md` remains authoritative for density, tokens, hairline borders, and typography floor.

## 1. Why the 6/29 plan is replaced

The 6/29 plan assumed the migration starting point was 31 CSS Module files. That
world no longer exists. Commit `ccf0cb5a` ("retire remaining css modules")
performed a wholesale **lossy automated migration** of nearly every route to
`createVuiStyleMap` — a name-inference class generator the 6/29 plan never
sanctioned. The codebase has since lived in an unplanned third state:

- 23 routes on `*.styles.ts` (createVuiStyleMap + per-key extensions)
- 3 routes still on `.module.css` (Agents / Config / Evolution)
- 2 product-component families (`agent-management`, `team-management`)

Weeks of layout bugs (stacked icon links, collapsed grids, flex→grid
mistranslation, sub-14px regressions) all traced to one root cause:
**createVuiStyleMap's key-name magic inference** ("key contains `grid` → emit
auto-fit columns; contains `panel` → emit panel chrome"). Silent defaults mean
silent breakage. All four damage classes are now repaired (audit:
`web/scripts/audit-style-migration.mjs` reports 0 findings; 1175 tests green),
but the fragility mechanism itself is still live.

## 2. Confirmed end state (unchanged north star, hardened route)

The layered architecture from 6/29 is kept verbatim:

```text
routes → product components → VUI primitives → HeroUI renderer → tokens
```

End state (user-confirmed, option C):

- Every route renders through **product components** built from VUI primitives.
- `*.styles.ts` files and `createVuiStyleMap` are **fully retired** — each
  route's styles.ts is deleted in the wave that componentizes that route.
- `.module.css` files are likewise deleted per wave (AgentsRoute Wave 1D etc.).
- Import boundaries stay test-enforced: routes never import `@heroui/react`;
  HeroUI appears only under `components/vui/renderers/`.

## 3. Phase 0 — Explicit Style Baseline (the stabilizer)

Full componentization of ~23 routes is a long campaign. During it, un-migrated
routes must stop breaking. Phase 0 removes the fragility mechanism in one
mechanical, provably visual-neutral step:

1. **Bake**: a codemod evaluates every `*.styles.ts` at build time and rewrites
   it as a plain explicit map — `key: "<the exact class string currently
   computed>"`. Output classes are byte-identical per key (verified by a
   before/after snapshot diff), so visual change is zero by construction.
2. **Delete the magic**: once no styles.ts imports it, `createVuiStyleMap`'s
   name-inference logic is removed. New keys must be written explicitly;
   there are no silent defaults left to mistranslate.
3. **Contract updates**: tests that assert on createVuiStyleMap internals are
   retargeted to the baked files (readable-floor ≥14px scan, no `.module.css`
   references, etc.). Assertions on resolved class values keep passing
   unchanged because the values are identical.

After Phase 0, a `*.styles.ts` is just an explicit route-scoped layout map —
the Tailwind equivalent of what the 6/26 spec allowed route CSS to own (local
grid/flex, column widths, breakpoints). It remains **transitional**: each
componentization wave deletes the file for its route.

## 4. Componentization waves (after Phase 0)

Order follows 6/29 §13, adjusted for work already done:

1. **Teams** (continue): candidate/screening/graph/memory/conversation
   sub-panels → `team-management` components; then research overview, canvas
   inspector, experiment/iteration/loop views. Wave-final: delete
   `TeamsRoute.styles.ts`.
2. **Memory** → `memory-management` components (subnav, pipeline, record
   lists, knowledge workspace).
3. **Chat chrome** (status bars, session rail, member index — NOT the
   streaming conversation surface, which stays last due to markdown/stream/
   scroll coupling).
4. **Agents 1D**: retire `AgentsRoute.module.css` + orphan styles.ts.
5. **Config / Git / Logs / Kernel / Launcher / Tools** utility routes.
6. Remaining routes; delete `createVuiStyleMap` file itself when the last
   styles.ts is gone.

Per-wave rules (unchanged from 6/29, proven in practice):

- Faithful reproduction: the recovered original CSS
  (`git show ccf0cb5a~1:web/src/routes/<X>.module.css`) is the visual truth
  for structure/density/surfaces. Typography floor: no sub-14px in route
  style maps; product components may keep faithful small sizes only where the
  6/26 density language requires it.
- Logic regions (state/query/mutation/handlers) are never touched by style
  waves.
- Data-dependent panels are only migrated when they can be rendered and
  screenshot-verified with real data.

## 5. Verification contract (every increment)

```bash
cd web
node node_modules/typescript/bin/tsc -b --noEmit   # NOT bare `npx tsc`
node_modules/.bin/vitest run
node_modules/.bin/vite build                        # then check dist CSS emits arbitrary values
# screenshots against dev :5174 or backend :8000 (Playwright, networkidle for
# data-gated views); compare against the recovered original CSS design
```

Architecture tests stay mandatory: vuiImportBoundary, vuiThemeFoundation
(≥14px floor), route layout tests, product component tests.

## 6. Coordination note (parallel automation)

This repository has a parallel automated committer ("codex") that mirrors
working-tree edits into `main`, merges its own branches, and deletes feature
branches. Consequences, learned the hard way:

- Work directly on `main`; commit promptly — uncommitted edits can be reverted
  by external branch switches.
- Re-run the full suite after external merges; the mirror has introduced
  contract regressions before.
- This spec file is the coordination mechanism: automation and future sessions
  should treat it — not 6/29 — as the current plan.

## 7. Decision log

- 2026-07-02: user selected end-state **C** (full componentization, retire
  styles.ts/createVuiStyleMap), **one-shot bake** for Phase 0, and writing
  this spec to replace 6/29.
- Damage-repair track (pre-Phase-0) closed at 0 audit findings the same day.
