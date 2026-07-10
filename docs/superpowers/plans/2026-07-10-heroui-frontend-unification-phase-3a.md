# HeroUI Frontend Unification Phase 3A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Converge Kernel, Usage, Logs, and Git into the established VUI desktop operations hierarchy without changing data sources, actions, Git/log semantics, or task lifecycle behavior.

**Architecture:** Routes retain query, mutation, selection, resize, scroll, and local-state ownership. Existing VUI compositions (VSurface, VMetricStrip, VStateSurface, and VActionGroup) replace route-local layout/state shells. HeroUI remains behind the VUI boundary. Deliver Kernel/Usage, then Logs/Git, then the 24-scenario desktop matrix.

**Tech Stack:** React 19, TypeScript, TanStack Query, VUI, HeroUI through VUI, Tailwind CSS v4, Vitest, Vite.

## Global Constraints

- Create C:\Users\17533\Desktop\Vibelution-worktrees\heroui-frontend-unification-phase-3a on codex/heroui-frontend-unification-phase-3a, based on current local main.
- Before every write scope run memory guard status, check, then a narrow claim; release only after fresh evidence.
- Touch only route, style, layout-test, and visual-matrix files named in this plan. Do not change backend APIs, DTOs, query keys, local-storage keys, usage normalization, Git commands, Logs cleanup behavior, task lifecycle, permissions, dictionaries, dependencies, versions, or package metadata.
- Import VUI only from ../components/vui; do not introduce direct route-level @heroui/react imports.
- Preserve /kernel, /usage, /logs, /git; preserve Logs resizing, preview, deletion confirmation; preserve Git file selection, commit, and worktree behavior.
- Text buttons are content sized and icon buttons are square. Full-width buttons are permitted only for semantic row selection.
- At 1280×720, 1440×900, and 1920×1080, do not allow page-level horizontal overflow, clipping, overlap, or state-driven layout shifts.
- Keep errors, destructive consequences, and commit blockers directly visible. Tooltips are supplementary only.
- Keep this desktop-only; preserve, but do not redesign, narrow-width behavior.
- Use TDD: add a focused test, observe failure, implement the minimum, rerun the test, inspect the scoped diff, then commit.
- Final verification includes focused Vitest, npm --prefix web run build, git diff --check, browser screenshots, console review, and a Launcher refresh decision. If active work blocks refresh, report 有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。.
- Version impact is patch for the completed implementation; this task does not edit version files. No push, PR, publication, remote deletion, or force operation is authorized.

---

## File Map

| Files | Responsibility |
| --- | --- |
| web/src/routes/KernelTaskCenterRoute.tsx, .styles.ts, .layout.test.ts | VUI surfaces, metric strip, task/timeline states, flat task and lifecycle rows. |
| web/src/routes/UsageRoute.tsx, .styles.ts, .layout.test.ts | VUI totals strip, honest not-called/error states, unchanged usage-source rows. |
| web/src/routes/LogsRoute.tsx, .styles.ts, .layout.test.ts | VUI major surfaces/state blocks while retaining resizable preview and cleanup semantics. |
| web/src/routes/GitRoute.tsx, .styles.ts, .layout.test.ts | VUI summary/state/action compositions while retaining file, diff, commit, and worktree semantics. |
| web/src/visual-regression/workbenchvisualmatrix.ts, .test.ts | 24 Phase 3A stable scenarios on top of the existing 18. |

## Preflight

Run before Task 1:

    git -C 'C:\Users\17533\Desktop\Vibelution' status --short --branch
    git -C 'C:\Users\17533\Desktop\Vibelution' worktree add -b 'codex/heroui-frontend-unification-phase-3a' 'C:\Users\17533\Desktop\Vibelution-worktrees\heroui-frontend-unification-phase-3a' main
    & 'C:\Users\17533\AppData\Local\Programs\Python\Python312\python.exe' 'C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py' 'C:\Users\17533\Desktop\Vibelution' status
    & 'C:\Users\17533\AppData\Local\Programs\Python\Python312\python.exe' 'C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py' 'C:\Users\17533\Desktop\Vibelution' check --scope 'web/src/routes/KernelTaskCenterRoute.tsx,web/src/routes/KernelTaskCenterRoute.styles.ts,web/src/routes/KernelTaskCenterRoute.layout.test.ts,web/src/routes/UsageRoute.tsx,web/src/routes/UsageRoute.styles.ts,web/src/routes/UsageRoute.layout.test.ts'

