# HeroUI Frontend Unification Phase 3B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Status:** completed-local-main
**Owner:** codex-heroui-phase3b-plan
**Claim:** claim-37484783343d
**Scope:** aggressive VUI/HeroUI migration for /supervised-evolution, /self-evolution, and /config
**Spec:** docs/superpowers/specs/2026-07-11-heroui-frontend-unification-phase-3b-design.md
**Goal:** Move all supported visible Evolution and Config controls plus repeated panels behind VUI/HeroUI while retaining current state owners and business semantics.

**Architecture:** Add one shared VStringSelect adapter over VSelect for existing string-value selection flows. Migrate Evolution and Config in independent commits, then add eighteen visual scenarios and perform a claim-bound local-main and Launcher/browser closeout.

**Tech Stack:** React, TypeScript, TanStack Query, EventSource, HeroUI behind VUI, Tailwind style maps, Vitest, Vite.

## Global Constraints

- Do not change backend routes/services, DTOs, query keys, cache ownership, EventSource behavior, permissions, or C:\Users\17533\Documents\Vibelution\config\config.toml.
- Do not add direct @heroui/react imports outside web/src/components/vui.
- The bridge maps display selection to an existing callback only; it must not create drafts, mutate data, synthesize defaults, or own a cache.
- Native-control exceptions are hidden file inputs, resize/drag affordances, and accessibility-only internals. They stay non-primary and contract-tested.
- Preserve callback order, disabled rules, confirmations, errors, scroll regions, and resizer ownership.
- Logging is not affected; developer/formal mode parity is preserved; version impact is expected to be patch.

## Planned File Map

| Files | Responsibility |
| --- | --- |
| web/src/components/vui/forms/VStringSelect.tsx, .test.tsx, index.ts | Shared string-value VSelect adapter and tests. |
| EvolutionRoute.tsx, .styles.ts, EvolutionActiveRunMonitorPanel, EvolutionProposalActionBandsPanel, EvolutionRunRecordsPanel | Supervised Evolution controls and repeated work surfaces. |
| ConfigRoute.tsx, .styles.ts, ConfigModelLibraryPanel, ConfigDraftPanel, ConfigOverviewPanel, ConfigRuntimePanel, ConfigHealthDiagnosticsPanel, ConfigWorkspacePlaceholderPanel | Config shell, form controls, and repeated panels. |
| EvolutionRoute.layout.test.ts, evolutionLiveRun.test.ts, ConfigRoute.layout.test.ts, configRouteLogic.test.ts | VUI boundary and existing state-contract regression coverage. |
| workbenchVisualMatrix.ts, .test.ts | Eighteen Phase 3B scenarios; total becomes 60. |

### Task 1: Add the VUI String-Select Bridge

**Files:**
- Create: web/src/components/vui/forms/VStringSelect.tsx
- Create: web/src/components/vui/forms/VStringSelect.test.tsx
- Modify: web/src/components/vui/index.ts

**Interfaces:**
- Consumes: VSelect, VSelectOption, React Key.
- Produces: VStringSelectOption, VStringSelectProps, resolveStringSelectChange.
- Excludes: React Query, mutations, EventSource, route drafts, and API payloads.

- [x] **Step 1: Write the failing behavior tests**

    import { describe, expect, it } from "vitest";
    import { resolveStringSelectChange } from "./VStringSelect";

    const options = [
      { value: "safe", label: "Safe" },
      { value: "disabled", label: "Disabled", disabled: true },
    ];

    describe("resolveStringSelectChange", () => {
      it("returns an enabled selection", () => {
        expect(resolveStringSelectChange("safe", options)).toBe("safe");
      });
      it("rejects empty, unknown, and disabled selections", () => {
        expect(resolveStringSelectChange(null, options)).toBeNull();
        expect(resolveStringSelectChange("unknown", options)).toBeNull();
        expect(resolveStringSelectChange("disabled", options)).toBeNull();
      });
    });

- [x] **Step 2: Verify RED**

    npm --prefix web exec vitest run src/components/vui/forms/VStringSelect.test.tsx

Expected: FAIL because the component and resolver do not exist.

