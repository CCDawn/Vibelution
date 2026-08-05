# Frontend Loading State Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the workbench shell and all key cards visible immediately while initial data loads, eliminate false zero/empty projections, preserve successful data during refresh, and keep errors local to their owning region.

**Architecture:** Add one pure query-presentation state helper and one VUI loading-value primitive, then migrate HomeRedirect, Usage, Git, and Agents onto those shared contracts. The shared foundation is committed first; three route lanes then run in isolated worktrees and merge back into the integration branch before serial build and browser verification.

**Tech Stack:** React 19, TypeScript 5.9, TanStack React Query 5, React Router 7, VUI/HeroUI primitives, Lucide React, Vitest 3, Vite 8.

## Global Constraints

- Page shell, headings, and key card geometry render immediately; no route may return a blank main surface while initial data is pending.
- Initial missing data renders `VLoadingValue` or `VStateSurface tone="loading"`; it must not render fabricated `0`, `-`, or empty-list semantics.
- Successful zero remains a real loaded value and must still display as `0`.
- Independent queries settle independently; do not wait for unrelated page data.
- Background refresh keeps the last successful data and exposes a quiet syncing indicator.
- First-load errors replace only the owning region and provide a local retry; refetch errors preserve stale data.
- Reuse `RouteLoadingShell`, `VStateSurface`, `VMetricStrip`, and `LoaderCircle`; add no dependency and no second loading component system.
- Respect `prefers-reduced-motion` with `motion-reduce:animate-none`.
- Do not change Agent summary DTOs, Teams query topology, global AbortSignal wiring, backend persistence, or unrelated route styling.
- All production changes follow RED → GREEN → REFACTOR; every behavior test must be observed failing for the intended reason before implementation.
- Root `C:\Users\17533\Desktop\Vibelution` remains on clean local `main`; task and page lanes use `codex/` branches under `C:\Users\17533\Desktop\Vibelution-worktrees`.
- Parallel page lanes must not edit shared VUI, shared query-presentation, router foundation, query keys, global styles, or test infrastructure after Task 1 commits the shared contract.

---

## File Map

### Shared foundation — serial owner

- Create `web/src/app/RouteLoadingShell.tsx`: reusable route-level loading shell currently embedded in `router.tsx`.
- Create `web/src/app/queryPresentation.ts`: pure React Query state-to-presentation mapping.
- Create `web/src/app/queryPresentation.test.ts`: state contract unit tests.
- Create `web/src/components/vui/display/VLoadingValue.tsx`: fixed-size accessible loading value.
- Modify `web/src/components/vui/display/VMetricStrip.tsx`: accept `ReactNode` metric values.
- Modify `web/src/components/vui/product/agent-management/AgentSummaryStrip.tsx`: accept `ReactNode` metric values.
- Modify `web/src/components/vui/index.ts`: export `VLoadingValue` and its props.
- Modify `web/src/components/vui/vuiLayoutTemplates.test.tsx`: lock loading-value markup and metric integration.
- Modify `web/src/app/router.tsx`: import the extracted shell.
- Modify `web/src/app/router.test.ts`: keep lazy fallback contract coverage after extraction.

### Lane A — HomeRedirect and Usage

- Create `web/src/routes/HomeRedirect.test.tsx`: real component state tests with controlled query result.
- Modify `web/src/routes/HomeRedirect.tsx`: visible pending and error surfaces.
- Modify `web/src/routes/UsageRoute.tsx`: preserve undefined rollups and load each visible region explicitly.
- Modify `web/src/routes/UsageRoute.styles.ts`: reserve fixed hero, overview, and source-tile value slots.
- Modify `web/src/routes/UsageRoute.layout.test.ts`: loading/loaded/refetch contract assertions.

### Lane B — Git

- Modify `web/src/routes/GitRoute.tsx`: independent status/commits/config/diff loading semantics.
- Modify `web/src/routes/GitRoute.styles.ts`: fixed summary and panel loading slots.
- Modify `web/src/routes/GitRoute.layout.test.ts`: no-false-zero and stable-panel contracts.

### Lane C — Agents

- Modify `web/src/routes/AgentsRoute.tsx`: bind initial list state to the actual summary/full-workspace race.
- Modify `web/src/routes/AgentListStatePanel.tsx`: consume resolved list presentation without infinite pending.
- Modify `web/src/routes/AgentsRoute.layout.test.ts`: summary query ownership, fallback race, and loading metric contracts.

### Integration owner

- Modify `tests/test_matrix.yaml` only if the selector does not already map every changed VUI/app/route test; do not edit it pre-emptively.
- Update `.docs/project-memory/lanes/web-workbench-surface.json` and generated memory views only after successful local-main integration, through the project memory sync command.

---

### Task 1: Shared Query Presentation and Loading Primitives

