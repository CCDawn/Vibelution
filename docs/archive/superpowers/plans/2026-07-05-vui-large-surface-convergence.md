# VUI Large Surface Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Tools, Logs, Research, Reset, and Kernel routes background-aware and visually consistent with the quiet VUI workbench grammar.

**Architecture:** This wave keeps HeroUI behind VUI and avoids backend/API changes. The implementation tightens existing route style maps and route aesthetic contracts before any style cleanup, so repeated page-background, header-card, button-panel, and card-wall patterns are mechanically guarded.

**Tech Stack:** React, TypeScript, Tailwind utility strings, VUI primitives, Vitest layout/static contracts, Vite build.

## Global Constraints

- Work in `C:\Users\17533\Desktop\Vibelution-worktrees\vui-large-surface-convergence` on branch `codex/vui-large-surface-convergence`.
- Guard claim: `claim-802324cb9704`.
- Scope is pure frontend route styles and tests: no backend, no API/DTO, no runtime manager, no config, no version files.
- Do not touch `ResearchFlowCanvasRoute*`, `LauncherRoute*`, `GitRoute*`, `SkillsRoute*`, or `PromptTemplatesRoute*` in this wave.
- Do not introduce route-level `@heroui/react` imports, new design tokens, `.module.css` fallback, raw hex colors, raw gradients, or a parallel design system.
- Preserve destructive/error/blocker affordances, keyboard focus, dense layout, scroll containment, and route-specific business geometry.
- Verification must include focused Vitest contracts, `npm --prefix web run build`, `git diff --check`, and browser screenshots for desktop/narrow target routes when practical.

---

### Task 1: Route Aesthetic Contract Expansion

**Files:**
- Modify: `web/src/routes/routeAestheticContract.test.ts`

**Interfaces:**
- Consumes: existing `extractStyleValue`, style-map source scanning, and `WORKBENCH_MAINLINE_STYLE_FILES`.
- Produces: failing tests for Wave 2.5 background-aware roots and layout-only chrome keys.

- [x] **Step 1: Add failing route-background coverage**

Add Tools, Logs, Research, Reset, and Kernel style files to a special-route list and assert that root keys do not include `bg-[var(--surface-page)]`.

- [x] **Step 2: Add failing chrome coverage**

Add Tools, Logs, Research, and Kernel key lists for header-card and button-panel anti-patterns. Assert those keys do not contain `bg-[var(--vui-surface-glass)]`, `shadow-[var(--vui-shadow-hairline)]`, or `rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)]`.

- [x] **Step 3: Verify RED**

Run: `npm --prefix web run test -- src/routes/routeAestheticContract.test.ts`

Expected: FAIL with offenders from Tools, Logs, Research, Reset, and Kernel.

### Task 2: Tools Route Chrome Convergence

**Files:**
- Modify: `web/src/routes/ToolsRoute.styles.ts`
- Modify if needed: `web/src/routes/ToolsRoute.layout.test.ts`

**Interfaces:**
- Consumes: Task 1 contract keys and existing Tools layout tests.
- Produces: layout-only Tools headers/toolbars and background-aware route root.

- [x] **Step 1: Make the minimal style changes**

Remove `bg-[var(--surface-page)]` from `styles.route`. Convert `detailHeader`, `detailActions`, `panelEyebrow`, and `panelHeader` to layout/typography/toolstrip classes without panel glass/shadow. Convert summary/grid wrappers to layout grids where the actual items still carry appropriate row/chip treatment.

- [x] **Step 2: Keep existing behavior contracts green**

Run: `npm --prefix web run test -- src/routes/ToolsRoute.layout.test.ts src/routes/routeAestheticContract.test.ts`

Expected: PASS.

### Task 3: Logs Route Chrome Convergence

**Files:**
- Modify: `web/src/routes/LogsRoute.styles.ts`
- Modify if needed: `web/src/routes/LogsRoute.layout.test.ts`

**Interfaces:**
- Consumes: Task 1 contract keys and existing Logs layout tests.
- Produces: background-aware Logs route root, row-like package/scene controls, and layout-only scene headers.

- [x] **Step 1: Make the minimal style changes**

Remove `bg-[var(--surface-page)]` from `styles.route`. Convert package navigation and scene controls away from panel-button hybrids. Keep selected/error/empty states visible.

- [x] **Step 2: Keep existing behavior contracts green**

Run: `npm --prefix web run test -- src/routes/LogsRoute.layout.test.ts src/routes/routeAestheticContract.test.ts`

Expected: PASS.

### Task 4: Research, Reset, and Kernel Surface Convergence

**Files:**
- Modify: `web/src/routes/ResearchRoute.styles.ts`
- Modify: `web/src/routes/ResearchRoute.layout.test.ts` if needed
- Modify: `web/src/routes/ResetRoute.styles.ts`
- Modify: `web/src/routes/ResetRoute.layout.test.ts` if needed
- Modify: `web/src/routes/KernelTaskCenterRoute.styles.ts`
- Modify: `web/src/routes/KernelTaskCenterRoute.layout.test.ts` if needed

**Interfaces:**
- Consumes: Task 1 contract keys and route-specific layout tests.
- Produces: background-aware roots and reduced header/row card chrome for Research, Reset, and Kernel.

- [x] **Step 1: Research minimal cleanup**

Remove the route root `surface-page` background. Convert `panelEyebrow`, `panelHeader`, `panelLead`, and summary/stage wrapper chrome toward layout-only or row/chip treatment without weakening content hierarchy.

- [x] **Step 2: Reset and Kernel minimal cleanup**

Remove root `surface-page` backgrounds. Convert Kernel `taskRowClass` away from a giant button-card while preserving click affordance. Keep Reset destructive/retired semantics readable.

- [x] **Step 3: Verify focused routes**

Run: `npm --prefix web run test -- src/routes/ResearchRoute.layout.test.ts src/routes/ResetRoute.layout.test.ts src/routes/KernelTaskCenterRoute.layout.test.ts src/routes/routeAestheticContract.test.ts`

Expected: PASS.

### Task 5: Full Frontend Verification And Visual Evidence

**Files:**
- No intended source changes beyond screenshots under `.runtime/visual-checks/vui-large-surface-convergence/` if browser verification is available.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: build/test/browser evidence and a clean diff ready for review.

- [x] **Step 1: Run focused contract batch**

Run: `npm --prefix web run test -- src/components/vui src/routes/routeAestheticContract.test.ts src/routes/RouteStyleDisplayContract.test.ts src/routes/ToolsRoute.layout.test.ts src/routes/LogsRoute.layout.test.ts src/routes/ResearchRoute.layout.test.ts src/routes/ResetRoute.layout.test.ts src/routes/KernelTaskCenterRoute.layout.test.ts`

Expected: PASS.

- [x] **Step 2: Run build and diff check**

Run: `npm --prefix web run build`

Expected: PASS.

Run: `git diff --check`

Expected: no output.

- [x] **Step 3: Capture visual evidence**

Run a dev server and inspect `/agents/tools`, `/logs`, `/research`, `/reset`, and `/kernel` at `1440x960` and `390x844`. Confirm background visibility, no card wall, no overlap, button fit, and preserved critical states.