- [x] **Step 3: Implement the smallest adapter**

    import { type Key, type ReactNode } from "react";
    import { VSelect, type VSelectOption } from "./VSelect";

    export type VStringSelectOption = {
      value: string;
      label: ReactNode;
      description?: ReactNode;
      disabled?: boolean;
    };

    export type VStringSelectProps = {
      ariaLabel: string;
      className?: string;
      isDisabled?: boolean;
      onValueChange: (value: string) => void;
      options: readonly VStringSelectOption[];
      placeholder?: string;
      value: string;
    };

    export function resolveStringSelectChange(
      key: Key | null,
      options: readonly VStringSelectOption[],
    ): string | null {
      const value = key == null ? "" : String(key);
      const option = options.find((candidate) => candidate.value === value);
      return option && !option.disabled ? option.value : null;
    }

    export function VStringSelect({
      ariaLabel, className, isDisabled, onValueChange, options, placeholder, value,
    }: VStringSelectProps) {
      const vuiOptions: VSelectOption[] = options.map((option) => ({
        id: option.value,
        label: option.label,
        description: option.description,
        disabled: option.disabled,
      }));
      return (
        <VSelect
          aria-label={ariaLabel}
          className={className}
          isDisabled={isDisabled}
          options={vuiOptions}
          placeholder={placeholder}
          selectedKey={value || null}
          onSelectionChange={(key) => {
            const nextValue = resolveStringSelectChange(key, options);
            if (nextValue !== null && nextValue !== value) onValueChange(nextValue);
          }}
        />
      );
    }

Export the component, resolver, and types from the VUI index.

- [x] **Step 4: Verify GREEN**

    npm --prefix web exec vitest run src/components/vui/forms/VStringSelect.test.tsx src/components/vui/vuiForms.test.tsx

Expected: PASS; only enabled known keys resolve, while empty/unknown/disabled keys cannot dispatch a route value callback.

- [x] **Step 5: Commit**

    git add -- web/src/components/vui/forms/VStringSelect.tsx web/src/components/vui/forms/VStringSelect.test.tsx web/src/components/vui/index.ts
    git commit -m "feat(vui): add string select bridge"

### Task 2: Migrate the Supervised Evolution Surface

**Files:**
- Modify: web/src/routes/EvolutionRoute.tsx and EvolutionRoute.styles.ts
- Modify: EvolutionActiveRunMonitorPanel.tsx and .styles.ts
- Modify: EvolutionProposalActionBandsPanel.tsx and .styles.ts
- Modify: EvolutionRunRecordsPanel.tsx and .styles.ts
- Modify: web/src/routes/EvolutionRoute.layout.test.ts
- Test: evolutionLiveRun.test.ts, supervisedRunSummary.test.ts, supervisedRunRecordLabel.test.ts

**Interfaces:**
- Consumes: Task 1 bridge; existing query/mutation callbacks, PaneCollapseHandle, stream parsing, selected IDs, and pane-size helpers.
- Produces: VUI route header, metric/status strips, state surfaces, supported form/action controls, and repeated panel surfaces.
- Excludes: evolutionLiveRun.ts, API types, query keys, EventSource parsing, payload shapes, mutation ownership, and resizer behavior.

- [x] **Step 1: Write failing Evolution layout assertions**

    expect(routeSource).toContain("VRouteHeader");
    expect(routeSource).toContain("VMetricStrip");
    expect(routeSource).toContain("VStateSurface");
    expect(routeSource).toContain("VStringSelect");
    expect(activeRunMonitorPanelSource).toContain("<VButton");
    expect(proposalActionBandsPanelSource).toContain("<VButton");
    expect(runRecordsPanelSource).toContain("<VButton");
    expect(evolutionSources).not.toContain("<VNativeButton");
    expect(evolutionSources).not.toContain("<VNativeInput");
    expect(evolutionSources).not.toContain("<VNativeSelect");
    expect(evolutionSources).not.toContain("<VNativeTextarea");

Keep assertions for parseRunStreamSnapshot, selectSupervisedRunStreamTarget, existing mutation handlers, and resize handles.

- [x] **Step 2: Verify RED**

    npm --prefix web exec vitest run src/routes/EvolutionRoute.layout.test.ts

Expected: FAIL because VNative controls remain and route-level VUI composition is absent.

- [x] **Step 3: Convert route controls and state surfaces**

    <VStringSelect
      ariaLabel={copy.source}
      value={selectedSource}
      options={sourceOptions.map((source) => ({
        value: source.value,
        label: source.label,
        disabled: source.disabled,
      }))}
      onValueChange={setSelectedSource}
    />
    <VInput
      aria-label={copy.runName}
      value={runName}
      onChange={(event) => setRunName(event.target.value)}
    />
    <VButton type="button" variant="primary" isDisabled={!canStartRun} onClick={startRun}>
      {copy.startRun}
    </VButton>

