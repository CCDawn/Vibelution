# HeroUI Frontend Unification Phase 2 Implementation Plan

> **Implementation status:** complete on 2026-07-10 after focused tests, production build, scoped diff review, Launcher refresh, and live Agents/Teams/Memory desktop verification.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Status Metadata

- **Status:** implemented and locally validated
- **Owner:** `codex-heroui-frontend-unification`
- **Planning claim:** `claim-3d254fa14e72`
- **Execution branch:** `codex/heroui-frontend-unification-phase-2`
- **Execution worktree:** `C:\Users\17533\Desktop\Vibelution-worktrees\heroui-frontend-unification-phase-2`
- **Scope:** apply the approved Phase 1 soft-layer contract to the current Agents, Teams, and Memory management surfaces without changing backend, DTO, query, cache, lifecycle, permission, or destructive-action semantics
- **Supersedes:** none
- **Design link:** `docs/superpowers/specs/2026-07-10-heroui-frontend-unification-design.md`
- **Prior implementation:** `docs/superpowers/plans/2026-07-10-heroui-frontend-unification-phase-1.md`
- **Validation:** focused Vitest, production build, scoped diff review, and live desktop browser evidence at `1280×720`, `1440×900`, and `1920×1080` in light and dark themes
- **Close condition:** Agents, Teams, and Memory primary management surfaces reuse the shared VUI surface/state/metric contracts, repeated rows are flat and scan-first, the current product behavior tests remain green, Launcher refresh is current, and project memory is synced

**Goal:** Finish the approved Phase 2 visual convergence for Agents, Teams, and Memory by making primary panels soft and coherent, repeated entities flat and scan-first, management metrics strip-based, and loading/empty/unavailable states VUI-owned while preserving every existing product behavior and data contract.

**Architecture:** The phase reuses Phase 1's `VSurface`, `VMetricStrip`, `VStateSurface`, `VPanelHeader`, `VSection`, and `VActionGroup` contracts. Route and product components continue to own state mapping and business composition; HeroUI remains behind VUI, while Agents, Teams, and Memory change only JSX composition and typed Tailwind class maps.

**Tech Stack:** React 19, TypeScript 5.9, HeroUI React 3.2.1, Tailwind CSS 4, Vite 8, Vitest 3, Zustand, TanStack Query.

## Global Constraints

- Desktop-only acceptance: validate exactly `1280×720`, `1440×900`, and `1920×1080`; do not add a phone, touch, or mobile-drawer design requirement.
- Preserve all existing routes, API/DTO shapes, query keys, cache semantics, mutations, permissions, lifecycle transitions, canvas data flow, graph behavior, archive/purge/cleanup confirmations, and optimistic rollback behavior.
- Do not modify `core/`, `web/src/api/types.ts`, `web/src/api/types/**`, `web/src/api/queryKeys.ts`, `web/src/i18n/dictionary.ts`, `VERSION`, `CHANGELOG.md`, `web/package.json`, or `web/package-lock.json`.
- Do not touch the active Challenge Cup backend scopes under `core/web/services/team_workflow/**` or their dirty root tests.
- Routes and product components must not import `@heroui/react`; all interaction primitives remain behind `web/src/components/vui/**`.
- Primary management columns may use one soft raised `VSurface`; repeated rows, metric cells, filter options, and detail groups remain flat inside that surface.
- Full-width controls are allowed only when the entire entity row is the action target. Compact toolbar, filter, retry, create, archive, and destructive controls remain content-sized.
- Critical errors, permission blockers, destructive consequences, and irreversible actions remain directly visible; Tooltips may contain only local explanation.
- Visual-only changes add no runtime-scene logs. If implementation changes behavior, stop and route that behavior through a new plan with logging and behavior tests.
- Developer-mode parity is preserved because this phase changes shared rendering only and does not change data source, write path, cache key, or permission logic.
- Project memory is single-writer state; sync only from validated local `main` under a separate memory claim.
- Phase 2 reports version impact `patch`; the full multi-phase program may later recommend `minor` after all routes converge.

---

## File Structure And Ownership

| Task area | Files | Responsibility |
| --- | --- | --- |
| Phase 2 evidence matrix | `web/src/visual-regression/workbenchVisualMatrix.ts`, `web/src/visual-regression/workbenchVisualMatrix.test.ts` | Adds explicit Agents/Teams/Memory light/dark desktop scenarios without changing viewport definitions |
| Agent primary surfaces | `web/src/components/vui/product/agent-management/AgentWorkspacePanel.tsx`, `AgentDenseList.tsx`, `AgentFilterRail.tsx`, `AgentManagementProduct.test.tsx` | Raised primary columns with flat filter and entity rows |
| Teams root workspace | `web/src/routes/TeamsRoute.tsx`, `TeamsRoute.styles.ts`, `TeamsRoute.layout.test.ts` | VUI-owned unavailable states, one raised canvas panel, and a bounded action group; no workflow/data changes |
| Memory overview | `web/src/routes/MemoryOverviewPanel.tsx`, `MemoryOverviewPanel.styles.ts`, `MemoryRoute.layout.test.ts` | Shared metric strip and primary overview/review surfaces |
| Memory manage and graph | `web/src/routes/MemoryManagePanel.tsx`, `MemoryManagePanel.styles.ts`, `MemoryGraphViewPanel.tsx`, `MemoryGraphViewPanel.styles.ts`, `MemoryRoute.layout.test.ts` | Raised primary workspaces, flat inner sections, shared empty state and metric strip |
| Governance closeout | approved design, this plan, Launcher evidence, browser observations, project memory | Phase status, local-main integration, refresh, memory, and version judgment |

## Interface Contract Between Tasks

No new package dependency or route-facing HeroUI API is introduced.

Task 2 changes the default product-surface contract to:

```tsx
<VSurface
  as={Element}
  data-vui-product="agent-workspace-panel"
  ariaLabel={ariaLabel}
  elevation="panel"
  padding="none"
  tone="rail"
/>
```

Tasks 4 and 5 consume the existing `VMetricStrip` interface:

```ts
export type VMetricStripMetric = {
  detail?: string;
  id?: string;
  label: string;
  tone?: VuiTone;
  value: string | number;
};
```

Tasks 3 and 5 consume the existing `VStateSurface` tones `loading`, `empty`, `unavailable`, and `error`; they must not add a route-local state vocabulary.

## Execution Worktree And Claim

At execution time, use `using-git-worktrees` and create the branch from the then-current local `main`:

```powershell
git -C "C:\Users\17533\Desktop\Vibelution" worktree add `
  "C:\Users\17533\Desktop\Vibelution-worktrees\heroui-frontend-unification-phase-2" `
  -b "codex/heroui-frontend-unification-phase-2" `
  main