Expected: root has no current-task changes, task worktree exists, and no active or ready claim overlaps Kernel/Usage.

### Task 1: Converge Kernel Task Center

**Files:**

- Modify: web/src/routes/KernelTaskCenterRoute.tsx
- Modify: web/src/routes/KernelTaskCenterRoute.styles.ts
- Test: web/src/routes/KernelTaskCenterRoute.layout.test.ts

**Interfaces:** Consume existing listKernelTasks(status, 120), getKernelTaskTimeline(selectedTaskId), URL-query selection, KernelTask, KernelTaskTimeline, and useShellI18n. Produce a read-only VUI route; retain query functions, URL semantics, selection, and data shapes.

- [ ] **Step 1: Write the failing layout contract**

Add this test:

    it("maps Kernel task state and facts through shared VUI compositions", () => {
      expect(routeSource).toContain("VSurface");
      expect(routeSource).toContain("VMetricStrip");
      expect(routeSource).toContain("VStateSurface");
      expect(routeSource).toContain("VActionGroup");
      expect(routeSource).toContain('ariaLabel={copy.taskList}');
      expect(routeSource).toContain('ariaLabel={copy.detail}');
      expect(styles.taskRowClass).toContain("w-full");
      expect(styles.taskRowSelectedClass).toContain("border-");
    });

- [ ] **Step 2: Verify failure**

    npm --prefix web test -- src/routes/KernelTaskCenterRoute.layout.test.ts

Expected: FAIL because required VUI imports are absent.

- [ ] **Step 3: Implement the minimal Kernel surface migration**

Replace the VUI import with:

    import { VActionGroup, VButton, VIconButton, VMetricStrip, VRouteHeader, VSelect, VStateSurface, VSurface } from "../components/vui";

Use VActionGroup ariaLabel={copy.status} around the existing filter and refresh controls. Define taskPaneContent as the existing task-query conditional after changing its three state branches to VStateSurface. Define timelinePaneContent as the existing selected-task conditional after changing its no-selection, error, and loading branches to VStateSurface. Replace outer task/detail sections with:

    <VSurface as="aside" ariaLabel={copy.taskList} className={styles.taskPaneClass} elevation="panel" padding="none" tone="rail">
      {taskPaneContent}
    </VSurface>
    <VSurface as="main" ariaLabel={copy.detail} className={styles.detailPaneClass} elevation="panel" padding="compact" tone="panel">
      {timelinePaneContent}
    </VSurface>

taskPaneContent maps existing error/loading/empty task branches to VStateSurface tones error/loading/empty. timelinePaneContent retains current detail, ledger, and lifecycle JSX after handling no selection, timeline error, and timeline loading.

Replace five existing metric cards with:

    <VMetricStrip
      ariaLabel={copy.detail}
      className={styles.summaryGridClass}
      metrics={[
        { id: "authority", label: copy.factAuthority, value: timeline.readModel.truthSource || "-", tone: "info" },
        { id: "view", label: copy.viewType, value: timeline.readModel.projection ? copy.projectionView : copy.directView },
        { id: "event", label: copy.event, value: shortId(timeline.event.eventId) },
        { id: "work-run", label: copy.workRun, value: shortId(timeline.execution.workRunId) },
        { id: "outcome", label: copy.outcome, value: timeline.outcome.status || "-" },
      ]}
    />

Delete obsolete local Metric and EmptyState functions. Keep TaskRow as a full-row VButton, keep delivery/evidence/lifecycle entries flat, retain all query and selection calls. Change summaryGridClass to "min-w-0 max-w-full overflow-x-auto", ledgerSectionClass to "grid min-w-0 gap-[7px] border-t border-vui-border-soft pt-2", and ledgerBucketClass to "grid min-w-0 content-start gap-[7px]". Retain all internal-scroll and long-ID constraints.

