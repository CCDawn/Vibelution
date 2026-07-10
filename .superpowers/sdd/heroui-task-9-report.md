# Task 9 implementation report

## Status

- Result: `DONE`
- Branch: `codex/heroui-frontend-unification`
- Implementation commit: `769530ca` (`fix: preserve AppShell nav label width`)
- Scope tier: `FAST_PATCH`

## Root cause and fix

The primary navigation container already used a single flex row with `overflow-x: auto`, and each label already used `white-space: nowrap`. However, the desktop `.navLink` flex items had no non-shrinking contract, so the flex algorithm compressed each link below its label width when the center top-bar column was constrained.

The production fix adds only `flex-shrink: 0` to the base desktop `.navLink` rule. The existing `max-width: 980px` rule still explicitly sets `flex: 1 1 0`, so its narrow-screen behavior remains unchanged. No AppShell height, route, API/DTO/query/cache behavior, top-level desktop structure, or VUI/HeroUI boundary changed.

## TDD evidence

### RED

Command:

```powershell
npm --prefix web test -- src/app/AppShell.layout.test.ts
```

Observed before production CSS was changed:

```text
src/app/AppShell.layout.test.ts (30 tests | 1 failed)
FAIL AppShell layout contract > keeps desktop primary navigation labels at their intrinsic readable width
AssertionError: expected ... to contain 'flex-shrink: 0'
Test Files  1 failed (1)
Tests       1 failed | 29 passed (30)
exit code 1
```

This was the intended behavior failure: the existing navigation preserved wrapping and container scrolling but lacked the link non-shrinking declaration.

### GREEN

Command:

```powershell
npm --prefix web test -- src/app/AppShell.layout.test.ts
```

Observed after the one-declaration CSS fix:

```text
src/app/AppShell.layout.test.ts (30 tests)
Test Files  1 passed (1)
Tests       30 passed (30)
exit code 0
```

## Build evidence

Command:

```powershell
npm --prefix web run build
```

Observed:

```text
> tsc -b && vite build
vite v8.0.13 building client environment for production...
4334 modules transformed.
✓ built in 1.00s
exit code 0
```

## Acceptance coverage

- At 1280x720 and 1440x900, the desktop base rule applies and `.navLink { flex-shrink: 0; white-space: nowrap; }` prevents a link client width from being flex-compressed below its label content width.
- `.nav { overflow-x: auto; max-width: 100%; }` remains unchanged, so excess primary-navigation width is owned by the navigation container rather than the document.
- AppShell structure and route declarations were not edited. Existing primary-route assertions in the focused AppShell suite remain green, and the existing React Router links remain keyboard-focusable.
- The test scopes its assertions to the base navigation rules, while the existing narrow-screen test continues to protect the explicit `max-width: 980px` ellipsis behavior.

## Changed files

- `web/src/app/AppShell.layout.test.ts`: added the focused desktop primary-navigation width contract.
- `web/src/design/workbench-shell.css`: added `flex-shrink: 0` to the base `.navLink` rule.
- `.superpowers/sdd/heroui-task-9-report.md`: recorded implementation, RED/GREEN, build, and review evidence.

## Self-review

- `git diff --check`: passed before the implementation commit.
- Minimality: one test and one production CSS declaration; no opportunistic refactor.
- Boundary review: no API, DTO, query, cache, route, dependency, package-lock, version, project-memory, Launcher, or HeroUI import changes.
- Logging decision: not affected; this is deterministic CSS layout behavior with no runtime branch or failure event to log.
- Launcher refresh: not performed per task instruction; refresh is recommended before live user testing, but not required for the requested focused test and production build evidence.
- Project memory: intentionally not touched per task instruction.
- Version impact: `patch` recommendation because this is localized user-visible layout polish; version files were intentionally not changed.
- Local Agent corpus: not applicable to this narrowly scoped CSS fix.
- Remaining risk: none identified within the requested scope.
