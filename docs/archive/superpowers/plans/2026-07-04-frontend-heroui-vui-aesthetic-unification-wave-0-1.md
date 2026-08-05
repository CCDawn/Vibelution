# Frontend HeroUI/VUI Aesthetic Unification Wave 0-1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the verification baseline and first Workbench-mainline aesthetic pass for the phased full-site HeroUI/VUI visual unification.

**Architecture:** Keep the existing layered architecture: `routes -> product components / route composition -> VUI primitives -> HeroUI renderer -> design tokens`. Wave 0 creates visual-regression and boundary evidence; Wave 1 adds reusable VUI aesthetic primitives and applies them to the most visible Workbench shell/route style-map anti-patterns without changing route data flow or behavior.

**Tech Stack:** React 19, TypeScript 5.9, Vite 8, Tailwind CSS 4, Vitest 3, HeroUI 3.2 behind local VUI primitives.

> Takeover status (2026-07-05): Wave 0-1 implementation validated in the current takeover. Original task boxes are retained as planning history; closure evidence is the test, build, and browser validation report in the handoff.

## Global Constraints

- HeroUI remains behind the VUI layer; routes must not import `@heroui/react` directly.
- Route code may own business layout, grid, column widths, responsive breakpoints, canvas dimensions, and state-specific composition.
- Route code must not redefine generic button families, card/panel shadows, full-page opaque wrappers, thick status borders, or broad visual grammar.
- Aesthetic direction is light-first, quiet operational glass, dense but readable, background-aware, 1px thin-line, compact pale controls, and operational clarity over decoration.
- Do not turn the product into a dark cyber dashboard, marketing hero page, or heavy SaaS admin surface.
- Do not change backend/API behavior, route data models, or business state machines.
- Do not mechanically convert stable CSS Modules for purity.
- Do not remove or reduce the visibility of critical error, blocker, destructive, focus, or accessibility states.
- Verification must include visual evidence, not only build success.
- Use npm from `web/`: `npm run build`, `npm test -- <test-file>`, and focused Vitest commands.
- Do not commit unless the user explicitly asks for commits.

---

## File structure and responsibilities

### New files

- `web/src/visual-regression/workbenchVisualMatrix.ts`
  - Exports the route/theme/background/viewport matrix used for manual or automated visual review.
  - Owns typed scenario data only; it does not launch a browser.

- `web/src/visual-regression/workbenchVisualMatrix.test.ts`
  - Verifies the visual matrix covers Wave 0 requirements: light/dark, default/custom background, desktop/narrow, dense content, empty/error/blocker/destructive states, and Workbench mainline routes.

- `web/src/components/vui/aesthetic/VWorkbenchAesthetic.tsx`
  - Adds reusable, route-safe aesthetic composition primitives for Wave 1: `VEmbeddedPanel`, `VDenseToolbar`, `VDenseRow`, `VStateRow`, `VMetricChip`, and `VStatusChip`.
  - These primitives compose VUI/Tailwind/token classes only; they do not import HeroUI directly.

- `web/src/components/vui/aesthetic/index.ts`
  - Barrel exports the aesthetic primitives.

- `web/src/components/vui/vuiAestheticPrimitives.test.tsx`
  - Server-render tests for the new primitives and their data attributes, tones, quiet defaults, and critical state visibility.

- `web/src/routes/routeAestheticContract.test.ts`
  - Static style-map tests for Wave 1 anti-patterns: header/eyebrow chrome, card-like action buttons, repeated active tone classes, and route full-page opaque backgrounds in Workbench mainline files.

### Modified files

- `web/src/components/vui/index.ts`
  - Exports the new aesthetic primitives.

- `web/src/components/vui/vuiImportBoundary.test.ts`
  - Adds the new `components/vui/aesthetic/` root to the explicit VUI-owned visual utility allowlist if needed by the existing boundary checks. Because `components/vui/` is already allowed, this should remain a no-op but is listed for reviewer awareness.

- `web/src/app/AppShellStatusGuidePanel.styles.ts`
  - Removes card chrome from `statusGuideCardHeader`; keeps layout-only header classes.

- `web/src/app/AppShellUtilityMenu.styles.ts`
  - Removes card chrome from `utilityPanelHeader`; keeps layout-only header classes.

- `web/src/app/AppShell.styles.ts`
  - Mirrors the same AppShell sub-style cleanup when those keys are still present in the transitional aggregate map.
  - Removes repeated active tone triples from keys like `activeWorkChip`, `navLinkActive`, `utilityButtonActive`, and status active classes where repeated in one string.

- `web/src/routes/ChatCodingRoute.styles.ts`
  - Removes card chrome from cache detail headers and segment headers.
  - Keeps modal/dialog/panel wrappers intact.

- `web/src/routes/MemoryRoute.styles.ts`
  - Removes card chrome from `detailHeader`, `detailMeta`, `panelEyebrow`, `panelHeader`, `ragPreviewHeader`.
  - Removes panel chrome from button-like keys such as `detailActionButton` and `matrixCardButton` while preserving button geometry and state classes.