- [ ] **Step 4: Verify and commit Kernel**

    npm --prefix web test -- src/routes/KernelTaskCenterRoute.layout.test.ts src/components/vui/vuiImportBoundary.test.ts
    git diff --check
    git diff -- web/src/routes/KernelTaskCenterRoute.tsx web/src/routes/KernelTaskCenterRoute.styles.ts web/src/routes/KernelTaskCenterRoute.layout.test.ts
    git add -- web/src/routes/KernelTaskCenterRoute.tsx web/src/routes/KernelTaskCenterRoute.styles.ts web/src/routes/KernelTaskCenterRoute.layout.test.ts
    git commit -m "style(web): unify Kernel task center hierarchy"

Expected: PASS; no mutation/POST appears; commit contains only the three Kernel files.

### Task 2: Converge Usage Metric and State Hierarchy

**Files:**

- Modify: web/src/routes/UsageRoute.tsx
- Modify: web/src/routes/UsageRoute.styles.ts
- Test: web/src/routes/UsageRoute.layout.test.ts

**Interfaces:** Consume current UsageSummaryResponse, queryKeys.usageSummary("global"), UsageSource, and useAppI18n. Produce VUI totals strip and truthful state surface without changing source classification or numeric rollups.

- [ ] **Step 1: Write the failing layout contract**

    it("uses a metric strip and distinguishes not-called usage from zero usage", () => {
      expect(routeSource).toContain("VMetricStrip");
      expect(routeSource).toContain("VStateSurface");
      expect(routeSource).toContain('lastSource === "not_called"');
      expect(routeSource).toContain("尚未调用");
      expect(routeSource).toContain("Not called yet");
      expect(styles.overviewBand).toContain("min-w-0");
    });

- [ ] **Step 2: Verify failure**

    npm --prefix web test -- src/routes/UsageRoute.layout.test.ts

Expected: FAIL because shared compositions are absent.

- [ ] **Step 3: Implement the minimal Usage migration**

Replace the VUI import with:

    import { VIconButton, VMetricStrip, VRouteHeader, VStateSurface, VStatusStrip, VSurface } from "../components/vui";

Replace overview cards with:

    <VMetricStrip
      ariaLabel={label(lang, "Token 用量概览", "Token usage overview")}
      className={styles.overviewBand}
      metrics={[
        { id: "all-time", label: label(lang, "全局累计", "All time"), value: numberText(allTime.totalTokens) },
        { id: "today", label: label(lang, "今日", "Today"), value: numberText(today.totalTokens) },
        { id: "last-seven-days", label: label(lang, "最近七日", "Last 7 days"), value: numberText(last7Days.totalTokens) },
        { id: "latest", label: label(lang, "最近一次", "Latest"), value: numberText(lastTokenUsage?.totalTokens), detail: formatTimestamp(lastTokenUsage?.recordedAt, lang) },
      ]}
      status={{ label: sourceLabel(lastSource, lang), tone: lastSource === "provider_usage" ? "success" : lastSource === "missing" ? "warning" : "info" }}
    />

Immediately below it render query error as VStateSurface tone="error", and !summary or lastSource === "not_called" as VStateSurface titled 尚未调用 / Not called yet with tone based on usageQuery.isFetching. Do not show missing usage as a successful zero. Wrap existing composition, rollup, and record panels in VSurface. Preserve source tiles, progress/breakdown rows, EMPTY_ROLLUP, rollupOrEmpty, sourceCount, query URL, and refresh behavior. Set overviewBand to "mx-3 mt-2 min-w-0 max-w-full overflow-x-auto" and add emptyState "mx-3 mt-2 min-w-0 max-w-full". Remove heroMetric, overviewStats, and overviewStat only after all references are gone.

- [ ] **Step 4: Verify and commit Usage**

    npm --prefix web test -- src/routes/UsageRoute.layout.test.ts src/components/vui/vuiImportBoundary.test.ts
    git diff --check
    git diff -- web/src/routes/UsageRoute.tsx web/src/routes/UsageRoute.styles.ts web/src/routes/UsageRoute.layout.test.ts
    git add -- web/src/routes/UsageRoute.tsx web/src/routes/UsageRoute.styles.ts web/src/routes/UsageRoute.layout.test.ts
    git commit -m "style(web): unify Usage metric hierarchy"

Expected: PASS; retain /api/usage/summary, queryKeys.usageSummary("global"), and source labels provider_usage, estimated, missing, not_called; no cost/billing behavior.

