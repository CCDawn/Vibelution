# Compact Quick Provider Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the permanently split quick-setup workspace with a compact desktop input flow whose result area appears only after detection begins.

**Architecture:** Keep `ConfigRoute` and the existing Provider/config APIs as state and persistence owners. Change only `ConfigQuickSetupPanel` presentation and its typed Tailwind style map, protecting the progressive state contract with component and layout tests before browser verification.

**Tech Stack:** React 19, TypeScript 5.9, VUI primitives, Tailwind CSS 4, Vitest 3, Vite 8, Launcher-managed local runtime.

## Global Constraints

- Target only `/config` → 模型库 → 快速配置.
- Desktop verification only: 1280×720, 1600×900, and 1920×1080; no mobile or touch-specific layout.
- Do not change backend APIs, Provider draft behavior, model recommendation rules, credential storage, or operator config ownership.
- Do not add dependencies or import `@heroui/react` from the route.
- Formal config remains `C:\Users\17533\Documents\Vibelution\config\config.toml` and is written only after explicit confirmation.
- API keys must not appear in rendered result/error copy, logs, cache, fixtures, or project memory.
- Logging decision: reuse existing bounded config mutation logs because behavior and API orchestration do not change.
- Runtime refresh: required before user-facing verification.
- Version impact: patch; report only, do not edit version files.

## File Map

- Modify `web/src/routes/ConfigQuickSetupPanel.test.tsx`: progressive-rendering and action-state component contract.
- Modify `web/src/routes/ConfigQuickSetupPanel.tsx`: compact input flow and conditional status/preview rendering.
- Modify `web/src/routes/ConfigQuickSetupPanel.styles.ts`: bounded desktop geometry and stable control/result layouts.
- Modify `web/src/routes/ConfigRoute.layout.test.ts`: route-level layout and VUI boundary lock.
- No backend, API type, configuration, dependency, or version file changes.

---

### Task 1: Lock the progressive quick-setup behavior

**Files:**
- Test: `web/src/routes/ConfigQuickSetupPanel.test.tsx`

**Interfaces:**
- Consumes: `ConfigQuickSetupPanelProps`, `ProviderQuickSetupState`, and existing callbacks without signature changes.
- Produces: rendering assertions that require idle input to omit the result region and active phases to expose it.

- [ ] **Step 1: Replace the permanent-result assertion with failing progressive-state tests**

Update the first component test so it requires the new copy and no idle result surface:

```tsx
it("renders a compact input flow without an idle result panel", () => {
  const markup = renderToStaticMarkup(<ConfigQuickSetupPanel {...props()} />);

  expect(markup).toContain("连接一个模型服务");
  expect(markup).toContain("选择服务商");
  expect(markup).toContain('type="password"');
  expect(markup).toContain("高级参数");
  expect(markup).toContain("检测连接");
  expect(markup).not.toContain('data-quick-setup-result="true"');
  expect(markup).not.toContain("等待检测");
});
```

Change the phase table to assert the active result region and final action copy:

```tsx
it.each([
  ["checking", "正在检测连接"],
  ["review", "确认生成的配置"],
  ["saving", "正在保存配置"],
  ["success", "配置已保存"],
  ["error", "需要处理后重试"],
] as const)("renders the progressive result region for %s", (phase, title) => {
  const state = {
    ...initialProviderQuickSetupState(),
    phase,
    errorKind: phase === "error" ? "auth" as const : "" as const,
    errorMessage: phase === "error" ? "认证失败" : "",
  };
  const markup = renderToStaticMarkup(<ConfigQuickSetupPanel {...props({ state })} />);

  expect(markup).toContain('data-quick-setup-result="true"');
  expect(markup).toContain(title);
  if (phase === "review") expect(markup).toContain("保存并完成");
});
```

Keep the no-auth and secret-redaction tests. Add a review fixture with one discovered model so the model selector and save action are exercised.

