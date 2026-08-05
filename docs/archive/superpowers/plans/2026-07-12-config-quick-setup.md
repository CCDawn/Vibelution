# Settings Quick Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `/config` around a desktop one-page Provider quick setup that normally requires only a provider choice, an API key, one detection action, and one explicit save confirmation.

**Architecture:** Keep `ConfigRoute` as the only query, mutation, and formal-apply owner. Add a presentation-only `ConfigQuickSetupPanel`, extend the existing pure `configProviderLogic.ts` rather than introducing a second Provider model, and retain `ConfigProviderRegistryPanel` as a separate management context. Reuse the existing Provider draft, credential, discovery, pin, route-preview, and config-apply APIs; do not create a new backend orchestration endpoint or a new configuration source.

**Tech Stack:** React 19, TypeScript 5.9, VUI/HeroUI primitives, Tailwind CSS 4, React Query, Vitest, Vite, existing Python config service/runtime-scene infrastructure.

## Global Constraints

- Execute as a `STANDARD_TASK` in `C:\Users\17533\Desktop\Vibelution-worktrees\config-quick-setup` on branch `codex/config-quick-setup`, created from current local `main`; root checkout must remain on `main`.
- Before editing, run the project memory guard `status`, `check`, and claim the exact frontend scopes. Claim at least `web/src/routes/ConfigRoute.tsx`, `web/src/routes/ConfigRoute.styles.ts`, `web/src/routes/configProviderLogic.ts`, the new quick-setup files, and their focused tests.
- Preserve `C:\Users\17533\Documents\Vibelution\config\config.toml` as the only formal operator-config source. Quick-setup preview state is session-only.
- Do not import `@heroui/react` from route files. Use VUI primitives and Tailwind-first styling.
- Do not design or test a mobile/touch layout for quick setup. The acceptance matrix is desktop-only: 1280x720, 1600x900, and 1920x1080.
- Never store, render back, log, serialize into errors, or put an API key into React Query cache, local storage, runtime scenes, snapshots, fixtures, or project memory.
- Detection must not call formal config apply. Formal apply occurs only after the user selects a model and clicks `确认并保存`.
- Preserve existing Provider registry, credential replacement, route preview, discovery, pin/unpin, diagnostics, migration, developer-mode, and leave-guard behavior.
- Keep the implementation minimal: no new backend endpoint unless existing APIs are proven unable to preserve the approved transaction boundary. Any such blocker requires stopping and revising this plan before coding around it.
- Commit after each green task using only the listed task files. Never use `git add .`.

---

## Task 1: Add deterministic quick-setup state and recommendation logic

**Files:**

- Modify: `web/src/routes/configProviderLogic.ts`
- Modify: `web/src/routes/configProviderLogic.test.ts`

- [ ] **Step 1: Write failing tests for the quick-setup state contract**

Add imports for the new pure API and tests that assert:

```ts
const initial = initialProviderQuickSetupState();
expect(initial.phase).toBe("input");
expect(initial.provider).toEqual(initialProviderWizardState());
expect(initial.selectedModelRef).toBe("");
expect(JSON.stringify(initial)).not.toContain("api-key-secret");

const checking = providerQuickSetupReducer(initial, { type: "start_check" });
expect(checking.phase).toBe("checking");

const reviewed = providerQuickSetupReducer(checking, {
  type: "check_succeeded",
  models: [model("provider-a/model-a")],
  selectedModelRef: "provider-a/model-a",
  recommendationReason: "template_default",
});
expect(reviewed.phase).toBe("review");
```

Cover reset-on-template-change, `auth_kind=none`, check failure, discovery fallback, no recommendation, save start/failure/success, and the invariant that actions contain no credential value.

- [ ] **Step 2: Write failing tests for deterministic model recommendation**

Use real `ConfigCatalogModel`-shaped fixtures and assert this order:

```ts
expect(recommendProviderModel(models, {
  templateDefaultModelRef: "provider-a/default",
  allowedProtocols: ["openai"],
})).toMatchObject({
  modelRef: "provider-a/default",
  reason: "template_default",
});
```

Also assert that disabled and protocol-incompatible models are excluded, a verified/capability-complete model wins when no template default exists, ties use a stable lexical `modelRef` order, and no safe candidate returns `{ modelRef: "", reason: "no_compatible_model" }`.

- [ ] **Step 3: Run the focused test and verify RED**

Run:

```powershell
npm --prefix web test -- --run web/src/routes/configProviderLogic.test.ts
```

Expected: FAIL because the quick-setup exports do not exist yet.

- [ ] **Step 4: Implement the smallest pure state API**

Add these exact public types/functions beside the existing wizard logic:

```ts
export type ProviderQuickSetupPhase =
  | "input"
  | "checking"
  | "review"
  | "saving"
  | "success"
  | "error";

export type ProviderQuickSetupErrorKind =
  | "auth"
  | "endpoint"
  | "discovery"
  | "no_recommendation"
  | "partial_save"
  | "save";

export type ProviderQuickSetupState = {
  phase: ProviderQuickSetupPhase;
  provider: ProviderWizardState;
  discoveredModels: ConfigCatalogModel[];
  selectedModelRef: string;
  recommendationReason: string;
  errorKind: ProviderQuickSetupErrorKind | "";
  errorMessage: string;
};

export type ProviderQuickSetupAction =
  | { type: "reset" }
  | { type: "set_provider"; provider: ProviderWizardState }
  | { type: "start_check" }
  | { type: "check_succeeded"; models: ConfigCatalogModel[]; selectedModelRef: string; recommendationReason: string }
  | { type: "check_failed"; errorKind: ProviderQuickSetupErrorKind; errorMessage: string }
  | { type: "select_model"; modelRef: string }
  | { type: "start_save" }
  | { type: "save_failed"; errorKind: "partial_save" | "save"; errorMessage: string }
  | { type: "save_succeeded" };

export function initialProviderQuickSetupState(): ProviderQuickSetupState;
export function providerQuickSetupReducer(
  state: ProviderQuickSetupState,
  action: ProviderQuickSetupAction,
): ProviderQuickSetupState;

export function recommendProviderModel(
  models: ConfigCatalogModel[],
  options: { templateDefaultModelRef?: string; allowedProtocols: string[] },
): { modelRef: string; reason: "template_default" | "verified_capabilities" | "stable_fallback" | "no_compatible_model" };
```

The reducer must compose `initialProviderWizardState()` and existing `ProviderWizardState`; do not duplicate Provider draft fields. Recommendation must be a side-effect-free sort/filter operation and must not mutate the backend model array.

- [ ] **Step 5: Run the focused test and verify GREEN**

Run the same Vitest command. Expected: PASS with all pre-existing and new logic tests green.

- [ ] **Step 6: Commit the pure logic slice**

```powershell
git add -- "web/src/routes/configProviderLogic.ts" "web/src/routes/configProviderLogic.test.ts"
git commit -m "feat(web): add Provider quick setup logic"
```

---

## Task 2: Build the presentation-only quick-setup panel

**Files:**

- Create: `web/src/routes/ConfigQuickSetupPanel.tsx`
- Create: `web/src/routes/ConfigQuickSetupPanel.styles.ts`
- Create: `web/src/routes/ConfigQuickSetupPanel.test.tsx`

- [ ] **Step 1: Write failing component tests for the two-input contract**

Render the panel with a small Provider-template fixture and assert:

- the initial surface has one Provider selector and one password input;
- `authKind: "none"` hides the credential field;
- advanced settings are collapsed by default;
- checking, auth error, endpoint error, discovery fallback, no recommendation, review, saving, and success keep the result surface mounted;
- `onDetect` receives `{ provider, credentialValue }` only after the user action;
- `onConfirm` receives the selected canonical model ref;
- the API key is absent from rendered result/error text after callbacks settle;
- no registry/detail/wizard component is rendered inside this panel.

