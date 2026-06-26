# Frontend Style System Design

## Confirmed Direction

- Vibelution needs a project-level frontend style system instead of continued page-by-page visual patching.
- The default visual direction is light-first, dense, quiet, and operational.
- Custom background images must remain visible and integrated with the workbench instead of being hidden behind opaque page cards.
- Lines must stay thin. Use 1px borders and hairlines only; avoid thick borders, heavy separators, heavy shadows, and visually bulky emphasis.
- Buttons must be minimal, pale, and precise to their function. Prefer icon buttons for clear commands and put supporting explanations in hover or focus tooltips.
- Inline explanatory copy should be removed from primary UI unless it is required for errors, blockers, destructive actions, or irreversible state.

## Current Evidence

- `web/src/main.tsx` already imports `web/src/design/tokens.css` and `web/src/design/base.css`, so the project has a shared CSS foundation.
- `web/src/app/AppShell.module.css` already owns theme and custom-background behavior, including custom background images and readability overlays.
- The style system is not yet unified because large route-owned CSS modules still define their own surfaces, cards, buttons, shadows, borders, and spacing.
- High-drift modules include `TeamsRoute.module.css`, `ChatCodingRoute.module.css`, `MemoryRoute.module.css`, `AgentsRoute.module.css`, `ConversationView.module.css`, `EvolutionRoute.module.css`, and `ConfigRoute.module.css`.

## Recommended Approach

Use a shared visual primitive layer, then migrate high-impact pages in waves.

Rejected alternatives:

- Token-only cleanup: low risk, but it cannot stop page modules from continuing to invent local button, card, and surface styles.
- Full visual rewrite: too much blast radius for the current multi-session project and likely to break working flows.

The chosen approach keeps the current app structure, adds a small set of reusable visual rules, and gradually replaces divergent page styles.

## Visual Contract

### Background And Surfaces

- `AppShell` remains the only owner of the global background image, readability overlay, and theme-level background behavior.
- Route pages should not create full-page opaque wrappers that hide the background.
- Add or standardize background-aware surface tokens:
  - page glass surface;
  - panel glass surface;
  - card glass surface;
  - toolbar surface;
  - input surface;
  - overlay surface.
- Light theme should be the reference target. Dark theme may remain supported, but new frontend polish should first prove the light-background experience.
- Surfaces should use subtle translucency, restrained blur where useful, and low-contrast borders. Avoid decorative gradients or glow effects.

### Lines And Emphasis

- Borders are always 1px. Emphasis uses color, tint, icon state, status dots, or small tags instead of 2px/3px borders.
- Replace thick left borders with a 1px accent hairline, small status marker, or soft background tint.
- Avoid large shadows for normal cards and panels. Use very light elevation only where separation from the background is necessary.
- Modal or overlay depth may use a stronger shadow, but it must not become the default card style.

### Buttons And Controls

- Standardize three button families:
  - quiet icon button: compact, pale background, 1px border, tooltip required when the icon is not self-evident;
  - quiet text button: short command labels only, no explanatory sentences;
  - soft primary button: pale accent fill, used only for the main action in a local region.
- Avoid full-width buttons unless the button is the only action in a narrow/mobile row.
- Buttons should hug their content, keep stable height, and avoid layout shift on hover, loading, or disabled states.
- Dangerous actions should be visually calm by default and become clearer on hover/focus or in confirmation surfaces.

### Information Density

- Default pages should favor compact toolbars, dense tables, tight cards, and predictable grids.
- Do not put UI cards inside other decorative cards.
- Route headers should reserve space for navigation, filters, status chips, and compact actions, not long descriptions.
- Large empty bands should be collapsed unless they are intentionally reserved for live content.
- Repeated items should show the strongest identifiers first: name, status, model/tag, time/count, and action entry.

### Explanatory Text

- Non-critical explanations move to hover or focus tooltips.
- Tooltips should be concise and attached to the exact control they explain.
- Persistent helper text is allowed only for empty states, destructive confirmations, blocked/error states, or first-run missing configuration.
- UI should not display implementation explanations such as internal pipeline wording unless the user must act on it.

## Shared Primitive Targets

The implementation should introduce reusable style primitives before migrating pages:

- route workspace shell;
- dense route toolbar;
- glass panel;
- compact section header;
- dense table/list row;
- compact metric chip;
- quiet icon button;
- quiet text button;
- soft primary button;
- tooltip/focus hint pattern.

These primitives may start as CSS tokens and shared CSS classes. If repeated React behavior is needed, introduce TypeScript components under `web/src/components/` with typed props.

## Rollout Plan

### Wave 0: Foundation

- Extend `web/src/design/tokens.css` with background-aware light surfaces, hairline borders, faint shadows, and quiet button tokens.
- Extend `web/src/design/base.css` only for safe global defaults such as focus, control sizing, and common disabled behavior.
- Adjust `web/src/app/AppShell.module.css` so custom background image integration remains consistent across route surfaces.

### Wave 1: Reference Pages

- Migrate `LauncherRoute` as the shell/control reference.
- Migrate `TeamsRoute` as the dense operational page reference.
- These two pages should prove the light-background, thin-line, minimal-button contract before wider rollout.

### Wave 2: Management And Knowledge Pages

- Apply the same primitives to `AgentsRoute`, `MemoryRoute`, and `GitRoute`.
- Remove redundant explanatory copy, duplicate actions, and locally styled command buttons.

### Wave 3: Conversation Surfaces

- Apply the same visual rules to `ChatCodingRoute` and `ConversationView`.
- Treat chat/status/execution rows as a separate interaction-heavy pass because they have live updates, markdown, tool logs, and performance-sensitive expansion behavior.

### Wave 4: Remaining Complex Pages

- Migrate `ConfigRoute`, `EvolutionRoute`, `LogsRoute`, `ResearchRoute`, and canvas-heavy pages after the shared primitives are proven.

## Testing And Review Contract

- Frontend changes use TypeScript by default.
- Every implementation wave must run the narrowest relevant Vitest layout tests and `npm --prefix web run build`.
- Visual work must be checked in a real browser with screenshots for desktop and mobile-sized viewports.
- Browser review must check:
  - background image visibility and readability;
  - no thick lines or bulky separators;
  - minimal pale buttons;
  - no text overlap or clipped control labels;
  - improved information density without crowding;
  - explanatory text moved to hover/focus where appropriate.
- Logging is not needed for pure CSS/spec work unless a visual change also changes runtime state or workflow behavior.

## Non-Goals

- Do not redesign product workflows in this style-system pass.
- Do not change API contracts, backend state, model bindings, or agent behavior.
- Do not remove critical errors, warnings, destructive-action confirmations, or blocked-state reasons from visible UI.
- Do not migrate all pages in one commit. The style system should land in small, reviewable waves.

## First Implementation Boundary

The first implementation plan should cover only Wave 0 and Wave 1:

- `web/src/design/tokens.css`
- `web/src/design/base.css`
- `web/src/app/AppShell.module.css`
- `web/src/routes/LauncherRoute.*`
- `web/src/routes/TeamsRoute.*`
- focused layout tests for the migrated pages

Later pages should be handled by separate task branches after the reference pages are accepted.