- Optional if visible in the same task batch after tests identify exact offenders: `web/src/routes/EvolutionRoute.styles.ts`, `web/src/routes/AgentsRoute.styles.ts`
  - Only make the exact header/action cleanup required to pass `routeAestheticContract.test.ts`; do not broaden the route rewrite.

---

### Task 1: Add the Wave 0 visual regression matrix

**Files:**
- Create: `web/src/visual-regression/workbenchVisualMatrix.ts`
- Create: `web/src/visual-regression/workbenchVisualMatrix.test.ts`

**Interfaces:**
- Produces:
  - `WorkbenchVisualTheme = "light" | "dark"`
  - `WorkbenchVisualBackground = "default" | "custom"`
  - `WorkbenchVisualViewport = "desktop" | "narrow"`
  - `WorkbenchVisualState = "dense" | "empty" | "error" | "blocker" | "destructive"`
  - `WorkbenchVisualScenario` object type
  - `WORKBENCH_VISUAL_SCENARIOS: WorkbenchVisualScenario[]`
  - `WORKBENCH_VISUAL_ACCEPTANCE_CHECKLIST: string[]`
  - `summarizeWorkbenchVisualCoverage(scenarios): { themes; backgrounds; viewports; states; paths }`
- Consumes: no implementation from other tasks.

- [ ] **Step 1: Write the failing matrix coverage test**

Create `web/src/visual-regression/workbenchVisualMatrix.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import {
  WORKBENCH_VISUAL_ACCEPTANCE_CHECKLIST,
  WORKBENCH_VISUAL_SCENARIOS,
  summarizeWorkbenchVisualCoverage,
} from "./workbenchVisualMatrix";

describe("Workbench visual regression matrix", () => {
  it("covers the Wave 0 theme, background, viewport, route, and state requirements", () => {
    const coverage = summarizeWorkbenchVisualCoverage(WORKBENCH_VISUAL_SCENARIOS);

    expect(coverage.themes).toEqual(["dark", "light"]);
    expect(coverage.backgrounds).toEqual(["custom", "default"]);
    expect(coverage.viewports).toEqual(["desktop", "narrow"]);
    expect(coverage.states).toEqual(["blocker", "dense", "destructive", "empty", "error"]);
    expect(coverage.paths).toEqual([
      "/",
      "/agents",
      "/chat",
      "/config",
      "/memory",
      "/memory/graph",
      "/supervised-evolution",
    ]);
  });

  it("keeps every scenario actionable for manual or automated screenshot capture", () => {
    expect(WORKBENCH_VISUAL_SCENARIOS).toHaveLength(12);

    for (const scenario of WORKBENCH_VISUAL_SCENARIOS) {
      expect(scenario.id).toMatch(/^[a-z0-9-]+$/);
      expect(scenario.path).toMatch(/^\//);
      expect(scenario.viewport.width).toBeGreaterThanOrEqual(390);
      expect(scenario.viewport.height).toBeGreaterThanOrEqual(720);
      expect(scenario.reviewFocus.length).toBeGreaterThanOrEqual(2);
      expect(scenario.expectedEvidence).toContain("screenshot");
    }
  });

  it("documents the quiet workbench visual acceptance checklist", () => {
    expect(WORKBENCH_VISUAL_ACCEPTANCE_CHECKLIST).toEqual([
      "background remains visible",
      "text remains readable",
      "1px thin-line borders",
      "quiet controls by default",
      "visible focus state",
      "clear destructive, error, and blocker states",
      "no card wall",
      "no full-page opaque route wrapper",
    ]);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run from repository root:

```bash
cd web && npm test -- src/visual-regression/workbenchVisualMatrix.test.ts
```

Expected: FAIL because `./workbenchVisualMatrix` does not exist.

- [ ] **Step 3: Implement the matrix**

Create `web/src/visual-regression/workbenchVisualMatrix.ts`:

```ts
export type WorkbenchVisualTheme = "light" | "dark";
export type WorkbenchVisualBackground = "default" | "custom";
export type WorkbenchVisualViewport = "desktop" | "narrow";
export type WorkbenchVisualState = "dense" | "empty" | "error" | "blocker" | "destructive";

export type WorkbenchVisualScenario = {
  id: string;
  path: string;
  theme: WorkbenchVisualTheme;
  background: WorkbenchVisualBackground;
  viewport: {
    width: number;
    height: number;
  };
  state: WorkbenchVisualState;
  reviewFocus: string[];
  expectedEvidence: "screenshot";
};

export const WORKBENCH_VISUAL_ACCEPTANCE_CHECKLIST = [
  "background remains visible",
  "text remains readable",
  "1px thin-line borders",
  "quiet controls by default",
  "visible focus state",
  "clear destructive, error, and blocker states",
  "no card wall",
  "no full-page opaque route wrapper",
] as const;