```

Then acquire one implementation claim from the task worktree:

```powershell
$python = "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe"
$guard = "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py"
$project = "C:\Users\17533\Desktop\Vibelution"
$scopes = @(
  "web/src/visual-regression/workbenchVisualMatrix.ts",
  "web/src/visual-regression/workbenchVisualMatrix.test.ts",
  "web/src/components/vui/product/agent-management/AgentWorkspacePanel.tsx",
  "web/src/components/vui/product/agent-management/AgentDenseList.tsx",
  "web/src/components/vui/product/agent-management/AgentFilterRail.tsx",
  "web/src/components/vui/product/agent-management/AgentManagementProduct.test.tsx",
  "web/src/routes/TeamsRoute.tsx",
  "web/src/routes/TeamsRoute.styles.ts",
  "web/src/routes/TeamsRoute.layout.test.ts",
  "web/src/routes/MemoryOverviewPanel.tsx",
  "web/src/routes/MemoryOverviewPanel.styles.ts",
  "web/src/routes/MemoryManagePanel.tsx",
  "web/src/routes/MemoryManagePanel.styles.ts",
  "web/src/routes/MemoryGraphViewPanel.tsx",
  "web/src/routes/MemoryGraphViewPanel.styles.ts",
  "web/src/routes/MemoryRoute.layout.test.ts",
  "docs/superpowers/specs/2026-07-10-heroui-frontend-unification-design.md",
  "docs/superpowers/plans/2026-07-10-heroui-frontend-unification-phase-2.md"
)
$claimArgs = @(
  $guard,
  $project,
  "claim",
  "--lane", "web-workbench-surface",
  "--agent", "codex-heroui-frontend-unification",
  "--task", "Implement HeroUI frontend Phase 2 · codex/heroui-frontend-unification-phase-2",
  "--ttl-minutes", "480",
  "--note", "Agents, Teams, and Memory frontend-only visual convergence; no backend, DTO, query-key, i18n hot-file, or dependency changes",
  "--json"
)
foreach ($scope in $scopes) {
  $claimArgs += @("--scope", $scope)
}
$claimJson = & $python @claimArgs
$implementationClaim = $claimJson | ConvertFrom-Json
if (-not $implementationClaim.ok -or -not $implementationClaim.claim.id) {
  throw "Unable to acquire the HeroUI Phase 2 implementation claim."
}
$implementationClaim.claim.id
```

Expected: one active `claim-...` id. If any file overlaps an active claim, stop before editing; do not use `--force`.

---

### Task 1: Extend The Desktop Evidence Matrix For Phase 2

**Files:**
- Modify: `web/src/visual-regression/workbenchVisualMatrix.test.ts`
- Modify: `web/src/visual-regression/workbenchVisualMatrix.ts`

**Interfaces:**
- Consumes: existing `compact`, `standard`, and `wide` viewport presets.
- Produces: 18 actionable scenarios with explicit `/agents`, `/teams`, `/memory`, `/memory/manage`, and `/memory/graph` Phase 2 coverage.

- [ ] **Step 1: Write the failing Phase 2 scenario test**

Change the path expectation and scenario-count test to:

```ts
expect(coverage.paths).toEqual([
  "/",
  "/agents",
  "/chat",
  "/config",
  "/memory",
  "/memory/graph",
  "/memory/manage",
  "/supervised-evolution",
  "/teams",
]);
```

```ts
it("adds explicit light and dark Phase 2 management-route coverage", () => {
  const phase2Paths = ["/agents", "/teams", "/memory", "/memory/manage", "/memory/graph"];

  for (const path of phase2Paths) {
    const scenarios = WORKBENCH_VISUAL_SCENARIOS.filter((scenario) => scenario.path === path);
    expect(scenarios.length).toBeGreaterThan(0);
  }

  expect(WORKBENCH_VISUAL_SCENARIOS.filter(({ id }) => id.startsWith("agents-"))).toHaveLength(2);
  expect(WORKBENCH_VISUAL_SCENARIOS.filter(({ id }) => id.startsWith("teams-"))).toHaveLength(2);
  expect(WORKBENCH_VISUAL_SCENARIOS.filter(({ id }) => id.startsWith("memory-"))).toHaveLength(6);
  expect(WORKBENCH_VISUAL_SCENARIOS).toHaveLength(18);
});
```

- [ ] **Step 2: Run the visual matrix test and verify RED**

Run: `npm --prefix web run test -- workbenchVisualMatrix.test.ts`

Expected: FAIL because `/teams` and `/memory/manage` are absent and the matrix contains 12 scenarios.

- [ ] **Step 3: Add the six exact Phase 2 scenarios**

Append these objects immediately after the existing `agents-light-default-standard-dense` and Memory scenarios while preserving the current 12 entries:

```ts
{
  id: "agents-dark-default-wide-dense",
  path: "/agents",
  theme: "dark",
  background: "default",
  viewport: wide,
  state: "dense",
  reviewFocus: ["raised Agent workspace columns", "flat filter and entity rows"],
  expectedEvidence: "screenshot",
},
{
  id: "teams-light-default-compact-dense",
  path: "/teams",
  theme: "light",
  background: "default",
  viewport: compact,
  state: "dense",
  reviewFocus: ["Team canvas hierarchy", "content-sized canvas actions"],
  expectedEvidence: "screenshot",
},
{
  id: "teams-dark-default-standard-error",
  path: "/teams",
  theme: "dark",
  background: "default",
  viewport: standard,
  state: "error",
  reviewFocus: ["unavailable state contrast", "Team summary and recovery action"],
  expectedEvidence: "screenshot",
},
{
  id: "memory-dark-default-standard-dense",
  path: "/memory",
  theme: "dark",
  background: "default",
  viewport: standard,
  state: "dense",
  reviewFocus: ["overview metric strip", "review panel hierarchy"],
  expectedEvidence: "screenshot",
},
{
  id: "memory-manage-light-default-wide-dense",
  path: "/memory/manage",
  theme: "light",
  background: "default",
  viewport: wide,
  state: "dense",
  reviewFocus: ["management column hierarchy", "flat filters and stable actions"],
  expectedEvidence: "screenshot",
},
{
  id: "memory-graph-dark-default-wide-dense",
  path: "/memory/graph",
  theme: "dark",
  background: "default",
  viewport: wide,
  state: "dense",
  reviewFocus: ["graph metric strip", "filter canvas inspector hierarchy"],
  expectedEvidence: "screenshot",
},
```

- [ ] **Step 4: Run the visual matrix test and confirm GREEN**

Run: `npm --prefix web run test -- workbenchVisualMatrix.test.ts`

Expected: PASS with 18 scenarios and the three existing desktop viewport classes unchanged.

- [ ] **Step 5: Commit the Phase 2 evidence contract**

```powershell
git add -- web/src/visual-regression/workbenchVisualMatrix.ts web/src/visual-regression/workbenchVisualMatrix.test.ts
git commit -m "test(web): extend Phase 2 visual matrix"
```

---

### Task 2: Raise Agent Workspace Columns And Flatten Repeated Rows

**Files:**
- Modify: `web/src/components/vui/product/agent-management/AgentManagementProduct.test.tsx`
- Modify: `web/src/components/vui/product/agent-management/AgentWorkspacePanel.tsx`
- Modify: `web/src/components/vui/product/agent-management/AgentFilterRail.tsx`
- Modify: `web/src/components/vui/product/agent-management/AgentDenseList.tsx`
- Test: `web/src/routes/AgentsRoute.layout.test.ts`

**Interfaces:**
- Consumes: Phase 1 `VSurfaceTone = "rail"` and `VSurfaceElevation = "panel"`.
- Produces: one raised surface per Agent workspace column and flat repeated filter/entity rows with stable selected and bulk-selected backgrounds.

- [ ] **Step 1: Write failing product-surface and flat-row tests**

Update `AgentManagementProduct.test.tsx` workspace assertions:

```ts
expect(markup).toContain('data-tone="rail"');
expect(markup).toContain('data-elevation="panel"');
expect(markup).toContain("bg-vui-surface-rail");
expect(markup).toContain("shadow-[var(--vui-elevation-panel)]");
expect(markup).not.toContain("bg-vui-surface-glass");
```

Add a source contract in the same file:

```ts
it("keeps repeated Agent filters and entities flat inside the raised workspace panels", () => {
  const filterSource = readFileSync(resolve(import.meta.dirname, "AgentFilterRail.tsx"), "utf8");
  const denseListSource = readFileSync(resolve(import.meta.dirname, "AgentDenseList.tsx"), "utf8");

  expect(filterSource).toContain("border-b border-[var(--vui-border-hairline)]");
  expect(filterSource).toContain("bg-transparent");
  expect(filterSource).not.toContain("rounded-[var(--radius-control)] border border-[var(--border-soft)] bg-[var(--vui-surface-row)]");
  expect(denseListSource).toContain('data-vui="agent-row"');
  expect(denseListSource).toContain("border-b-[var(--vui-border-hairline)]");
  expect(denseListSource).toContain("rounded-none");
});
```

- [ ] **Step 2: Run the focused Agent tests and verify RED**

Run:

```powershell
npm --prefix web run test -- AgentManagementProduct.test.tsx AgentsRoute.layout.test.ts
```

Expected: FAIL because the workspace still uses `tone="glass"` without elevation and filter/entity rows still use individual rounded borders.

- [ ] **Step 3: Change the Agent workspace product surface**

Replace the `VSurface` props in `AgentWorkspacePanel.tsx` with:

```tsx
<VSurface
  as={Element}
  data-vui-product="agent-workspace-panel"
  ariaLabel={ariaLabel}
  elevation="panel"
  padding="none"
  tone="rail"
  className={[
    "grid min-h-0 content-start gap-[var(--agent-density-gap)] p-[var(--agent-panel-pad)]",
    className,
  ]
    .filter(Boolean)
    .join(" ")}
