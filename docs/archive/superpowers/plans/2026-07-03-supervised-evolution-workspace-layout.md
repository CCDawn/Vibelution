# Supervised Evolution Workspace Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the supervised evolution page so the first viewport behaves like a dense operations workspace instead of a mostly empty conversation canvas with stacked cards.

**Architecture:** Keep existing backend and worktree-run data authority intact. Change only the supervised evolution route, its Tailwind style helpers, the top workflow stepper styles, and the existing layout contract tests.

**Tech Stack:** React, TypeScript, Tailwind utility class strings, Vitest static layout contracts, Vite build.

## Global Constraints

- Keep root `C:\Users\17533\Desktop\Vibelution` on `main`; implement in `C:\Users\17533\Desktop\Vibelution-worktrees\supervised-evolution-workspace-layout`.
- Do not change backend supervised evolution behavior or worktree-run action APIs.
- Use TDD: update tests first, verify they fail, then implement.
- Preserve active worktree-run termination/approval/merge data paths.
- Avoid nested cards and large empty operational bands.

---

### Task 1: Replace Old Layout Contract Tests

**Files:**
- Modify: `web/src/routes/SupervisedWorkspaceControls.test.ts`
- Modify: `web/src/routes/EvolutionRoute.layout.test.ts`

**Interfaces:**
- Consumes: existing raw-source test pattern with `routeSource`, `stylesSource`, `tabsStylesSource`.
- Produces: failing tests that require compact stepper styles, flattened workflow presentation, and center overview fallback names.

- [ ] **Step 1: Write failing test expectations**

In `SupervisedWorkspaceControls.test.ts`, replace fixed-width rail expectations with compact stepper expectations:

```ts
expect(tabsStylesSource).toContain("flex-[0_1_620px]");
expect(tabsStylesSource).toContain("grid-cols-[repeat(4,minmax(88px,1fr))]");
expect(tabsStylesSource).not.toContain("flex-[1_1_860px]");
expect(tabsStylesSource).not.toContain("max-w-[920px]");
expect(tabsStylesSource).not.toContain("grid-cols-[repeat(4,minmax(132px,1fr))]");
```

In `EvolutionRoute.layout.test.ts`, add a supervised workspace test requiring:

```ts
expect(routeSource).toContain("selectedWorkflowOverviewItems");
expect(routeSource).toContain("styles.caseOverviewWorkspace");
expect(routeSource).toContain("selectedWorkflowHasConversationMessages ? (");
expect(routeSource).toContain("styles.workflowStepRail");
expect(routeSource).not.toContain("styles.supervisedWorkflowCardGrid");
expect(stylesSource).toContain(".caseOverviewWorkspace");
expect(stylesSource).toContain(".workflowStepRail");
expect(stylesSource).not.toContain(".supervisedWorkflowCardGrid");
expect(stylesSource).not.toContain(".supervisedWorkflowCardButton");
```

- [ ] **Step 2: Verify red**

Run:

```powershell
npm --prefix web run test -- SupervisedWorkspaceControls.test.ts EvolutionRoute.layout.test.ts
```

Expected: FAIL because the compact stepper, center overview fallback, and flattened workflow rail do not exist yet.

### Task 2: Implement Compact Stepper Styles

**Files:**
- Modify: `web/src/routes/SupervisedWorkspaceTabs.styles.ts`
- Modify: `web/src/routes/SupervisedWorkspaceTabs.tsx`

**Interfaces:**
- Consumes: `SupervisedWorkspaceTabSummary`, `WORKFLOW_STEPS`, `activeWorkflowStepId`.
- Produces: the same tab behavior with smaller layout footprint and no large card-rail sizing.

- [ ] **Step 1: Update style helper values**

Set `flowTabsClass` to a bounded stepper footprint:

```ts
"grid flex-[0_1_620px] grid-cols-[repeat(4,minmax(88px,1fr))] gap-1 rounded-md border border-vui-border-soft",
"min-w-[min(420px,100%)] max-w-[680px] bg-[var(--surface-panel-muted)] p-[2px]",
```

Keep `role="tab"` and existing click behavior.

- [ ] **Step 2: Verify focused control tests**

Run:

```powershell
npm --prefix web run test -- SupervisedWorkspaceControls.test.ts
```

Expected: PASS.

### Task 3: Flatten Workflow Cards Into A Rail

**Files:**
- Modify: `web/src/routes/EvolutionRoute.tsx`
- Modify: `web/src/routes/EvolutionRoute.styles.ts`

**Interfaces:**
- Consumes: `supervisedWorkflowCards`, `supervisedSelectedWorkflowStep`, `setSelectedSupervisedWorkflowStepId`.
- Produces: `.workflowStepRail`, `.workflowStepButton`, `.workflowStepPreview`, `.workflowStepMeta` route style entries.

- [ ] **Step 1: Replace card wall JSX**