export const WORKBENCH_VISUAL_SCENARIOS: WorkbenchVisualScenario[] = [
  {
    id: "home-light-default-desktop-empty",
    path: "/",
    theme: "light",
    background: "default",
    viewport: { width: 1440, height: 960 },
    state: "empty",
    reviewFocus: ["AppShell background ownership", "route outlet empty/default state"],
    expectedEvidence: "screenshot",
  },
  {
    id: "chat-light-default-desktop-dense",
    path: "/chat",
    theme: "light",
    background: "default",
    viewport: { width: 1440, height: 960 },
    state: "dense",
    reviewFocus: ["conversation workspace hierarchy", "quiet toolbar and row density"],
    expectedEvidence: "screenshot",
  },
  {
    id: "chat-dark-default-desktop-dense",
    path: "/chat",
    theme: "dark",
    background: "default",
    viewport: { width: 1440, height: 960 },
    state: "dense",
    reviewFocus: ["dark smoke contrast", "focus and active conversation states"],
    expectedEvidence: "screenshot",
  },
  {
    id: "chat-light-custom-desktop-dense",
    path: "/chat",
    theme: "light",
    background: "custom",
    viewport: { width: 1440, height: 960 },
    state: "dense",
    reviewFocus: ["custom background visibility", "readability overlay strength"],
    expectedEvidence: "screenshot",
  },
  {
    id: "supervised-light-default-desktop-blocker",
    path: "/supervised-evolution",
    theme: "light",
    background: "default",
    viewport: { width: 1440, height: 960 },
    state: "blocker",
    reviewFocus: ["next action visibility", "blocker state prominence"],
    expectedEvidence: "screenshot",
  },
  {
    id: "supervised-light-custom-narrow-blocker",
    path: "/supervised-evolution",
    theme: "light",
    background: "custom",
    viewport: { width: 390, height: 844 },
    state: "blocker",
    reviewFocus: ["narrow viewport layout stability", "background-aware panels"],
    expectedEvidence: "screenshot",
  },
  {
    id: "agents-light-default-desktop-dense",
    path: "/agents",
    theme: "light",
    background: "default",
    viewport: { width: 1440, height: 960 },
    state: "dense",
    reviewFocus: ["agent list/detail panel hierarchy", "status chip language"],
    expectedEvidence: "screenshot",
  },
  {
    id: "memory-light-default-desktop-dense",
    path: "/memory",
    theme: "light",
    background: "default",
    viewport: { width: 1440, height: 960 },
    state: "dense",
    reviewFocus: ["memory overview panel nesting", "metric/status chip consistency"],
    expectedEvidence: "screenshot",
  },
  {
    id: "memory-light-custom-narrow-empty",
    path: "/memory",
    theme: "light",
    background: "custom",
    viewport: { width: 390, height: 844 },
    state: "empty",
    reviewFocus: ["empty state readability", "narrow route header actions"],
    expectedEvidence: "screenshot",
  },
  {
    id: "memory-graph-light-default-desktop-dense",
    path: "/memory/graph",
    theme: "light",
    background: "default",
    viewport: { width: 1440, height: 960 },
    state: "dense",
    reviewFocus: ["graph page special-layout exception", "generic chrome consistency"],
    expectedEvidence: "screenshot",
  },
  {
    id: "config-light-default-desktop-destructive",
    path: "/config",
    theme: "light",
    background: "default",
    viewport: { width: 1440, height: 960 },
    state: "destructive",
    reviewFocus: ["destructive action visibility", "quiet non-primary controls"],
    expectedEvidence: "screenshot",
  },
  {
    id: "config-dark-custom-desktop-error",
    path: "/config",
    theme: "dark",
    background: "custom",
    viewport: { width: 1440, height: 960 },
    state: "error",
    reviewFocus: ["error state contrast", "custom background overlay in dark smoke"],
    expectedEvidence: "screenshot",
  },
];

function sortedUnique<T extends string>(items: T[]): T[] {
  return Array.from(new Set(items)).sort();
}

export function summarizeWorkbenchVisualCoverage(scenarios: WorkbenchVisualScenario[]) {
  return {
    themes: sortedUnique(scenarios.map((scenario) => scenario.theme)),
    backgrounds: sortedUnique(scenarios.map((scenario) => scenario.background)),
    viewports: sortedUnique(scenarios.map((scenario) => (scenario.viewport.width < 700 ? "narrow" : "desktop"))),
    states: sortedUnique(scenarios.map((scenario) => scenario.state)),
    paths: sortedUnique(scenarios.map((scenario) => scenario.path)),
  };
}
```

- [ ] **Step 4: Run the focused matrix test**

Run:

```bash
cd web && npm test -- src/visual-regression/workbenchVisualMatrix.test.ts
```

Expected: PASS.

- [ ] **Step 5: Run build smoke**

Run:

```bash
cd web && npm run build
```

Expected: PASS.

---

### Task 2: Add reusable quiet-workbench VUI aesthetic primitives

**Files:**
- Create: `web/src/components/vui/aesthetic/VWorkbenchAesthetic.tsx`
- Create: `web/src/components/vui/aesthetic/index.ts`
- Create: `web/src/components/vui/vuiAestheticPrimitives.test.tsx`
- Modify: `web/src/components/vui/index.ts`

**Interfaces:**
- Consumes: existing `VSurface` from `web/src/components/vui/primitives/VSurface.tsx`.
- Produces:
  - `VEmbeddedPanel(props)`
  - `VDenseToolbar(props)`
  - `VDenseRow(props)`
  - `VStateRow(props)`
  - `VMetricChip(props)`
  - `VStatusChip(props)`
  - `VStatusTone = "neutral" | "accent" | "success" | "warning" | "danger"`

- [ ] **Step 1: Write the failing primitive render test**

Create `web/src/components/vui/vuiAestheticPrimitives.test.tsx`:

```tsx
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  VDenseRow,
  VDenseToolbar,
  VEmbeddedPanel,
  VMetricChip,
  VStateRow,
  VStatusChip,
} from "./index";