>
  {children}
</VSurface>
```

- [ ] **Step 4: Flatten Agent filter rows without changing the filter callbacks**

Replace the two filter constants in `AgentFilterRail.tsx`:

```ts
const GROUP_BUTTON_BASE =
  "grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 w-full min-h-[34px] px-[9px] py-[6px] rounded-none border-0 border-b border-[var(--vui-border-hairline)] bg-transparent text-[var(--fg-secondary)] text-left transition-[background,color,border-color] duration-150 hover:bg-[var(--vui-surface-row-hover)] hover:text-[var(--fg-primary)]";

const GROUP_BUTTON_ACTIVE =
  "border-l-2 border-l-[var(--accent-warm)] bg-[color-mix(in_srgb,var(--accent-warm)_9%,transparent)] text-[var(--fg-primary)]";
```

Change the advanced summary class to this exact flat disclosure row while preserving the current `<details>` state and child sections:

```tsx
<summary className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 min-h-[34px] px-[9px] py-[6px] rounded-none border-0 border-b border-[var(--vui-border-hairline)] bg-transparent text-[var(--fg-secondary)] text-[0.8rem] font-[760] cursor-pointer list-none [&::-webkit-details-marker]:hidden hover:bg-[var(--vui-surface-row-hover)] hover:text-[var(--fg-primary)]">
```

Do not change search, storage-path, `aria-pressed`, or `onSelectGroup` behavior.

- [ ] **Step 5: Flatten Agent entity rows while preserving full-row selection**

Replace the first, hover, active, and bulk-selected classes in `AgentRow`:

```ts
const rowClass = [
  "w-full min-h-[44px] px-2 py-[var(--agent-row-pad-y)] border-0 border-b border-l-2 border-b-[var(--vui-border-hairline)] border-l-transparent rounded-none bg-transparent text-[var(--fg-primary)] text-left items-center gap-2 min-w-0 grid",
  GRID_TEMPLATE,
  "max-[860px]:grid-cols-[1fr] max-[860px]:items-start",
  "transition-[border-color,background] duration-150 hover:bg-[var(--vui-surface-row-hover)]",
  row.active
    ? "border-l-[var(--accent-warm)] bg-[color-mix(in_srgb,var(--accent-warm)_9%,transparent)]"
    : "",
  row.bulkSelected ? "bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)]" : "",
]
  .filter(Boolean)
  .join(" ");
```

Keep the bulk checkbox as a separate square target and retain every current column, badge, Tooltip title, and callback.

- [ ] **Step 6: Run Agent behavior, product, and boundary tests**

Run:

```powershell
npm --prefix web run test -- AgentManagementProduct.test.tsx AgentsRoute.layout.test.ts vuiImportBoundary.test.ts vuiPrimitives.test.tsx
```

Expected: PASS; Agent API/cache/lifecycle source assertions remain unchanged, product panels render as `rail/panel`, and no direct HeroUI import appears outside VUI.

- [ ] **Step 7: Commit the Agent management convergence**

```powershell
git add -- `
  web/src/components/vui/product/agent-management/AgentManagementProduct.test.tsx `
  web/src/components/vui/product/agent-management/AgentWorkspacePanel.tsx `
  web/src/components/vui/product/agent-management/AgentFilterRail.tsx `
  web/src/components/vui/product/agent-management/AgentDenseList.tsx