### Task 3: Converge Logs Without Changing Resizers, Preview, or Cleanup

**Files:**

- Modify: web/src/routes/LogsRoute.tsx
- Modify: web/src/routes/LogsRoute.styles.ts
- Test: web/src/routes/LogsRoute.layout.test.ts

**Interfaces:** Consume index/content queries, LOG_SIDEBAR_STORAGE_KEY, LOG_RIGHT_RAIL_STORAGE_KEY, width normalization, deep-link parsing, preview renderer, and cleanup callbacks. Produce the same three-column workspace with VUI major surfaces and explicit states.

- [ ] **Step 1: Write the failing layout contract**

    it("uses VUI surfaces without changing the resizable logs contract", () => {
      expect(routeSource).toContain("VSurface");
      expect(routeSource).toContain("VStateSurface");
      expect(routeSource).toContain("VActionGroup");
      expect(routeSource).toContain("LOG_SIDEBAR_STORAGE_KEY");
      expect(routeSource).toContain("LOG_RIGHT_RAIL_STORAGE_KEY");
      expect(styles.resizableLayout).toContain("grid-cols-[var(--logs-sidebar-width)_auto_minmax(0,1fr)]");
      expect(styles.packageButtonPath).toContain("truncate");
      expect(styles.rootButtonPath).toContain("truncate");
      expect(styles.deleteButton).toContain("w-fit");
    });

- [ ] **Step 2: Verify failure**

    npm --prefix web test -- src/routes/LogsRoute.layout.test.ts

Expected: FAIL because required VUI compositions are absent.

- [ ] **Step 3: Implement Logs composition boundaries only**

Replace the VUI import with:

    import { VActionGroup, VButton, VIconButton, VNativeInput, VRouteHeader, VStateSurface, VStatusStrip, VSurface } from "../components/vui";

Use VSurface as="aside" for existing sidebar and right rail. Preserve their classes, children, resize handles, style variables, and query/resizer code. In renderLogIndexState and renderLogPreviewState replace only the outer local state shell with:

    <VStateSurface className={styles.stateSurface} tone={tone} title={title} skeletonLines={tone === "loading" ? 2 : false}>
      {detail}
    </VStateSurface>

Wrap only existing clear/delete controls in VActionGroup ariaLabel={t("logsCleanupActions")}. Keep callbacks, disabled rules, confirmation, labels, and deletion behavior exactly unchanged. Add only:

    stateSurface: "stateSurface min-w-0 max-w-full",
    cleanupActionGroup: "cleanupActionGroup min-w-0 border-t border-[var(--vui-border-soft)] pt-1.5",

Do not modify resizableLayout, workspace, previewPane, numeric resize constants, LazyFilePreview, or runtime-scene deep-link parsing. Keep path truncation; add a title only where a long-path element lacks full-value disclosure.

- [ ] **Step 4: Verify and commit Logs**

    npm --prefix web test -- src/routes/LogsRoute.layout.test.ts src/components/vui/vuiImportBoundary.test.ts
    git diff --check
    git diff -- web/src/routes/LogsRoute.tsx web/src/routes/LogsRoute.styles.ts web/src/routes/LogsRoute.layout.test.ts
    git add -- web/src/routes/LogsRoute.tsx web/src/routes/LogsRoute.styles.ts web/src/routes/LogsRoute.layout.test.ts
    git commit -m "style(web): unify Logs workspace hierarchy"

Expected: PASS; resizer keys/helpers, preview ordering, deep links, and delete callbacks remain intact; commit contains only the three Logs files.

### Task 4: Converge Git Without Changing Commit or Worktree Semantics

**Files:**

- Modify: web/src/routes/GitRoute.tsx
- Modify: web/src/routes/GitRoute.styles.ts
- Test: web/src/routes/GitRoute.layout.test.ts

**Interfaces:** Consume Git status/diff/config/commit queries, selected files, commitSelected, generateMessage, stagedOutsideSelection, commit blocker state, and useGitRouteI18n. Produce VUI summaries/states/action grouping without changing Git commands or route copy.