Use VRouteHeader, VMetricStrip, VSurface, VSection, and VStateSurface around current Live/Runs/Library content. Keep grid variables, pane handles, EventSource, query keys, and callbacks intact.

- [x] **Step 4: Convert all supported panel controls**

    <VButton
      type="button"
      variant="danger"
      isDisabled={isBusy || !canDelete}
      onClick={() => onDeleteRunRecord(run.runId)}
    >
      {copy.delete}
    </VButton>

Replace every VNativeButton, VNativeInput, VNativeSelect, and VNativeTextarea in the named panels. Do not move onRunAction, onDeleteRunRecord, proposal-action handlers, selected IDs, or local edit state into VUI.

- [x] **Step 5: Verify GREEN**

    npm --prefix web exec vitest run src/routes/EvolutionRoute.layout.test.ts src/routes/evolutionLiveRun.test.ts src/routes/supervisedRunSummary.test.ts src/routes/supervisedRunRecordLabel.test.ts

Expected: PASS; VUI boundaries pass and stream/run-summary/record-label behavior remains unchanged.

- [x] **Step 6: Commit**

    git add -- web/src/routes/EvolutionRoute.tsx web/src/routes/EvolutionRoute.styles.ts web/src/routes/EvolutionActiveRunMonitorPanel.tsx web/src/routes/EvolutionActiveRunMonitorPanel.styles.ts web/src/routes/EvolutionProposalActionBandsPanel.tsx web/src/routes/EvolutionProposalActionBandsPanel.styles.ts web/src/routes/EvolutionRunRecordsPanel.tsx web/src/routes/EvolutionRunRecordsPanel.styles.ts web/src/routes/EvolutionRoute.layout.test.ts
    git commit -m "style(web): unify Evolution control surfaces"

### Task 3: Migrate the Config Shell and Panels

**Files:**
- Modify: web/src/routes/ConfigRoute.tsx and ConfigRoute.styles.ts
- Modify: ConfigModelLibraryPanel.tsx and .styles.ts
- Modify: ConfigDraftPanel.tsx and .styles.ts
- Modify: ConfigOverviewPanel.tsx and .styles.ts
- Modify: ConfigRuntimePanel.tsx and .styles.ts
- Modify: ConfigHealthDiagnosticsPanel.tsx and .styles.ts
- Modify: ConfigWorkspacePlaceholderPanel.tsx and .styles.ts
- Modify: web/src/routes/ConfigRoute.layout.test.ts
- Test: web/src/routes/configRouteLogic.test.ts

**Interfaces:**
- Consumes: Task 1 bridge, current Config workspace/draft state, buildConfigApplyPayload, deriveConfigEditorSyncState, shouldBlockConfigLeave, and existing panel callbacks.
- Produces: VUI shell/panel/form controls with unchanged source path, draft, validation, save, restore, reload, secret, and leave-guard semantics.
- Excludes: API clients, configRouteLogic.ts, persistence payloads, secret behavior, external operator config, and mutation ownership.

- [x] **Step 1: Write failing Config boundary assertions**

    expect(routeSource).toContain("VRouteHeader");
    expect(routeSource).toContain("VStatusStrip");
    expect(routeSource).toContain("VStringSelect");
    expect(configSources).toContain("<VSurface");
    expect(configSources).toContain("<VSection");
    expect(configSources).not.toContain("<VNativeInput");
    expect(configSources).not.toContain("<VNativeSelect");
    expect(configSources).not.toContain("<VNativeTextarea");
    expect(configSources).not.toContain("<VNativeButton");
    expect(routeSource).toContain('type="file"');

Keep existing assertions for apply payloads, dirty/validation recovery, pending secrets, LazyJsonCodeMirror, and leave guards.

- [x] **Step 2: Verify RED**

    npm --prefix web exec vitest run src/routes/ConfigRoute.layout.test.ts

Expected: FAIL because VNative controls and non-VUI shell patterns remain.

- [x] **Step 3: Convert form fields without moving draft ownership**

    <VInput
      aria-label={label}
      value={getString(fieldValue)}
      onChange={(event) => updateSectionDraft(absolutePath, event.target.value)}
    />
    <VTextarea
      aria-label={label}
      value={getString(fieldValue)}
      minRows={3}
      onChange={(event) => updateSectionDraft(absolutePath, event.target.value)}
    />
    <VStringSelect
      ariaLabel={label}
      value={getString(fieldValue)}
      options={options.map((option) => ({
        value: option.value,
        label: option.label,
        disabled: option.disabled,
      }))}
      onValueChange={(nextValue) => updateSectionDraft(absolutePath, nextValue)}
    />