Use a typed props fixture matching:

```ts
export type ConfigQuickSetupPanelProps = {
  state: ProviderQuickSetupState;
  templates: ConfigProviderTemplate[];
  credentialValue: string;
  disabled: boolean;
  onCredentialChange: (value: string) => void;
  onProviderChange: (provider: ProviderWizardState) => void;
  onDetect: (input: { provider: ProviderWizardState; credentialValue: string }) => void;
  onModelChange: (modelRef: string) => void;
  onConfirm: () => void;
  onReset: () => void;
};
```

Import the existing backend DTO type actually used by `ConfigProviderWizard`; if its exported name differs from `ConfigProviderTemplate`, alias the real type locally instead of inventing a duplicate DTO.

- [ ] **Step 2: Run the component test and verify RED**

```powershell
npm --prefix web test -- --run web/src/routes/ConfigQuickSetupPanel.test.tsx
```

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement the semantic desktop layout with VUI**

Build a stable two-column section:

```tsx
<VSection className={styles.root} aria-labelledby="provider-quick-setup-title">
  <div className={styles.inputColumn}>{/* provider, credential, advanced, detect */}</div>
  <section className={styles.resultColumn} aria-live="polite">
    {/* stable progress/error/recommendation/save surface */}
  </section>
</VSection>
```

Use `VStringSelect`, `VInput` with `type="password"`, `VButton`, `VStatusChip`, `VStateSurface`, and the project-native disclosure primitive already used in `web/src/routes`. If there is no VUI disclosure, use semantic `<details>/<summary>` styled through the local styles module. Do not call APIs, touch React Query, or own the canonical workspace.

Define these exact base layout tokens in `ConfigQuickSetupPanel.styles.ts`:

```ts
root: "grid min-w-0 grid-cols-[minmax(22rem,0.9fr)_minmax(28rem,1.1fr)] gap-4",
inputColumn: "min-w-0 space-y-4",
resultColumn: "min-h-[28rem] min-w-0",
```

Do not add mobile breakpoints for this component. Keep button dimensions stable across busy/error states and use text plus icon/status labels rather than color alone.

- [ ] **Step 4: Run tests and build**

```powershell
npm --prefix web test -- --run web/src/routes/ConfigQuickSetupPanel.test.tsx
npm --prefix web run build
```

Expected: both PASS; TypeScript confirms the component boundary contains no API ownership.

- [ ] **Step 5: Commit the panel slice**

```powershell
git add -- "web/src/routes/ConfigQuickSetupPanel.tsx" "web/src/routes/ConfigQuickSetupPanel.styles.ts" "web/src/routes/ConfigQuickSetupPanel.test.tsx"
git commit -m "feat(web): build one-page Provider setup panel"
```

---

## Task 3: Orchestrate detection and explicit save in `ConfigRoute`

**Files:**

- Modify: `web/src/routes/ConfigRoute.tsx`
- Modify: `web/src/routes/ConfigRoute.layout.test.ts`

- [ ] **Step 1: Replace obsolete route-source assertions with failing quick-setup contract tests**

Remove only assertions that require the four-step wizard to be the default visible context. Keep all registry, credential, pin/unpin, route-preview, canonical identity, migration, and VUI safety tests.

Add source-contract assertions for:

```ts
expect(configRouteSource).toContain("ConfigQuickSetupPanel");
expect(configRouteSource).toContain('type ProviderWorkspaceMode = "quick" | "manage" | "advanced"');
expect(configRouteSource).toContain("handlePrepareProviderQuickSetup");
expect(configRouteSource).toContain("handleConfirmProviderQuickSetup");
expect(configRouteSource).toContain("recommendProviderModel");
```