```tsx
it("shows model confirmation only after detection reaches review", () => {
  const state = {
    ...initialProviderQuickSetupState(),
    phase: "review" as const,
    provider: {
      ...initialProviderWizardState(),
      templateId: "openai",
      providerId: "openai",
      label: "OpenAI 官方 API",
      baseUrl: "https://api.openai.com/v1",
      defaultProtocol: "responses",
    },
    discoveredModels: [{
      availability: "observed" as const,
      label: "GPT-5",
      modelKey: "openai/gpt-5",
      modelRef: "openai/gpt-5",
      status: "observed",
      upstreamId: "gpt-5",
      capabilities: {},
    }],
    selectedModelRef: "openai/gpt-5",
    recommendationReason: "使用 Provider 模板默认模型",
  };
  const markup = renderToStaticMarkup(<ConfigQuickSetupPanel {...props({ state })} />);

  expect(markup).toContain("默认模型");
  expect(markup).toContain("GPT-5");
  expect(markup).toContain("保存并完成");
});
```

- [ ] **Step 2: Run the component test and verify the new contract fails**

Run:

```powershell
npm --prefix web test -- ConfigQuickSetupPanel.test.tsx
```

Expected: FAIL because idle currently mounts `data-quick-setup-result="true"`, renders “等待检测”, and uses “检测并生成配置”.

- [ ] **Step 3: Commit the red test**

```powershell
git add -- web/src/routes/ConfigQuickSetupPanel.test.tsx
git commit -m "test(config): require progressive quick setup"
```

### Task 2: Implement the compact progressive panel

**Files:**
- Modify: `web/src/routes/ConfigQuickSetupPanel.tsx`
- Modify: `web/src/routes/ConfigQuickSetupPanel.styles.ts`
- Modify: `web/src/routes/ConfigRoute.layout.test.ts`
- Test: `web/src/routes/ConfigQuickSetupPanel.test.tsx`

**Interfaces:**
- Consumes: unchanged `ConfigQuickSetupPanelProps` callbacks: `onProviderChange`, `onCredentialChange`, `onDetect`, `onModelChange`, `onConfirm`, and `onReset`.
- Produces: an idle input band, conditional `data-quick-setup-result="true"` region, and stable phase-specific button copy.

- [ ] **Step 1: Add failing layout assertions**

Extend the quick-setup route contract in `ConfigRoute.layout.test.ts`:

```ts
expect(quickSetupStyles.workspace).toContain("max-w-[72rem]");
expect(quickSetupStyles.inputGrid).toContain("grid-template-columns");
expect(quickSetupSource).toContain('state.phase !== "input"');
expect(quickSetupStylesSource).not.toContain("min-h-[28rem]");
expect(quickSetupStylesSource).not.toContain("minmax(22rem,0.9fr)_minmax(28rem,1.1fr)");
```

Update the copy assertions from “检测并生成配置” / “确认并保存” to “检测连接” / “保存并完成”. Keep the VUI boundary assertion and the no-`@heroui/react` route assertion.

- [ ] **Step 2: Run the layout test and verify it fails**

Run:

```powershell
npm --prefix web test -- ConfigRoute.layout.test.ts
```

Expected: FAIL because the current style map defines permanent two-column geometry and `min-h-[28rem]`.

- [ ] **Step 3: Restructure the panel without changing orchestration**

In `ConfigQuickSetupPanel.tsx`:

- Change the heading to `title="连接一个模型服务"` and `meta="约 1 分钟"`.
- Derive `const showResult = state.phase !== "input";`.
- Keep Provider mapping, `canDetect`, `canConfirm`, credential rules, and all callback payloads unchanged.
- Render Provider, conditional API Key, and the detect button in one `styles.inputGrid`.
- Keep “高级参数” below the main input grid and closed by default.
- Use `检测中…` while checking, `重新检测` after error, and `检测连接` otherwise.
- Render the result section only when `showResult` is true:

Define the conditional copy and facts before the JSX so the result region does not need a second state owner:

```tsx
const detectLabel = state.phase === "checking"
  ? "检测中…"
  : state.phase === "error"
    ? "重新检测"
    : "检测连接";
const resultFacts = [
  { key: "provider", label: "Provider", value: state.provider.label || selectedTemplate?.label || "-" },
  { key: "endpoint", label: "端点", value: state.provider.baseUrl || "-" },
  { key: "protocol", label: "协议", value: state.provider.defaultProtocol || "-" },
  { key: "models", label: "发现模型", value: state.discoveredModels.length },
];
const resultMessage = state.phase === "error"
  ? state.errorMessage || "检测或保存未完成，请检查输入后重试。"
  : state.phase === "review"
    ? `推荐理由：${state.recommendationReason || "等待选择"}`
    : state.phase === "success"
      ? "当前模型连接已经保存并同步。"
      : "保持当前页面，完成后会在这里显示结果。";
```

```tsx
{showResult ? (
  <section className={styles.resultRegion} data-quick-setup-result="true" aria-live="polite">
    <div className={styles.resultHeader}>
      <h3 className={styles.resultTitle}>{result.title}</h3>
      <VStatusChip tone={state.phase === "error" ? "danger" : state.phase === "success" ? "success" : "accent"}>
        {state.phase}
      </VStatusChip>
    </div>
    <VStateSurface
      tone={result.tone}
      busy={state.phase === "checking" || state.phase === "saving"}
      skeletonLines={state.phase === "checking" ? 3 : false}
      title={result.title}
      facts={state.phase === "review" || state.phase === "success" ? resultFacts : []}
    >
      {resultMessage}
    </VStateSurface>
    {state.phase === "review" ? (
      <div className={styles.reviewActions}>
        <label className={styles.field}>
          <span>默认模型</span>
          <VStringSelect
            ariaLabel="默认模型"
            value={state.selectedModelRef}
            options={state.discoveredModels.map((model) => ({
              value: model.modelRef,
              label: model.label || model.modelRef,
              description: model.modelRef,
            }))}
            onValueChange={onModelChange}
          />
        </label>
        <VButton variant="ghost" onPress={onReset}>重新检测</VButton>
        <VButton variant="primary" isDisabled={!canConfirm} onPress={onConfirm}>保存并完成</VButton>
      </div>
    ) : null}
  </section>
) : null}
```

Keep error copy credential-free and do not add API calls or persistence in the component.

- [ ] **Step 4: Replace permanent split geometry with bounded desktop styles**

In `ConfigQuickSetupPanel.styles.ts`, replace `workspace`, `inputColumn`, `resultColumn`, and `modelList` with focused entries:

```ts
workspace: "vui-routes-configquicksetuppanel workspace grid w-full max-w-[72rem] min-w-0 gap-3",
inputPanel: `vui-routes-configquicksetuppanel inputPanel ${panelSurface} grid min-w-0 gap-3 p-4`,
inputGrid: "vui-routes-configquicksetuppanel inputGrid grid min-w-0 items-end [grid-template-columns:minmax(15rem,1fr)_minmax(18rem,1.2fr)_max-content] gap-3",
primaryAction: "vui-routes-configquicksetuppanel primaryAction min-w-[8.5rem] justify-center",
resultRegion: `vui-routes-configquicksetuppanel resultRegion ${panelSurface} grid min-w-0 gap-3 p-4`,
reviewActions: "vui-routes-configquicksetuppanel reviewActions grid min-w-0 items-end [grid-template-columns:minmax(18rem,1fr)_max-content_max-content] gap-2",
```

Preserve typed local style ownership. Do not add CSS modules, inline styles, full-width action buttons, or mobile breakpoint rules.

- [ ] **Step 5: Run focused tests until both contracts pass**

Run:

```powershell
npm --prefix web test -- ConfigQuickSetupPanel.test.tsx ConfigRoute.layout.test.ts
```

Expected: both files PASS; secret-redaction and no-auth tests remain green.

- [ ] **Step 6: Review the implementation diff and commit**

Run:

```powershell
git diff --check
git diff -- web/src/routes/ConfigQuickSetupPanel.tsx web/src/routes/ConfigQuickSetupPanel.styles.ts web/src/routes/ConfigQuickSetupPanel.test.tsx web/src/routes/ConfigRoute.layout.test.ts
```

Confirm no API, backend, Provider logic, config, dependency, or version files changed. Then:

```powershell
git add -- web/src/routes/ConfigQuickSetupPanel.tsx web/src/routes/ConfigQuickSetupPanel.styles.ts web/src/routes/ConfigQuickSetupPanel.test.tsx web/src/routes/ConfigRoute.layout.test.ts
git commit -m "feat(config): compact quick setup flow"
```

### Task 3: Validate, refresh, and integrate the user-visible result

**Files:**
- Verify only: task-branch diff and generated `web/dist` output (do not stage `web/dist` unless already tracked by project policy).
- Update after merge: project-memory lane through its owning sync tool, not by hand-editing generated HTML.

**Interfaces:**
- Consumes: Task 2 component behavior and style contract.
- Produces: build evidence, real desktop screenshots, Launcher-served bundle evidence, local-main integration, released claim, and project-memory reconciliation.

- [ ] **Step 1: Run focused and build validation in the task worktree**

Run:

```powershell
npm --prefix web test -- ConfigQuickSetupPanel.test.tsx ConfigRoute.layout.test.ts
npm --prefix web run build
```

Expected: Vitest exits 0; TypeScript and Vite build exit 0. Record bundle-budget output separately if run; do not misclassify an existing baseline budget failure as this feature's regression.

- [ ] **Step 2: Run the project closeout gate for the claimed web scope**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' scripts\local_quality_gate.py closeout --base main --claim-id claim-0b5c6f942fee
```

Expected: selected web tests/build pass and merge preflight reports the task branch based on the validated local `main`.

- [ ] **Step 3: Merge the task branch into root local `main`**

Before merging, verify:

```powershell
git -C C:\Users\17533\Desktop\Vibelution status --short --branch
git -C C:\Users\17533\Desktop\Vibelution rev-parse HEAD
```

If local `main` moved, merge it into the task branch and rerun Step 1. Otherwise fast-forward local `main`:

```powershell
git -C C:\Users\17533\Desktop\Vibelution merge --ff-only codex/compact-quick-config
```

Do not push or create a PR.

- [ ] **Step 4: Refresh through Launcher and verify the served bundle**

Run from root local `main`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\vibelution_launcher.ps1 -Action restart
```

Respect the active-work guard; if blocked, report the standard block message instead of bypassing it. Confirm `/config` returns HTTP 200 and the served `ConfigRoute` chunk contains “连接一个模型服务” and omits the old permanent result geometry marker `min-h-[28rem]`.

- [ ] **Step 5: Perform real browser visual QA**

At 1280×720, 1600×900, and 1920×1080 in light and dark themes, verify:

- idle has no “等待检测” half-page panel;
- Provider, API Key, and “检测连接” align in one compact work area;
- disabled, checking, error, review, saving, and success preserve control geometry;
- long Provider/model names do not overlap;
- keyboard focus is visible and no page-level horizontal overflow occurs;
- browser console has no new errors.

Capture screenshots for at least idle and one active-result state. If a real API key is unavailable, exercise non-secret fixtures or the no-auth template; never log or persist a credential for QA.

- [ ] **Step 6: Reconcile project memory and release the claim**

Run the memory sync against root local `main`, deriving the freshly verified merge SHA in the same PowerShell session and keeping the update bounded to this task:

```powershell
$mergeSha = git -C 'C:\Users\17533\Desktop\Vibelution' rev-parse HEAD
$memoryUpdate = "commit $mergeSha；focused Vitest 与 web build 通过；Launcher 已刷新；1280/1600/1920 双主题视觉验收通过。"
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' 'C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\sync_project_memory.py' 'C:\Users\17533\Desktop\Vibelution' --lane web-workbench-surface --focus '快速配置紧凑单页已合入本地 main' --update $memoryUpdate
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' 'C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py' 'C:\Users\17533\Desktop\Vibelution' release --claim-id claim-0b5c6f942fee --status completed --reason '紧凑快速配置已合入并完成测试、构建、刷新和视觉验收'
```

Release the active claim as `completed` only after these checks pass.

- [ ] **Step 7: Final report**

Report changed files, exact test/build/refresh results, visual viewport evidence, local-main commit, version impact `patch`, logging decision, developer/formal parity, no remote publication, and any residual risk. Do not claim completion from task-branch tests alone.