git commit -m "style(web): flatten Agent management rows"
```

---

### Task 3: Give Teams One Canvas Surface And Shared Unavailable States

**Files:**
- Modify: `web/src/routes/TeamsRoute.layout.test.ts`
- Modify: `web/src/routes/TeamsRoute.tsx`
- Modify: `web/src/routes/TeamsRoute.styles.ts`

**Interfaces:**
- Consumes: existing `VSurface`, `VStateSurface`, `VActionGroup`, `VButton`, `VIconButton`, `VStatusStrip`, and all existing Team route state/callbacks.
- Produces: one raised Team canvas panel, a bounded canvas toolbar action group, and VUI-owned list/detail unavailable surfaces.

- [ ] **Step 1: Write failing Teams composition tests**

Add these assertions to `TeamsRoute.layout.test.ts`:

```ts
it("uses shared Phase 2 surfaces for Team unavailable and canvas states", () => {
  expect(routeSource).toContain("VActionGroup");
  expect(routeSource).toContain("VSurface");
  expect(routeSource).toContain('tone="unavailable"');
  expect(routeSource).toContain('tone="rail"');
  expect(routeSource).toContain('elevation="panel"');
  expect(routeSource).not.toContain("<section className={styles.teamUnavailableCard}");
  expect(routeStyles.canvasPanel).not.toContain("rounded-[var(--radius-panel)]");
  expect(routeStyles.canvasPanel).not.toContain("bg-[var(--vui-surface-panel)]");
  expect(routeStyles.teamUnavailableSurface).not.toContain("bg-[var(--vui-surface-panel)]");
});
```

Reconcile the existing geometry/operational assertions in the same test file so they test the new ownership layer instead of the retired route-local chrome:

- Replace `expect(routeStyles.teamUnavailableSurface).not.toContain("justify-center")` with `expect(routeStyles.teamUnavailableSurface).toContain("justify-center")`.
- Delete the old `justify-items-center` and `teamUnavailableActions` assertions.
- Replace the positive `canvasPanel` panel-background assertion with `expect(routeStyles.canvasPanel).not.toContain("bg-[var(--vui-surface-panel)]")`.
- Remove `"teamUnavailableCard"` and `"teamUnavailableSurface"` from `routeOperationalPanelKeys`; `VStateSurface` now owns their operational color/border contract while these style keys own geometry only.

- [ ] **Step 2: Run Teams layout and logic tests and verify RED**

Run:

```powershell
npm --prefix web run test -- TeamsRoute.layout.test.ts TeamsRoute.logic.test.ts teamsRouteViewModel.test.ts
```

Expected: FAIL because unavailable branches still render route-local cards and `canvasPanel` still owns panel chrome.

- [ ] **Step 3: Add only the shared VUI imports required by the composition**

Add `VActionGroup` and `VSurface` to the existing VUI import block. Do not remove `VNativeButton`; deep research workflow controls remain outside this task.

```ts
import {
  VActionGroup,
  VButton,
  VIconButton,
  VNativeButton,
  VNativeInput,
  VNativeSelect,
  VNativeTextarea,
  VRouteHeader,
  VSelect,
  VStateSurface,
  VStatusStrip,
  VSurface,
} from "../components/vui";
```

- [ ] **Step 4: Replace both Team unavailable cards with VStateSurface**

Use the same outer `main` and replace the list-unavailable branch body with:

```tsx
<VStateSurface
  className={styles.teamUnavailableCard}
  title={teamUnavailableTitle}
  tone="unavailable"
  facts={[
    { key: "teams", label: lang === "zh" ? "团队" : "Teams", value: visibleTeamSummary.activeTeamCount },
    { key: "members", label: lang === "zh" ? "成员" : "Members", value: visibleTeamSummary.memberCount },
    { key: "source", label: lang === "zh" ? "来源" : "Source", value: "Agent Center" },
  ]}
  actions={(
    <VButton type="button" variant="secondary" onPress={() => void teamsQuery.refetch()} isDisabled={teamsQuery.isFetching}>
      <RefreshCw size={14} />
      {teamsQuery.isFetching ? (lang === "zh" ? "刷新中" : "Refreshing") : (lang === "zh" ? "刷新" : "Refresh")}
    </VButton>
  )}
>
  {teamUnavailableDetail || teamUnavailableMessage}
</VStateSurface>
```

Replace the detail-unavailable branch body with:

```tsx
<VStateSurface
  className={styles.teamUnavailableCard}
  title={teamWorkspaceUnavailableTitle}
  tone="unavailable"
  facts={[
    { key: "team", label: lang === "zh" ? "团队" : "Team", value: selectedTeamReference?.name ?? effectiveTeamId },
    { key: "detail", label: lang === "zh" ? "详情" : "Details", value: teamDetailLoadMode },
    { key: "status", label: lang === "zh" ? "状态" : "Status", value: lang === "zh" ? "失败" : "failed" },
  ]}
  actions={(
    <VButton type="button" variant="secondary" onPress={() => void teamDetailQuery.refetch()} isDisabled={teamDetailQuery.isFetching}>
      <RefreshCw size={14} />
      {teamDetailQuery.isFetching ? (lang === "zh" ? "刷新中" : "Refreshing") : (lang === "zh" ? "刷新详情" : "Refresh details")}
    </VButton>
  )}
>
  {teamWorkspaceUnavailableDetail || teamWorkspaceUnavailableMessage}
</VStateSurface>
```

The mutation/query callbacks, failure classification, and directly visible messages remain unchanged.

- [ ] **Step 5: Move Team canvas chrome to VSurface and group toolbar actions**

Replace the opening and closing `main` element for the canvas panel with:

```tsx
<VSurface
  as="main"
  className={canvasPanelClassName}
  elevation="panel"
  padding="none"
  tone="rail"
  id="research-organization-canvas"
>
```

```tsx
</VSurface>
```

Replace the exact opening tag `<div className={styles.toolbarActions}>` with the following tag, and replace only its matching closing `</div>` with `</VActionGroup>`. Keep every intervening child control, link, callback, disabled reason, and destructive-action branch byte-for-byte unchanged:

```tsx
<VActionGroup
  className={styles.toolbarActions}
  ariaLabel={lang === "zh" ? "团队画布操作" : "Team canvas actions"}
>
</VActionGroup>
```

- [ ] **Step 6: Reduce route styles to geometry-only hooks**

Set these exact values in `TeamsRoute.styles.ts`:

```ts
canvasPanel:
  "canvasPanel min-w-0 !flex min-h-0 flex-col overflow-hidden",
teamUnavailableCard:
  "teamUnavailableCard w-full max-w-[720px]",
teamUnavailableSurface:
  "teamUnavailableSurface grid min-h-0 flex-1 grid-cols-[minmax(0,720px)] content-start justify-center overflow-auto px-3 py-4",
toolbarActions:
  "toolbarActions max-w-[min(100%,680px)] items-start justify-end overflow-visible max-[900px]:justify-start [&_a]:min-w-[72px] [&_a]:whitespace-nowrap [&_button]:min-w-[72px] [&_button]:whitespace-nowrap",