describe("VUI quiet-workbench aesthetic primitives", () => {
  it("renders embedded panels without primary panel chrome", () => {
    const markup = renderToStaticMarkup(
      <VEmbeddedPanel ariaLabel="Evidence summary">
        <strong>Evidence</strong>
      </VEmbeddedPanel>,
    );

    expect(markup).toContain('data-vui="embedded-panel"');
    expect(markup).toContain('aria-label="Evidence summary"');
    expect(markup).toContain("bg-vui-surface-row/70");
    expect(markup).toContain("shadow-none");
    expect(markup).not.toContain("shadow-[var(--vui-shadow-hairline)]");
  });

  it("renders dense toolbars and rows with stable data attributes", () => {
    const markup = renderToStaticMarkup(
      <VDenseToolbar ariaLabel="Memory filters">
        <VMetricChip label="Items" value="42" />
        <VStatusChip tone="accent">Active</VStatusChip>
        <VDenseRow>Knowledge source</VDenseRow>
      </VDenseToolbar>,
    );

    expect(markup).toContain('data-vui="dense-toolbar"');
    expect(markup).toContain('role="toolbar"');
    expect(markup).toContain('aria-label="Memory filters"');
    expect(markup).toContain('data-vui="metric-chip"');
    expect(markup).toContain('data-vui="status-chip"');
    expect(markup).toContain('data-vui="dense-row"');
    expect(markup).toContain("Items");
    expect(markup).toContain("42");
  });

  it("keeps critical row and chip states visibly distinct", () => {
    const markup = renderToStaticMarkup(
      <div>
        <VStateRow tone="danger">Delete confirmation required</VStateRow>
        <VStateRow tone="warning">Blocked by review</VStateRow>
        <VStatusChip tone="danger">Failed</VStatusChip>
        <VStatusChip tone="success">Ready</VStatusChip>
      </div>,
    );

    expect(markup).toContain('data-tone="danger"');
    expect(markup).toContain('data-tone="warning"');
    expect(markup).toContain('data-tone="success"');
    expect(markup).toContain("var(--state-error)");
    expect(markup).toContain("var(--state-warning)");
    expect(markup).toContain("var(--state-success)");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd web && npm test -- src/components/vui/vuiAestheticPrimitives.test.tsx
```

Expected: FAIL because exports do not exist.

- [ ] **Step 3: Implement the primitives**

Create `web/src/components/vui/aesthetic/VWorkbenchAesthetic.tsx`:

```tsx
import { type ComponentPropsWithoutRef, type ReactNode } from "react";

import { VSurface } from "../primitives/VSurface";

export type VStatusTone = "neutral" | "accent" | "success" | "warning" | "danger";

type DivProps = ComponentPropsWithoutRef<"div">;

type VEmbeddedPanelProps = ComponentPropsWithoutRef<"section"> & {
  ariaLabel?: string;
  children: ReactNode;
};

type VDenseToolbarProps = DivProps & {
  ariaLabel: string;
};

type VDenseRowProps = DivProps & {
  children: ReactNode;
};

type VStateRowProps = VDenseRowProps & {
  tone?: VStatusTone;
};

type VMetricChipProps = DivProps & {
  label: ReactNode;
  value: ReactNode;
};

type VStatusChipProps = DivProps & {
  children: ReactNode;
  tone?: VStatusTone;
};

const stateToneClass: Record<VStatusTone, string> = {
  accent:
    "border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] text-[var(--accent-cool)]",
  danger:
    "border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  neutral: "border-vui-border-subtle bg-vui-surface-row/70 text-vui-fg-secondary",
  success:
    "border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  warning:
    "border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
};

export function VEmbeddedPanel({ ariaLabel, className, children, ...props }: VEmbeddedPanelProps) {
  return (
    <VSurface
      {...props}
      as="section"
      data-vui="embedded-panel"
      ariaLabel={ariaLabel}
      padding="compact"
      tone="row"
      className={[
        "bg-vui-surface-row/70 shadow-none backdrop-blur-0",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </VSurface>
  );
}

export function VDenseToolbar({ ariaLabel, className, ...props }: VDenseToolbarProps) {
  return (
    <div
      {...props}
      data-vui="dense-toolbar"
      role="toolbar"
      aria-label={ariaLabel}
      className={[
        "flex min-w-0 flex-wrap items-center gap-1.5 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-toolbar px-2 py-1.5",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    />
  );
}

export function VDenseRow({ className, children, ...props }: VDenseRowProps) {
  return (
    <div
      {...props}
      data-vui="dense-row"
      className={[
        "min-w-0 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row px-2 py-1.5 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-vui-fg-secondary",
        "focus-within:ring-2 focus-within:ring-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)]",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </div>
  );
}

export function VStateRow({ className, children, tone = "neutral", ...props }: VStateRowProps) {
  return (
    <VDenseRow
      {...props}
      data-tone={tone}
      className={[stateToneClass[tone], className].filter(Boolean).join(" ")}
    >
      {children}
    </VDenseRow>
  );
}

export function VMetricChip({ className, label, value, ...props }: VMetricChipProps) {
  return (
    <span
      {...props}
      data-vui="metric-chip"
      className={[
        "inline-flex min-h-6 w-fit max-w-full items-center gap-1.5 rounded-full border border-vui-border-subtle bg-vui-control-muted px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-vui-fg-secondary",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span className="text-vui-fg-tertiary">{label}</span>
      <strong className="font-semibold text-vui-fg-primary">{value}</strong>
    </span>
  );
}

export function VStatusChip({ className, children, tone = "neutral", ...props }: VStatusChipProps) {
  return (
    <span
      {...props}
      data-vui="status-chip"
      data-tone={tone}
      className={[
        "inline-flex min-h-6 w-fit max-w-full items-center rounded-full border px-2 text-[var(--vui-font-xs)] font-semibold leading-none",
        stateToneClass[tone],
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </span>
  );
}
```

Create `web/src/components/vui/aesthetic/index.ts`:

```ts
export {
  VDenseRow,
  VDenseToolbar,
  VEmbeddedPanel,
  VMetricChip,
  VStateRow,
  VStatusChip,
  type VStatusTone,
} from "./VWorkbenchAesthetic";
```

Modify `web/src/components/vui/index.ts` by adding these exports after the existing layout exports:

```ts
export {
  VDenseRow,
  VDenseToolbar,
  VEmbeddedPanel,
  VMetricChip,
  VStateRow,
  VStatusChip,
  type VStatusTone,
} from "./aesthetic";
```

- [ ] **Step 4: Run focused VUI tests**

Run:

```bash
cd web && npm test -- src/components/vui/vuiAestheticPrimitives.test.tsx src/components/vui/vuiPrimitives.test.tsx src/components/vui/vuiLayoutTemplates.test.tsx src/components/vui/vuiImportBoundary.test.ts
```

Expected: PASS.

- [ ] **Step 5: Run build smoke**

Run:

```bash
cd web && npm run build
```

Expected: PASS.

---

### Task 3: Add static aesthetic contract tests for Wave 1 style-map cleanup

**Files:**
- Create: `web/src/routes/routeAestheticContract.test.ts`

**Interfaces:**
- Consumes: no app interfaces; reads raw source files.
- Produces: failing/passing guardrails for Wave 1 cleanup.

- [ ] **Step 1: Write the failing static contract test**

Create `web/src/routes/routeAestheticContract.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const appRoot = resolve(import.meta.dirname, "../app");
const routeRoot = import.meta.dirname;

const WORKBENCH_MAINLINE_STYLE_FILES = [
  resolve(appRoot, "AppShell.styles.ts"),
  resolve(appRoot, "AppShellStatusGuidePanel.styles.ts"),
  resolve(appRoot, "AppShellUtilityMenu.styles.ts"),
  resolve(routeRoot, "ChatCodingRoute.styles.ts"),
  resolve(routeRoot, "MemoryRoute.styles.ts"),
] as const;

const HEADER_CHROME_KEYS = [
  "activeWorkDetailHeader",
  "cacheDetailHeader",
  "cacheDetailSegmentHeader",
  "detailHeader",
  "detailMeta",
  "panelEyebrow",
  "panelHeader",
  "ragPreviewHeader",
  "statusGuideCardHeader",
  "utilityPanelHeader",
] as const;

const BUTTON_CHROME_KEYS = [
  "detailActionButton",
  "matrixCardButton",
] as const;

function readSource(file: string) {
  return readFileSync(file, "utf-8");
}

function extractStyleValue(source: string, key: string) {
  const pattern = new RegExp(`${key}:\\s*\\r?\\n?\\s*"([^"]*)"`);
  return source.match(pattern)?.[1] ?? "";
}

function collectValues(keys: readonly string[]) {
  return WORKBENCH_MAINLINE_STYLE_FILES.flatMap((file) => {
    const source = readSource(file);
    return keys
      .map((key) => ({ file, key, value: extractStyleValue(source, key) }))
      .filter((entry) => entry.value.length > 0);
  });
}

function countOccurrences(source: string, token: string) {
  return source.split(token).length - 1;
}

describe("route aesthetic contract", () => {
  it("keeps header and eyebrow style keys layout-only instead of card-like", () => {
    const violations = collectValues(HEADER_CHROME_KEYS)
      .filter(
        (entry) =>
          entry.value.includes("bg-[var(--vui-surface-glass)]") ||
          entry.value.includes("shadow-[var(--vui-shadow-hairline)]") ||
          entry.value.includes("rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)]"),
      )
      .map((entry) => `${entry.file.split(/[/\\\\]/).pop()}:${entry.key}`);

    expect(violations).toEqual([]);
  });

  it("keeps button style keys from also carrying panel chrome", () => {
    const violations = collectValues(BUTTON_CHROME_KEYS)
      .filter(
        (entry) =>
          entry.value.includes("bg-[var(--vui-surface-glass)]") ||
          entry.value.includes("shadow-[var(--vui-shadow-hairline)]") ||
          entry.value.includes("rounded-[var(--radius-panel)]"),
      )
      .map((entry) => `${entry.file.split(/[/\\\\]/).pop()}:${entry.key}`);

    expect(violations).toEqual([]);
  });

  it("keeps repeated active accent tone classes from becoming the design language", () => {
    const offenders = WORKBENCH_MAINLINE_STYLE_FILES.flatMap((file) => {
      const source = readSource(file);
      return [
        "border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)]",
        "bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)]",
        "border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)]",
        "bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
      ]
        .filter((token) => countOccurrences(source, token) > 28)
        .map((token) => `${file.split(/[/\\\\]/).pop()}:${token}`);
    });

    expect(offenders).toEqual([]);
  });

  it("keeps Workbench routes from owning full-page opaque surface-page wrappers", () => {
    const offenders = [
      resolve(routeRoot, "ChatCodingRoute.styles.ts"),
      resolve(routeRoot, "MemoryRoute.styles.ts"),
    ]
      .flatMap((file) => {
        const source = readSource(file);
        return ["route", "graphCanvasShell", "cacheDonutShell", "cacheDetailDonutShell"]
          .map((key) => ({ file, key, value: extractStyleValue(source, key) }))
          .filter((entry) => entry.value.includes("bg-[var(--surface-page)]"))
          .map((entry) => `${entry.file.split(/[/\\\\]/).pop()}:${entry.key}`);
      });

    expect(offenders).toEqual([]);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails against current known anti-patterns**

Run:

```bash
cd web && npm test -- src/routes/routeAestheticContract.test.ts
```

Expected: FAIL. The failure should list known offenders such as `AppShellStatusGuidePanel.styles.ts:statusGuideCardHeader`, `AppShellUtilityMenu.styles.ts:utilityPanelHeader`, `ChatCodingRoute.styles.ts:cacheDetailHeader`, `MemoryRoute.styles.ts:panelEyebrow`, or route surface-page wrappers.

- [ ] **Step 3: Keep the test unchanged for Task 4**

Do not loosen the test. Task 4 makes the source meet this contract.

---

### Task 4: Clean AppShell and Workbench mainline style-map anti-patterns

**Files:**
- Modify: `web/src/app/AppShellStatusGuidePanel.styles.ts`
- Modify: `web/src/app/AppShellUtilityMenu.styles.ts`
- Modify: `web/src/app/AppShell.styles.ts`
- Modify: `web/src/routes/ChatCodingRoute.styles.ts`
- Modify: `web/src/routes/MemoryRoute.styles.ts`
- Test: `web/src/routes/routeAestheticContract.test.ts`
- Test: existing layout tests that read these styles:
  - `web/src/app/AppShell.layout.test.ts`
  - `web/src/routes/ChatCodingRoute.layout.test.ts`
  - `web/MemoryRouteCss.layout.test.ts`

**Interfaces:**
- Consumes: Task 3 `routeAestheticContract.test.ts`.
- Produces: style maps where known header/eyebrow keys are layout-only, button keys are not panel+button hybrids, and Workbench route wrappers remain background-aware.

- [ ] **Step 1: Run the failing contract as a baseline**

Run:

```bash
cd web && npm test -- src/routes/routeAestheticContract.test.ts
```

Expected: FAIL with the anti-patterns to remove.

- [ ] **Step 2: Replace AppShell subpanel header chrome**

In `web/src/app/AppShellStatusGuidePanel.styles.ts`, replace this value:

```ts
statusGuideCardHeader: "vui-app-appshell statusGuideCardHeader min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 flex flex-wrap items-center gap-1.5",
```

with:

```ts
statusGuideCardHeader: "vui-app-appshell statusGuideCardHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
```

In `web/src/app/AppShellUtilityMenu.styles.ts`, replace this value:

```ts
utilityPanelHeader: "vui-app-appshell utilityPanelHeader min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 flex flex-wrap items-center gap-1.5",
```

with:

```ts
utilityPanelHeader: "vui-app-appshell utilityPanelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
```

- [ ] **Step 3: Mirror the AppShell aggregate style cleanup**

In `web/src/app/AppShell.styles.ts`, make the same replacements for:

```ts
statusGuideCardHeader:
utilityPanelHeader:
```

Use exactly these target strings:

```ts
statusGuideCardHeader:
  "vui-app-appshell statusGuideCardHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
utilityPanelHeader:
  "vui-app-appshell utilityPanelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
```

For active tone duplication in `AppShell.styles.ts`, replace repeated double-accent values with one canonical active token sequence. Example for `navLinkActive`, change from the current repeated sequence to:

```ts
navLinkActive:
  "vui-app-appshell navLinkActive min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] text-[var(--accent-cool)]",
```

Apply the same canonical active tone sequence to other AppShell keys that contain both `_38%/_11%` and `_34%/_10%` active accent sequences in one class string, while preserving unique layout/positioning classes on the same key. Do not remove danger/warning/success state sequences.

- [ ] **Step 4: Remove Chat cache detail header card chrome and surface-page wrappers**

In `web/src/routes/ChatCodingRoute.styles.ts`, replace:

```ts
cacheDetailHeader:
  "vui-routes-chatcodingroute cacheDetailHeader min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 flex flex-wrap items-center gap-1.5",
cacheDetailSegmentHeader:
  "vui-routes-chatcodingroute cacheDetailSegmentHeader min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 flex flex-wrap items-center gap-1.5",
```

with:

```ts
cacheDetailHeader:
  "vui-routes-chatcodingroute cacheDetailHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
cacheDetailSegmentHeader:
  "vui-routes-chatcodingroute cacheDetailSegmentHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
```

Replace route-owned full-page wrappers that include `bg-[var(--surface-page)]`:

```ts
cacheDetailDonutShell:
  "vui-routes-chatcodingroute cacheDetailDonutShell min-w-0 grid h-full min-h-0 content-start overflow-hidden text-[var(--fg-primary)] rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
cacheDonutShell:
  "vui-routes-chatcodingroute cacheDonutShell min-w-0 grid h-full min-h-0 content-start overflow-hidden text-[var(--fg-primary)]",
```

If the exact existing value has additional non-background classes, preserve those classes and remove only `bg-[var(--surface-page)]`.

- [ ] **Step 5: Remove Memory header/eyebrow card chrome and button-panel hybrids**

In `web/src/routes/MemoryRoute.styles.ts`, replace these header-like values:

```ts
detailHeader:
  "detailHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
detailMeta:
  "detailMeta min-w-0 flex flex-wrap items-center gap-1.5 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
panelEyebrow:
  "panelEyebrow min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
panelHeader:
  "panelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
ragPreviewHeader:
  "ragPreviewHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
```

Replace `detailActionButton` with a button-only value:

```ts
detailActionButton:
  "detailActionButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55",
```

Replace `matrixCardButton` with a button-only value:

```ts
matrixCardButton:
  "matrixCardButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55",
```

Remove `bg-[var(--surface-page)]` from `route` and `graphCanvasShell` while preserving grid, height, overflow, and text classes:

```ts
route:
  "route min-w-0 grid h-full min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden text-[var(--fg-primary)]",
graphCanvasShell:
  "graphCanvasShell min-w-0 grid h-full min-h-0 content-start overflow-hidden text-[var(--fg-primary)] gap-2 p-2 min-h-[360px] bg-[var(--vui-gradient-route-soft)] after:content-[''] after:[background-size:91px_91px]",
```

- [ ] **Step 6: Run the static aesthetic contract**

Run:

```bash
cd web && npm test -- src/routes/routeAestheticContract.test.ts
```

Expected: PASS.

If it fails because a listed key still has card chrome, remove only the chrome token from that key. Do not delete layout, overflow, state, or responsive classes.

- [ ] **Step 7: Run layout contract tests for affected files**

Run:

```bash
cd web && npm test -- src/app/AppShell.layout.test.ts src/routes/ChatCodingRoute.layout.test.ts MemoryRouteCss.layout.test.ts src/routes/RouteStyleDisplayContract.test.ts
```

Expected: PASS.

- [ ] **Step 8: Run build smoke**

Run:

```bash
cd web && npm run build
```

Expected: PASS.

---

### Task 5: Add visual regression handoff documentation and final verification checklist

**Files:**
- Modify: `docs/superpowers/specs/2026-07-04-frontend-heroui-vui-aesthetic-unification-design.md`
- Modify: `web/src/visual-regression/workbenchVisualMatrix.ts`
- Test: `web/src/visual-regression/workbenchVisualMatrix.test.ts`

**Interfaces:**
- Consumes: Task 1 visual matrix.
- Produces: manual visual review instructions tied to the exact matrix and Wave 1 scope.

- [ ] **Step 1: Extend the matrix with a human-readable review command note**

In `web/src/visual-regression/workbenchVisualMatrix.ts`, add this export after `WORKBENCH_VISUAL_ACCEPTANCE_CHECKLIST`:

```ts
export const WORKBENCH_VISUAL_REVIEW_PROTOCOL = [
  "Start the app with: cd web && npm run dev -- --host 127.0.0.1",
  "For each scenario, open the path, set the stored theme to the scenario theme, and use a custom background when background is custom.",
  "Capture a screenshot or attach an observation note for every scenario id.",
  "Reject the wave if a screenshot shows a card wall, opaque route wrapper, unreadable text, invisible focus, or muted destructive/error/blocker state.",
] as const;
```

- [ ] **Step 2: Add protocol assertions to the visual matrix test**

In `web/src/visual-regression/workbenchVisualMatrix.test.ts`, update the import:

```ts
import {
  WORKBENCH_VISUAL_ACCEPTANCE_CHECKLIST,
  WORKBENCH_VISUAL_REVIEW_PROTOCOL,
  WORKBENCH_VISUAL_SCENARIOS,
  summarizeWorkbenchVisualCoverage,
} from "./workbenchVisualMatrix";
```

Add this test:

```ts
it("documents how to collect visual evidence for the matrix", () => {
  expect(WORKBENCH_VISUAL_REVIEW_PROTOCOL).toEqual([
    "Start the app with: cd web && npm run dev -- --host 127.0.0.1",
    "For each scenario, open the path, set the stored theme to the scenario theme, and use a custom background when background is custom.",
    "Capture a screenshot or attach an observation note for every scenario id.",
    "Reject the wave if a screenshot shows a card wall, opaque route wrapper, unreadable text, invisible focus, or muted destructive/error/blocker state.",
  ]);
});
```

- [ ] **Step 3: Update the design spec with the Wave 0-1 implementation handoff**

Append this section to `docs/superpowers/specs/2026-07-04-frontend-heroui-vui-aesthetic-unification-design.md`:

```md
## Wave 0-1 implementation handoff

The first implementation plan covers only Wave 0 and Wave 1.

Wave 0 deliverables:

- `web/src/visual-regression/workbenchVisualMatrix.ts` defines the first visual-regression matrix.
- The matrix covers light, dark, default background, custom background, desktop, narrow, dense, empty, error, blocker, and destructive review states.
- Import-boundary and VUI contract tests remain part of the verification gate.

Wave 1 deliverables:

- `web/src/components/vui/aesthetic/VWorkbenchAesthetic.tsx` provides reusable quiet-workbench primitives for embedded panels, dense toolbars, dense rows, state rows, metric chips, and status chips.
- Workbench mainline style maps remove the first known header/eyebrow/button chrome anti-patterns.
- The AppShell, Chat, and Memory baseline no longer depend on card-like headers or panel-button hybrids for common visual grammar.

Wave 1 is not the full-site migration. Later waves should start only after reviewing the Wave 1 screenshots and deciding which route family should be next.
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
cd web && npm test -- src/visual-regression/workbenchVisualMatrix.test.ts src/routes/routeAestheticContract.test.ts src/components/vui/vuiAestheticPrimitives.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Run full verification gate for Wave 0-1**

Run:

```bash
cd web && npm test -- src/visual-regression/workbenchVisualMatrix.test.ts src/routes/routeAestheticContract.test.ts src/components/vui/vuiAestheticPrimitives.test.tsx src/components/vui/vuiImportBoundary.test.ts src/components/vui/vuiDesignCssContract.test.ts src/app/AppShell.layout.test.ts src/routes/ChatCodingRoute.layout.test.ts MemoryRouteCss.layout.test.ts src/routes/RouteStyleDisplayContract.test.ts
cd web && npm run build
```

Expected: both commands PASS.

- [ ] **Step 6: Collect manual visual evidence**

Run:

```bash
cd web && npm run dev -- --host 127.0.0.1
```

Expected: Vite starts and prints a local URL, usually `http://127.0.0.1:5173/`.

For each id in `WORKBENCH_VISUAL_SCENARIOS`, open the path and capture a screenshot or write an observation note. Minimum evidence list:

```text
home-light-default-desktop-empty
chat-light-default-desktop-dense
chat-dark-default-desktop-dense
chat-light-custom-desktop-dense
supervised-light-default-desktop-blocker
supervised-light-custom-narrow-blocker
agents-light-default-desktop-dense
memory-light-default-desktop-dense
memory-light-custom-narrow-empty
memory-graph-light-default-desktop-dense
config-light-default-desktop-destructive
config-dark-custom-desktop-error
```

Reject the wave if any evidence shows:

```text
- background is hidden by a route-owned opaque wrapper
- text is unreadable on custom background
- headers/eyebrows look like nested cards
- button-like controls still carry panel chrome
- focus state is not visible
- destructive, error, or blocker state is too quiet to notice
- narrow viewport has route header/action layout jumps
```

---

## Self-review notes

Spec coverage:

- Wave 0 baseline and guards are covered by Task 1 and Task 5.
- VUI/product composition primitives are covered by Task 2.
- Workbench mainline first visual cleanup is covered by Task 3 and Task 4.
- HeroUI import boundary remains covered by existing `vuiImportBoundary.test.ts` and included in the verification gate.
- Full visual regression is represented by `WORKBENCH_VISUAL_SCENARIOS` and the manual evidence protocol.
- Later Waves 2-4 are intentionally not implemented by this plan; the approved spec says the first implementation plan should start with Wave 0 and Wave 1 only.

Placeholder scan:

- No TBD/TODO placeholders are used.
- Every new test and implementation file has concrete code.
- Commands include expected outcomes.

Type consistency:

- `WorkbenchVisualScenario`, `WORKBENCH_VISUAL_SCENARIOS`, `WORKBENCH_VISUAL_ACCEPTANCE_CHECKLIST`, `WORKBENCH_VISUAL_REVIEW_PROTOCOL`, and `summarizeWorkbenchVisualCoverage` are consistently named.
- `VEmbeddedPanel`, `VDenseToolbar`, `VDenseRow`, `VStateRow`, `VMetricChip`, `VStatusChip`, and `VStatusTone` are consistently named across implementation, barrel exports, and tests.