Keep hidden file inputs and pointer crop/resizer affordances native with existing accept, onChange, and pointer handling.

- [x] **Step 4: Convert shell and repeated panels**

    <VButton
      type="button"
      variant="primary"
      isDisabled={!canSaveConfig || Boolean(busyAction)}
      onClick={saveConfig}
    >
      {copy.save}
    </VButton>

Use VRouteHeader and VStatusStrip for source, dirty, validation, and restart facts; use VSurface, VSection, and VPanelHeader for listed panels. Do not move editor text, pending secrets, model-editor state, validation result, busy state, or query-client calls into VUI. Preserve CodeMirror and table scroll bounds.

- [x] **Step 5: Verify GREEN**

    npm --prefix web exec vitest run src/routes/ConfigRoute.layout.test.ts src/routes/configRouteLogic.test.ts

Expected: PASS; visual boundary moves to VUI while payloads, leave guard, validation recovery, and secret state remain unchanged.

- [x] **Step 6: Commit**

    git add -- web/src/routes/ConfigRoute.tsx web/src/routes/ConfigRoute.styles.ts web/src/routes/ConfigModelLibraryPanel.tsx web/src/routes/ConfigModelLibraryPanel.styles.ts web/src/routes/ConfigDraftPanel.tsx web/src/routes/ConfigDraftPanel.styles.ts web/src/routes/ConfigOverviewPanel.tsx web/src/routes/ConfigOverviewPanel.styles.ts web/src/routes/ConfigRuntimePanel.tsx web/src/routes/ConfigRuntimePanel.styles.ts web/src/routes/ConfigHealthDiagnosticsPanel.tsx web/src/routes/ConfigHealthDiagnosticsPanel.styles.ts web/src/routes/ConfigWorkspacePlaceholderPanel.tsx web/src/routes/ConfigWorkspacePlaceholderPanel.styles.ts web/src/routes/ConfigRoute.layout.test.ts
    git commit -m "style(web): unify Config control surfaces"

### Task 4: Expand Visual Coverage to 60 Scenarios

**Files:**
- Modify: web/src/visual-regression/workbenchVisualMatrix.ts
- Modify: web/src/visual-regression/workbenchVisualMatrix.test.ts

**Interfaces:**
- Consumes: current 42-scenario matrix and WORKBENCH_DESKTOP_VIEWPORTS.
- Produces: 18 stable scenarios for /supervised-evolution, /self-evolution, and /config at light/dark × 1280/1440/1920.

- [x] **Step 1: Write the failing matrix test**

    const paths = ["/supervised-evolution", "/self-evolution", "/config"];
    const phase3bScenarios = WORKBENCH_VISUAL_SCENARIOS.filter((scenario) => scenario.id.startsWith("phase3b-"));
    expect(phase3bScenarios).toHaveLength(18);
    expect(WORKBENCH_VISUAL_SCENARIOS).toHaveLength(60);
    for (const path of paths) {
      expect(phase3bScenarios.filter((scenario) => scenario.path === path)).toHaveLength(6);
    }
    expect(WORKBENCH_VISUAL_SCENARIOS.some((scenario) => scenario.id === "supervised-light-default-standard-blocker")).toBe(true);
    expect(WORKBENCH_VISUAL_SCENARIOS.some((scenario) => scenario.id === "config-light-default-standard-destructive")).toBe(true);

- [x] **Step 2: Verify RED**

    npm --prefix web exec vitest run src/visual-regression/workbenchVisualMatrix.test.ts

Expected: FAIL because the current matrix has 42 scenarios, no phase3b-prefixed scenarios, and no /self-evolution Phase 3B coverage.

- [x] **Step 3: Add route focus and scenarios**

    const PHASE_3B_ROUTE_FOCUS = [
      {
        path: "/supervised-evolution",
        id: "phase3b-supervised-evolution",
        focus: ["live run action hierarchy", "disabled and blocker state"],
      },
      {
        path: "/self-evolution",
        id: "phase3b-self-evolution",
        focus: ["track workspace hierarchy", "conversation and control separation"],
      },
      {
        path: "/config",
        id: "phase3b-config",
        focus: ["dirty/save status clarity", "dense form and model-library controls"],
      },
    ] as const;

