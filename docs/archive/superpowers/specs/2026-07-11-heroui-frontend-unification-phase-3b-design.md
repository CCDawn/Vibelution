# HeroUI Frontend Unification Phase 3B Design

- **Status:** user-approved
- **Owner:** codex-heroui-phase3b-design
- **Claim:** claim-2ff4239d7b3c
- **Scope:** aggressive VUI/HeroUI migration for `/supervised-evolution`, `/self-evolution`, and `/config`
- **Supersedes:** none; follows Phase 3A without changing its scope
- **Implementation link:** pending Phase 3B implementation plan
- **Validation:** route/unit contracts, 60-scenario visual matrix, production build, Launcher refresh, and browser verification
- **Close condition:** all visible supported controls and repeated panels on the three routes use the approved VUI/HeroUI compositions, while existing state ownership and business semantics remain unchanged.

## 1. Intent And Boundaries

Phase 3B completes the deferred high-complexity portion of the HeroUI/VUI unification program. It covers the supervised Evolution workspace, the self-evolution track, and Config. Unlike Phase 3A, this is an aggressive visual and interaction-primitive migration: route shells, repeated panels, and every visible supported button, input, select, and textarea move to project-owned VUI compositions backed by HeroUI.

The product goal is an operational console where a user can immediately see whether an Evolution run is actionable and trustworthy, or whether a Config workspace is sourced correctly, dirty, blocked, or ready to save. The target is denser, calmer, and more consistent than a route-by-route collection of native control styling.

This is still a frontend presentation migration. It must not change Evolution run creation, EventSource handling, proposal action semantics, Config persistence, draft validation, request payloads, API DTOs, query keys, cache invalidation, permissions, or the external operator configuration source:

`C:\Users\17533\Documents\Vibelution\config\config.toml`

## 2. Approved Direction

Three approaches were considered:

1. Shell-only convergence: replace page headers and broad surfaces while leaving deep panels and controls untouched. This is low risk but leaves the user-visible interaction model fragmented.
2. **Approved — compatibility-first aggressive convergence:** migrate all supported visible controls and repeated panels to VUI/HeroUI while preserving current state owners and callbacks through adapters.
3. Full behavioral redesign: replace the workspaces, form models, and mutation flows. This would expand into configuration and Evolution product semantics and is out of scope.

The approved direction is deliberately aggressive in visible UI coverage, but conservative about product ownership. HeroUI is an accessible rendering primitive; VUI remains the Vibelution semantic layer; route modules and existing child panels retain business state and callbacks.

## 3. Surface Design

### 3.1 Evolution

`/supervised-evolution` keeps its Live, Runs, and Library route views. `/self-evolution` keeps its independent track and conversation/workspace semantics. Their hierarchy becomes:

1. `VRouteHeader` communicates track, current run status, and context-specific actions.
2. `VMetricStrip` and `VStatusStrip` carry concise current facts rather than independent statistic cards.
3. `VSurface`, `VSection`, and `VPanelHeader` form the launch, active-run, record, library, and evidence workspaces.
4. `VStateSurface` renders loading, unavailable, blocked, error, and empty states without collapsing the reserved workspace geometry.
5. `VActionGroup`, `VButton`, and `VIconButton` group mutations by local effect and keep destructive actions visibly distinct.

The live three-pane workspace, internal scroll regions, resizable pane handles, workflow tabs, active-run monitor, record queue/detail relationship, proposal action bands, and self-track boundary remain functional exactly as today. The migration may change their wrappers and supported controls, not their layout ownership, stream logic, or mutation ordering.

### 3.2 Config

`/config` remains a settings workbench rather than a generic form page. Its hierarchy becomes:

1. `VRouteHeader` and a compact status strip show source path, dirty state, validation state, restart requirement, and global actions.
2. `VSurface` retains the section navigation rail and main editing workspace.
3. Route-local `VSection`/`VPanelHeader` compositions unify Overview, Runtime, Draft, Model Library, and Health Diagnostics panels.
4. Dense field rows expose important blocking information directly; supplemental source or formula text moves to existing hover/focus help where appropriate.
5. Draft, validation, save, restore, reload, and destructive actions retain their current copy, disabled rules, confirmation behavior, and callbacks.

Config remains a projection and editing surface over the existing Config workspace API and operator-config source. No UI component may persist a value, create a parallel draft, or infer a model/provider default outside the existing route state and mutations.

## 4. Form And Control Migration Contract

Every supported visible control in the Phase 3B route modules and their owned panels migrates to these VUI primitives:

| Current visible control | Phase 3B composition | State-owner rule |
| --- | --- | --- |
| ordinary action button | `VButton` | Call the existing callback unchanged. |
| familiar tool action | `VIconButton` plus accessible label/tooltip | Call the existing callback unchanged. |
| text, number, password, or URL input | `VInput` with `VFieldRow` where a label/help surface exists | Route/panel draft state remains the value owner. |
| textarea | `VTextarea` with bounded rows and resize behavior | Route/panel draft state remains the value owner. |
| string-valued select | a shared VUI string-select bridge over `VSelect` | Convert selection to the existing value callback exactly once. |
| repeated panel or workspace region | `VSurface`, `VSection`, `VPanelHeader`, and existing product panel | Existing query/mutation/stream state remains the source. |