```

Delete the unused `teamUnavailableMeta` and `teamUnavailableActions` keys after their JSX is gone. Do not change canvas dimensions, node styles, edge styles, workflow panels, or Team data wiring.

- [ ] **Step 7: Run Teams behavior, loading, and UI boundary tests**

Run:

```powershell
npm --prefix web run test -- TeamsRoute.layout.test.ts TeamsRoute.logic.test.ts TeamsRoute.canvas-data.test.ts teamsRouteViewModel.test.ts vuiImportBoundary.test.ts vuiLayoutTemplates.test.tsx
```

Expected: PASS; cold loading remains inside the workspace, canvas data/cache behavior remains intact, unavailable states preserve facts and retry, and no route-level HeroUI import is introduced.

- [ ] **Step 8: Commit the Teams primary-surface convergence**

```powershell
git add -- web/src/routes/TeamsRoute.tsx web/src/routes/TeamsRoute.styles.ts web/src/routes/TeamsRoute.layout.test.ts
git commit -m "style(web): unify Teams primary surfaces"
```

---

### Task 4: Replace Memory Overview Card Grids With Shared Metrics And Primary Panels

**Files:**
- Modify: `web/src/routes/MemoryRoute.layout.test.ts`
- Modify: `web/src/routes/MemoryOverviewPanel.tsx`
- Modify: `web/src/routes/MemoryOverviewPanel.styles.ts`

**Interfaces:**
- Consumes: `VMetricStrip`, `VSurface`, `VPanelHeader`, and `VChip`.
- Produces: one metric strip, one review surface, and two primary overview surfaces without nested summary cards.

- [ ] **Step 1: Write failing Memory overview composition tests**

Replace the old summary-card assertions in `MemoryRoute.layout.test.ts` with:

```ts
it("uses shared metric and primary-surface contracts for the Memory overview", () => {
  expect(overviewPanelSource).toContain("VMetricStrip");
  expect(overviewPanelSource).toContain("VSurface");
  expect(overviewPanelSource).toContain("VPanelHeader");
  expect(overviewPanelSource).not.toContain("styles.summaryCard");
  expect(overviewPanelStyles.overviewPanel).not.toContain("rounded-[var(--radius-panel)]");
  expect(overviewPanelStyles.overviewPanel).not.toContain("bg-[var(--vui-surface-panel)]");
  expect(overviewPanelStyles.reviewQueuePanel).not.toContain("bg-[var(--vui-surface-panel)]");
});
```

This replacement has two exact cleanup sites in the current test file:

- In `keeps dense Memory workspaces bounded with internal scrolling`, delete every assertion that reads `overviewPanelStyles.summaryGrid` or `overviewPanelStyles.summaryCard`.
- In `delegates the dense overview body to a dedicated panel component`, replace the `styles.summaryGrid` source/style expectations with `expect(overviewPanelSource).toContain("VMetricStrip")` and `expect(overviewPanelSource).not.toContain("styles.summaryCard")`.

- [ ] **Step 2: Run Memory layout tests and verify RED**

Run: `npm --prefix web run test -- MemoryRoute.layout.test.ts`

Expected: FAIL because the overview still renders a bordered summary grid with six child cards and route-local panel headers.

- [ ] **Step 3: Replace the Memory summary grid with VMetricStrip**

Add the import:

```ts
import { VChip, VMetricStrip, VPanelHeader, VSurface } from "../components/vui";
```

Replace `styles.summaryGrid` and its six child sections with:

```tsx
<VMetricStrip
  ariaLabel={copy.healthOverview}
  metrics={[
    { id: "sections", label: copy.sectionCount, value: summary?.sectionCount ?? 0 },
    { id: "items", label: copy.itemCount, value: summary?.itemCount ?? 0 },
    { id: "visible", label: copy.agentVisible, value: summary?.agentVisibleCount ?? 0 },
    { id: "runtime", label: copy.runtimeInjected, value: summary?.runtimeInjectedCount ?? 0 },
    { id: "managed", label: copy.managedMemory, value: managedStateCount },
    { id: "overrides", label: copy.disabledOrOverridden, value: disabledOrOverriddenCount },
  ]}
/>
```

- [ ] **Step 4: Convert the review and two overview regions into primary VSurface panels**

Use this structure for the review queue:

```tsx
<VSurface className={styles.reviewQueuePanel} elevation="panel" tone="rail">
  <VPanelHeader
    eyebrow={copy.healthOverview}
    title={copy.reviewQueue}
    actions={<VChip tone="neutral">{priorityReviewCount}</VChip>}
  />
  <div title={copy.reviewQueueHint}>{reviewQueue}</div>
</VSurface>
```

Use this structure for each overview panel, substituting the current title/count/list values:

```tsx
<VSurface className={styles.overviewPanel} elevation="panel" tone="rail">
  <VPanelHeader
    eyebrow={copy.healthOverview}
    title={copy.affectedRuntimeMemory}
    actions={<VChip tone="neutral">{runtimeMemoryCount}</VChip>}
  />
  {runtimeMemoryList}
</VSurface>
```

Keep `projectMemoryQueue`, `warningStrip`, and all list data unchanged.

- [ ] **Step 5: Remove retired overview chrome from the style map**

Delete `summaryGrid`, `summaryCard`, `panelHeader`, `panelEyebrow`, and `countPill`. Set:

```ts
overviewPanel:
  "overviewPanel grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-auto",
reviewQueuePanel:
  "reviewQueuePanel grid min-h-0 max-h-[min(280px,34vh)] content-start gap-1.5 overflow-auto",