- [ ] **Step 1: Write the failing layout contract**

    it("uses VUI metrics, state, and action grouping without changing Git ownership", () => {
      expect(routeSource).toContain("VMetricStrip");
      expect(routeSource).toContain("VStateSurface");
      expect(routeSource).toContain("VActionGroup");
      expect(routeSource).toContain("commitSelected");
      expect(routeSource).toContain("generateMessage");
      expect(routeSource).toContain("stagedOutsideSelection");
      expect(routeSource).toContain("commitBlockReasonText");
      expect(gitRouteStyles.fileButton).toContain("grid-cols-[22px_34px_minmax(0,1fr)]");
      expect(gitRouteStyles.commitActions).toContain("flex");
    });

- [ ] **Step 2: Verify failure**

    npm --prefix web test -- src/routes/GitRoute.layout.test.ts

Expected: FAIL because required VUI compositions are absent.

- [ ] **Step 3: Implement the minimal Git migration**

Replace the VUI import with:

    import { VActionGroup, VButton, VIconButton, VMetricStrip, VNativeButton, VNativeSelect, VNativeTextarea, VRouteHeader, VStateSurface, VSurface } from "../components/vui";

Replace six summary cards with:

    <VMetricStrip
      ariaLabel={t("gitPageTitle")}
      className={styles.summaryGrid}
      metrics={[
        { id: "branch", label: t("gitBranch"), value: status?.branch || status?.headRevShort || "-" },
        { id: "changed", label: t("gitChangedFiles"), value: status?.counts.total ?? 0 },
        { id: "upstream", label: t("gitUpstream"), value: upstream?.name || upstream?.remote || t("gitNoUpstream") },
        { id: "ahead-behind", label: t("gitAheadBehind"), value: aheadBehind },
        { id: "local-commits", label: t("gitLocalCommits"), value: localCommitCount },
        { id: "worktrees", label: t("gitWorktreeBranches"), value: [worktreeBranchCount, worktreeTotalCount].join(" / ") },
      ]}
    />

Render unavailable and initial empty preview states with VStateSurface, preserving current conditions/copy. Use VSurface for changed-file rail, diff workspace, and commit rail without altering classes, responsive grid placement, PaneCollapseHandle, file selection, diff queries, or worktree selection.

Replace the current commitActions wrapper with VActionGroup and keep its two existing VButton children unchanged:

    <VActionGroup ariaLabel={t("gitManualCommit")} className={styles.commitActions}>
      <VButton type="button" variant="secondary" className={styles.secondaryButton} onPress={generateMessage} isDisabled={aiDisabled} title={aiDraftBlockReasonText || undefined} icon={<Bot size={15} />}>
        {generateMessageMutation.isPending ? t("gitAiGenerating") : t("gitAiGenerateMessage")}
      </VButton>
      <VButton type="button" variant="primary" className={styles.primaryButton} onPress={commitSelected} isDisabled={commitDisabled} title={commitBlockReasonText || undefined} icon={<GitCommitHorizontal size={15} />}>
        {commitMutation.isPending ? t("gitCommitting") : t("gitCommitSelected")}
      </VButton>
    </VActionGroup>

The two controls retain current callbacks, disabled values, titles, icons, and busy labels. Keep commitBlockReasonText in current direct commitBlockReason element. Do not change commitDisabled, stagedOutsideSelection, mutations, or i18n keys. Set summaryGrid to "mx-3 mt-1.5 min-w-0 max-w-full overflow-x-auto" and commitActions to "flex min-w-0 flex-wrap justify-end gap-1.5 max-[520px]:justify-start".

- [ ] **Step 4: Verify and commit Git**

    npm --prefix web test -- src/routes/GitRoute.layout.test.ts src/routes/gitRouteLogic.test.ts src/components/vui/vuiImportBoundary.test.ts
    git diff --check
    git diff -- web/src/routes/GitRoute.tsx web/src/routes/GitRoute.styles.ts web/src/routes/GitRoute.layout.test.ts
    git add -- web/src/routes/GitRoute.tsx web/src/routes/GitRoute.styles.ts web/src/routes/GitRoute.layout.test.ts
    git commit -m "style(web): unify Git operations hierarchy"

Expected: PASS; no i18n/API/DTO/Git-command/worktree behavior files enter the commit.

### Task 5: Add the 24-Scenario Phase 3A Desktop Visual Matrix

**Files:**