The string-select bridge is a small shared VUI adapter because both Evolution and Config have native `value/onChange` select flows. It accepts a string value, a typed option collection, disabled options, and one value-change callback. It maps only selection representation; it must not call mutations, own a cache, or synthesize a default selection.

The only allowed native-control exceptions are hidden file inputs, resize/drag affordances, and accessibility-only internals that HeroUI does not represent safely. Every exception must be non-primary, documented in the route contract test, and unavailable as an ordinary visible form or action control.

No Phase 3B route may import `@heroui/react` directly. All HeroUI usage stays behind VUI wrappers.

## 5. State And Failure Contract

| Surface | Required visible states | Invariant |
| --- | --- | --- |
| Evolution | loading, no runnable source, active run, disabled action, failed/blocked run, completed record, long reference | Existing EventSource/query/mutation data keeps its current authority; the UI only projects it. |
| Self Evolution | loading, unavailable workspace, conversation/workspace ready, long content | Track routing and conversation state do not move into a visual wrapper. |
| Config | loading failure, dirty draft, validation failure, saving, restart required, disabled destructive action, long configuration value | Existing draft state and save/restore/validation mutations keep their current authority. |

An adapter failure must preserve the current displayed value and avoid mutation dispatch. Existing error messages, retries, confirmations, disabled states, and query invalidations remain visible and unchanged. Critical destructive or permission-blocking information must remain in the normal layout, not only in a tooltip.

Developer and formal modes use the same frontend projection and state paths for this migration. The developer-mode judgment is **parity preserved**.

## 6. Source Of Truth

| Fact | Canonical source | Writer | UI / derived readers | Refresh rule |
| --- | --- | --- | --- | --- |
| supervised run, stream events, proposal lifecycle | existing Evolution APIs, React Query, EventSource, and mutations | existing route/service actions | Evolution route and extracted panels | existing query invalidation and stream snapshot rules |
| self-evolution overview and workspace | existing overview query and workspace cache | existing self-evolution flow | self track boundary and conversation workspace | existing polling/cache policy |
| persisted configuration | Config workspace API backed by external operator config | existing Config save path | Config route and panels | existing reload/save invalidation |
| configuration draft and validation | existing Config route-local draft state and mutations | existing Config draft handlers | Config field/panel projections | existing validation, save, restore, and leave-guard behavior |
| control-local selection representation | VUI form bridge only | control interaction | one VUI wrapper | discarded/recomputed from the canonical owner on rerender |

## 7. Responsive And Accessibility Contract

Desktop is the primary operating surface at 1280x720, 1440x900, and 1920x1080. Existing pane-resize behavior and internal scroll ownership remain intact. At 720px, the migration must retain the existing one-column or stacked fallback without page-level horizontal scrolling; it is a safety check, not a new mobile information architecture.

Every migrated visible control must have a stable accessible name, keyboard focus style, content-sized geometry unless a full-row action is intentional, and non-color state cues. Long Chinese and English labels, long IDs, error text, and configuration values must either truncate with a recoverable title/tooltip or wrap within an intentionally scrollable detail region. Loading-to-loaded transitions must preserve enough geometry to prevent disruptive layout shifts.

## 8. Validation And Review

The implementation must use test-first changes for the shared string-select bridge and for each behavior-sensitive migration seam.

1. Add focused VUI tests for value mapping, disabled options, empty selection, and one callback per user selection.
2. Update Evolution and Config layout contracts to prove supported visible controls use VUI and only named native exceptions remain.
3. Run existing Evolution/Config logic tests to prove mutation callbacks, draft handling, cache rules, and route decisions are unchanged.
4. Extend `workbenchVisualMatrix` with 18 stable Phase 3B scenarios: `/supervised-evolution`, `/self-evolution`, and `/config` × light/dark × compact/standard/wide. The total matrix becomes 60 scenarios.
5. Run targeted Vitest, `npm --prefix web run build`, scoped diff review, and a Launcher refresh decision.
6. After a normal guarded Launcher refresh, capture real browser evidence for all three desktop viewports and both themes; separately inspect the 720px fallback, console errors, page-level overflow, focus/disabled controls, loading/ready transitions, and longest realistic content available in the running instance.

Phase 3B does not add runtime-scene logging because it intentionally introduces no business branch, API behavior, persistence behavior, or lifecycle transition. If implementation discovers a required semantic change, it leaves Phase 3B scope and requires a new decision before merging.

## 9. Scope And Close Conditions

In scope are the three route entries, their directly owned visible Evolution/Config panels, a narrowly justified shared VUI select bridge, their route/component/layout tests, and the visual matrix.

Out of scope are backend routes and services, TypeScript API DTOs, query keys, caches, i18n copy changes except unavoidable accessible labels for newly represented controls, operator config, runtime/Launcher behavior, package/dependency changes, direct HeroUI route imports, and unrelated route cleanup.

Phase 3B is complete only when:

- supported visible controls on the three routes are represented by VUI/HeroUI compositions;
- state ownership remains identical to the documented sources of truth;
- existing business callbacks and request semantics remain intact;
- the 60-scenario matrix, focused tests, production build, and live visual checks pass;
- only named native exceptions remain and they are contract-tested;
- Launcher refresh is completed or explicitly blocked by active work;
- project memory and claim state are synchronized; and
- version impact is recorded as `patch` unless implementation reveals a broader behavior change.