```

Keep `overviewGrid` unchanged.

- [ ] **Step 6: Run Memory and VUI metric tests**

Run:

```powershell
npm --prefix web run test -- MemoryRoute.layout.test.ts vuiLayoutTemplates.test.tsx vuiPrimitives.test.tsx
```

Expected: PASS; overview metrics render as one strip, primary surfaces own elevation, and runtime/project-memory review data remains unchanged.

- [ ] **Step 7: Commit the Memory overview convergence**

```powershell
git add -- web/src/routes/MemoryOverviewPanel.tsx web/src/routes/MemoryOverviewPanel.styles.ts web/src/routes/MemoryRoute.layout.test.ts
git commit -m "style(web): unify Memory overview hierarchy"
```

---

### Task 5: Converge Memory Manage And Graph Workspaces

**Files:**
- Modify: `web/src/routes/MemoryRoute.layout.test.ts`
- Modify: `web/src/routes/MemoryManagePanel.tsx`
- Modify: `web/src/routes/MemoryManagePanel.styles.ts`
- Modify: `web/src/routes/MemoryGraphViewPanel.tsx`
- Modify: `web/src/routes/MemoryGraphViewPanel.styles.ts`

**Interfaces:**
- Consumes: `VSurface`, `VSection`, `VStateSurface`, `VMetricStrip`, and existing Memory callbacks.
- Produces: three raised manage columns, a flat filter section, a shared empty state, one graph metric strip, and three primary graph columns.

- [ ] **Step 1: Write failing Memory manage/graph composition tests**

Add to `MemoryRoute.layout.test.ts`:

```ts
it("uses shared Phase 2 surfaces for Memory manage and graph workspaces", () => {
  expect(managePanelSource).toContain("VSurface");
  expect(managePanelSource).toContain("VSection");
  expect(managePanelSource).toContain("VStateSurface");
  expect(managePanelStyles.manageFilterPanel).not.toContain("bg-[var(--vui-surface-panel)]");
  expect(graphViewPanelSource).toContain("VMetricStrip");
  expect(graphViewPanelSource).toContain("VSurface");
  expect(graphViewPanelSource).not.toContain("styles.summaryCard");
  expect(graphViewPanelStyles.sourcePanel).not.toContain("bg-[var(--vui-surface-panel)]");
  expect(graphViewPanelStyles.graphCanvasPanel).not.toContain("rounded-[var(--radius-panel)]");
});
```

In the existing `tightens Memory detail, manage, source, and graph surfaces without glass card walls` test, delete the three assertions that read `graphViewPanelStyles.summaryGrid` or `graphViewPanelStyles.summaryCard`; the new `VMetricStrip` source assertions above replace that retired style-map contract.

- [ ] **Step 2: Run Memory layout tests and verify RED**

Run: `npm --prefix web run test -- MemoryRoute.layout.test.ts`

Expected: FAIL because manage/graph primary columns and graph summary still own route-local panel/card chrome.

- [ ] **Step 3: Convert Memory manage primary columns to VSurface**

Change the import to:

```ts
import { VButton, VNativeInput, VSection, VStateSurface, VSurface } from "../components/vui";
```

Replace the exact opening tag `<main className={styles.manageListPanel}>` with the following opening tag, and replace its matching `</main>` with `</VSurface>`. Do not change any child header, search, filter, bulk-action, or `memoryList` JSX:

```tsx
<VSurface as="main" className={styles.manageListPanel} elevation="panel" tone="rail">
</VSurface>
```

Replace the exact opening tag `<section className={styles.manageFormPanel}>` with the following opening tag, and replace its matching `</section>` with `</VSurface>`. Do not change the child editor header, editor, `selectedConfig`, or empty-state branch until Step 4:

```tsx
<VSurface className={styles.manageFormPanel} elevation="panel" tone="rail">
</VSurface>
```

The third `detailPanel` is already a dedicated primary detail surface and remains unchanged in this task.

- [ ] **Step 4: Flatten the manage filter group and use VStateSurface for empty selection**

Replace the manage-filter wrapper/header with:

```tsx
<VSection
  className={styles.manageFilterPanel}
  title={copy.manageFilters}
  meta={visibleItemCount}
  aria-label={copy.manageFilters}
>
  <div className={styles.filterGroup}>
    {manageFilterOptions.map((option) => (
      <VButton
        key={option.id}
        type="button"
        className={option.id === activeManageFilterId ? `${styles.filterButton} ${styles.filterButtonActive}` : styles.filterButton}
        onClick={() => onManageFilterChange(option.id)}
        aria-pressed={option.id === activeManageFilterId}
      >
        <span>{option.label}</span>
        <strong>{option.count}</strong>
      </VButton>
    ))}
  </div>
</VSection>
```

Replace the empty-selection section with:

```tsx
<VStateSurface className={styles.emptyDetail} icon={<Brain size={18} />} title={copy.selectedMemory} tone="empty">
  {copy.noMatches}
</VStateSurface>
```

Keep all destructive, selection, create/edit, and bulk callbacks unchanged.

- [ ] **Step 5: Reduce manage style hooks to geometry**

Set:

```ts
manageFilterPanel:
  "manageFilterPanel gap-1.5 border-y border-[var(--vui-border-hairline)] py-1.5",
manageFormPanel:
  "manageFormPanel min-h-0 overflow-auto grid gap-1 text-[var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full [&>p]:hidden",
manageListPanel:
  "manageListPanel grid min-h-0 content-start gap-1.5 overflow-auto",
emptyDetail:
  "emptyDetail min-h-[96px]",
```

Delete `manageFilterHeader`; it is replaced by `VSection` title/meta.

- [ ] **Step 6: Replace the graph summary cards with VMetricStrip**

Change the graph import to:

```ts
import { VButton, VMetricStrip, VNativeInput, VSection, VSurface } from "../components/vui";
```

Replace the six-card summary grid with:

```tsx
<VMetricStrip
  ariaLabel={copy.knowledgeGraph}
  metrics={[
    { id: "visible-nodes", label: copy.graphVisibleNodes, value: filteredGraphNodes.length, detail: `${copy.graphNodes}: ${graphPayload?.summary.nodeCount ?? 0}` },
    { id: "visible-edges", label: copy.graphVisibleEdges, value: filteredGraphEdges.length, detail: `${copy.graphEdges}: ${graphPayload?.summary.edgeCount ?? 0}` },
    { id: "gpu", label: copy.graphGpu, value: graphPayload?.operatingBoundary.gpuPreferred ? copy.yes : copy.no },
    { id: "worker", label: copy.graphWorker, value: graphPayload?.operatingBoundary.layoutWorker ? copy.yes : copy.no },
    { id: "readonly", label: copy.graphReadOnly, value: graphPayload?.operatingBoundary.readOnly ? copy.yes : copy.no },
    { id: "acl", label: copy.graphAcl, value: graphPayload?.operatingBoundary.honorsKnowledgeAcl ? copy.yes : copy.no },
  ]}
/>
```

- [ ] **Step 7: Move graph primary chrome to VSurface and flatten the inner filter section**

Replace the exact opening `<aside className={styles.sourcePanel}>` and matching `</aside>` with the following `VSurface` opening and closing tags. Keep the existing panel header and search JSX unchanged:

```tsx
<VSurface as="aside" className={styles.sourcePanel} elevation="panel" tone="rail">
</VSurface>
```

Inside that surface, replace the exact `<section className={styles.managementPanel}>` wrapper and its existing `managementHeader` child with this `VSection` opening tag; retain the current `graphTypeList` and conditional clear button unchanged, then replace the matching `</section>` with `</VSection>`:

```tsx
<VSection className={styles.managementPanel} title={copy.graphNodes} eyebrow={copy.graphNodeTypes}>
</VSection>
```

Replace the exact opening `<main className={styles.graphCanvasPanel}>` and matching `</main>` with the following `VSurface` tags. Keep the current toolbar, `Suspense` canvas, and graph node list JSX unchanged:

```tsx
<VSurface as="main" className={styles.graphCanvasPanel} elevation="panel" tone="rail">
</VSurface>
```

`MemoryGraphNodeInspectorPanel` remains the third dedicated primary column. Do not change graph query data, worker loading, WebGL fallback, node selection, relation focus, or inspector callbacks.

Set these style hooks:

```ts
graphCanvasPanel:
  "graphCanvasPanel grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] gap-2 overflow-hidden",
managementPanel:
  "managementPanel gap-1.5 border-t border-[var(--vui-border-hairline)] pt-1.5",
sourcePanel:
  "sourcePanel min-h-0 overflow-auto",
