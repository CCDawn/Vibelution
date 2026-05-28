# Vibelution Design Context

## Design Register

Vibelution uses a product UI register. The design serves repeated engineering work, runtime diagnosis, and controlled evolution. The default visual mode is compact, ops-heavy, and console-like.

## Theme

Default to dark mode for the primary workbench: a developer inspects runtime state, logs, diffs, and Agent activity for long sessions on a desktop monitor, often while debugging uncertain behavior. Light mode exists as a supported alternate theme, but dark mode is the primary design reference.

## Color Strategy

Restrained product palette.

- Canvas: deep neutral surfaces anchored by `--bg-canvas`, `--bg-panel`, and `--surface-panel`.
- Primary text: high-contrast neutral via `--fg-primary`.
- Secondary text: quieter operational copy via `--fg-secondary`.
- Tertiary text: metadata, timestamps, and less urgent labels via `--fg-tertiary`.
- Primary accent: blue via `--accent-warm` and `--accent-warm-2` for selection, primary action, focus, and active state.
- Secondary accent: teal via `--accent-cool` and `--accent-cool-2` for complementary status or secondary operational emphasis.
- Semantic state: `--state-success`, `--state-warning`, and `--state-error` for real state only.

Future palette work should migrate toward perceptual OKLCH tokens when practical, but existing CSS tokens remain the source of truth until a scoped token migration is planned and tested.

## Typography

- Use the existing native-feeling UI stack:
  - Display: `Segoe UI Variable Display`, `Segoe UI`, sans-serif.
  - Body: `Segoe UI Variable Text`, `Segoe UI`, sans-serif.
  - Mono: `JetBrains Mono`, `Cascadia Code`, monospace.
- Keep product typography fixed and compact. Do not use viewport-scaled hero typography inside workbench routes.
- Use mono type for code, logs, IDs, technical traces, and structured evidence. Do not use mono only as a decorative signal.
- Maintain clear scale contrast without oversized headings in dense panels.
- Letter spacing should stay at `0` for normal UI text. Use tracked micro-labels sparingly.

## Layout

- Favor stable app-shell structure: fixed top bar, route workspace, contextual sidebars, panels, tabs, and split panes.
- Use predictable grids and flex layouts. For dense tools, consistency is more valuable than surprise.
- Route-level surfaces should be compact and scannable, with important state above fold.
- Avoid page sections that look like marketing bands. These are work surfaces.
- Do not nest cards. Use spacing, dividers, headings, and alignment to create hierarchy inside panels.
- Cards are acceptable for repeated items, summaries, modals, or genuinely framed tools, but not as the default answer for every grouping.

## Components

- Interactive controls need visible default, hover, focus-visible, active, disabled, loading, error, and success states when those states are possible.
- Keep button, input, select, tab, pill, and panel vocabulary consistent across routes.
- Use the existing `lucide-react` icon set when an icon is needed. Do not introduce a second icon family without a scoped design-system decision.
- Preserve small radii:
  - Controls: `--radius-control` around 7px.
  - Panels: `--radius-panel` around 8px.
  - Cards: `--radius-card` around 7px.
  - Pills may remain fully rounded when they are badges or compact status chips.
- Focus rings must remain visible and consistent through `--focus-ring`.

## Motion

- Motion is for state communication, not decoration.
- Normal UI feedback should stay around 100-250ms.
- Larger layout changes can use 300-500ms only when the transition helps orientation.
- Avoid page-load choreography on task routes.
- Do not animate layout-driving properties casually. Prefer opacity, transform, bounded reveal, or state-specific transitions.
- Respect reduced-motion preferences.

## Responsive Behavior

- Design primarily for desktop workbench use, but pages must not break on narrower windows.
- Collapse sidebars, stack panels, and preserve task order instead of shrinking text beyond usability.
- Touch targets should be at least 44px where touch use is plausible.
- Text must not overflow buttons, cards, status chips, or route headers. Long Agent names, paths, IDs, and translated strings need wrapping or truncation rules.

## UX Writing

- Copy should be short, specific, and operational.
- Buttons should name the action: `Save changes`, `Open logs`, `Archive Agent`, `Start run`.
- Destructive actions must name the object and consequence.
- Empty states should explain what becomes possible after the first action.
- Errors should say what happened, why when known, and what the user can do next.
- Keep Vibelution domain terms stable: Agent, Turn, Tool, Tool Call, Workbench, Self-Evolution, Supervised Evolution, Gym, Case, Attempt, Trace, Decision Record, Lineage.

## Design Bans

- No generic landing-page hero treatment in product routes.
- No decorative gradient text.
- No glass panels as the default component style.
- No side-stripe accent borders on cards or alerts.
- No repeated icon-heading-text card grids as a route scaffold.
- No modals as the first answer when inline or progressive disclosure would work.
- No display fonts in labels, buttons, data, logs, or dense operational controls.
- No decorative motion that delays task completion.

## Verification Expectations

For frontend visual changes, verify the relevant route in a browser or screenshot-capable tool across at least desktop and a narrower viewport when feasible. Check contrast, focus, responsive behavior, text overflow, loading or empty states, and whether the result still reads as a Vibelution workbench surface rather than a generic AI-generated interface.
