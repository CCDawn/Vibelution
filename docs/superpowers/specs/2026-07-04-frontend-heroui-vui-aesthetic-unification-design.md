# Frontend HeroUI/VUI Aesthetic Unification Design

Date: 2026-07-04
Status: Draft approved for written spec review

## Confirmed intent

The goal is a phased full-site visual unification, starting with the Workbench mainline. This is not a request to make every page look like stock HeroUI. HeroUI remains the renderer behind VUI primitives. The visible product goal is to make the frontend feel like a light-first, quiet, dense, background-aware AI workbench.

Confirmed choices:

- Target: full-site unification, phased rather than one-shot.
- First scope: Workbench mainline.
- Aesthetic priority: quiet workbench.
- Verification: full visual regression.

## Existing constraints and facts

The current frontend already has a visual architecture:

```text
routes
  -> product components / route composition
  -> VUI primitives
  -> HeroUI renderer
  -> design tokens
```

HeroUI must stay behind the VUI layer. Routes should not import `@heroui/react` directly or define route-local HeroUI slot overrides. Route code may own business layout, grid, column widths, responsive breakpoints, canvas dimensions, and state-specific composition. Route code should not redefine generic button families, card/panel shadows, full-page opaque wrappers, thick status borders, or broad visual grammar.

The current visual direction from existing specs is:

- light-first;
- quiet operational glass;
- dense but readable;
- background-aware;
- 1px thin-line system;
- compact pale controls;
- operational clarity over decoration.

This design should not turn the product into a dark cyber dashboard, marketing hero page, or heavy SaaS admin surface.

## Architecture and scope

### Architecture

The unification keeps the existing layering intact:

```text
routes
  -> product components / route composition
  -> VUI primitives
  -> HeroUI renderer
  -> design tokens
```

Aesthetic optimization mainly moves repeated or conflicting route-local visual grammar upward into product components, VUI compositions, or tokens. It does not replace application behavior, data authority, or route state machines.

### In scope

- AppShell, topbar, route outlet shell, and Workbench mainline pages.
- Route headers, primary workspace surfaces, panels, cards, toolbars, dense rows, status chips, and form-control parity.
- Cleanup of visible duplicate/conflicting class strings when they affect visual consistency.
- Extraction of reusable product/VUI compositions where reuse or visible quality improves.
- Full-site rollout by waves after Workbench baseline is established.
- Visual regression across theme, background, density, and viewport scenarios.

### Out of scope

- Backend/API behavior changes.
- Route data-model rewrites.
- Mechanical conversion of stable CSS Modules for purity.
- Large marketing-style redesign.
- Large glow/gradient/animation layer.
- Direct route imports from `@heroui/react`.
- Removing critical error, blocker, destructive, or accessibility states in the name of quietness.

## Visual grammar

### Core principles

Full-site unification means different business pages share one visual language, not that they become identical.

- AppShell owns global background and atmosphere.
- Routes must not add full-page strong backgrounds, opaque masks, page-level image backgrounds, or decorative gradients.
- VUI/product components own generic appearance.
- Route-local styles own only business layout and local composition.
- HeroUI is a renderer, not a route-facing design system.
- Use fewer cards, fewer borders, fewer emphasis colors.
- Prefer typography, spacing, 1px dividers, restrained alpha surfaces, and clear state language over stacked glass cards.

### Reusable units to stabilize

#### RouteWorkspace / VWorkbenchPage

The main page container controls page padding, gap, background transparency, and workbench embedding. It should preserve custom background visibility while keeping content readable.

#### RouteHeader / SectionHeader

Headers orient the user and expose local operations. They should not become nested cards by default. Ordinary explanations should be short; detailed explanations should move to tooltips, helper text, or contextual empty states.

#### GlassPanel / GlassCard / EmbeddedPanel

Surface levels should be distinct:

- `GlassPanel`: primary working region.
- `GlassCard`: local content block.
- `EmbeddedPanel`: light nested region inside a primary panel, avoiding card pile effects.

These levels should share consistent border width, radius, alpha, shadow, and blur rules.

#### DenseToolbar

Dense toolbars handle filters, refresh, mode switches, and small operations. Buttons default to quiet. Each local region should have at most one soft primary action. Icon-only actions need accessible labels or tooltips.