- Modify: web/src/visual-regression/workbenchvisualmatrix.ts
- Test: web/src/visual-regression/workbenchvisualmatrix.test.ts

**Interfaces:** Consume WorkbenchVisualScenario, WORKBENCH_DESKTOP_VIEWPORTS, and existing scenarios. Produce six dense screenshot scenarios per Phase 3A route: light/dark × compact/standard/wide.

- [ ] **Step 1: Write the failing coverage test**

    it("covers all stable Phase 3A operational route combinations", () => {
      const paths = ["/kernel", "/usage", "/logs", "/git"];
      const scenarios = WORKBENCH_VISUAL_SCENARIOS.filter((scenario) => paths.includes(scenario.path));
      expect(scenarios).toHaveLength(24);
      for (const path of paths) {
        const routeScenarios = scenarios.filter((scenario) => scenario.path === path);
        expect(routeScenarios).toHaveLength(6);
        expect(routeScenarios.map((scenario) => scenario.theme).sort()).toEqual(["dark", "dark", "dark", "light", "light", "light"]);
        expect(routeScenarios.map((scenario) => scenario.viewport.width).sort((left, right) => left - right)).toEqual([1280, 1280, 1440, 1440, 1920, 1920]);
        expect(routeScenarios.every((scenario) => scenario.state === "dense" && scenario.expectedEvidence === "screenshot")).toBe(true);
      }
    });

- [ ] **Step 2: Verify failure**

    npm --prefix web test -- src/visual-regression/workbenchvisualmatrix.test.ts

Expected: FAIL because no Phase 3A scenarios exist.

- [ ] **Step 3: Add complete scenario generator**

Add above WORKBENCH_VISUAL_SCENARIOS:

    const PHASE_3A_ROUTE_FOCUS = [
      { path: "/kernel", id: "kernel", focus: ["task queue row density", "selected task and lifecycle hierarchy"] },
      { path: "/usage", id: "usage", focus: ["metric strip readability", "truthful usage-source state"] },
      { path: "/logs", id: "logs", focus: ["resizable preview hierarchy", "long path and cleanup visibility"] },
      { path: "/git", id: "git", focus: ["file/diff/commit hierarchy", "direct commit blocker visibility"] },
    ] as const;

    const PHASE_3A_THEME_VIEWPORTS = [
      { theme: "light" as const, viewport: compact, viewportId: "compact" },
      { theme: "light" as const, viewport: standard, viewportId: "standard" },
      { theme: "light" as const, viewport: wide, viewportId: "wide" },
      { theme: "dark" as const, viewport: compact, viewportId: "compact" },
      { theme: "dark" as const, viewport: standard, viewportId: "standard" },
      { theme: "dark" as const, viewport: wide, viewportId: "wide" },
    ] as const;

    const PHASE_3A_VISUAL_SCENARIOS: WorkbenchVisualScenario[] = PHASE_3A_ROUTE_FOCUS.flatMap((route) =>
      PHASE_3A_THEME_VIEWPORTS.map(({ theme, viewport, viewportId }) => ({
        id: [route.id, theme, "default", viewportId, "dense"].join("-"),
        path: route.path,
        theme,
        background: "default",
        viewport,
        state: "dense",
        reviewFocus: route.focus,
        expectedEvidence: "screenshot",
      })),
    );

Append ...PHASE_3A_VISUAL_SCENARIOS to current array. Update existing coverage expectations to include four paths and total length from 18 to 42. Do not alter earlier scenarios.

- [ ] **Step 4: Verify and commit matrix**

    npm --prefix web test -- src/visual-regression/workbenchvisualmatrix.test.ts src/routes/KernelTaskCenterRoute.layout.test.ts src/routes/UsageRoute.layout.test.ts src/routes/LogsRoute.layout.test.ts src/routes/GitRoute.layout.test.ts src/components/vui/vuiImportBoundary.test.ts
    git diff --check
    git add -- web/src/visual-regression/workbenchvisualmatrix.ts web/src/visual-regression/workbenchvisualmatrix.test.ts
    git commit -m "test(web): cover Phase 3A operations visual matrix"

Expected: PASS; total matrix is 42 and exactly 24 stable Phase 3A combinations exist.

### Task 6: Build, Launcher, Browser Evidence, and Local-Main Closeout