Replace the `supervisedWorkflowCardGrid` article/button/footer block with a flat rail:

```tsx
<div className={styles.workflowStepRail} aria-label={lang === "zh" ? "监督进化步骤导航" : "Supervised evolution step navigation"}>
  {supervisedWorkflowCards.map((step) => {
    const selected = step.id === supervisedSelectedWorkflowStep.id;
    const current = step.id === supervisedRuntimeWorkflowStepId;
    return (
      <button
        key={step.id}
        type="button"
        className={selected ? `${styles.workflowStepButton} ${styles.workflowStepButtonActive}` : styles.workflowStepButton}
        aria-pressed={selected}
        onClick={() => setSelectedSupervisedWorkflowStepId(step.id)}
      >
        <span className={styles.workflowStepMeta}>{current ? (lang === "zh" ? "当前" : "Live") : statusLabel(step.status)}</span>
        <strong>{supervisedWorkflowStepLabel(step, lang)}</strong>
        <span className={styles.workflowStepPreview}>{step.livePreview || step.summary || (lang === "zh" ? "等待实时输出" : "Waiting for live output")}</span>
      </button>
    );
  })}
</div>
```

- [ ] **Step 2: Remove old nested card style exports**

Delete style entries for `supervisedWorkflowCardGrid`, `supervisedWorkflowCard`, `supervisedWorkflowCardButton`, `supervisedWorkflowCardFooter`, `supervisedWorkflowLivePreview`, and update references to the new rail names.

- [ ] **Step 3: Verify layout tests still fail only on center fallback**

Run:

```powershell
npm --prefix web run test -- EvolutionRoute.layout.test.ts
```

Expected: FAIL only for missing `selectedWorkflowOverviewItems` / `caseOverviewWorkspace` if Task 4 is not complete yet.

### Task 4: Add Center Overview Fallback

**Files:**
- Modify: `web/src/routes/EvolutionRoute.tsx`
- Modify: `web/src/routes/EvolutionRoute.styles.ts`

**Interfaces:**
- Consumes: `selectedWorkflowHasConversationMessages`, `selectedWorkflowTaskSummary`, `selectedWorkflowConversationNotice`, `supervisedClosedLoopRecord`, `monitoredRun`, selected step metadata.
- Produces: `selectedWorkflowOverviewItems` and `.caseOverviewWorkspace` fallback DOM.

- [ ] **Step 1: Derive overview items before render**

Add:

```ts
const selectedWorkflowOverviewItems = [
  { label: lang === "zh" ? "阶段" : "Stage", value: supervisedWorkflowStepLabel(supervisedSelectedWorkflowStep, lang) },
  { label: lang === "zh" ? "状态" : "Status", value: statusLabel(supervisedSelectedWorkflowStep.status) },
  { label: lang === "zh" ? "摘要" : "Summary", value: selectedWorkflowTaskSummary || selectedWorkflowConversationNotice },
  { label: lang === "zh" ? "最近闭环" : "Latest ledger", value: supervisedClosedLoopDecisionLabel || supervisedClosedLoopRecord?.nextAction.label || "--" },
];
```

- [ ] **Step 2: Render fallback when messages are absent**

Wrap the current `LazyConversationView` branch:

```tsx
{selectedWorkflowHasConversationMessages ? (
  <LazyConversationView ... />
) : (
  <div className={styles.caseOverviewWorkspace}>
    {selectedWorkflowOverviewItems.map((item) => (
      <article key={item.label} className={styles.caseOverviewItem}>
        <span>{item.label}</span>
        <strong>{item.value || "--"}</strong>
      </article>
    ))}
    {supervisedLiveConversationSupplement}
  </div>
)}
```

- [ ] **Step 3: Add fallback styles**

Add `caseOverviewWorkspace` and `caseOverviewItem` style entries with compact grid rows, no nested card wall, and internal scrolling.

- [ ] **Step 4: Verify focused layout tests**

Run:

```powershell
npm --prefix web run test -- SupervisedWorkspaceControls.test.ts EvolutionRoute.layout.test.ts
```

Expected: PASS.

### Task 5: Validate Build And Review

**Files:**
- Review all changed files from `git diff --stat`.

**Interfaces:**
- Consumes: completed implementation.
- Produces: validation evidence and merge-ready branch.

- [ ] **Step 1: Run web build**

Run:

```powershell
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 2: Run diff check**

Run:

```powershell
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 3: Self-review**

Run:

```powershell
git diff -- web/src/routes/SupervisedWorkspaceControls.test.ts web/src/routes/SupervisedWorkspaceTabs.styles.ts web/src/routes/EvolutionRoute.layout.test.ts web/src/routes/EvolutionRoute.tsx web/src/routes/EvolutionRoute.styles.ts
```

Expected: changes are limited to the supervised layout contract, no backend API or worktree authority changes.