Also assert the default branch renders quick setup alone, management renders `ConfigProviderRegistryPanel`, the legacy wizard is not simultaneously mounted, and the formal `handleApply` call exists only in confirm orchestration—not in detection orchestration.

- [ ] **Step 2: Run the layout contract and verify RED**

```powershell
npm --prefix web test -- --run web/src/routes/ConfigRoute.layout.test.ts
```

Expected: FAIL on missing quick-setup imports/mode/handlers.

- [ ] **Step 3: Add route-owned mode, reducer, and ephemeral credential state**

Add:

```ts
type ProviderWorkspaceMode = "quick" | "manage" | "advanced";

const [providerWorkspaceMode, setProviderWorkspaceMode] = useState<ProviderWorkspaceMode>("quick");
const [providerQuickSetupState, dispatchProviderQuickSetup] = useReducer(
  providerQuickSetupReducer,
  undefined,
  initialProviderQuickSetupState,
);
const [providerQuickCredential, setProviderQuickCredential] = useState("");
```

Clear `providerQuickCredential` on Provider-template change, successful save, reset, and route unmount. Do not include it in query keys, mutation payload logs, errors, or quick-setup reducer actions.

- [ ] **Step 4: Implement detection as draft-only orchestration**

Add `handlePrepareProviderQuickSetup` that:

1. dispatches `start_check`;
2. resolves the backend-owned Provider ID through `handleSuggestProviderId`;
3. creates/updates only the Provider draft using the existing canonical `buildProviderWizardDraft` path and existing credential mutation;
4. calls `handleDiscoverProvider` using the newest returned/synchronized workspace, not a captured stale state;
5. calls `recommendProviderModel` and dispatches `check_succeeded` or a typed recoverable failure;
6. never calls `handleApply`, `handleApplyProviderRoutePreview`, or writes formal operator config.

Do not catch all errors into one generic message. Map authentication, endpoint, discovery, and no-recommendation outcomes to their explicit state; preserve discovered models when only recommendation fails.

- [ ] **Step 5: Implement confirmation as the only formal-apply path**

Add `handleConfirmProviderQuickSetup` that:

1. rejects confirmation unless phase is `review` and `selectedModelRef` is canonical;
2. dispatches `start_save`;
3. pins only the selected model through `handlePinProviderModels`;
4. previews/applies the Provider route through the existing backend-token authority;
5. calls the existing `handleApply` only after all prerequisite draft mutations succeed;
6. invalidates/refetches the config workspace on success;
7. clears the credential and dispatches `save_succeeded`;
8. reports `partial_save` when a draft/credential mutation succeeded but formal apply did not.

If the existing route-preview helper combines preview and apply, split it into two local helpers without changing the backend contract so the quick-setup confirm path can preserve ordering and error attribution.

- [ ] **Step 6: Render mutually exclusive workspace contexts**

Replace the simultaneous registry/detail/wizard stack with a compact mode switch and one active body. The `quick` branch renders `ConfigQuickSetupPanel` with the state and callbacks defined in Tasks 2 and 3; the `manage` branch renders the existing `ConfigProviderRegistryPanel` with all current props unchanged; the `advanced` branch renders the existing `ConfigProviderWizard` with all current props unchanged. Do not use CSS hiding to keep inactive branches mounted.

Label the third entry `高级设置`; it may reuse the existing wizard/manual fields during this slice. Preserve `structuredActionsDisabled`, `busyAction`, leave guard, and current Provider-management callbacks.

- [ ] **Step 7: Run route, logic, and component tests**

```powershell
npm --prefix web test -- --run web/src/routes/configProviderLogic.test.ts web/src/routes/ConfigQuickSetupPanel.test.tsx web/src/routes/ConfigRoute.layout.test.ts
```

Expected: PASS. Inspect the output and confirm no pre-existing Provider management contract was deleted merely to make the suite green.

- [ ] **Step 8: Commit route orchestration**

