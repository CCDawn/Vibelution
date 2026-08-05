# HeroUI Frontend Unification Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the shared soft-layer desktop visual foundation, then apply it to AppShell and the existing three-column Chat workbench without changing product behavior or data contracts.

**Architecture:** HeroUI remains the accessible interaction primitive behind project-owned VUI components; routes continue to consume VUI and typed Tailwind style maps. Shared tokens and VUI primitives define surface/elevation/Tooltip behavior, while AppShell and Chat only compose those contracts and retain all existing API, query, store, resize, stream, cache, and lifecycle ownership.

**Tech Stack:** React 19, TypeScript 5.9, HeroUI React 3.2.1, Tailwind CSS 4, Vite 8, Vitest 3, Zustand, TanStack Query.

## Global Constraints

- Desktop-only product contract: validate `1280×720`, `1440×900`, and `1920×1080`; do not add phone, touch, or mobile-drawer design requirements.
- Keep the existing macro layout: Chat remains conversation index on the left, conversation in the center, and status rail on the right.
- At and above `1280px`, all three Chat columns remain available; below `1280px`, compact desktop mode may auto-collapse only the right status rail and must retain an explicit reopen control.
- Preserve existing routes, API/DTO shapes, query keys, cache semantics, message protocols, permissions, business state, resizing, collapse controls, and persisted panel widths.
- Route code must not add direct `@heroui/react` imports; HeroUI stays behind `web/src/components/vui/**`.
- Reuse the installed `@heroui/react` dependency and npm/package-lock flow; do not run the HeroUI installer, replace npm with Bun, or modify dependency versions in this phase.
- Text buttons remain content-sized by default; icon-only buttons remain square, accessible by name, and reachable through hover/focus Tooltip behavior.
- Critical errors, permission blockers, destructive consequences, irreversible actions, and recovery instructions remain directly visible.
- Visual-only changes add no runtime-scene logging. If implementation reveals a behavior change, stop and re-plan that change with logging and behavior tests.
- Do not edit `VERSION`, `CHANGELOG.md`, `web/package.json`, or `web/package-lock.json`; Phase 1 reports version impact `patch` and defers a coherent program-level `minor` decision.
- Do not hand-edit `.docs/project-memory/**` from the task worktree. Sync the `web-workbench-surface` lane only after validated local-main integration, or provide the exact update proposal if the memory claim is unavailable.

---

## File Structure And Ownership

| Area | Files | Responsibility |
| --- | --- | --- |
| Desktop evidence contract | `web/src/visual-regression/workbenchVisualMatrix.ts`, `web/src/visual-regression/workbenchVisualMatrix.test.ts` | Canonical compact/standard/wide desktop viewport matrix and screenshot checklist |
| Shared visual tokens | `web/src/design/tokens.css`, `web/src/design/tailwind.css`, `web/src/components/vui/vuiThemeFoundation.test.tsx` | Soft panel/overlay radii, elevation aliases, surface color bridge, and light/dark parity |
| VUI primitive API | `web/src/components/vui/primitives/VSurface.tsx`, `web/src/components/vui/primitives/VIconButton.tsx`, `web/src/components/vui/index.ts`, `web/src/components/vui/vuiPrimitives.test.tsx`, `web/src/components/vui/vuiThemeFoundation.test.tsx` | Project-owned surface tone/elevation and mandatory icon Tooltip behavior |
| AppShell | `web/src/app/AppShell.tsx`, `web/src/app/AppShell.styles.ts`, `web/src/app/AppShell.layout.test.ts`, `web/src/design/workbench-shell.css` | Three top-bar groups, soft grouping, stable compact desktop labels, and utility geometry |
| Chat desktop layout | `web/src/routes/ChatCodingRoute.tsx`, `web/src/routes/ChatCodingRoute.styles.ts`, `web/src/routes/ChatCodingRoute.layout.test.ts` | Three-column layout, below-1280 status-only auto-collapse, resize/collapse preservation |
| Chat status rail | `web/src/routes/ChatCodingRoute.tsx`, `web/src/routes/ChatCodingRoute.styles.ts`, `web/src/routes/ChatCodingLeftStatus.layout.test.ts`, `web/src/routes/chat/TokenCoreStatusPanel.tsx`, `web/src/routes/chat/LlmPayloadTracePanel.tsx` | One raised rail surface, flat internal groups, concise labels, Tooltip detail |
| Chat index and center states | `web/src/routes/ChatCodingRoute.tsx`, `web/src/routes/ChatCodingRoute.styles.ts`, `web/src/routes/ChatCodingRoute.layout.test.ts`, `web/src/routes/chat/ChatSessionWorkspacePanel.tsx`, `web/src/routes/chat/ChatSessionWorkspacePanel.styles.ts` | One soft index surface, stable action rows, shared loading/empty/error/unavailable surfaces |
| Final evidence | design spec, this plan, validated task commits, browser screenshots/observations, project-memory sync output | Completion status, Launcher decision, memory/version handoff |

## Interface Contract Between Tasks

Task 2 produces these exact CSS variables for Tasks 3–7:

```css
--vui-radius-panel-soft: 10px;
--vui-radius-overlay: 12px;
--vui-elevation-panel: var(--vui-elevation-1-sheen);
--vui-elevation-overlay: var(--vui-elevation-2-sheen);
```

Task 3 produces these exact public types and props:

```ts
export type VSurfaceTone = "panel" | "rail" | "glass" | "toolbar" | "row";
export type VSurfaceElevation = "flat" | "panel" | "overlay";

export type VSurfaceProps = ComponentPropsWithoutRef<"section"> & {
  as?: VSurfaceElement;
  ariaLabel?: string;
  children: ReactNode;
  "data-vui"?: string;
  elevation?: VSurfaceElevation;
  padding?: VSurfacePadding;
  tone?: VSurfaceTone;
};

export type VIconButtonProps = Omit<
  VButtonProps,
  "children" | "icon" | "isIconOnly" | "aria-label"
> & {
  label: string;
  icon: ReactNode;
  title?: string;
  tooltip?: ReactNode;
};
```

Tasks 4–7 may consume only those project-owned interfaces. They must not pass HeroUI-specific state or color values through route code.

---

## Execution Preflight Claim

Before Task 1, run this exact PowerShell block from the task worktree. It creates one bounded implementation claim for the files owned by this plan and prints the generated claim id for the execution log:

```powershell
$python = "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe"
$guard = "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py"
$project = "C:\Users\17533\Desktop\Vibelution"
$claimJson = & $python $guard $project claim `
  --lane "web-workbench-surface" `
  --scope "web/src/visual-regression/workbenchVisualMatrix.ts" `
  --scope "web/src/visual-regression/workbenchVisualMatrix.test.ts" `
  --scope "web/src/design/tokens.css" `
  --scope "web/src/design/tailwind.css" `
  --scope "web/src/design/workbench-shell.css" `
  --scope "web/src/components/vui/index.ts" `
  --scope "web/src/components/vui/primitives/VSurface.tsx" `
  --scope "web/src/components/vui/primitives/VIconButton.tsx" `
  --scope "web/src/components/vui/vuiPrimitives.test.tsx" `
  --scope "web/src/components/vui/vuiThemeFoundation.test.tsx" `
  --scope "web/src/app/AppShell.tsx" `
  --scope "web/src/app/AppShell.styles.ts" `
  --scope "web/src/app/AppShell.layout.test.ts" `
  --scope "web/src/routes/ChatCodingRoute.tsx" `
  --scope "web/src/routes/ChatCodingRoute.styles.ts" `
  --scope "web/src/routes/ChatCodingRoute.layout.test.ts" `
  --scope "web/src/routes/ChatCodingLeftStatus.layout.test.ts" `
  --scope "web/src/routes/chat/TokenCoreStatusPanel.tsx" `
  --scope "web/src/routes/chat/LlmPayloadTracePanel.tsx" `
  --scope "web/src/routes/chat/ChatSessionWorkspacePanel.tsx" `
  --scope "web/src/routes/chat/ChatSessionWorkspacePanel.styles.ts" `
  --scope "docs/superpowers/specs/2026-07-10-heroui-frontend-unification-design.md" `
  --scope "docs/superpowers/plans/2026-07-10-heroui-frontend-unification-phase-1.md" `
  --agent "codex-heroui-frontend-unification" `
  --task "Implement HeroUI frontend Phase 1 · codex/heroui-frontend-unification" `
  --ttl-minutes 480 `
  --note "Tasks 1-8; focused Vitest, build, scoped diff, Launcher, and 1280/1440/1920 browser evidence required" `
  --json