**Files:** No product-code edits. Write .docs/project-memory only with a separate claim and owning sync/render tool.

**Interfaces:** Consume task commits, focused suites, Launcher status, and visual matrix. Produce fresh local-main evidence, explicit refresh result, memory/claim decision, and patch-impact report.

- [ ] **Step 1: Verify complete task branch**

    npm --prefix web test -- src/routes/KernelTaskCenterRoute.layout.test.ts src/routes/UsageRoute.layout.test.ts src/routes/LogsRoute.layout.test.ts src/routes/GitRoute.layout.test.ts src/routes/gitRouteLogic.test.ts src/components/vui/vuiImportBoundary.test.ts src/visual-regression/workbenchvisualmatrix.test.ts
    npm --prefix web run build
    git diff main...HEAD --check
    git diff main...HEAD --name-only
    git status --short --branch

Expected: all tests/build PASS; worktree clean; only fourteen planned frontend files appear. Any backend/API/DTO/query/i18n/version/package/config/Git-command/log-cleanup file blocks integration.

- [ ] **Step 2: Fast-forward only when root is clean**

    git -C 'C:\Users\17533\Desktop\Vibelution' status --short --branch
    git -C 'C:\Users\17533\Desktop\Vibelution' merge --ff-only codex/heroui-frontend-unification-phase-3a
    git -C 'C:\Users\17533\Desktop\Vibelution' status --short --branch
    npm --prefix 'C:\Users\17533\Desktop\Vibelution\web' test -- src/routes/KernelTaskCenterRoute.layout.test.ts src/routes/UsageRoute.layout.test.ts src/routes/LogsRoute.layout.test.ts src/routes/GitRoute.layout.test.ts src/components/vui/vuiImportBoundary.test.ts src/visual-regression/workbenchvisualmatrix.test.ts
    npm --prefix 'C:\Users\17533\Desktop\Vibelution\web' run build

Expected: fast-forward and fresh root verification PASS. If root is dirty or cannot fast-forward, stop and preserve all work; never reset, overwrite, or force merge.

- [ ] **Step 3: Refresh by Launcher and collect visual evidence**

Query Launcher status first. If active work exists, stop with the mandated block message. Otherwise refresh through Launcher, then inspect all 24 stable scenarios plus:

    Kernel: loading, empty/filter-empty, error, selected task, long task/ref.
    Usage: loading, not-called, API error, provider/estimated/missing source, long values.
    Logs: index/preview loading, missing/empty/partial/error, long path disclosure, cleanup, resizer focus.
    Git: loading, clean, unavailable, selected file, disabled/busy commit, direct blocker.

For every check, review page overflow, clipping, overlap, focus, inner scrolling, theme contrast, and application console errors. Record browser-plugin telemetry separately from application-console failures.

- [ ] **Step 4: Sync memory and release claims**

Acquire a separate memory claim before writing project memory. Use installed project-memory sync/render workflow, never hand-edit generated views. Release implementation claim with commit IDs, root test/build result, Launcher result, browser matrix result, version impact patch, and residual risk. Report no remote push/PR.

## Plan Self-Review

| Requirement | Task coverage |
| --- | --- |
| Kernel compact queue, selection, lifecycle, and states | Task 1 |
| Usage metric strip and truthful not-called state | Task 2 |
| Logs resizers, preview, paths, and cleanup boundary | Task 3 |
| Git metrics, clean/error states, commit/worktree behavior | Task 4 |
| Four routes × two themes × three viewports | Tasks 5–6 |
| Tests, VUI boundary, build, diff, browser, Launcher | Tasks 1–6 |
| Claim, memory, version, remote decisions | Global Constraints and Task 6 |

The plan specifies concrete files, test code, implementation interfaces, commands, expected outcomes, commit scopes, and recovery gates. It uses current VUI APIs, adds no i18n key, does not enter Phase 3B, and makes no protected business-semantic change.

## Execution Handoff

Plan complete and saved to docs/superpowers/plans/2026-07-10-heroui-frontend-unification-phase-3a.md.

Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task and review every task before continuing.
2. **Inline Execution** — execute tasks in this session through executing-plans, with checkpoints after Kernel/Usage, Logs/Git, and closeout.

Which approach?