Map every entry through the existing six light/dark × compact/standard/wide variants with dense state and screenshot evidence. Keep older blocker/error/destructive Config and supervised scenarios because they cover distinct non-stable states.

- [x] **Step 4: Verify GREEN and commit**

    npm --prefix web exec vitest run src/visual-regression/workbenchVisualMatrix.test.ts
    git add -- web/src/visual-regression/workbenchVisualMatrix.ts web/src/visual-regression/workbenchVisualMatrix.test.ts
    git commit -m "test(web): cover HeroUI Phase 3B visual matrix"

Expected: PASS; all prior scenarios remain and the total is exactly 60.

### Task 5: Integrate, Refresh, and Close

**Files:**
- Modify only files listed in Tasks 1-4.
- Sync after merge with the project-memory scripts for web-workbench-surface.

- [x] **Step 1: Create the implementation claim and task worktree**

    $root = "C:\Users\17533\Desktop\Vibelution"
    $worktree = "C:\Users\17533\Desktop\Vibelution-worktrees\heroui-frontend-unification-phase-3b"
    $branch = "codex/heroui-frontend-unification-phase-3b"
    $scopes = @(
      "web/src/components/vui/forms/VStringSelect.tsx",
      "web/src/components/vui/forms/VStringSelect.test.tsx",
      "web/src/components/vui/index.ts",
      "web/src/routes/EvolutionRoute.tsx",
      "web/src/routes/EvolutionRoute.styles.ts",
      "web/src/routes/EvolutionActiveRunMonitorPanel.tsx",
      "web/src/routes/EvolutionActiveRunMonitorPanel.styles.ts",
      "web/src/routes/EvolutionProposalActionBandsPanel.tsx",
      "web/src/routes/EvolutionProposalActionBandsPanel.styles.ts",
      "web/src/routes/EvolutionRunRecordsPanel.tsx",
      "web/src/routes/EvolutionRunRecordsPanel.styles.ts",
      "web/src/routes/EvolutionRoute.layout.test.ts",
      "web/src/routes/ConfigRoute.tsx",
      "web/src/routes/ConfigRoute.styles.ts",
      "web/src/routes/ConfigModelLibraryPanel.tsx",
      "web/src/routes/ConfigModelLibraryPanel.styles.ts",
      "web/src/routes/ConfigDraftPanel.tsx",
      "web/src/routes/ConfigDraftPanel.styles.ts",
      "web/src/routes/ConfigOverviewPanel.tsx",
      "web/src/routes/ConfigOverviewPanel.styles.ts",
      "web/src/routes/ConfigRuntimePanel.tsx",
      "web/src/routes/ConfigRuntimePanel.styles.ts",
      "web/src/routes/ConfigHealthDiagnosticsPanel.tsx",
      "web/src/routes/ConfigHealthDiagnosticsPanel.styles.ts",
      "web/src/routes/ConfigWorkspacePlaceholderPanel.tsx",
      "web/src/routes/ConfigWorkspacePlaceholderPanel.styles.ts",
      "web/src/routes/ConfigRoute.layout.test.ts",
      "web/src/visual-regression/workbenchVisualMatrix.ts",
      "web/src/visual-regression/workbenchVisualMatrix.test.ts"
    )
    $claimArgs = @($root, "claim", "--lane", "web-workbench-surface")
    foreach ($scope in $scopes) { $claimArgs += @("--scope", $scope) }
    $claim = & "$root\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" @claimArgs --agent codex-heroui-phase3b --task "Implement HeroUI Phase 3B" --ttl-minutes 240 --json | ConvertFrom-Json
    git -C $root worktree add $worktree -b $branch main

Expected: a non-overlapping claim and an isolated branch based on the then-current local main.

- [x] **Step 2: Run focused validation in the clean task worktree**

    npm --prefix web exec vitest run src/components/vui/forms/VStringSelect.test.tsx src/components/vui/vuiForms.test.tsx src/routes/EvolutionRoute.layout.test.ts src/routes/evolutionLiveRun.test.ts src/routes/supervisedRunSummary.test.ts src/routes/supervisedRunRecordLabel.test.ts src/routes/ConfigRoute.layout.test.ts src/routes/configRouteLogic.test.ts src/visual-regression/workbenchVisualMatrix.test.ts
    npm --prefix web run build
    git diff --check