$implementationClaim = $claimJson | ConvertFrom-Json
if (-not $implementationClaim.ok -or -not $implementationClaim.claim.id) {
  throw "Unable to acquire the HeroUI Phase 1 implementation claim."
}
$implementationClaim.claim.id
```

Expected: the guard prints a new `claim-...` id with status `active`. If another claim overlaps, stop before editing and report the conflicting id/scope; do not use `--force`.

---

### Task 1: Replace Mobile Visual Gates With The Desktop Acceptance Matrix

**Files:**
- Modify: `web/src/visual-regression/workbenchVisualMatrix.ts:1-150`
- Modify: `web/src/visual-regression/workbenchVisualMatrix.test.ts:1-65`

**Interfaces:**
- Consumes: approved desktop viewport contract `1280×720`, `1440×900`, `1920×1080`.
- Produces: `WorkbenchVisualViewport = "compact" | "standard" | "wide"`, `WORKBENCH_DESKTOP_VIEWPORTS`, and `classifyWorkbenchVisualViewport(width: number)`.

- [ ] **Step 1: Write the failing desktop-matrix tests**

Replace the viewport coverage and scenario-bound assertions with:

```ts
it("covers compact, standard, and wide desktop viewports without a mobile gate", () => {
  const coverage = summarizeWorkbenchVisualCoverage(WORKBENCH_VISUAL_SCENARIOS);

  expect(coverage.viewports).toEqual(["compact", "standard", "wide"]);
  expect(WORKBENCH_VISUAL_SCENARIOS.some(({ viewport }) => viewport.width === 1280 && viewport.height === 720)).toBe(true);
  expect(WORKBENCH_VISUAL_SCENARIOS.some(({ viewport }) => viewport.width === 1440 && viewport.height === 900)).toBe(true);
  expect(WORKBENCH_VISUAL_SCENARIOS.some(({ viewport }) => viewport.width === 1920 && viewport.height === 1080)).toBe(true);
  expect(WORKBENCH_VISUAL_SCENARIOS.every(({ viewport }) => viewport.width >= 1280)).toBe(true);
});