**Files:**
- Create: `web/src/app/RouteLoadingShell.tsx`
- Create: `web/src/app/queryPresentation.ts`
- Create: `web/src/app/queryPresentation.test.ts`
- Create: `web/src/components/vui/display/VLoadingValue.tsx`
- Modify: `web/src/app/router.tsx:1-120`
- Modify: `web/src/app/router.test.ts:1-110`
- Modify: `web/src/components/vui/display/VMetricStrip.tsx:1-70`
- Modify: `web/src/components/vui/product/agent-management/AgentSummaryStrip.tsx:1-35`
- Modify: `web/src/components/vui/index.ts:1-35`
- Test: `web/src/components/vui/vuiLayoutTemplates.test.tsx`

**Interfaces:**
- Produces: `deriveQueryPresentation(input: QueryPresentationInput): QueryPresentation`.
- Produces: `QueryPresentation = "initial-loading" | "loaded" | "refreshing" | "error-empty" | "error-with-data"`.
- Produces: `VLoadingValue({ label, className, ...spanProps }: VLoadingValueProps)`.
- Produces: `RouteLoadingShell({ surface, label?, meta? }: RouteLoadingShellProps)`.
- Later page lanes may consume these exports but may not modify them.

- [ ] **Step 1: Write the failing pure state tests**

Create `web/src/app/queryPresentation.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { deriveQueryPresentation } from "./queryPresentation";

describe("query presentation", () => {
  it.each([
    [{ hasData: false, isPending: true, isFetching: true, isError: false }, "initial-loading"],
    [{ hasData: true, isPending: false, isFetching: false, isError: false }, "loaded"],
    [{ hasData: true, isPending: false, isFetching: true, isError: false }, "refreshing"],
    [{ hasData: false, isPending: false, isFetching: false, isError: true }, "error-empty"],
    [{ hasData: true, isPending: false, isFetching: false, isError: true }, "error-with-data"],
  ] as const)("maps %o to %s", (input, expected) => {
    expect(deriveQueryPresentation(input)).toBe(expected);
  });
});
```

- [ ] **Step 2: Extend the VUI test with the desired loading value**

Add `VLoadingValue` and `VMetricStrip` to the imports in `vuiLayoutTemplates.test.tsx`, render:

```tsx
<VMetricStrip
  ariaLabel="Agent summary"
  metrics={[
    { id: "agents", label: "Agents", value: <VLoadingValue label="Loading agents" /> },
  ]}
/>
```

and assert:

```ts
expect(markup).toContain('data-vui="loading-value"');
expect(markup).toContain('role="status"');
expect(markup).toContain('aria-label="Loading agents"');
expect(markup).toContain("animate-spin");
expect(markup).toContain("motion-reduce:animate-none");
```

- [ ] **Step 3: Run RED and confirm missing-module failures**

Run:

```powershell
npm --prefix web run test -- src/app/queryPresentation.test.ts src/components/vui/vuiLayoutTemplates.test.tsx --reporter=dot
```

Expected: FAIL because `queryPresentation.ts` and `VLoadingValue` do not exist.

- [ ] **Step 4: Implement the pure query presentation helper**

Create `web/src/app/queryPresentation.ts`:

```ts
export type QueryPresentation =
  | "initial-loading"
  | "loaded"
  | "refreshing"
  | "error-empty"
  | "error-with-data";

export type QueryPresentationInput = {
  hasData: boolean;
  isError: boolean;
  isFetching: boolean;
  isPending: boolean;
};

export function deriveQueryPresentation({
  hasData,
  isError,
  isFetching,
  isPending,
}: QueryPresentationInput): QueryPresentation {
  if (isError) {
    return hasData ? "error-with-data" : "error-empty";
  }
  if (!hasData && isPending) {
    return "initial-loading";
  }
  if (hasData && isFetching) {
    return "refreshing";
  }
  return "loaded";
}
```

- [ ] **Step 5: Implement and export `VLoadingValue`**

Create `web/src/components/vui/display/VLoadingValue.tsx`:

```tsx
import { LoaderCircle } from "lucide-react";
import { type ComponentPropsWithoutRef } from "react";

export type VLoadingValueProps = Omit<ComponentPropsWithoutRef<"span">, "children"> & {
  label: string;
};

export function VLoadingValue({ className, label, ...props }: VLoadingValueProps) {
  return (
    <span
      {...props}
      data-vui="loading-value"
      role="status"
      aria-label={label}
      className={[
        "inline-flex h-[1em] min-w-[1.25em] items-center justify-center align-middle",
        className,
      ].filter(Boolean).join(" ")}
    >
      <LoaderCircle
        aria-hidden="true"
        className="size-[0.9em] animate-spin motion-reduce:animate-none"
      />
    </span>
  );
}
```

Export it from `web/src/components/vui/index.ts`:

```ts
export { VLoadingValue, type VLoadingValueProps } from "./display/VLoadingValue";
```

- [ ] **Step 6: Allow ReactNode metric values**

In `VMetricStrip.tsx`, import `ReactNode` and change the metric type:

```ts
import { type ComponentPropsWithoutRef, type ReactNode } from "react";

export type VMetricStripMetric = {
  detail?: string;
  id?: string;
  label: string;
  tone?: VuiTone;
  value: ReactNode;
};
```

In `AgentSummaryStrip.tsx`, make the same type change:

```ts
import { type ReactNode } from "react";

export type AgentSummaryMetric = {
  id: string;
  label: string;
  value: ReactNode;
  detail?: string;
  tone?: VuiTone;
};
```

- [ ] **Step 7: Extract the route loading shell without changing markup**

Create `web/src/app/RouteLoadingShell.tsx`:

```tsx
import { type RouteErrorSurface } from "./RouteErrorBoundary";
import styles from "./router.styles";

export type RouteLoadingShellProps = {
  label?: string;
  meta?: string;
  surface?: RouteErrorSurface;
};

export function RouteLoadingShell({
  label,
  meta = "加载界面模块",
  surface = "workbench",
}: RouteLoadingShellProps) {
  const resolvedLabel = label ?? (surface === "launcher" ? "正在打开启动器" : "正在打开工作台");
  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      data-vui-app={surface}
      className={styles.routeLoadingSurfaceClass}
    >
      <div className={styles.routeLoadingPanelClass}>
        <strong className={styles.routeLoadingTitleClass}>{resolvedLabel}</strong>
        <span className={styles.routeLoadingMetaClass}>{meta}</span>
      </div>
    </div>
  );
}
```

In `router.tsx`, delete the local `RouteLoadingShell` function and add:

```ts
import { RouteLoadingShell } from "./RouteLoadingShell";
```

- [ ] **Step 8: Run GREEN for shared contracts**

Run:

```powershell
npm --prefix web run test -- src/app/queryPresentation.test.ts src/app/router.test.ts src/components/vui/vuiLayoutTemplates.test.tsx --reporter=dot
```

Expected: all tests PASS; router fallback markup remains unchanged.

- [ ] **Step 9: Review and commit the shared foundation**

Run:

```powershell
git diff --check
git status --short --branch
git add -- web/src/app/RouteLoadingShell.tsx web/src/app/queryPresentation.ts web/src/app/queryPresentation.test.ts web/src/app/router.tsx web/src/app/router.test.ts web/src/components/vui/display/VLoadingValue.tsx web/src/components/vui/display/VMetricStrip.tsx web/src/components/vui/product/agent-management/AgentSummaryStrip.tsx web/src/components/vui/index.ts web/src/components/vui/vuiLayoutTemplates.test.tsx
git commit -m "feat(web): define shared loading states"
```

Expected: one scoped commit; worktree clean.

---

### Task 2: Lane A — HomeRedirect and Usage

**Dependencies:** Task 1 commit.

**Files:**
- Create: `web/src/routes/HomeRedirect.test.tsx`
- Modify: `web/src/routes/HomeRedirect.tsx`
- Modify: `web/src/routes/UsageRoute.tsx`
- Modify: `web/src/routes/UsageRoute.styles.ts` only when fixed value-slot sizing is required
- Test: `web/src/routes/UsageRoute.layout.test.ts`

**Interfaces:**
- Consumes: `deriveQueryPresentation`, `RouteLoadingShell`, `VLoadingValue`, `VStateSurface`, `VButton`.
- Produces: visible `/` pending/error behavior and Usage region-level loading behavior.
- Must not modify Task 1 files.

- [ ] **Step 1: Create the isolated lane and claim exact scopes**

From the integration worktree after Task 1:

```powershell
git worktree add 'C:\Users\17533\Desktop\Vibelution-worktrees\loading-state-home-usage' -b codex/loading-state-home-usage HEAD
```

Create `.venv` and `web/node_modules` Junctions using the verified root targets. Claim only the five Lane A files in lane `frontend-loading-state-home-usage`.

- [ ] **Step 2: Write RED tests for HomeRedirect**

Create `HomeRedirect.test.tsx` with hoisted controlled query state:

```tsx
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const queryState = vi.hoisted(() => ({
  current: {
    data: undefined as undefined | { defaultRoute?: string },
    error: null as unknown,
    isError: false,
    isFetching: true,
    isPending: true,
    refetch: vi.fn(),
  },
}));

vi.mock("@tanstack/react-query", () => ({ useQuery: () => queryState.current }));
vi.mock("react-router-dom", () => ({
  Navigate: ({ to }: { to: string }) => <span data-navigate-to={to} />,
}));

import { HomeRedirect } from "./HomeRedirect";

describe("HomeRedirect loading contract", () => {
  beforeEach(() => {
    queryState.current = {
      data: undefined,
      error: null,
      isError: false,
      isFetching: true,
      isPending: true,
      refetch: vi.fn(),
    };
  });

  it("renders a visible workbench shell while config is pending", () => {
    const markup = renderToStaticMarkup(<HomeRedirect />);
    expect(markup).toContain('data-vui-app="workbench"');
    expect(markup).toContain('aria-busy="true"');
    expect(markup).toContain("正在确定默认工作台");
  });

  it("renders a local error surface instead of guessing a route", () => {
    queryState.current = {
      ...queryState.current,
      isError: true,
      isFetching: false,
      isPending: false,
      error: new Error("config unavailable"),
    };
    const markup = renderToStaticMarkup(<HomeRedirect />);
    expect(markup).toContain('data-tone="error"');
    expect(markup).toContain("config unavailable");
    expect(markup).not.toContain("data-navigate-to");
  });
});
```