```powershell
git add -- "web/src/routes/ConfigRoute.tsx" "web/src/routes/ConfigRoute.layout.test.ts"
git commit -m "feat(web): orchestrate Provider quick setup"
```

---

## Task 4: Clean up the settings shell and Provider management layout

**Files:**

- Modify: `web/src/routes/ConfigRoute.styles.ts`
- Modify: `web/src/routes/ConfigProviderRegistryPanel.styles.ts`
- Modify: `web/src/routes/ConfigRoute.layout.test.ts`

- [ ] **Step 1: Add failing layout-source assertions for the approved information hierarchy**

Assert that:

- the settings sidebar has a bounded desktop width and the content column owns scrolling;
- the Provider workspace mode switch is in the model section header;
- quick setup has no fixed or sticky bottom save bar;
- registry list and detail use a bounded management grid instead of a tall list followed by detail;
- the quick setup contract contains no `sm:`, `md:`, or mobile stacking rule;
- route-level direct `@heroui/react`, raw `<button>`, raw `<input>`, and page-level horizontal overflow remain prohibited.

Do not delete unrelated existing responsive tests for other settings sections; only replace the old Provider comparison/mobile assumptions that conflict with the approved desktop-only quick setup.

- [ ] **Step 2: Run the layout contract and verify RED**

```powershell
npm --prefix web test -- --run web/src/routes/ConfigRoute.layout.test.ts
```

Expected: FAIL on the old simultaneous-stack and bottom-bar layout tokens.

- [ ] **Step 3: Implement the compact settings hierarchy**

Adjust local style constants so:

- left navigation is visually grouped and wide enough for Chinese labels/counts;
- title, sync state, and mode switch form one compact header;
- active model context consumes the main viewport without a second competing workflow below it;
- quick setup maintains its two-column geometry at all three target desktop widths;
- management mode uses a bounded list/detail grid and internal scrolling;
- transient notices wrap and clamp without widening the page;
- no fixed bottom edit layer obscures the active panel.

Preserve all semantic selectors referenced by current tests and add stable `data-state`/`data-mode` selectors only where browser validation needs them.

- [ ] **Step 4: Run focused tests and production build**

```powershell
npm --prefix web test -- --run web/src/routes/ConfigQuickSetupPanel.test.tsx web/src/routes/ConfigRoute.layout.test.ts
npm --prefix web run build
npm --prefix web run check:bundle
```

Expected: all PASS and no page-level overflow/bundle-budget regression.

- [ ] **Step 5: Commit the shell cleanup**

```powershell
git add -- "web/src/routes/ConfigRoute.styles.ts" "web/src/routes/ConfigProviderRegistryPanel.styles.ts" "web/src/routes/ConfigRoute.layout.test.ts"
git commit -m "style(web): simplify settings workspace layout"
```

---

## Task 5: Prove the real API boundary and secret-safe logging

**Files:**

- Modify only if a missing assertion is found: `tests/test_web_config_routes.py`
- Modify only if existing events cannot express the outcome safely: `core/web/services/config_service.py`

- [ ] **Step 1: Audit existing Provider draft/apply events before changing backend code**

Use `rg` around the exact Provider create, credential, discovery, pin, route preview/apply, and config apply handlers. Record whether existing events already provide bounded fields equivalent to:

```py
{
    "providerId": provider_id,
    "stage": stage,
    "outcome": outcome,
    "errorType": error_type,
    "modelCount": model_count,
}
```

The event must not include API key values, full request bodies, full Provider responses, or full prompts.

- [ ] **Step 2: Add a failing regression test only for a real coverage gap**

If existing route tests do not prove secret redaction and apply ordering, add tests that submit a sentinel credential such as `sk-never-log-this` and assert it is absent from captured runtime-scene/audit payloads and error bodies. Also assert draft mutations can complete without formal config apply, and apply occurs only through the explicit apply route.

If existing tests already prove all three properties, do not edit backend files; record `logging decision: existing bounded events sufficient` in the task notes.