Expected: all selected tests pass, build succeeds, and the diff is clean.

- [x] **Step 3: Close out and merge only when local main is current**

    & "$root\.venv\Scripts\python.exe" "$root\scripts\local_quality_gate.py" closeout --base main --claim-id $claim.claim.id
    & "$root\.venv\Scripts\python.exe" "$root\scripts\local_quality_gate.py" verify-manifest --claim-id $claim.claim.id
    git -C $root merge --ff-only $branch

Expected: the manifest is bound to current main and the clean task branch fast-forwards root main. If main moved, merge it into the task worktree and rerun closeout; do not force merge.

- [x] **Step 4: Refresh through Launcher and collect live evidence**

Read GET http://127.0.0.1:8000/api/launcher/status. If activeWorkRuns.count is nonzero, stop with the project-standard active-work block. Otherwise run:

    & "C:\Users\17533\Desktop\Vibelution\scripts\vibelution_launcher.ps1" -Action restart

Verify /supervised-evolution, /self-evolution, and /config in light/dark at 1280x720, 1440x900, and 1920x1080. Inspect 720px separately for page overflow. Check loading/ready geometry, disabled controls, safe blocker/error/destructive visibility, long labels, focus, internal scroll boundaries, and application console errors. Browser-plugin telemetry is not application-console evidence.

- [x] **Step 5: Synchronize memory and clean only task resources**

    $skillRoot = "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory"
    & "$root\.venv\Scripts\python.exe" "$skillRoot\scripts\sync_project_memory.py" $root --lane web-workbench-surface --focus "HeroUI Phase 3B Evolution and Config migration validated on local main" --phase validated-local-main --health green --update "Record final local-main SHA, focused checks, build, Launcher/browser evidence, no remote action, and patch impact."
    & "$root\.venv\Scripts\python.exe" "$skillRoot\scripts\render_overview.py" $root
    & "$root\.venv\Scripts\python.exe" "$skillRoot\scripts\agent_work_guard.py" $root release --claim-id $claim.claim.id --status completed --reason "Merged with focused tests, build, Launcher, and browser evidence."
    git -C $root worktree remove -- $worktree
    git -C $root branch -d $branch

Expected: project memory records the local-main SHA and validation; only the clean Phase 3B worktree and branch are removed. Do not push or create a PR.

## Plan Review Loop

| Lens | Challenge | Conclusion |
| --- | --- | --- |
| User intent | Does aggressive migration still preserve behavior? | PASS — Tasks 2-3 migrate supported visible controls while retaining callback and state ownership. |
| Reuse | Does the plan create a parallel form system? | PASS — Reuse current VUI primitives and adapt one string-select representation gap. |
| State ownership | Can VUI own a second Evolution/Config state? | PASS — Task interfaces exclude route drafts, query state, streams, and mutations from VUI. |
| Test evidence | Can style tests hide behavior regressions? | PASS — bridge behavior tests, existing logic tests, matrix, build, and live browser checks are all required. |
| Risk | Can scope leak into backend or operator config? | PASS — named files and global constraints prohibit it; native exceptions are audited. |

## Plan Self-Review and Ledger

- **Coverage:** Tasks 1-4 cover the bridge, Evolution, Config, native exceptions, state ownership, and 60-scenario visual evidence. Task 5 covers worktree, closeout, Launcher, memory, and cleanup.
- **Type consistency:** VStringSelectOption, VStringSelectProps, resolveStringSelectChange, value, and onValueChange are defined in Task 1 and used with the same spelling later.
- **Reuse decision:** ADAPT current VUI with one string-select bridge; do not install dependencies or import HeroUI in routes.
- **Unresolved risk:** VInput/VTextarea event parity and VSelect representation must prove RED then GREEN before route migration. Active work can block Launcher refresh.
- **Task 4 contract correction:** The 18 Phase 3B stable scenarios are identified by the phase3b ID prefix. The existing four target-route blocker/error/destructive scenarios remain in the 60-scenario total and are intentionally excluded from the 18-scenario new-coverage count.
- **Task graph:** ccdawn-task-splitting must determine the execution partition before implementation.
- **Local-main closeout:** `8c0dd93c` was validated after a clean fast-forward with the full Web suite, production build, Launcher restart, and the 18-combination browser matrix. No remote push or PR was created; version impact is patch-only.
- **Recommended next stage:** ccdawn-task-splitting, then execute in the named Phase 3B worktree.