- [ ] **Step 3: Add RED source contracts for Usage**

In `UsageRoute.layout.test.ts`, add assertions:

```ts
it("distinguishes pending rollups from loaded zero values", () => {
  expect(routeSource).toContain("deriveQueryPresentation");
  expect(routeSource).toContain("<VLoadingValue");
  expect(routeSource).not.toContain("function rollupOrEmpty");
  expect(routeSource).not.toContain("const allTime = rollupOrEmpty");
  expect(routeSource).toContain('usagePresentation === "initial-loading"');
  expect(routeSource).toContain('usagePresentation === "refreshing"');
});
```

- [ ] **Step 4: Run RED**

Run:

```powershell
npm --prefix web run test -- src/routes/HomeRedirect.test.tsx src/routes/UsageRoute.layout.test.ts --reporter=dot
```

Expected: FAIL because HomeRedirect still returns `null` and Usage still calls `rollupOrEmpty`.

- [ ] **Step 5: Implement HomeRedirect visible states**

Replace the pending `return null` path with:

```tsx
const presentation = deriveQueryPresentation({
  hasData: Boolean(configQuery.data),
  isError: configQuery.isError,
  isFetching: configQuery.isFetching,
  isPending: configQuery.isPending,
});

if (presentation === "initial-loading") {
  return <RouteLoadingShell label="正在确定默认工作台" meta="读取工作台配置" />;
}

if (presentation === "error-empty") {
  return (
    <VStateSurface
      tone="error"
      title="工作台配置读取失败"
      actions={<VButton type="button" onPress={() => void configQuery.refetch()}>重试</VButton>}
    >
      {configQuery.error instanceof Error ? configQuery.error.message : "无法确定默认工作台。"}
    </VStateSurface>
  );
}
```

Keep the existing `Navigate` for loaded data.

- [ ] **Step 6: Implement Usage presentation without early zero normalization**

Replace `rollupOrEmpty` usage with optional rollups and a loaded-only fallback:

```tsx
const usagePresentation = deriveQueryPresentation({
  hasData: Boolean(summary),
  isError: usageQuery.isError,
  isFetching: usageQuery.isFetching,
  isPending: usageQuery.isPending,
});
const initialUsageLoading = usagePresentation === "initial-loading";
const allTime = globalTokenUsage?.allTime;
const today = globalTokenUsage?.today;
const last7Days = globalTokenUsage?.last7Days;
const sessionUsage = summary?.sessionTokenUsage;
const agentUsage = summary?.agentTokenUsage;
const scopeUsage = summary?.scopeTokenUsage;
const loadedRollup = (rollup: TokenUsageRollup | undefined) => rollup ?? EMPTY_ROLLUP;
const allTimeLoaded = loadedRollup(allTime);
```

Use the loaded aliases only for calculations, and render visible values through:

```tsx
function usageValue(loading: boolean, value: number | undefined, loadingLabel: string) {
  return loading ? <VLoadingValue label={loadingLabel} /> : numberText(value);
}
```

Apply `usageValue` to hero, overview, source, rollup, and count values. For long composition/list regions, keep their panel container and render a `VStateSurface tone="loading" skeletonLines={3}` inside the panel while `initialUsageLoading` is true. Set the header refresh status to “同步中” only for `refreshing`, and render a warning while `error-with-data` preserves old data.

In `UsageRoute.styles.ts`, add these exact stable-height tokens to the existing class strings:

```ts
heroMetric: "min-h-[76px]",
overviewStat: "min-h-[58px]",
sourceTile: "min-h-[50px]",
```

The actual exported strings keep all existing tokens and add the indicated `min-h-*` token immediately after `grid`. Add test assertions for all three tokens.

- [ ] **Step 7: Run Lane A GREEN tests**

Run:

```powershell
npm --prefix web run test -- src/routes/HomeRedirect.test.tsx src/routes/UsageRoute.layout.test.ts src/app/router.test.ts src/components/vui/vuiLayoutTemplates.test.tsx --reporter=dot
```

Expected: all tests PASS.

- [ ] **Step 8: Commit Lane A**

```powershell
git diff --check
git add -- web/src/routes/HomeRedirect.tsx web/src/routes/HomeRedirect.test.tsx web/src/routes/UsageRoute.tsx web/src/routes/UsageRoute.styles.ts web/src/routes/UsageRoute.layout.test.ts
git commit -m "fix(web): keep home and usage visible while loading"
```