```

Delete graph `summaryGrid` and `summaryCard` after their JSX is removed.

- [ ] **Step 8: Run Memory layout, graph, and control-boundary tests**

Run:

```powershell
npm --prefix web run test -- MemoryRoute.layout.test.ts vuiLayoutTemplates.test.tsx vuiPrimitives.test.tsx vuiImportBoundary.test.ts
```

Expected: PASS; Memory mutation/query/cleanup/graph assertions remain green and only rendering composition/style ownership changes.

- [ ] **Step 9: Commit Memory manage and graph convergence**

```powershell
git add -- `
  web/src/routes/MemoryManagePanel.tsx `
  web/src/routes/MemoryManagePanel.styles.ts `
  web/src/routes/MemoryGraphViewPanel.tsx `
  web/src/routes/MemoryGraphViewPanel.styles.ts `
  web/src/routes/MemoryRoute.layout.test.ts
git commit -m "style(web): converge Memory management workspaces"
```

---

### Task 6: Validate, Integrate, Refresh, And Close Phase 2

**Files:**
- Modify after successful evidence: `docs/superpowers/specs/2026-07-10-heroui-frontend-unification-design.md`
- Modify after successful evidence: `docs/superpowers/plans/2026-07-10-heroui-frontend-unification-phase-2.md`
- Regenerate only from validated local `main` under a memory claim: `.docs/project-memory/**`, `PROJECT_MEMORY.html`

**Interfaces:**
- Consumes: Tasks 1-5 commits.
- Produces: fresh focused validation, browser evidence, local-main integration, Launcher current/ready evidence, project-memory sync, claim release, and Phase 2 completion status.

- [ ] **Step 1: Run the complete focused Phase 2 suite**

Run:

```powershell
npm --prefix web run test -- `
  workbenchVisualMatrix.test.ts `
  AgentManagementProduct.test.tsx `
  AgentsRoute.layout.test.ts `
  TeamsRoute.layout.test.ts `
  TeamsRoute.logic.test.ts `
  TeamsRoute.canvas-data.test.ts `
  teamsRouteViewModel.test.ts `
  MemoryRoute.layout.test.ts `
  vuiImportBoundary.test.ts `
  vuiPrimitives.test.tsx `
  vuiLayoutTemplates.test.tsx `
  vuiThemeFoundation.test.tsx
```

Expected: every named file passes with zero failed tests.

- [ ] **Step 2: Run production build and scoped repository checks**

```powershell
npm --prefix web run build
git diff --check main...HEAD
git status --short --branch
git diff --stat main...HEAD
git log --oneline main..HEAD
```

Expected: build exits 0; diff check is empty; only the planned Phase 2 files appear; no backend, DTO, query-key, i18n hot-file, dependency, version, or unrelated dirty file appears.

- [ ] **Step 3: Self-review product and import boundaries**

```powershell
rg -n 'from "@heroui/react"|from ''@heroui/react''' `
  web/src/routes/AgentsRoute.tsx `
  web/src/routes/TeamsRoute.tsx `
  web/src/routes/MemoryRoute.tsx `
  web/src/routes/MemoryOverviewPanel.tsx `
  web/src/routes/MemoryManagePanel.tsx `
  web/src/routes/MemoryGraphViewPanel.tsx
git diff main...HEAD -- `
  web/src/routes/TeamsRoute.tsx `
  web/src/routes/MemoryManagePanel.tsx `
  web/src/routes/MemoryGraphViewPanel.tsx
```

Expected: no direct HeroUI import; diff changes composition/styles/tests only and leaves fetch URLs, query keys, mutations, caches, permission checks, archive/purge/cleanup confirmation, canvas callbacks, and graph callbacks unchanged.

- [ ] **Step 4: Reconcile against current local main before merging**

From the root checkout:

```powershell
git branch --show-current
git status --short --branch
& '.venv\Scripts\python.exe' `
  'C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py' `
  'C:\Users\17533\Desktop\Vibelution' status --json
git diff --name-only main...codex/heroui-frontend-unification-phase-2
```

Expected: root remains `main`; current unrelated dirty files are reviewed and do not overlap the Phase 2 frontend paths; no active claim overlaps the implementation files. If local `main` advanced, merge `main` into the task branch, rerun Steps 1-3, then return to this gate.

- [ ] **Step 5: Merge one reviewed Phase 2 branch into local main**

```powershell
git merge --no-ff codex/heroui-frontend-unification-phase-2 -m "Merge HeroUI frontend unification Phase 2"
```

Expected: merge succeeds without staging or modifying unrelated root dirty files. On a semantic conflict, abort the merge and resolve in the task worktree; do not overwrite another Agent's files.

- [ ] **Step 6: Run the smallest decisive post-merge tests on root main**

```powershell
npm --prefix web run test -- `
  AgentManagementProduct.test.tsx `
  AgentsRoute.layout.test.ts `
  TeamsRoute.layout.test.ts `
  MemoryRoute.layout.test.ts `
  workbenchVisualMatrix.test.ts
npm --prefix web run build
git diff --check HEAD^1..HEAD
```

Expected: zero failed tests, build exit 0, and merge diff check empty.

- [ ] **Step 7: Refresh through Launcher only when active work is clear**

Check `/api/launcher/status` or Launcher status first. If active work is nonzero, report exactly:

```text
有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。
```

Do not treat a previous force-takeover phrase as reusable authorization. When active work is zero, run:

```powershell
powershell -ExecutionPolicy Bypass -File `
  "C:\Users\17533\Desktop\Vibelution\scripts\vibelution_launcher.ps1" `
  -Action restart
```

Poll the actual Launcher conditions until `Session: current`, `Frontend: current`, overall state `ready`, backend healthy, browser alive, active work `0`, and pending/processing command counts `0`.

- [ ] **Step 8: Collect live Phase 2 browser evidence**

Use the in-app Browser and validate these routes in both light and dark themes:

```text
/agents
/teams
/memory
/memory/manage
/memory/graph
```

At `1280×720`, `1440×900`, and `1920×1080`, verify:

- no page-level horizontal overflow or clipped primary action;
- Agent primary columns remain readable and repeated filter/entity rows are flat;
- Team unavailable/loading states stay inside the route shell and expose facts plus recovery action;
- Team canvas, nodes, edge layers, room actions, and archive disabled reasons remain usable;
- Memory overview/manage/graph use metric strips and primary surfaces without nested card walls;
- text buttons remain content-sized, icon actions remain square and named;
- longest realistic Chinese and English labels do not overlap;
- loading, empty, unavailable, error, disabled, busy, selected, and destructive states preserve geometry;
- hover/focus states are reachable for interactive controls;
- browser console has zero new error or warning entries attributable to Phase 2.

Any failure returns to its owning task, followed by focused tests, build, Launcher refresh, and the same viewport/theme check.