it("keeps every desktop scenario actionable for screenshot capture", () => {
  expect(WORKBENCH_VISUAL_SCENARIOS).toHaveLength(12);

  for (const scenario of WORKBENCH_VISUAL_SCENARIOS) {
    expect(scenario.id).toMatch(/^[a-z0-9-]+$/);
    expect(scenario.path).toMatch(/^\//);
    expect(scenario.viewport.width).toBeGreaterThanOrEqual(1280);
    expect(scenario.viewport.height).toBeGreaterThanOrEqual(720);
    expect(scenario.reviewFocus.length).toBeGreaterThanOrEqual(2);
    expect(scenario.expectedEvidence).toBe("screenshot");
  }
});
```

Also change the first coverage expectation from:

```ts
expect(coverage.viewports).toEqual(["desktop", "narrow"]);
```

to:

```ts
expect(coverage.viewports).toEqual(["compact", "standard", "wide"]);
```

- [ ] **Step 2: Run the test and verify the old mobile matrix fails**

Run: `npm --prefix web run test -- workbenchVisualMatrix.test.ts`

Expected: FAIL because the current coverage is `desktop/narrow`, two scenarios are `390×844`, and no scenario is `1920×1080`.

- [ ] **Step 3: Implement exact desktop viewport presets and classification**

Replace the viewport type and add the presets/classifier:

```ts
export type WorkbenchVisualViewport = "compact" | "standard" | "wide";

export const WORKBENCH_DESKTOP_VIEWPORTS = {
  compact: { width: 1280, height: 720 },
  standard: { width: 1440, height: 900 },
  wide: { width: 1920, height: 1080 },
} as const;

export function classifyWorkbenchVisualViewport(width: number): WorkbenchVisualViewport {
  if (width >= WORKBENCH_DESKTOP_VIEWPORTS.wide.width) {
    return "wide";
  }
  if (width <= WORKBENCH_DESKTOP_VIEWPORTS.compact.width) {
    return "compact";
  }
  return "standard";
}
```

Use these exact viewport assignments across the 12 existing scenarios while keeping their route/state/theme/background coverage:

```ts
const compact = WORKBENCH_DESKTOP_VIEWPORTS.compact;
const standard = WORKBENCH_DESKTOP_VIEWPORTS.standard;
const wide = WORKBENCH_DESKTOP_VIEWPORTS.wide;

// Scenario viewport order, preserving the existing scenario order:
// home=standard, chat-light=compact, chat-dark=standard, chat-custom=wide,
// supervised-default=standard, supervised-custom=compact,
// agents=standard, memory-default=standard, memory-custom=compact,
// memory-graph=wide, config-light=standard, config-dark=wide.
```

For every scenario, update the id segment from `desktop`/`narrow` to `compact`/`standard`/`wide` and assign `viewport: compact`, `viewport: standard`, or `viewport: wide` exactly as listed above. Replace the coverage calculation with:

```ts
viewports: sortedUnique(
  scenarios.map((scenario) => classifyWorkbenchVisualViewport(scenario.viewport.width)),
),
```

Update the review protocol start command to the repository-safe form:

```ts
"Start the app through Vibelution Launcher; use a scoped Vite dev server only when Launcher cannot render the task branch before integration.",
```

Update the matching test expectation to the same exact string:

```ts
expect(WORKBENCH_VISUAL_REVIEW_PROTOCOL[0]).toBe(
  "Start the app through Vibelution Launcher; use a scoped Vite dev server only when Launcher cannot render the task branch before integration.",
);
```

- [ ] **Step 4: Run the desktop-matrix test and confirm it passes**

Run: `npm --prefix web run test -- workbenchVisualMatrix.test.ts`

Expected: PASS; coverage reports `compact`, `standard`, and `wide`, with no viewport narrower than 1280.

- [ ] **Step 5: Commit the desktop evidence contract**

```powershell
git add -- web/src/visual-regression/workbenchVisualMatrix.ts web/src/visual-regression/workbenchVisualMatrix.test.ts
git commit -m "test(web): define desktop visual acceptance matrix"
```

---

### Task 2: Add The Restrained Soft-Layer Token Contract

**Files:**
- Modify: `web/src/components/vui/vuiThemeFoundation.test.tsx:20-120`
- Modify: `web/src/design/tokens.css:32-82,205-250`
- Modify: `web/src/design/tailwind.css:10-30`

**Interfaces:**
- Consumes: existing `--vui-elevation-1-sheen`, `--vui-elevation-2-sheen`, surface tokens, and light/dark theme blocks.
- Produces: `--vui-radius-panel-soft`, `--vui-radius-overlay`, `--vui-elevation-panel`, `--vui-elevation-overlay`, and Tailwind `vui-surface-rail`/`vui-surface-raised` mappings.

- [ ] **Step 1: Write the failing semantic-token assertions**

Add these tokens to the existing shared-token loop:

```ts
for (const token of [
  "--vui-radius-panel-soft",
  "--vui-radius-overlay",
  "--vui-elevation-panel",
  "--vui-elevation-overlay",
]) {
  expect(tokensSource).toContain(token);
}

expect(tokensSource).toContain("--vui-radius-panel-soft: 10px;");
expect(tokensSource).toContain("--vui-radius-overlay: 12px;");
expect(tokensSource).toContain("--vui-elevation-panel: var(--vui-elevation-1-sheen);");
expect(tokensSource).toContain("--vui-elevation-overlay: var(--vui-elevation-2-sheen);");
expect(tailwindSource).toContain("--color-vui-surface-rail: var(--vui-surface-rail)");
expect(tailwindSource).toContain("--color-vui-surface-raised: var(--vui-surface-raised)");
```

- [ ] **Step 2: Run the foundation test and verify the missing tokens fail**

Run: `npm --prefix web run test -- vuiThemeFoundation.test.tsx`

Expected: FAIL because the four semantic aliases and two Tailwind surface mappings do not exist yet.

- [ ] **Step 3: Add the tokens without remapping legacy route radii**

Add this block after the existing elevation scale in both theme token scopes where theme-specific elevation variables are defined:

```css
  --vui-radius-panel-soft: 10px;
  --vui-radius-overlay: 12px;
  --vui-elevation-panel: var(--vui-elevation-1-sheen);
  --vui-elevation-overlay: var(--vui-elevation-2-sheen);
```

Do not change `--radius-panel` globally in this phase. Add these mappings inside `@theme inline` in `tailwind.css`:

```css
  --color-vui-surface-rail: var(--vui-surface-rail);
  --color-vui-surface-raised: var(--vui-surface-raised);
```

- [ ] **Step 4: Run the token and import-boundary tests**

Run: `npm --prefix web run test -- vuiThemeFoundation.test.tsx vuiImportBoundary.test.ts`

Expected: PASS; both themes expose the aliases and route-level HeroUI boundaries remain unchanged.

- [ ] **Step 5: Commit the shared visual aliases**

```powershell
git add -- web/src/components/vui/vuiThemeFoundation.test.tsx web/src/design/tokens.css web/src/design/tailwind.css
git commit -m "style(web): add restrained soft-layer tokens"
```

---

### Task 3: Extend VSurface And Make Icon Tooltips A VUI Contract

**Files:**
- Modify: `web/src/components/vui/vuiPrimitives.test.tsx:45-115`
- Modify: `web/src/components/vui/vuiThemeFoundation.test.tsx:150-200`
- Modify: `web/src/components/vui/primitives/VSurface.tsx:1-55`
- Modify: `web/src/components/vui/primitives/VIconButton.tsx:1-40`
- Modify: `web/src/components/vui/index.ts:1-10`

**Interfaces:**
- Consumes: Task 2 token contract and existing `VButton`/`VTooltip` wrappers.
- Produces: `VSurfaceTone`, `VSurfaceElevation`, `elevation` prop, `rail` tone, and VIconButton `tooltip` prop with label fallback.

- [ ] **Step 1: Write the failing primitive rendering tests**

Import `VSurface` in `vuiPrimitives.test.tsx`, then add:

```tsx
it("renders project-owned surface tone and elevation contracts", () => {
  const markup = renderToStaticMarkup(
    <VSurface tone="rail" elevation="panel" ariaLabel="Status rail">
      Status
    </VSurface>,
  );

  expect(markup).toContain('data-tone="rail"');
  expect(markup).toContain('data-elevation="panel"');
  expect(markup).toContain("bg-vui-surface-rail");
  expect(markup).toContain("shadow-[var(--vui-elevation-panel)]");
  expect(markup).toContain("rounded-[var(--vui-radius-panel-soft)]");
});

it("gives every icon button a HeroUI tooltip trigger with an accessible name", () => {
  const markup = renderToStaticMarkup(
    <VibelutionHeroProvider>
      <VIconButton label="Refresh" tooltip="Refresh frontend data" icon={<Search size={14} />} />
    </VibelutionHeroProvider>,
  );

  expect(markup).toContain('data-slot="tooltip-trigger"');
  expect(markup).toContain('aria-label="Refresh"');
  expect(markup).toContain('data-vui="icon-button"');
});
```

- [ ] **Step 2: Run the primitive tests and verify the new API fails to compile**

Run: `npm --prefix web run test -- vuiPrimitives.test.tsx vuiThemeFoundation.test.tsx`

Expected: FAIL with type errors for `tone="rail"`, `elevation`, and `tooltip`.

- [ ] **Step 3: Implement VSurface tone/elevation without exposing HeroUI props**

Replace the private tone types/maps and extend the props with:

```tsx
type VSurfaceElement = "article" | "aside" | "div" | "header" | "main" | "section";
export type VSurfaceTone = "panel" | "rail" | "glass" | "toolbar" | "row";
export type VSurfaceElevation = "flat" | "panel" | "overlay";
type VSurfacePadding = "none" | "compact" | "normal";

export type VSurfaceProps = ComponentPropsWithoutRef<"section"> & {
  as?: VSurfaceElement;
  ariaLabel?: string;
  children: ReactNode;
  "data-vui"?: string;
  elevation?: VSurfaceElevation;
  padding?: VSurfacePadding;
  tone?: VSurfaceTone;
};

const toneClass: Record<VSurfaceTone, string> = {
  glass: "bg-vui-surface-glass backdrop-blur-[1px]",
  panel: "bg-vui-surface-panel/82",
  rail: "bg-vui-surface-rail",
  row: "bg-vui-surface-row",
  toolbar: "bg-vui-surface-toolbar",
};

const elevationClass: Record<VSurfaceElevation, string> = {
  flat: "shadow-none",
  panel: "shadow-[var(--vui-elevation-panel)]",
  overlay: "shadow-[var(--vui-elevation-overlay)]",
};
```

Update the component defaults and rendered attributes/classes exactly as follows:

```tsx
export function VSurface({
  as: Element = "section",
  ariaLabel,
  "aria-label": nativeAriaLabel,
  className,
  children,
  "data-vui": dataVui = "surface",
  elevation = "flat",
  padding = "compact",
  tone = "panel",
  ...props
}: VSurfaceProps) {
  return (
    <Element
      {...props}
      data-vui={dataVui}
      data-tone={tone}
      data-elevation={elevation}
      aria-label={ariaLabel ?? nativeAriaLabel}
      className={[
        "min-w-0 rounded-[var(--vui-radius-panel-soft)] border border-vui-border-subtle",
        toneClass[tone],
        elevationClass[elevation],
        paddingClass[padding],
        className,
      ].filter(Boolean).join(" ")}
    >
      {children}
    </Element>
  );
}
```

- [ ] **Step 4: Implement Tooltip-backed VIconButton**

Replace `VIconButton.tsx` with:

```tsx
import { type ReactNode } from "react";

import { VButton, type VButtonProps } from "./VButton";
import { VTooltip } from "./VTooltip";

export type VIconButtonProps = Omit<
  VButtonProps,
  "children" | "icon" | "isIconOnly" | "aria-label"
> & {
  label: string;
  icon: ReactNode;
  title?: string;
  tooltip?: ReactNode;
};

export function VIconButton({ label, icon, title, tooltip, ...props }: VIconButtonProps) {
  return (
    <VTooltip content={tooltip ?? label}>
      <VButton
        {...props}
        data-vui="icon-button"
        isIconOnly
        aria-label={label}
        title={title ?? label}
        className={[
          "h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] min-w-[var(--vui-control-height-sm)] aspect-square flex-none shrink-0 px-0",
          props.className,
        ].filter(Boolean).join(" ")}
      >
        {icon}
      </VButton>
    </VTooltip>
  );
}
```

Export the new public types from `index.ts`:

```ts
export {
  VSurface,
  type VSurfaceElevation,
  type VSurfaceProps,
  type VSurfaceTone,
} from "./primitives/VSurface";
```

- [ ] **Step 5: Run primitive, layout-template, and boundary tests**

Run: `npm --prefix web run test -- vuiPrimitives.test.tsx vuiThemeFoundation.test.tsx vuiLayoutTemplates.test.tsx vuiImportBoundary.test.ts`

Expected: PASS; existing buttons keep their geometry, all icon buttons render through VTooltip, and routes still have no direct HeroUI imports.

- [ ] **Step 6: Commit the VUI primitive contract**

```powershell
git add -- web/src/components/vui/index.ts web/src/components/vui/primitives/VSurface.tsx web/src/components/vui/primitives/VIconButton.tsx web/src/components/vui/vuiPrimitives.test.tsx web/src/components/vui/vuiThemeFoundation.test.tsx
git commit -m "feat(web): extend VUI surface and icon tooltip contracts"
```

---

### Task 4: Unify AppShell Into Three Stable Desktop Groups

**Files:**
- Modify: `web/src/app/AppShell.layout.test.ts:20-130,177-215`
- Modify: `web/src/app/AppShell.tsx:2116-2385`
- Modify: `web/src/app/AppShell.styles.ts:42-51,112-119,222-267`
- Modify: `web/src/design/workbench-shell.css:125-289,1237-1296`

**Interfaces:**
- Consumes: Task 2 soft-layer variables and Task 3 VIconButton Tooltip behavior.
- Produces: stable group markers `brand`, `navigation`, `system-actions`; one soft primary navigation group; one compact system-action group; 1280 desktop fit contract.

- [ ] **Step 1: Write failing AppShell grouping and geometry assertions**

Add this focused contract to `AppShell.layout.test.ts`:

```ts
it("exposes three stable desktop top-bar groups with shared soft-layer geometry", () => {
  expect(shellSource).toContain('data-shell-group="brand"');
  expect(shellSource).toContain('data-shell-group="navigation"');
  expect(shellSource).toContain('data-shell-group="system-actions"');
  expect(styles.nav).toContain("rounded-[var(--vui-radius-panel-soft)]");
  expect(styles.nav).toContain("bg-[var(--vui-surface-toolbar)]");
  expect(styles.nav).toContain("shadow-[var(--vui-elevation-panel)]");
  expect(styles.topActions).toContain("rounded-[var(--vui-radius-panel-soft)]");
  expect(styles.topActions).toContain("bg-[var(--vui-surface-toolbar)]");
  expect(styles.actionIconButton).toContain("h-[var(--vui-control-height-sm)]");
  expect(styles.actionIconButton).toContain("w-[var(--vui-control-height-sm)]");
  expect(shellStyles).toContain("@media (max-width: 1279px)");
});
```

Update the compact-desktop slice to begin at `@media (max-width: 1279px)` and end at the existing `@media (max-width: 1180px)` block.

- [ ] **Step 2: Run the AppShell test and verify the grouping contract fails**

Run: `npm --prefix web run test -- AppShell.layout.test.ts`

Expected: FAIL because group markers and soft-layer group classes are absent and the compact desktop block still begins at 1420px.

- [ ] **Step 3: Add semantic group markers without changing navigation behavior**

Change only the opening elements in `AppShell.tsx`:

```tsx
<div className={styles.brandBlock} data-shell-group="brand">
```

```tsx
<nav className={styles.nav} data-shell-group="navigation">
```

```tsx
<div className={styles.topActions} data-shell-group="system-actions">
```

Keep every existing link, menu, status query, lifecycle guard, handler, and route unchanged. Pass explicit Tooltip copy to the four utility icon buttons while preserving their current accessible labels:

```tsx
tooltip={themeToggleLabel}
tooltip={refreshFrontendLabel}
tooltip={hideTopBarLabel}
tooltip={lifecycleMenuLabel}
```

- [ ] **Step 4: Apply the shared geometry through typed style slots**

Use these exact typed style values:

```ts
nav:
  "vui-app-appshell nav min-w-0 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-toolbar)] p-[3px] shadow-[var(--vui-elevation-panel)]",
topActions:
  "vui-app-appshell topActions min-w-0 flex flex-nowrap items-center gap-1 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-toolbar)] p-1 shadow-[var(--vui-elevation-panel)]",
actionIconButton:
  "vui-app-appshell actionIconButton h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] min-w-[var(--vui-control-height-sm)]",
```

In `workbench-shell.css`, remove the duplicated border/background/padding declarations from `.nav` so the typed slot is authoritative, and keep only layout/overflow behavior:

```css
:where(.vui-app-appshell).nav {
  display: flex;
  justify-self: center;
  flex-wrap: nowrap;
  gap: 3px;
  max-width: 100%;
  overflow-x: auto;
  overscroll-behavior-x: contain;
  scrollbar-width: none;
}
```

Replace the 1420 compact-label block with:

```css
@media (max-width: 1279px) {
  :where(.vui-app-appshell).brandSubtle,
  :where(.vui-app-appshell).topClock span:last-child,
  :where(.vui-app-appshell).utilityTriggerLabel,
  :where(.vui-app-appshell).statusBadgeLabel {
    display: none;
  }

  :where(.vui-app-appshell).topBar {
    gap: 8px;
    padding-inline: 12px;
  }
}
```

Leave the existing sub-980 and sub-640 compatibility code untouched; it is not part of the desktop acceptance gate and must not be expanded.

- [ ] **Step 5: Run AppShell and VUI regression tests**

Run: `npm --prefix web run test -- AppShell.layout.test.ts vuiPrimitives.test.tsx vuiThemeFoundation.test.tsx`

Expected: PASS; navigation and system actions are visually grouped, icon buttons retain square geometry and Tooltip access, and lifecycle behavior assertions remain unchanged.

- [ ] **Step 6: Commit AppShell unification**

```powershell
git add -- web/src/app/AppShell.tsx web/src/app/AppShell.styles.ts web/src/app/AppShell.layout.test.ts web/src/design/workbench-shell.css
git commit -m "style(web): unify AppShell desktop action groups"
```

---

### Task 5: Change Chat Compact Desktop Mode To Status-Only Auto-Collapse

**Files:**
- Modify: `web/src/routes/ChatCodingRoute.layout.test.ts:457-525,664-712`
- Modify: `web/src/routes/ChatCodingRoute.tsx:1177-1188,1770-1778,3790-3812,6252-6258`
- Modify: `web/src/routes/ChatCodingRoute.styles.ts:485-489`

**Interfaces:**
- Consumes: existing `leftRailCollapsed`, `rightPaneCollapsed`, `PaneCollapseHandle`, persisted panel widths, and resize helpers.
- Produces: `CHAT_COMPACT_DESKTOP_MEDIA_QUERY = "(max-width: 1279px)"`, `compactDesktopLayout`, and status-only automatic collapse.

- [ ] **Step 1: Replace the old center-first assertions with failing compact-desktop behavior assertions**

Replace the current narrow-screen test with:

```ts
it("uses compact desktop mode below 1280px and auto-collapses only the status rail", () => {
  expect(routeSource).toContain('const CHAT_COMPACT_DESKTOP_MEDIA_QUERY = "(max-width: 1279px)";');
  expect(routeSource).toContain("compactDesktopLayout");
  expect(routeSource).toContain("compactDesktopAutoCollapseRef");
  expect(routeSource).toContain("window.matchMedia(CHAT_COMPACT_DESKTOP_MEDIA_QUERY)");
  expect(routeSource).toContain("setRightPaneCollapsed(true)");
  expect(routeSource).not.toContain("setLeftRailCollapsed(true)");
  expect(routeSource).toContain("styles.layoutCompactDesktop");
  expect(routeStyles.layoutCompactDesktop).toContain("minmax(520px,1fr)");
  expect(routeStyles.layoutCompactDesktop).toContain("var(--chat-left-pane-width,300px)");
  expect(routeStyles.layoutCompactDesktop).toContain("var(--chat-right-pane-width,0px)");
});
```

Update the focused-conversation expectation from `max-[980px]:w-full` to `max-[1279px]:w-full` only if that style is touched in this task.

- [ ] **Step 2: Run the Chat layout test and verify the old 980px dual-collapse behavior fails**

Run: `npm --prefix web run test -- ChatCodingRoute.layout.test.ts`

Expected: FAIL because the code still uses `CHAT_CENTER_FIRST_MEDIA_QUERY`, 980px, and collapses both rails.

- [ ] **Step 3: Rename the local compact-layout state and preserve user controls**

Use these exact declarations:

```ts
const CHAT_COMPACT_DESKTOP_MEDIA_QUERY = "(max-width: 1279px)";
```

```ts
const [compactDesktopLayout, setCompactDesktopLayout] = useState(false);
const compactDesktopAutoCollapseRef = useRef(false);
```

Replace the media effect with:

```ts
useEffect(() => {
  if (typeof window === "undefined") {
    return;
  }
  const mediaQuery = window.matchMedia(CHAT_COMPACT_DESKTOP_MEDIA_QUERY);
  function applyCompactDesktopState(matches: boolean) {
    setCompactDesktopLayout(matches);
    if (matches && !compactDesktopAutoCollapseRef.current) {
      compactDesktopAutoCollapseRef.current = true;
      setRightPaneCollapsed(true);
    }
    if (!matches) {
      compactDesktopAutoCollapseRef.current = false;
    }
  }
  applyCompactDesktopState(mediaQuery.matches);
  const handleChange = (event: MediaQueryListEvent) => {
    applyCompactDesktopState(event.matches);
  };
  mediaQuery.addEventListener("change", handleChange);
  return () => mediaQuery.removeEventListener("change", handleChange);
}, []);
```

Do not change either `PaneCollapseHandle`; the right handle remains the explicit reopen path. Change the layout class selection to:

```tsx
className={compactDesktopLayout ? `${styles.layout} ${styles.layoutCompactDesktop}` : styles.layout}
```

- [ ] **Step 4: Rename and narrow the typed layout style**

Replace `layoutCenterFirst` with:

```ts
layoutCompactDesktop:
  "vui-routes-chatcodingroute layoutCompactDesktop min-w-0 !gap-0 !p-0 !grid-cols-[var(--chat-left-pane-width,300px)_var(--chat-pane-gutter)_minmax(520px,1fr)_var(--chat-pane-gutter)_minmax(0,var(--chat-right-pane-width,0px))] max-[980px]:!grid-cols-[minmax(260px,var(--chat-left-pane-width,300px))_var(--chat-pane-gutter)_minmax(420px,1fr)_var(--chat-pane-gutter)_minmax(0,var(--chat-right-pane-width,0px))]",
```

This compatibility floor must not auto-collapse the conversation index or add a drawer.

- [ ] **Step 5: Run focused layout, resize, and store tests**

Run: `npm --prefix web run test -- ChatCodingRoute.layout.test.ts chatCodingRouteViewModel.test.ts shellStore.test.ts`

Expected: PASS; 1279px and below collapses only the status rail, manual handles and persisted widths remain covered, and 1280px retains all columns.

- [ ] **Step 6: Commit compact desktop behavior**

```powershell
git add -- web/src/routes/ChatCodingRoute.tsx web/src/routes/ChatCodingRoute.styles.ts web/src/routes/ChatCodingRoute.layout.test.ts
git commit -m "fix(web): preserve Chat index in compact desktop mode"
```

---

### Task 6: Turn The Chat Status Rail Into One Soft Surface With Flat Groups

**Files:**
- Modify: `web/src/routes/ChatCodingLeftStatus.layout.test.ts:1-60`
- Modify: `web/src/routes/ChatCodingRoute.layout.test.ts:714-805,1105-1135`
- Modify: `web/src/routes/ChatCodingRoute.tsx:6473-6615`
- Modify: `web/src/routes/ChatCodingRoute.styles.ts:129-130,271-272,355-372,489-499,835-844,1049-1194`
- Modify: `web/src/routes/chat/TokenCoreStatusPanel.tsx:1-130`
- Modify: `web/src/routes/chat/LlmPayloadTracePanel.tsx:1-100`

**Interfaces:**
- Consumes: Task 3 `VTooltip`; existing token metrics, LLM trace data, mode toggles, session state, mental state, and pet actions.
- Produces: one raised right rail, separator-based flat groups, compact visible labels, hover/focus detail, unchanged critical states/actions.

- [ ] **Step 1: Write failing flat-rail and copy-reduction tests**

Replace the old per-card surface assertions with:

```ts
it("uses one raised status rail with flat separator-based groups", () => {
  expect(styles.leftRail).toContain("rounded-[var(--vui-radius-panel-soft)]");
  expect(styles.leftRail).toContain("bg-[var(--vui-surface-rail)]");
  expect(styles.leftRail).toContain("shadow-[var(--vui-elevation-panel)]");
  expect(styles.leftBlock).toContain("border-b");
  expect(styles.leftBlock).toContain("bg-transparent");
  expect(styles.leftBlock).toContain("shadow-none");
  expect(styles.leftBlock).not.toContain("rounded-[var(--radius-panel)]");
  expect(styles.leftBlock).not.toContain("!bg-[var(--vui-surface-rail)]");
});
```

Add these source assertions to `ChatCodingRoute.layout.test.ts`:

```ts
expect(tokenCoreStatusPanelSource).toContain("VTooltip");
expect(tokenCoreStatusPanelSource).not.toContain('<p className={styles.blockEyebrow}>Token</p>');
expect(llmPayloadTracePanelSource).toContain("VTooltip");
expect(llmPayloadTracePanelSource).not.toContain('<p className={styles.blockEyebrow}>LLM</p>');
expect(routeSource).not.toContain('<p className={styles.blockEyebrow}>{lang === "zh" ? "模式控制" : "Mode controls"}</p>');
expect(routeSource).not.toContain('<p className={styles.sectionMetaLine}>{mentalCompactLine || mentalSourceLabel}</p>');
expect(routeSource).toContain("groupManagementHint");
expect(routeSource).toContain("sessionBindingNotice");
```

- [ ] **Step 2: Run the status layout tests and verify the card-wall contract fails**

Run: `npm --prefix web run test -- ChatCodingLeftStatus.layout.test.ts ChatCodingRoute.layout.test.ts`

Expected: FAIL because every `leftBlock` still owns a border/background and the four duplicate eyebrow/meta lines remain visible.

- [ ] **Step 3: Move elevation to the rail and flatten internal sections**

Use these exact style contracts:

```ts
leftRail:
  "vui-routes-chatcodingroute leftRail min-w-0 !flex h-full min-h-0 !flex-col overflow-auto rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-rail)] p-1 shadow-[var(--vui-elevation-panel)] [scrollbar-gutter:stable] [grid-column:5] [grid-row:1]",
leftBlock:
  "vui-routes-chatcodingroute leftBlock grid min-w-0 shrink-0 gap-1.5 border-0 border-b border-[var(--vui-border-subtle)] bg-transparent p-2 shadow-none last:border-b-0",
blockEyebrow:
  "vui-routes-chatcodingroute blockEyebrow min-w-0 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-tertiary)]",
```

Keep independent selected/tone backgrounds on metric cells, mode controls, active skill, and blocker notices. Do not flatten destructive or error emphasis.

- [ ] **Step 4: Move token metric detail into VTooltip**

Import `VTooltip` with `VButton`. Replace the duplicate eyebrow/title header with:

```tsx
<div className={styles.sectionHeader}>
  <h3 id={titleId} className={styles.sectionTitle}>Token</h3>
</div>
```

For each metric, wrap the interactive or focusable item in the same VTooltip contract:

```tsx
const metricItem = metric.key === "cache" ? (
  <VButton
    type="button"
    className={styles.tokenStatusMetricButton}
    isDisabled={!cacheDetailAvailable}
    onClick={cacheDetailAvailable ? onOpenCacheDetail : undefined}
    aria-disabled={!cacheDetailAvailable}
    aria-label={cacheDetailOpenLabel}
    aria-expanded={cacheDetailAvailable ? cacheDetailOpen : undefined}
    aria-controls={cacheDetailAvailable ? "cache-detail-dialog" : undefined}
  >
    {metricContent}
  </VButton>
) : (
  <div
    className={metricClassName}
    style={metricStyle}
    tabIndex={0}
    aria-label={`${metric.label} ${metric.value}. ${metric.meta}`}
    role="listitem"
  >
    {metricContent}
  </div>
);

return (
  <VTooltip key={metric.key} content={metric.title}>
    {metricItem}
  </VTooltip>
);
```

For the cache branch, move `metricClassName`, `metricStyle`, and `role="listitem"` onto a single wrapper around the Tooltip so the list semantics remain valid; do not duplicate the class on the button.

- [ ] **Step 5: Compress LLM, mode, and companion headers while retaining accessible detail**

Import `VTooltip` in `LlmPayloadTracePanel.tsx`. Replace its header with:

```tsx
<div className={styles.sectionHeader}>
  <h3 className={styles.sectionTitle}>{title}</h3>
  {subtitle ? (
    <VTooltip content={subtitle}>
      <span className={styles.llmPayloadTraceHelp} tabIndex={0} aria-label={subtitle}>i</span>
    </VTooltip>
  ) : null}
</div>
```

Add the typed style:

```ts
llmPayloadTraceHelp:
  "vui-routes-chatcodingroute llmPayloadTraceHelp grid h-5 w-5 place-items-center rounded-full border border-[var(--vui-border-subtle)] text-[var(--vui-font-xs)] font-semibold text-[var(--fg-tertiary)]",
```

In `ChatCodingRoute.tsx`, render one title for mode controls:

```tsx
<div className={styles.sectionHeader}>
  <h3 className={styles.sectionTitle}>{lang === "zh" ? "运行模式" : "Run modes"}</h3>
  <span className={styles.featurePresetScope} title={t("chatFeaturePanelHint")}>
    {lang === "zh" ? "下轮生效" : "Next turn"}
  </span>
</div>
```

Render one companion title and move the changing source/detail into a focusable Tooltip on the status badge:

```tsx
<div className={styles.sectionHeader}>
  <h3 className={styles.sectionTitle}>{t("mentalState")} / {t("petSpace")}</h3>
  <VTooltip content={mentalCompactLine || mentalSourceLabel}>
    <span
      className={`${styles.mentalStateBadge} ${styles[`mentalStateBadge_${mentalCognitiveStateValue}`]}`}
      tabIndex={0}
    >
      {mentalStateLabel}
    </span>
  </VTooltip>
</div>
```

Add `VTooltip` to the existing VUI import in `ChatCodingRoute.tsx`. Keep `sessionBindingNotice`, group ownership guidance, running locks, minimum-member blockers, error text, and destructive consequences directly visible.

- [ ] **Step 6: Run the status, primitive, and boundary tests**

Run: `npm --prefix web run test -- ChatCodingLeftStatus.layout.test.ts ChatCodingRoute.layout.test.ts vuiPrimitives.test.tsx vuiImportBoundary.test.ts`

Expected: PASS; the rail owns the soft surface, internal groups are flat, duplicate prose is removed, Tooltip triggers are present, and critical information remains inline.

- [ ] **Step 7: Commit the status-rail unification**

```powershell
git add -- web/src/routes/ChatCodingRoute.tsx web/src/routes/ChatCodingRoute.styles.ts web/src/routes/ChatCodingRoute.layout.test.ts web/src/routes/ChatCodingLeftStatus.layout.test.ts web/src/routes/chat/TokenCoreStatusPanel.tsx web/src/routes/chat/LlmPayloadTracePanel.tsx
git commit -m "style(web): flatten Chat status rail hierarchy"
```

---

### Task 7: Unify The Conversation Index And Center Workspace States

**Files:**
- Modify: `web/src/routes/ChatCodingRoute.layout.test.ts:170-205,2021-2050,2525-2585`
- Modify: `web/src/routes/ChatCodingRoute.tsx:84,6158-6249,7350-7440`
- Modify: `web/src/routes/ChatCodingRoute.styles.ts:239-240,630-646,823-846`
- Modify: `web/src/routes/chat/ChatSessionWorkspacePanel.tsx:1-130`
- Modify: `web/src/routes/chat/ChatSessionWorkspacePanel.styles.ts:1-30`

**Interfaces:**
- Consumes: existing `VStateSurface`, Task 2 soft-layer variables, current query error classification, and current session-index actions.
- Produces: one raised conversation-index surface; shared loading/empty/error/unavailable center states; stable, content-sized index actions.

- [ ] **Step 1: Write failing shared-state and outer-surface tests**

Replace the raw `<div>` expectations with:

```ts
it("uses VStateSurface for center loading, empty, error, and unavailable states", () => {
  expect(chatSessionWorkspacePanelSource).toContain('import { VStateSurface } from "../../components/vui"');
  expect(chatSessionWorkspacePanelSource).toContain('tone="loading"');
  expect(chatSessionWorkspacePanelSource).toContain('tone="empty"');
  expect(chatSessionWorkspacePanelSource).toContain('tone="error"');
  expect(chatSessionWorkspacePanelSource).toContain('tone="unavailable"');
  expect(chatSessionWorkspacePanelSource).not.toContain("<div className={styles.emptyConversationSurface}");
  expect(chatSessionWorkspacePanelSource).not.toContain("<div className={styles.emptySurface}");
});
```

Add the index surface contract:

```ts
it("renders the conversation index as one soft panel with flat rows and compact actions", () => {
  expect(routeStyles.rightPane).toContain("rounded-[var(--vui-radius-panel-soft)]");
  expect(routeStyles.rightPane).toContain("bg-[var(--vui-surface-rail)]");
  expect(routeStyles.rightPane).toContain("shadow-[var(--vui-elevation-panel)]");
  expect(routeStyles.sessionActionRow).toContain("flex-wrap");
  expect(routeStyles.newSessionButton).toContain("!w-auto");
  expect(routeStyles.panelSearchInput).toContain("w-full");
  expect(directSessionIndexItemStyles.sessionItem).not.toContain("shadow-[var(--vui-elevation-panel)]");
});
```

- [ ] **Step 2: Run Chat layout tests and verify the raw state surfaces fail**

Run: `npm --prefix web run test -- ChatCodingRoute.layout.test.ts vuiLayoutTemplates.test.tsx`

Expected: FAIL because center states still use route-local div surfaces and the index rail has no outer soft surface.

- [ ] **Step 3: Replace center route-local state wrappers with VStateSurface**

Import `VStateSurface` and implement the fallback/branches exactly as follows:

```tsx
const conversationLoadingFallback = (
  <VStateSurface
    className={styles.loadingSurface}
    tone="loading"
    title={loadingSessionLabel}
    skeletonLines={2}
    role="status"
    aria-live="polite"
  />
);

if (!activeSessionId && !sessionsPending) {
  return <VStateSurface className={styles.emptyConversationSurface} tone="empty" title={noSessionsLabel} />;
}

if (hasBlockingError) {
  return <VStateSurface className={styles.emptySurface} tone="error" title={blockingErrorMessage} />;
}

if (invalidChildSessionLinkMessage) {
  return (
    <VStateSurface
      className={styles.emptySurface}
      tone="unavailable"
      title={invalidChildSessionLinkMessage}
    />
  );
}
```

Use `tone="empty"` for the unavailable CLI-run content branch. Keep transient errors as directly visible `role="status"` notices above trustworthy conversation content.

Reduce the route-specific styles to geometry only:

```ts
emptyConversationSurface:
  "vui-routes-chatsessionworkspacepanel emptyConversationSurface min-h-[74px] w-[min(360px,calc(100%_-_32px))] place-self-center text-center",
emptySurface:
  "vui-routes-chatsessionworkspacepanel emptySurface h-full min-h-[min(420px,calc(100dvh_-_190px))] place-self-stretch place-items-center text-center",
loadingSurface:
  "vui-routes-chatsessionworkspacepanel loadingSurface min-h-[120px]",
```

Delete `loadingSurfaceBody`, `loadingSkeletonLine`, and `loadingSkeletonLineShort` from the typed map after their JSX is removed.

- [ ] **Step 4: Use VStateSurface for index loading/empty/blocking rows**

Add `VStateSurface` to the existing VUI import in `ChatCodingRoute.tsx`. Keep the surrounding ternary and the existing `ConversationIndexTree`, load-more, and context-menu fragment unchanged. Replace the five current state elements with these exact elements:

```tsx
<VStateSurface
  className={styles.panelState}
  tone="error"
  title={sessionComposerErrors.__sessions__}
/>
```

```tsx
<div className={styles.panelNotice} role="status">
  {sessionsErrorMessage}
</div>
```

```tsx
<VStateSurface className={styles.panelState} tone="error" title={sessionsErrorMessage} />
```

```tsx
<VStateSurface
  className={styles.panelState}
  tone="loading"
  title={t("loadingSession")}
  skeletonLines={2}
/>
```

```tsx
<VStateSurface
  className={styles.panelState}
  tone="empty"
  title={sessionFilter.trim() ? t("noSessionMatches") : t("noSessionsYet")}
/>
```

The second element is intentionally unchanged because a transient error must remain visible beside trustworthy cached index content. Do not move data fetching, mutations, cache updates, or context-menu state.

- [ ] **Step 5: Give the index rail one surface and preserve content-sized actions**

Use these exact style contracts:

```ts
rightPane:
  "vui-routes-chatcodingroute rightPane min-w-0 grid h-full min-h-0 gap-[var(--chat-workbench-gap)] overflow-hidden rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-rail)] p-[var(--chat-workbench-gap)] shadow-[var(--vui-elevation-panel)] [grid-column:1] [grid-row:1]",
panelState:
  "vui-routes-chatcodingroute panelState min-h-[72px] place-items-center text-center",
sessionActionRow:
  "vui-routes-chatcodingroute sessionActionRow flex min-w-0 flex-wrap items-center justify-start gap-1.5 border-0 bg-transparent p-0",
```

Keep `newSessionButton` as `!w-auto`, `panelSearchInput` as `w-full`, the search row separate from actions, and all session rows flat with selected/hover state only.

- [ ] **Step 6: Run center/index, cache, and conversation behavior tests**

Run: `npm --prefix web run test -- ChatCodingRoute.layout.test.ts vuiLayoutTemplates.test.tsx chatSessionState.test.ts chatWorkspaceCache.test.ts ConversationView.test.tsx`

Expected: PASS; shared state surfaces render, session list/detail/cache behavior remains unchanged, action geometry is stable, and no new route-level HeroUI import exists.

- [ ] **Step 7: Commit center and index unification**

```powershell
git add -- web/src/routes/ChatCodingRoute.tsx web/src/routes/ChatCodingRoute.styles.ts web/src/routes/ChatCodingRoute.layout.test.ts web/src/routes/chat/ChatSessionWorkspacePanel.tsx web/src/routes/chat/ChatSessionWorkspacePanel.styles.ts
git commit -m "style(web): unify Chat index and workspace states"
```

---

### Task 8: Run Full Phase 1 Evidence, Integrate Locally, Refresh, And Close Memory

**Files:**
- Modify after successful validation: `docs/superpowers/specs/2026-07-10-heroui-frontend-unification-design.md`
- Modify after successful validation: `docs/superpowers/plans/2026-07-10-heroui-frontend-unification-phase-1.md`
- Regenerate only after local-main integration and an acquired memory claim: `.docs/project-memory/**`, `PROJECT_MEMORY.html`
- Produce evidence outside Git when screenshots are not intentionally retained: browser screenshots/observation notes for `/chat` and AppShell at the three desktop viewports

**Interfaces:**
- Consumes: Tasks 1–7 commits and the existing Launcher/project-memory guard paths.
- Produces: fresh test/build/diff evidence, three-size light/dark visual evidence, local-main integration decision, Launcher refresh result, memory update or exact proposal, and Phase 1 completion status.

- [ ] **Step 1: Run the complete focused Phase 1 suite**

Run:

```powershell
npm --prefix web run test -- workbenchVisualMatrix.test.ts vuiImportBoundary.test.ts vuiPrimitives.test.tsx vuiThemeFoundation.test.tsx vuiLayoutTemplates.test.tsx AppShell.layout.test.ts ChatCodingLeftStatus.layout.test.ts ChatCodingRoute.layout.test.ts chatCodingRouteViewModel.test.ts shellStore.test.ts chatSessionState.test.ts chatWorkspaceCache.test.ts ConversationView.test.tsx
```

Expected: PASS with zero failed tests. All named test files exist in the approved worktree; do not silently omit any coverage area.

- [ ] **Step 2: Run production build and scoped Git checks**

Run:

```powershell
npm --prefix web run build
git diff --check main...HEAD
git status --short --branch
git diff --stat main...HEAD
git log --oneline main..HEAD
```

Expected: build exits 0; diff check is empty; only Phase 1 files appear; the task branch contains the design/plan commit plus the seven scoped implementation commits.

- [ ] **Step 3: Self-review the implementation boundaries before integration**

Run:

```powershell
rg -n 'from "@heroui/react"|from ''@heroui/react''' web/src/routes web/src/app
git diff main...HEAD -- web/src/routes/ChatCodingRoute.tsx web/src/app/AppShell.tsx
```

Expected: no new direct HeroUI import appears in routes/AppShell; the diff changes layout/copy/composition only and does not modify API URLs, query keys, DTOs, mutation semantics, caches, message protocols, lifecycle guards, or route paths.

- [ ] **Step 4: Integrate into local main only if the root gate is safe**

From `C:\Users\17533\Desktop\Vibelution`, run:

```powershell
git branch --show-current
git status --short --branch
git diff --name-only
git merge --no-ff codex/heroui-frontend-unification
```

Expected before merge: branch is `main`; existing dirty files are reviewed as unrelated to Phase 1; Git reports no overlap. Expected after merge: local merge succeeds without touching or staging unrelated user/Agent changes. If overlap or semantic conflict exists, stop before merge and report the exact files; do not reset, stash, overwrite, or auto-resolve unrelated work.

- [ ] **Step 5: Use Launcher refresh and collect desktop browser evidence**

First inspect Launcher/active-work state through the project-native Launcher path. If active work blocks refresh, report exactly:

```text
有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。
```

Do not force takeover without the exact user confirmation phrase `确认强制接管并刷新 Vibelution`.

After a safe Launcher refresh, inspect `/chat` and the AppShell in light and dark themes at:

```text
1280×720
1440×900
1920×1080
```

For each viewport verify: no page-level horizontal overflow; no clipped buttons; text buttons hug content; icon buttons are square and expose hover/focus Tooltip; session index remains left; conversation remains dominant; status rail remains right; only status rail auto-collapses below 1280; resize/reopen controls work; light/dark contrast is readable; long Chinese/English labels do not overlap; loading/empty/error/busy surfaces do not shift the workbench; browser console has no new errors.

Expected: all checks pass. Any visual failure returns to the owning task and repeats its focused tests, build, refresh, and screenshot check.

- [ ] **Step 6: Record completion status in the spec and plan**

After all evidence is fresh, change the spec metadata to:

```markdown
- **Status:** Phase 1 implemented and locally validated; later frontend phases remain planned separately
- **Validation:** focused Vitest suite passed; `npm --prefix web run build` passed; scoped diff review passed; desktop browser evidence passed at `1280×720`, `1440×900`, and `1920×1080` in light and dark themes
```

Add this plan status immediately below the header:

```markdown
> **Implementation status:** complete on 2026-07-10 after focused tests, production build, scoped diff review, Launcher refresh, and three-viewport light/dark browser verification.
```

Commit only those two documentation files on local main:

```powershell
git add -- docs/superpowers/specs/2026-07-10-heroui-frontend-unification-design.md docs/superpowers/plans/2026-07-10-heroui-frontend-unification-phase-1.md
git commit -m "docs(web): record HeroUI Phase 1 validation"
```

- [ ] **Step 7: Sync project memory through its owning script or provide the exact proposal**

From local main, first ensure the memory surfaces are clean, acquire a narrow memory claim, run the sync, stage only the newly generated files, commit them, and release the memory claim:

```powershell
$python = "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe"
$guard = "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py"
$sync = "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\sync_project_memory.py"
$project = "C:\Users\17533\Desktop\Vibelution"
$memoryBefore = @(git status --short -- .docs/project-memory PROJECT_MEMORY.html)
if ($memoryBefore.Count -gt 0) {
  throw "Project-memory surfaces already contain unrelated changes; provide the exact update proposal instead of syncing."
}
$memoryClaimJson = & $python $guard $project claim `
  --lane "web-workbench-surface" `
  --scope ".docs/project-memory" `
  --scope "PROJECT_MEMORY.html" `
  --agent "codex-heroui-frontend-unification" `
  --task "Sync HeroUI frontend Phase 1 memory · main" `
  --ttl-minutes 60 `
  --note "Run owning sync script after validated local-main integration" `
  --json
$memoryClaim = $memoryClaimJson | ConvertFrom-Json
if (-not $memoryClaim.ok -or -not $memoryClaim.claim.id) {
  throw "Unable to acquire the project-memory claim; provide the exact update proposal instead."
}
& $python $sync $project --lane "web-workbench-surface" --focus "HeroUI frontend unification Phase 1" --update "AppShell and Chat now use the shared restrained soft-layer desktop contract: content-sized controls, Tooltip-backed icon actions, raised primary rails with flat internal groups, concise operational copy, shared workspace states, and status-only compact-desktop auto-collapse. Focused Vitest, production build, scoped diff review, and 1280/1440/1920 light-dark browser checks passed."
if ($LASTEXITCODE -ne 0) {
  & $python $guard $project release --claim-id $memoryClaim.claim.id --status blocked --reason "HeroUI Phase 1 project-memory sync failed."
  throw "Project-memory sync failed."
}
$memoryFiles = @(git diff --name-only -- .docs/project-memory PROJECT_MEMORY.html)
if ($memoryFiles.Count -eq 0) {
  & $python $guard $project release --claim-id $memoryClaim.claim.id --status blocked --reason "Sync produced no project-memory diff."
  throw "Project-memory sync produced no diff."
}
git add -- $memoryFiles
git commit -m "docs(memory): record HeroUI Phase 1"
& $python $guard $project release --claim-id $memoryClaim.claim.id --status completed --reason "HeroUI Phase 1 project memory synced and committed."
```

Expected: sync and commit exit 0; only newly generated memory files are staged; the lane and generated views contain the exact focus/update text; the memory claim is completed. If the initial clean-state or claim gate fails, do not hand-edit memory and report the exact `--focus` and `--update` values above as the proposal.

- [ ] **Step 8: Release the implementation claim and report the closure decisions**

Resolve the single active implementation claim by its exact agent and task identity, then release it:

```powershell
$python = "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe"
$guard = "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py"
$project = "C:\Users\17533\Desktop\Vibelution"
$status = (& $python $guard $project status --json | ConvertFrom-Json)
$matchingClaims = @(
  $status.claims | Where-Object {
    $_.agent -eq "codex-heroui-frontend-unification" -and
    $_.task -eq "Implement HeroUI frontend Phase 1 · codex/heroui-frontend-unification" -and
    $_.status -eq "active"
  }
)
if ($matchingClaims.Count -ne 1) {
  throw "Expected exactly one active HeroUI Phase 1 implementation claim."
}
& $python $guard $project release --claim-id $matchingClaims[0].id --status completed --reason "HeroUI Phase 1 focused tests, build, scoped diff review, desktop browser evidence, local-main integration, Launcher decision, and memory handoff completed."
```

Expected: the implementation claim becomes completed. Final report must state: requirement coverage, test/build counts, browser viewports/themes, Launcher refresh result, project-memory status, local-main commit(s), no remote push/PR, version impact `patch`, and any residual risk.

---

## Plan Review Gate

### Spec Coverage

- Desktop-only viewport contract: Task 1 and Task 8.
- Shared soft surfaces, radii, elevation, light/dark parity: Tasks 2–3.
- VUI/HeroUI ownership and icon Tooltip accessibility: Task 3, enforced again in Task 8.
- AppShell three-group hierarchy and content-sized utilities: Task 4.
- Stable three-column Chat and status-only compact desktop collapse: Task 5.
- Flat status groups, reduced explanatory copy, visible critical blockers: Task 6.
- Conversation index, action layout, loading/empty/error/unavailable consistency: Task 7.
- Build, screenshots, console, Launcher, memory, version, and integration decisions: Task 8.
- API/DTO/query/cache/business behavior non-goals: protected by task boundaries and Task 8 diff review.

### Review Matrix

| Challenge | Evidence | Gate conclusion |
| --- | --- | --- |
| Shared tokens could restyle unrelated routes | Task 2 adds aliases and explicitly does not remap legacy `--radius-panel`; only Phase 1 consumers opt in | PASS |
| Compact mode could hide the wrong rail | Current source maps `rightPaneCollapsed` to the status rail and `leftRailCollapsed` to the conversation index; Task 5 asserts only `setRightPaneCollapsed(true)` | PASS |
| Copy reduction could hide operational blockers | Task 6 removes only duplicate eyebrow/meta copy and explicitly preserves group locks, binding mismatch, errors, permissions, and destructive consequences | PASS |
| VIconButton Tooltip could leak HeroUI into routes | Task 3 implements Tooltip inside VUI and Task 8 scans routes/AppShell for direct HeroUI imports | PASS |
| Large `ChatCodingRoute.tsx` could invite behavior drift | Tasks 5–7 name narrow line regions, preserve stores/queries/mutations, and run existing route/cache/state tests | PASS |
| Desktop-only direction could delete compatibility code | Tasks 4–5 leave existing sub-desktop compatibility code in place unless directly required; no mobile drawer or touch path is added | PASS |

### Placeholder And Type Consistency Check

- All implementation tasks name exact files, interfaces, failing commands, expected failures, minimal code, passing commands, and scoped commits.
- `VSurfaceTone`, `VSurfaceElevation`, `VSurfaceProps`, and `VIconButtonProps.tooltip` use the same names in Tasks 2–7.
- Compact viewport names are consistently `compact`, `standard`, and `wide`; the runtime media query is consistently `CHAT_COMPACT_DESKTOP_MEDIA_QUERY` at `1279px`.
- No dependency, API, DTO, query-key, route, cache-key, or backend change is required by this plan.

## Execution Handoff

Plan implementation must begin only after choosing one route:

1. **Subagent-Driven (recommended):** dispatch one fresh implementation worker per task, then perform requirement and code-quality review between tasks.
2. **Inline Execution:** execute this plan in the current task with `executing-plans`, using task-level checkpoints and the same test/commit gates.