---

### Task 3: Lane B — Git Loading Semantics

**Dependencies:** Task 1 commit.

**Files:**
- Modify: `web/src/routes/GitRoute.tsx`
- Modify: `web/src/routes/GitRoute.styles.ts`
- Test: `web/src/routes/GitRoute.layout.test.ts`

**Interfaces:**
- Consumes: `deriveQueryPresentation`, `VLoadingValue`, `VStateSurface`.
- Produces: independent status/commits loading and stable Git workspace panes.
- Must not modify Task 1 or other route lane files.

- [ ] **Step 1: Create isolated worktree and claim the three Git files**

```powershell
git worktree add 'C:\Users\17533\Desktop\Vibelution-worktrees\loading-state-git' -b codex/loading-state-git HEAD
```

Create dependency Junctions and claim scopes in lane `frontend-loading-state-git`.

- [ ] **Step 2: Write RED Git loading contracts**

Add to `GitRoute.layout.test.ts`:

```ts
it("keeps Git summary cards visible without projecting pending status as zero", () => {
  expect(routeSource).toContain("deriveQueryPresentation");
  expect(routeSource).toContain("statusInitialLoading");
  expect(routeSource).toContain("<VLoadingValue");
  expect(routeSource).toContain('statusPresentation === "refreshing"');
  expect(routeSource).not.toContain("<strong>{status?.counts.total ?? 0}</strong>");
  expect(routeSource).not.toContain("<strong>{status?.branch || status?.headRevShort || \"-\"}</strong>");
});

it("reserves loading surfaces for the Git workspace panes", () => {
  expect(routeSource).toContain('tone="loading"');
  expect(routeSource).toContain("gitStatusLoading");
  expect(gitRouteStyles.summaryCard).toContain("min-h-");
});
```

- [ ] **Step 3: Run RED**

```powershell
npm --prefix web run test -- src/routes/GitRoute.layout.test.ts --reporter=dot
```

Expected: FAIL on the new loading contract assertions.

- [ ] **Step 4: Implement independent Git presentations**

Add:

```tsx
const statusPresentation = deriveQueryPresentation({
  hasData: Boolean(statusQuery.data),
  isError: statusQuery.isError,
  isFetching: statusQuery.isFetching,
  isPending: statusQuery.isPending,
});
const commitsPresentation = deriveQueryPresentation({
  hasData: Boolean(commitsQuery.data),
  isError: commitsQuery.isError,
  isFetching: commitsQuery.isFetching,
  isPending: commitsQuery.isPending,
});
const statusInitialLoading = statusPresentation === "initial-loading";
const gitStatusLoading = lang === "zh" ? "正在读取 Git 状态" : "Loading Git status";
```

Render each status-derived summary value as:

```tsx
<strong>
  {statusInitialLoading
    ? <VLoadingValue label={gitStatusLoading} />
    : status?.branch || status?.headRevShort || "-"}
</strong>
```

Use the same pattern for counts, upstream, ahead/behind, local commits, and worktree count. `noChangedFiles` must require `statusPresentation === "loaded" || statusPresentation === "refreshing"`. During `initial-loading`, render the normal three-pane workspace with `VStateSurface tone="loading" skeletonLines` in each pane. Do not block `recentCommits` when `commitsPresentation` is loaded.

For `error-with-data`, retain status data and show a warning notice. For `error-empty`, render a status-owned error surface with `statusQuery.refetch` without hiding already loaded commits.

- [ ] **Step 5: Stabilize summary and pane value slots**

Add the fixed geometry to the existing `summaryCard` string in `GitRoute.styles.ts`:

```ts
summaryCard: `grid min-h-[52px] min-w-0 grid-cols-[auto_minmax(0,1fr)] items-baseline gap-1.5 ${panelSurface} px-2 py-[5px] text-left text-inherit disabled:cursor-default disabled:opacity-75 data-[vui=native-button]:cursor-pointer data-[vui=native-button]:hover:border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] data-[vui=native-button]:hover:bg-[color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-panel))] [&_span]:whitespace-nowrap [&_span]:text-[var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-vui-fg-tertiary [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-vui-fg-primary`,
```

Ensure the loading surface fills the existing pane without adding a new card wrapper or page-level height.

- [ ] **Step 6: Run GREEN and commit Lane B**

```powershell
npm --prefix web run test -- src/routes/GitRoute.layout.test.ts src/app/router.test.ts src/components/vui/vuiLayoutTemplates.test.tsx --reporter=dot
git diff --check
git add -- web/src/routes/GitRoute.tsx web/src/routes/GitRoute.styles.ts web/src/routes/GitRoute.layout.test.ts
git commit -m "fix(web): preserve Git cards during loading"
```

Expected: tests PASS and one scoped commit.

---

### Task 4: Lane C — Agents Summary and Workspace Fallback Race

**Dependencies:** Task 1 commit.

**Files:**
- Modify: `web/src/routes/AgentsRoute.tsx`
- Modify: `web/src/routes/AgentListStatePanel.tsx`
- Test: `web/src/routes/AgentsRoute.layout.test.ts`

**Interfaces:**
- Consumes: `deriveQueryPresentation`, `VLoadingValue`, `AgentSummaryMetric.value: ReactNode`.
- Produces: summary-owned initial list loading and a deterministic summary/full-workspace fallback race.
- Must not change `/api/agents`, query keys, Agent DTO types, or shared VUI files.

- [ ] **Step 1: Create isolated worktree and claim the three Agent files**

```powershell
git worktree add 'C:\Users\17533\Desktop\Vibelution-worktrees\loading-state-agents' -b codex/loading-state-agents HEAD
```

Create dependency Junctions and claim scopes in lane `frontend-loading-state-agents`.

- [ ] **Step 2: Write RED Agent ownership contracts**

Add to `AgentsRoute.layout.test.ts`:

```ts
it("binds the initial Agent list to the active summary/full-workspace data sources", () => {
  expect(routeSource).toContain("agentWorkspaceInitialLoading");
  expect(routeSource).toContain("agentWorkspaceInitialError");
  expect(routeSource).toContain("agentSummaryQuery.isError");
  expect(routeSource).toContain("agentSummaryQuery.isPending");
  expect(routeSource).toContain("<VLoadingValue");
  expect(routeSource).not.toContain("isError: workspaceQuery.isError,");
  expect(routeSource).not.toContain("isPending: workspaceQuery.isPending,");
});

it("keeps real zero distinct from an unresolved Agent summary", () => {
  expect(routeSource).toContain("agentSummaryInitialLoading");
  expect(routeSource).toContain("loadingAgentMetricValue");
  expect(routeSource).toContain("summary?.activeAgentCount ?? 0");
});
```

- [ ] **Step 3: Run RED**

```powershell
npm --prefix web run test -- src/routes/AgentsRoute.layout.test.ts --reporter=dot
```

Expected: FAIL because the list still passes `workspaceQuery.isError/isPending` directly and metrics always normalize to zero.

- [ ] **Step 4: Derive the summary/full-workspace race**

After `const workspace = workspaceQuery.data ?? lightweightWorkspace`, add:

```tsx
const hasAgentWorkspace = Boolean(workspace);
const agentWorkspaceInitialLoading = !hasAgentWorkspace && (
  agentSummaryQuery.isPending
  || (fullWorkspaceNeeded && workspaceQuery.isPending)
);
const agentWorkspaceInitialError = !hasAgentWorkspace
  && agentSummaryQuery.isError
  && (!fullWorkspaceNeeded || workspaceQuery.isError);
const agentWorkspaceError = agentSummaryQuery.error ?? workspaceQuery.error;
const agentSummaryPresentation = deriveQueryPresentation({
  hasData: Boolean(agentSummaryQuery.data),
  isError: agentSummaryQuery.isError,
  isFetching: agentSummaryQuery.isFetching,
  isPending: agentSummaryQuery.isPending,
});
const agentSummaryInitialLoading = agentSummaryPresentation === "initial-loading";
const loadingAgentMetricValue = <VLoadingValue label={copy.loading} />;
```

This means:

- default Agent route errors when the summary fails;
- a deep-linked full workspace keeps loading while either source can still succeed;
- it errors only after both available sources fail;
- any successful source immediately supplies the workspace.

- [ ] **Step 5: Render metric placeholders instead of false zero**

For each `agentSummaryMetrics` item, use:

```tsx
value: agentSummaryInitialLoading
  ? loadingAgentMetricValue
  : summary?.activeAgentCount ?? 0,
```

Use the relevant real summary field for every metric. Do not replace `0` after the summary is loaded.

- [ ] **Step 6: Wire the list panel to the resolved state**

Pass:

```tsx
isError: agentWorkspaceInitialError,
error: agentWorkspaceError,
isPending: agentWorkspaceInitialLoading,
hasWorkspace: hasAgentWorkspace,
```

Keep `AgentListStatePanel` priority as error → loading → empty → list. Add `aria-busy={isPending && !hasWorkspace || undefined}` to its loading `VEmptyState` wrapper or replace the loading branch with `VStateSurface tone="loading" skeletonLines={3}` if `VEmptyState` cannot expose busy semantics.

- [ ] **Step 7: Run GREEN and commit Lane C**

```powershell
npm --prefix web run test -- src/routes/AgentsRoute.layout.test.ts src/components/vui/vuiLayoutTemplates.test.tsx --reporter=dot
git diff --check
git add -- web/src/routes/AgentsRoute.tsx web/src/routes/AgentListStatePanel.tsx web/src/routes/AgentsRoute.layout.test.ts
git commit -m "fix(web): distinguish Agent loading from zero"
```

Expected: tests PASS and one scoped commit.

---

### Task 5: Parallel Lane Integration and Contract Reconciliation

**Dependencies:** Tasks 2, 3, and 4 completed with clean lane worktrees and commits.

**Files:**
- Merge-only reconciliation in the integration worktree.
- Modify `tests/test_matrix.yaml` only if selector output omits one of the focused tests.

**Interfaces:**
- Consumes: one commit from each page lane.
- Produces: one integration branch containing the shared foundation and all page changes.

- [ ] **Step 1: Verify every lane before merge**

For each lane:

```powershell
git status --short --branch
git log -1 --oneline
git diff --check HEAD^
```

Expected: clean worktree, one reviewed route commit, no diff-check errors, claim still active until integration accepts the commit.

- [ ] **Step 2: Merge lane branches serially into `codex/loading-state-contract`**

From the integration worktree:

```powershell
git merge --no-ff codex/loading-state-home-usage -m "merge: integrate home and usage loading states"
git merge --no-ff codex/loading-state-git -m "merge: integrate Git loading states"
git merge --no-ff codex/loading-state-agents -m "merge: integrate Agent loading states"
```

Expected: no shared-file conflicts because lane scopes are disjoint. If a conflict touches a Task 1 file, stop and reject the offending lane commit instead of manually blending contracts.

- [ ] **Step 3: Run selector and reconcile the validation map**

```powershell
& .\.venv\Scripts\python.exe tests\select_tests.py --from-git main --json
```

Expected: output includes the focused VUI/router/Agents/Git/Usage tests and frontend build. If it does not, first add a failing selector test in `tests/test_select_tests.py`, verify RED, then make the narrow `tests/test_matrix.yaml` mapping change and verify GREEN.

- [ ] **Step 4: Run the combined multi-worker Vitest gate**

```powershell
npm --prefix web run test -- src/app/queryPresentation.test.ts src/app/router.test.ts src/routes/HomeRedirect.test.tsx src/routes/UsageRoute.layout.test.ts src/routes/GitRoute.layout.test.ts src/routes/AgentsRoute.layout.test.ts src/components/vui/vuiLayoutTemplates.test.tsx --reporter=dot
```

Expected: all focused tests PASS with multiple Vitest workers.

- [ ] **Step 5: Run production build**

```powershell
npm --prefix web run build
```

Expected: TypeScript build and Vite production bundle PASS with no new warnings or errors.

- [ ] **Step 6: Review the integrated diff**

```powershell
git diff --check main...HEAD
git diff --stat main...HEAD
git status --short --branch
```

Confirm no DTO, Teams query, AbortSignal, dependency, lockfile, backend, config, or unrelated route changes entered the branch.

- [ ] **Step 7: Release page-lane claims and clean page-lane resources**

After the merged commits and combined tests pass, mark each page claim `completed`. Verify each page worktree is clean, safely remove its `.venv` and `web/node_modules` Junctions, then remove its worktree and delete only its merged branch.

---

### Task 6: Browser Verification, Final Review, and Local-Main Closeout

**Dependencies:** Task 5 build and tests pass; no active scope collision; integration branch clean.

**Files:**
- No application edits unless verification exposes a reproducible defect; any defect returns to a RED test in the owning task.
- Update project memory only after successful local-main integration.

- [ ] **Step 1: Run claim-bound closeout before merge**

Acquire or renew one integration claim covering the final changed file set. Capture the claim ID from the guard output and fail closed if it is missing:

```powershell
$guard = 'C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py'
$claimOutput = & .\.venv\Scripts\python.exe $guard 'C:\Users\17533\Desktop\Vibelution' claim --lane frontend-loading-state --scope web/src/app --scope web/src/components/vui --scope web/src/routes/HomeRedirect.tsx --scope web/src/routes/HomeRedirect.test.tsx --scope web/src/routes/UsageRoute.tsx --scope web/src/routes/UsageRoute.styles.ts --scope web/src/routes/UsageRoute.layout.test.ts --scope web/src/routes/GitRoute.tsx --scope web/src/routes/GitRoute.styles.ts --scope web/src/routes/GitRoute.layout.test.ts --scope web/src/routes/AgentsRoute.tsx --scope web/src/routes/AgentListStatePanel.tsx --scope web/src/routes/AgentsRoute.layout.test.ts --agent codex-loading-state-contract --task 'Integrate unified frontend loading states' --ttl-minutes 180
$integrationClaimId = [regex]::Match(($claimOutput -join "`n"), 'claim-[0-9a-f]+').Value
if (-not $integrationClaimId) { throw 'Integration claim ID was not returned.' }
& .\.venv\Scripts\python.exe scripts\local_quality_gate.py closeout --base main --claim-id $integrationClaimId
& .\.venv\Scripts\python.exe scripts\local_quality_gate.py verify-manifest --manifest .runtime\quality_gates\loading-state-contract.json --base main
```

Expected: both commands report `outcome: passed`; the manifest binds the current local `main` and task HEAD.

- [ ] **Step 2: Perform final code and UI review**

Review must confirm:

- no P0/P1/P2 findings;
- initial pending never renders false zero/empty values;
- loaded zero remains visible;
- stale data survives background refresh;
- errors stay local;
- reduced-motion and accessible loading labels remain present;
- the integrated branch is fast-forwardable from current local `main`.

- [ ] **Step 3: Fast-forward local main**

From `C:\Users\17533\Desktop\Vibelution` after confirming it is clean:

```powershell
git merge --ff-only codex/loading-state-contract
```

If local `main` moved, merge current `main` into the task worktree, rerun affected tests, closeout, and manifest verification before retrying.

- [ ] **Step 4: Run post-merge tests and build on real main**

```powershell
npm --prefix web run test -- src/app/queryPresentation.test.ts src/app/router.test.ts src/routes/HomeRedirect.test.tsx src/routes/UsageRoute.layout.test.ts src/routes/GitRoute.layout.test.ts src/routes/AgentsRoute.layout.test.ts src/components/vui/vuiLayoutTemplates.test.tsx --reporter=dot
npm --prefix web run build
```

Expected: all focused tests and production build PASS on local `main`.

- [ ] **Step 5: Refresh through Launcher when guards allow**

Check active work first. If active work exists, report the standard block message and defer runtime acceptance. Otherwise use the normal Launcher refresh path; do not raw-start Vite or uvicorn.

- [ ] **Step 6: Verify real loading behavior in browser**

At desktop and mobile widths, verify `/`, `/agents`, `/git`, and `/usage`:

- route shell visible immediately;
- key card geometry present before data;
- spinner/skeleton visible instead of `0`/`-`;
- cards reveal independently;
- background refresh keeps old data;
- local error and retry surface remain inside the owning region;
- no page-level horizontal overflow or disruptive layout shift;
- browser console contains no new error/warning.

Use controlled local delay only if an existing test/dev mechanism supports it; do not add a production delay or test-only production API.

- [ ] **Step 7: Sync project memory and finish cleanup**

Use the project memory guard, sync lane `web-workbench-surface`, render the dashboard, verify the update in JSON/HTML, release the integration claim, remove the task Junctions/worktree, prune worktrees, and delete only `codex/loading-state-contract` after confirming it is merged and clean.

Record:

- local main commit;
- focused test count and build result;
- browser routes/viewports checked;
- Launcher refresh result or exact active-work deferral;
- version impact `patch`;
- no remote push unless separately authorized.

---

## Parallel Execution Graph

```text
Task 1 shared foundation
  ├─ Task 2 Home + Usage lane
  ├─ Task 3 Git lane
  └─ Task 4 Agents lane
          ↓
Task 5 serial lane merge + multi-worker tests + build
          ↓
Task 6 review + closeout + local-main integration + runtime QA
```

Task 2, Task 3, and Task 4 are the only parallel phase. Task 1, Task 5, and Task 6 remain serial because they own shared contracts, integration state, or runtime evidence.

## Plan Review Record

- **User intent challenge:** PASS. The plan renders all card containers immediately and uses per-region loading rather than waiting for the whole page.
- **Ownership challenge:** PASS. Shared VUI/router files have one serial owner; page lanes have disjoint file scopes and claims.
- **Data-semantics challenge:** PASS. `deriveQueryPresentation` preserves the distinction between missing, loaded zero, refreshing stale data, and empty success.
- **Testing challenge:** PASS. Each task begins with a failing behavior or contract test, records expected RED, then runs focused GREEN and combined gates.
- **Conflict challenge:** PASS. Parallel lanes branch only after the shared commit and may not edit Task 1 files; integration rejects shared-file drift.
- **Scope challenge:** PASS. DTO slimming, query waterfall removal, AbortSignal, backend caching, dependencies, and unrelated visual work remain excluded.
- **Runtime challenge:** PASS with gate. Browser acceptance occurs only after local-main merge and normal Launcher refresh; active work defers refresh rather than forcing takeover.

## Workflow Ledger

- **Confirmed Intent:** Keep the entire page/card structure visible immediately; unresolved regions show loading, completed regions show data, and failures remain local.
- **Accepted Plan:** Commit shared loading semantics first, implement three disjoint page lanes in parallel, then merge and validate serially.
- **Reuse Decision:** ADAPT existing `RouteLoadingShell`, `VStateSurface`, `VMetricStrip`, and Lucide `LoaderCircle`; no external package or new design system.
- **Task Graph:** Shared Task 1 → parallel Tasks 2/3/4 → integration Task 5 → closeout Task 6.
- **Validation Evidence Before Implementation:** Existing baseline passes 4 Vitest files / 94 tests in 4.66 seconds.
- **Unresolved Risks:** Current Launcher runtime may remain stale while other active work exists; this blocks final browser acceptance but not isolated implementation or build verification.
- **Recommended Next Stage:** `subagent-driven-development`, with the orchestrator owning Task 1/5/6 and isolated subagents owning Tasks 2/3/4.