- [ ] **Step 3: Implement only the minimal missing logging field**

If Step 2 exposes a gap, extend the existing config-service event at the owning mutation boundary. Do not add a `quick_setup` backend endpoint, accept a UI phase enum as backend truth, or duplicate frontend orchestration in Python.

- [ ] **Step 4: Run backend regression tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_config_routes.py -q
```

Expected: PASS. Search captured output and changed fixtures for the sentinel credential; expected result is zero matches.

- [ ] **Step 5: Commit only if backend/test files changed**

```powershell
git add -- "core/web/services/config_service.py" "tests/test_web_config_routes.py"
git commit -m "test(config): protect quick setup mutation boundary"
```

Skip this commit when the audit proves no file change is needed.

---

## Task 6: Full validation, browser QA, integration, and refresh

**Files:**

- Modify: `.docs/project-memory/memory.json` or the lane file selected by `.docs/project-memory/INDEX.md` only while holding the project-memory claim
- Modify version files only through the project release/version workflow if the integration gate requests the approved patch impact

- [ ] **Step 1: Run the complete focused regression set**

```powershell
npm --prefix web test -- --run web/src/routes/configProviderLogic.test.ts web/src/routes/ConfigQuickSetupPanel.test.tsx web/src/routes/ConfigRoute.layout.test.ts
.\.venv\Scripts\python.exe -m pytest tests/test_web_config_routes.py -q
npm --prefix web run build
npm --prefix web run check:bundle
git diff --check main...HEAD
```

Expected: every command PASS, no whitespace errors, and no secret appears in test output.

- [ ] **Step 2: Self-review the branch against the approved design**

Inspect `git diff --stat main...HEAD` and `git diff main...HEAD --` for:

- only two conditional required inputs on the initial quick-setup view;
- one detect action and one explicit save action;
- no formal apply from detection;
- deterministic recommendation with visible reason;
- mutually exclusive quick/manage/advanced contexts;
- preserved registry and credential editing safeguards;
- no direct HeroUI route imports, new fact source, mobile contract, or secret-bearing state/logging.

Fix any issue with a failing regression test first, then rerun Step 1.

- [ ] **Step 3: Pass the project closeout executor and reconcile claims**

Run the project-native closeout/guard commands documented in `DEVELOPMENT_STANDARD.md`: check the claim, ensure the branch is mergeable, update the `web-workbench-surface` memory lane while holding its single-writer claim, and release every task claim after synchronization. Record `version impact: patch`; do not hand-edit version files unless the closeout workflow assigns the bump.

- [ ] **Step 4: Self-merge into local `main` after gates pass**

From the clean root integration checkout, confirm `main` has not diverged semantically, merge `codex/config-quick-setup` using the project-approved non-interactive merge flow, and rerun the decisive frontend tests plus `npm --prefix web run build` on root `main`. Do not delete the task worktree until the root verification passes and memory/claims are reconciled.

- [ ] **Step 5: Refresh through Launcher and perform desktop visual QA**

First run the Launcher active-work guard. If any active work remains, stop and report exactly:

`有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。`

Otherwise refresh through Launcher, open `/config`, and capture/inspect each of these states in light and dark themes at 1280x720, 1600x900, and 1920x1080:

- idle;
- checking;
- authentication error;
- discovery fallback/no recommendation;
- review with longest Chinese/English labels;
- saving;
- success;
- manage-existing-connections mode.

Acceptance: no page-level horizontal overflow, no content-obscuring bottom bar, no loading geometry jump, no console error, clear focus order, and only the active workspace context visible.

- [ ] **Step 6: Produce the completion report**

Report exact commits, changed files, test/build outputs, browser matrix results, logging decision, secret-safety evidence, runtime refresh result, root-main merge evidence, project-memory sync, claim release, residual risks, and `version impact: patch`. Do not claim remote publication; push/PR remain out of scope unless separately authorized.