#### DenseRow / StateRow

Rows represent lists, queues, logs, tasks, memory entries, and similar dense content. Hover, focus, selected, disabled, stale, error, and destructive states should be consistent. Rows should not default to independent cards.

#### MetricChip / StatusChip

Status and metric chips use low-saturation color, 1px borders, and compact geometry. High emphasis is reserved for errors, blockers, destructive states, or active primary workflow state.

#### FormField parity

`VInput`, `VSelect`, `VTextarea`, `VCheckbox`, and `VNative*` controls must reach visual parity for height, radius, border, focus, placeholder, disabled, invalid, and helper states. They do not all need to become HeroUI wrappers if visual parity and accessibility are preserved.

### Anti-pattern checklist

The cleanup should target these recurring problems:

- `*Eyebrow` or `*Header` styles accidentally include panel/card background, border, shadow, or padding.
- Class strings repeat or conflict on border, background, text, gap, padding, or display mode.
- Labels, metadata, helper text, and small summaries are wrapped as cards.
- Routes define generic button/card/panel families.
- Most visible text collapses to `text-xs`, flattening hierarchy.
- Evidence, summary, detail, and action blocks become nested card walls.
- Custom background plus many translucent surfaces creates visual noise.
- Launcher, canvas, graph, logs, or tools pages feel like separate products because generic chrome differs.

## Implementation waves

### Wave 0: visual baseline and guards

Goal: make full-site unification verifiable before broad editing.

Actions:

- Inventory pages: AppShell, Chat, Supervised Evolution, Self Evolution, Agents, Teams, Memory, Config, Logs, Git, Tools, Launcher, and canvas/graph pages.
- Define screenshot matrix:
  - light theme;
  - dark theme;
  - default background;
  - custom background;
  - desktop viewport;
  - narrow viewport;
  - at least one dense-content state;
  - at least one empty/error/blocker state.
- Add or run import-boundary checks:
  - routes do not import `@heroui/react`;
  - HeroUI appears only in VUI renderer or VUI primitive wrappers.
- Freeze visual checklist:
  - background remains visible;
  - text remains readable;
  - borders are thin;
  - buttons are quiet;
  - focus is visible;
  - destructive/error/blocker states are clear;
  - no card wall;
  - no full-page opaque wrapper.

Exit criteria:

- Page inventory exists.
- Baseline screenshots or screenshot plan exists for the selected matrix.
- Boundary check command or test exists.
- Checklist is available for later review.

### Wave 1: Workbench mainline baseline

Goal: establish the quiet workbench visual baseline on the highest-impact surfaces.

Targets:

- AppShell, topbar, nav, and route outlet shell.
- Route headers.
- Primary workbench content surfaces.
- Most visible header, toolbar, panel, row, and status areas in Chat, Evolution, Agents, and Memory.

Actions:

- Reduce topbar and route-header visual noise.
- Reduce nested cards and duplicate borders.
- Extract repeated panel/header/toolbar/metric/status grammar into product/VUI compositions.
- Keep route CSS focused on layout.
- Remove class-string duplicates or conflicts when they affect visible output.
- Improve typography hierarchy without losing dense workbench efficiency.
- Validate custom-background readability.

Exit criteria:

- Main Workbench pages share the same surface, header, toolbar, status, and row language.
- The workbench reads as embedded operational UI, not a stack of cards.
- No route direct HeroUI import is introduced.
- Visual regression passes the agreed matrix for affected pages.

### Wave 2: high-traffic route convergence

Goal: apply the Wave 1 grammar to the main working routes.

Targets:

- Chat / Coding.
- Supervised Evolution / Self Evolution.
- Agents / Teams.
- Memory.
- Config.

Rules:

- Do not change API or data flow.
- Do not rewrite business state.
- Replace visible chrome and layout composition only.
- Preserve or improve errors, blockers, empty states, destructive confirmations, and accessibility states.

Exit criteria:

- Main routes share common product/VUI visual units.
- Route-local generic visual grammar is reduced.
- Critical states remain clear.
- Visual regression passes affected pages.

### Wave 3: special pages and legacy visual language

