# HeroUI-first Agent Management Frontend Refactor Plan

> Date: 2026-06-29
> Scope: frontend visual architecture and first-wave Agent Management refactor plan
> Status: draft for user review
> Decision source: user selected `CBB`, then `AB`

## 1. Confirmed Direction

The first version of the frontend refactor uses **HeroUI as the unified component system**.

Confirmed choices:

- First-wave page: **Agent Management**.
- Migration mode: **page waves**, not a single all-at-once rewrite.
- Validation: **build + tests + browser screenshot** for each wave.
- Current turn: **write the complete refactor plan first**, no business code implementation.

The goal is not to build the perfect custom design system first. The first version should use HeroUI to rapidly unify the visible component language, then refine Vibelution-specific details in later waves.

## 2. Product Design Contract

The refactor must preserve the existing Vibelution visual north star:

- Light-first.
- Quiet operational workbench.
- Background-aware surfaces.
- Thin 1px line system.
- Pale, compact, precise buttons.
- High information density.
- Explanatory text reduced in the primary UI and moved to hover, tooltip, detail, or empty state surfaces.

HeroUI is allowed because it can quickly standardize component shape, states, accessibility, and interaction behavior. It must not turn Vibelution into a generic SaaS dashboard or decorative component showcase.

## 3. Technical Context

Current frontend stack:

- Vite + React 19 + TypeScript.
- CSS Modules and `web/src/design/tokens.css` / `web/src/design/base.css`.
- `lucide-react` is already the icon source.
- No current Tailwind, HeroUI, shadcn, or Radix dependencies in `web/package.json`.

Current CSS weight:

- 31 CSS Module files.
- Around 926 KB of CSS Module source.
- Largest high-drift route styles include `TeamsRoute.module.css`, `ChatCodingRoute.module.css`, `MemoryRoute.module.css`, `AgentsRoute.module.css`, and `ConversationView.module.css`.

Agent Management is a good first wave because it contains many repeated component types:

- buttons;
- chips and status pills;
- panels and cards;
- tabs and segmented controls;
- search/filter controls;
- selection rows;
- tables/lists;
- detail forms;
- danger/reset/archive zones;
- tooltips and action clusters.

## 4. External Library Decisions

### 4.1 HeroUI

Use HeroUI as the first-version component system.

Rationale from official docs:

- HeroUI is built for React and Tailwind CSS v4.
- HeroUI v3 is documented as React 19-compatible and built on React Aria.
- HeroUI uses CSS variables, BEM classes, Tailwind utilities, data attributes, and slot customization for styling.
- HeroUI has a provider requirement at the root of the React app.

Implication for Vibelution:

- HeroUI should be installed and initialized once at app level.
- Theme values must be bridged to Vibelution tokens.
- Use individual HeroUI components where useful if bundle growth needs control.
- Do not adopt HeroUI Pro page templates or marketing-style blocks for core workbench routes.

### 4.2 Tailwind CSS v4

Use Tailwind v4 as the new styling architecture for migrated components and new route surfaces.

Rationale from official docs:

- Tailwind v4 supports Vite via `@tailwindcss/vite`.
- Tailwind v4 is CSS-first and can be imported from CSS with `@import "tailwindcss"`.
- Tailwind v4 has automatic content detection and does not require the old Tailwind config by default.

Implication for Vibelution:

- Add Tailwind through the Vite plugin.
- Keep Vibelution semantic tokens as the source of product visual meaning.
- Use Tailwind classes for layout, density, state, spacing, and HeroUI slot overrides.
- Avoid arbitrary one-off colors in route code.

### 4.3 shadcn/ui and Radix

Do not use shadcn/ui or Radix as the first-version component system.

They remain future options:

- shadcn/ui can be used later when HeroUI cannot match Vibelution's desired local behavior.
- Radix can be used later for lower-level primitives if HeroUI components are too opinionated.

First-wave rule:

- No shadcn/Radix introduction unless a specific Agent Management interaction cannot be implemented cleanly with HeroUI.

### 4.4 lucide-react

Continue using `lucide-react`.

Rules:

- Icons remain semantic and action-specific.
- Icon-only buttons must have accessible labels and tooltip/title behavior.
- Do not replace lucide with HeroUI icon examples.

## 5. Architecture Proposal

### 5.1 New Frontend Style Layers

Recommended structure:

```text
web/src/design/
  tokens.css
  base.css
  tailwind.css
  heroui-theme.css

web/src/components/heroui/
  HeroProvider.tsx
  heroSlots.ts
  heroVariants.ts

web/src/components/ui/
  VButton.tsx
  VChip.tsx
  VPanel.tsx
  VField.tsx
  VTooltip.tsx
```

The exact filenames may change during implementation, but the responsibilities should remain stable.

### 5.2 Layer Responsibilities

`tokens.css`

- Owns Vibelution semantic design values.
- Remains the primary product design source.
- Keeps light/dark theme and background-aware variables.

`tailwind.css`

- Imports Tailwind.
- Adds Vibelution theme mappings using Tailwind v4's CSS-first model.
- Defines utility-friendly aliases for surfaces, hairlines, control heights, and density.

`heroui-theme.css`

- Overrides HeroUI theme variables and BEM/data-attribute styling.
- Makes HeroUI look like Vibelution: lighter, thinner, quieter, denser.
- Avoids route-specific hard-coded component styling.

`HeroProvider.tsx`

- Wraps the app with `HeroUIProvider`.
- Integrates with the existing app theme state.
- Keeps provider setup centralized.

`components/ui/*`

- Provides Vibelution wrappers over commonly used HeroUI components.
- Hides repetitive HeroUI props and slot class names from route files.
- Keeps route code focused on product structure, not component styling internals.

## 6. First-wave Agent Management Refactor

### 6.1 Page Goals

The first Agent Management wave should make the page visibly more consistent and easier to scan without changing backend behavior.

Expected user-visible result:

- Header, summary, filters, agent list, detail panel, and action zones share one component grammar.
- Buttons are compact, pale, and precise.
- Status values use unified HeroUI-backed chips/badges.
- Repeated explanatory text is reduced or moved to hover/details.
- Main Agent list and selected detail panel remain high-density.
- Background image remains visible through the workspace; no full-page opaque slab.

### 6.2 Non-goals

First wave does not:

- Change Agent API contracts.
- Change workspace cache behavior.
- Redesign backend data structures.
- Replace all pages.
- Delete all CSS Modules.
- Introduce shadcn/Radix.
- Rework Agent business logic.

### 6.3 Candidate Component Mapping

| Current Surface | First-wave HeroUI Direction |
| --- | --- |
| Header refresh / return actions | `Button` via Vibelution wrapper |
| Summary cards | `Card` or custom `VPanel` backed by HeroUI styling |
| Health/runtime/count pills | `Chip` |
| Search input | `Input` |
| Group/category controls | `Tabs`, `ButtonGroup`, or compact custom wrapper |
| Agent rows | `Table` or dense custom row list using HeroUI slots |
| Detail tabs | `Tabs` |
| Forms/selects | `Input`, `Textarea`, `Select`, `Switch`, `Checkbox` |
| Dialog-like actions | `Modal` if existing behavior needs overlay |
| Tooltips | HeroUI `Tooltip` |
| Danger/reset/archive zones | `Card`/`Alert` style with calm default danger tone |

### 6.4 Agent Page Migration Sequence

1. **Foundation patch**
   - Install Tailwind v4 and HeroUI.
   - Add Vite Tailwind plugin.
   - Add HeroUI provider.
   - Add Vibelution HeroUI theme bridge.
   - Add first wrappers: `VButton`, `VChip`, `VTooltip`, `VPanel`.

2. **Agent Management header and summary**
   - Replace route-specific refresh/summary/pill styles with wrappers.
   - Keep layout stable.
   - Validate screenshot against existing first viewport.

3. **Agent list and filters**
   - Replace search/filter controls.
   - Convert agent state/role/model tags to unified chips.
   - Keep list density at least as high as current layout.
   - Preserve selected/current/running/unread visual states.

4. **Detail panel controls**
   - Migrate tabs, buttons, fields, selects, switches, and status sections.
   - Keep form behavior unchanged.
   - Move long helper text into tooltip/details where possible.

5. **Danger and reset zones**
   - Unify archive/purge/reset styling.
   - Keep dangerous actions calm by default but unmistakable on hover/focus/confirmation.

6. **CSS cleanup**
   - Remove only dead Agent Management CSS proven unused by tests and source search.
   - Do not globally delete shared styles until later waves.

## 7. Styling Rules For HeroUI In Vibelution

HeroUI components must be customized to these defaults:

- `radius`: small to medium; avoid pill everything except chips.
- `shadow`: off or very faint by default.
- `border`: 1px hairline.
- `button height`: compact.
- `button color`: pale default, one soft primary per local region.
- `card background`: translucent or background-aware, not opaque white slabs.
- `table/list rows`: dense, stable height, clear hover/selected states.
- `focus`: accessibility-first; focus ring may be stronger than normal borders.
- `motion`: low intensity, respect reduced motion.

No route may use HeroUI defaults if those defaults conflict with Vibelution's light, quiet, dense visual language.

## 8. Testing And Review Contract

Each wave must pass:

- `npm --prefix web run build`
- relevant focused Vitest tests for changed route/components
- route layout/static tests if touched
- browser screenshot of the changed page

For Agent Management first wave:

- Add/update tests that assert Tailwind/HeroUI provider setup.
- Add/update Agent Management tests that assert the route consumes Vibelution UI wrappers or HeroUI components through the approved layer.
- Use browser screenshots for:
  - Agent Management default page;
  - active/selected agent state if available;
  - form/detail panel state if reachable;
  - narrow viewport only if the changed surface is responsive-sensitive.

## 9. Rollback Plan

Every wave should be reversible.

Rollback rules:

- Keep each wave on its own branch.
- Do not mix dependency installation, provider setup, Agent route migration, and CSS deletion into one unreviewable patch unless the patch is still small.
- If HeroUI styling breaks density or layout, keep Tailwind setup and provider work, but revert the route migration.
- Do not delete old CSS until the corresponding migrated surface is validated.

## 10. Key Risks

### Risk 1: HeroUI default style is too decorative

Mitigation:

- Use wrappers and theme overrides.
- Review screenshots against Vibelution's style system doc.
- Prefer compact slots and low-contrast variants.

### Risk 2: CSS Modules and Tailwind fight each other

Mitigation:

- Tailwind is the new migration surface.
- CSS Modules remain for legacy and complex layout during transition.
- Use clear ownership comments and tests for migrated sections.

### Risk 3: Bundle or CSS size grows too much

Mitigation:

- Prefer individual HeroUI component imports if needed.
- Run `npm --prefix web run build`.
- Run bundle budget checks if dependency size becomes a concern.

### Risk 4: Accessibility or keyboard behavior changes

Mitigation:

- HeroUI/React Aria should improve baseline accessibility.
- Preserve all accessible names for icon-only buttons.
- Check keyboard focus for menus, tabs, dialogs, and list actions.

### Risk 5: Agent Management logic is too large for safe visual rewrite

Mitigation:

- Refactor only visible component surfaces first.
- Avoid business-logic changes.
- Split implementation into header/summary, list/filter, detail/form, danger/reset patches.

## 11. Implementation Readiness Checklist

Before starting implementation:

- Create an isolated worktree and branch.
- Claim write scope for:
  - `web/package.json`
  - `web/package-lock.json`
  - `web/vite.config.ts`
  - `web/src/design/**`
  - `web/src/components/**`
  - `web/src/routes/AgentsRoute.tsx`
  - `web/src/routes/AgentsRoute.module.css`
  - related tests
- Confirm no active conflicting claim touches Agent Management.
- Run baseline focused tests for `AgentsRoute`.
- Capture or inspect current Agent Management page before editing.

Implementation should start with the foundation patch only if dependency installation is approved. Then continue into Agent Management migration waves.

## 12. Open Decisions For User Review

1. Should the first implementation branch include dependency setup and the first Agent Management visual surface in one PR, or split them?
   - Recommended: split if dependency diff is large; combine if the setup is tiny and tests stay clear.

2. Should Agent Management use HeroUI `Table`, or keep a custom dense row list using HeroUI `Card/Chip/Button` primitives?
   - Recommended: decide after inspecting current row interactions in browser. Dense custom row list is likely safer for the first wave.

3. Should old CSS Modules be aggressively deleted after each surface migration?
   - Recommended: delete only proven-dead CSS per wave.

## 13. Source Notes

- HeroUI React docs: HeroUI is a React component library built on Tailwind CSS v4 and React Aria, with provider setup and customizable CSS variables/slots.
- HeroUI Tailwind v4 docs: HeroUI v3 follows Tailwind v4 and CSS-first theming.
- Tailwind CSS docs: Tailwind v4 supports Vite through `@tailwindcss/vite` and CSS import via `@import "tailwindcss"`.
- Existing Vibelution style spec: `docs/superpowers/specs/2026-06-26-frontend-style-system-design.md`.