- [ ] **Step 9: Record Phase 2 completion in the design and plan**

Update the design status to:

```markdown
- **Status:** Phase 1 and Phase 2 implemented and locally validated; Evolution/operational and remaining-route phases remain planned separately
- **Implementation link:** `docs/superpowers/plans/2026-07-10-heroui-frontend-unification-phase-2.md`
- **Validation:** Phase 1 AppShell/Chat and Phase 2 Agents/Teams/Memory focused Vitest, production build, scoped diff review, Launcher refresh, and three-viewport light/dark browser evidence passed
```

Add immediately below this plan header:

```markdown
> **Implementation status:** complete on 2026-07-10 after focused tests, production build, scoped diff review, Launcher refresh, and live Agents/Teams/Memory desktop verification.
```

Commit the two governance files on local main:

```powershell
git add -- `
  docs/superpowers/specs/2026-07-10-heroui-frontend-unification-design.md `
  docs/superpowers/plans/2026-07-10-heroui-frontend-unification-phase-2.md
git commit -m "docs(web): record HeroUI Phase 2 validation"
```

- [ ] **Step 10: Sync project memory under a separate memory claim**

```powershell
$python = "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe"
$guard = "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py"
$sync = "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\sync_project_memory.py"
$project = "C:\Users\17533\Desktop\Vibelution"
$memoryClaimJson = & $python $guard $project claim `
  --lane "web-workbench-surface" `
  --scope ".docs/project-memory" `
  --scope "PROJECT_MEMORY.html" `
  --agent "codex-heroui-frontend-unification" `
  --task "Sync HeroUI frontend Phase 2 memory · main" `
  --ttl-minutes 60 `
  --note "Record validated Agents, Teams, and Memory visual convergence" `
  --json
$memoryClaim = $memoryClaimJson | ConvertFrom-Json
if (-not $memoryClaim.ok -or -not $memoryClaim.claim.id) {
  throw "Unable to acquire the Phase 2 project-memory claim."
}
& $python $sync $project `
  --lane "web-workbench-surface" `
  --owner "codex-heroui-frontend-unification" `
  --focus "HeroUI Phase 2 Agents/Teams/Memory validated on local main" `
  --phase "validated-runtime" `
  --health green `
  --update "HeroUI frontend Phase 2 applies the Phase 1 soft-layer contract to Agents, Teams, and Memory: raised primary management surfaces, flat repeated rows and filters, shared metric strips, VUI-owned unavailable/empty states, preserved canvas/graph/lifecycle behavior, and three-viewport light/dark live verification. Focused Vitest, production build, scoped diff review, Launcher current/ready checks, and browser console review passed; no remote push or PR."
if ($LASTEXITCODE -ne 0) {
  & $python $guard $project release --claim-id $memoryClaim.claim.id --status blocked --reason "HeroUI Phase 2 memory sync failed."
  throw "Project-memory sync failed."
}
& $python $guard $project release --claim-id $memoryClaim.claim.id --status completed --reason "HeroUI Phase 2 memory synced and rendered."
```

Verify the exact focus/update appears in `memory.json`, `lanes/web-workbench-surface.json`, `overview.html`, `INDEX.md`, and root `PROJECT_MEMORY.html`.

- [ ] **Step 11: Release the implementation claim and remove the clean worktree**

```powershell
& $python $guard $project release `
  --claim-id $implementationClaim.claim.id `
  --status completed `
  --reason "HeroUI Phase 2 tests, build, scoped review, local-main integration, Launcher refresh, live browser evidence, and project-memory sync completed."
git -C "C:\Users\17533\Desktop\Vibelution" worktree remove `
  "C:\Users\17533\Desktop\Vibelution-worktrees\heroui-frontend-unification-phase-2"
git -C "C:\Users\17533\Desktop\Vibelution" branch -d `
  "codex/heroui-frontend-unification-phase-2"
```

Expected: implementation claim is completed, worktree is clean and removed, merged local branch is deleted, local `main` remains current, unrelated root dirty files are preserved, and no remote operation occurs.

---

## Plan Review Gate

### Spec Coverage

- Phase 2 route group `Agents + Teams + Memory`: Tasks 2-5.
- Reuse Phase 1 foundation without route-level HeroUI: all tasks; enforced by Task 6.
- Raised primary panels with flat repeated content: Tasks 2-5.
- Metric/status strips instead of dashboard card walls: Tasks 4-5.
- Shared loading/empty/unavailable states: Tasks 3 and 5.
- Existing lifecycle, cache, permission, destructive, canvas, and graph behavior: protected by Global Constraints and focused behavior tests.
- Desktop `1280×720`, `1440×900`, `1920×1080`, light/dark, overflow, focus, console: Tasks 1 and 6.
- Launcher, memory, version, local-main integration, and no remote publication: Task 6.

### Review Matrix

| Challenge | Evidence | Gate conclusion |
| --- | --- | --- |
| Agents is already heavily VUI-migrated; extra changes could be churn | Task 2 changes only the primary surface tone/elevation and repeated row/filter chrome; query, route, and editor components are untouched | PASS |
| Teams has an active backend research claim and a 13k-line route | The plan claims only three frontend files, never touches backend/DTO/query-key files, and changes two unavailable branches plus the outer canvas surface/action wrapper | PASS |
| Memory has many independent management panels | Tasks 4-5 target the highest-level overview/manage/graph workspaces and reuse existing extracted components; no cleanup, mutation, graph, or permission path moves | PASS |
| Raised primary surfaces could recreate a card wall | Only primary workspace columns use `elevation="panel"`; repeated rows/filter groups/metrics are explicitly flattened or strip-based | PASS |
| Full-width buttons might be incorrectly removed | Full-width remains on entity-row actions where the whole row is clickable; compact toolbar and mutation actions remain content-sized | PASS |
| Route visual changes could hide blockers or destructive consequences | VStateSurface keeps unavailable facts/retry visible; existing archive/purge/cleanup labels, disabled reasons, confirmations, and failure branches remain in place | PASS |

### Placeholder And Type Consistency Check

- The plan contains no unresolved placeholder markers or undefined helper/type.
- Every implementation task names exact files, RED command, minimal code, GREEN command, and scoped commit.
- `tone="rail"`, `elevation="panel"`, `VMetricStrip`, `VStateSurface`, `VSection`, and `VActionGroup` match the currently exported VUI APIs.
- The plan introduces no API, DTO, query-key, dependency, version-file, or backend write.

## Execution Handoff

Two supported execution routes:

1. **Inline Execution — recommended for this repository:** use `executing-plans` in one Phase 2 worktree, complete Tasks 1-6 sequentially, and stop only at the merge/Launcher safety gates. This avoids subagent write overlap with active local claims.
2. **Subagent-Driven:** use `subagent-driven-development` with one fresh worker per task and two-stage review, but only if the user explicitly requests subagents; current repository instructions otherwise prohibit spawning them.