Goal: unify special pages without destroying their business-specific density or canvas behavior.

Targets:

- Launcher.
- Tools.
- Logs and Git.
- Canvas, graph, and flow pages.

Strategy:

- Do not force canvas/log/terminal-like pages to look like ordinary list pages.
- Preserve business-specific grid, terminal, graph, and canvas needs.
- Unify buttons, chips, panel chrome, headers, toolbars, focus states, and empty states.
- Treat Launcher as a sub-plan because it currently has the strongest separate visual language.

Exit criteria:

- Special pages no longer feel like separate products because of generic chrome.
- Special layout affordances remain intact.
- Visual regression covers dense and narrow states.

### Wave 4: full visual regression and closure

Goal: prove the result is controlled and consistent across the product.

Actions:

- Run full screenshot matrix.
- Run build and typecheck.
- Run relevant unit/integration tests.
- Run import-boundary check.
- Smoke routes.
- Manually review screenshots for:
  - light-first quality;
  - custom background visibility;
  - dense-page readability;
  - mobile/narrow layout stability;
  - visible focus/error/destructive states.

Exit criteria:

- Visual language is consistent across the inventory.
- Main workbench surfaces remain background-aware and readable.
- No direct route HeroUI usage.
- No critical state was made invisible.

## Risk controls

### Scope expansion

Control each wave with a page list and exit criteria. Do not combine visual work with backend, route state, or data-flow changes.

### Silent visual regression from mechanical migration

Do not convert stable CSS Modules or old style maps just for purity. Change them when there is visible quality improvement, reuse improvement, or boundary enforcement value.

### HeroUI misuse

Use import-boundary checks. Pages consume VUI/product components only. HeroUI stays in renderer and primitive wrappers.

### Wrong aesthetic direction

Use the checklist: light-first, quiet controls, thin-line, background-aware, dense but readable. Avoid cyber, neon, marketing, or heavy SaaS admin styling.

### Efficiency loss

Preserve compact workbench density. Improve hierarchy and readability without turning the app into a spacious presentation site.

### Expensive validation

Create a baseline matrix once. Each wave updates only affected page snapshots plus shared shell snapshots.

## Verification plan

Verification must include visual evidence, not only build success.

### Automated or scriptable checks

- Build.
- Typecheck.
- Relevant unit/integration tests.
- Import-boundary grep/test for route-level HeroUI imports.
- Screenshot capture if a Playwright or equivalent harness exists or is added.

### Manual visual review

Review at least:

- light theme with default background;
- dark theme smoke;
- custom background with readability overlay;
- dense-content page;
- empty state;
- error/blocker/destructive state;
- narrow viewport.

### Completion criteria

A wave is complete only when:

- affected pages no longer depend on route-local repeated chrome for common visual language;
- the main area feels like an embedded workbench rather than a card pile;
- buttons, surfaces, headers, chips, rows, focus, and critical states are consistent;
- build/type/test/boundary checks pass;
- visual review evidence exists for the agreed matrix.

## Open implementation notes

The first implementation plan should start with Wave 0 and Wave 1 only. Later waves should be planned after reviewing Wave 1 screenshots and regressions. This keeps the confirmed full-site goal while preventing one-shot uncontrolled churn.

## Wave 0-1 implementation handoff

The first implementation plan covers only Wave 0 and Wave 1.

Wave 0 deliverables:

- `web/src/visual-regression/workbenchVisualMatrix.ts` defines the first visual-regression matrix.
- The matrix covers light, dark, default background, custom background, desktop, narrow, dense, empty, error, blocker, and destructive review states.
- Import-boundary and VUI contract tests remain part of the verification gate.

Wave 1 deliverables:

- `web/src/components/vui/aesthetic/VWorkbenchAesthetic.tsx` provides reusable quiet-workbench primitives for embedded panels, dense toolbars, dense rows, state rows, metric chips, and status chips.
- Workbench mainline style maps remove the first known header/eyebrow/button chrome anti-patterns.
- The AppShell, Chat, and Memory baselines no longer depend on card-like headers or panel-button hybrids for common visual grammar.

Wave 1 is not the full-site migration. Later waves should start only after reviewing the Wave 1 screenshots and deciding which route family should be next.
