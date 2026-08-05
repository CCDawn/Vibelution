# Vibelution Frontend Style System Design V2.1

> Light-first · Quiet operational · Background-aware · Token-driven

This spec defines the project-level frontend visual language for Vibelution. It replaces page-by-page visual patching with a reusable, reviewable, gradually migratable style system.

## 0. Design Conclusion

Vibelution should not become a heavy SaaS admin panel, a marketing landing page, or a high-saturation decorative dashboard. Its best direction is:

**A light, quiet, dense, background-aware AI workbench.**

Core traits:

- **Light-first**: the light experience is the primary design target; dark theme remains supported but is not the main anchor for new polish.
- **Dense but calm**: information density is high, but hierarchy, spacing, state, and color keep scanning clear.
- **Background-integrated**: custom backgrounds are part of product personality and must not be hidden behind opaque full-page cards.
- **Thin-line system**: normal borders, dividers, and emphasis use 1px hairlines. Thick borders and heavy shadows are not the default layering tool.
- **Quiet controls**: buttons are compact, pale, precise, and close to the task. They should not create visual noise.
- **Operational clarity**: the UI primarily serves task execution, state judgment, filtering, switching, inspection, and recovery.

## 1. North Star: Ambient Workbench

### 1.1 Product Feel

| Keyword | Meaning | Implementation |
| --- | --- | --- |
| Ambient | Background, theme, status, and workspace feel naturally connected | Translucent surfaces, low-contrast borders, light readability overlays |
| Workbench | The UI is an operating surface, not a showcase page | Compact toolbars, stable grids, status and actions first |
| Quiet | The default state is calm; emphasis appears only when useful | Pale buttons, thin lines, faint shadows, hover/focus strengthening |
| Precise | Every control is short, predictable, and task-specific | Icon buttons with tooltip, short labels, stable heights |
| Alive | AI, task, and session states feel live without being distracting | Status dots, compact progress chips, low-intensity motion |
| Systematic | Pages do not invent local card/button/shadow languages | Semantic tokens, shared primitives, wave-based migration |

### 1.2 Visual Sentence

**A translucent control desk laid over the user's background: light, thin, precise, dense, and always readable.**

### 1.3 Directions To Avoid

- Heavy admin style: oversized cards, large shadows, oversized buttons, and excessive whitespace.
- Decorative glass style: high blur, colored glow, aggressive gradients, or glossy effects.
- Route islands: each route owning its own button, card, shadow, and surface grammar.
- Manual-like UI: non-essential explanatory text permanently occupying the primary interface.

## 2. Current Project Judgment

### 2.1 Existing Foundation

- `web/src/main.tsx` already imports `web/src/design/tokens.css` and `web/src/design/base.css`.
- `web/src/app/AppShell.module.css` already owns theme and custom-background behavior, including custom background images and readability overlays.
- The problem is not absence of a foundation. The problem is route-owned CSS continuing to redefine surfaces, cards, buttons, shadows, borders, and spacing.

### 2.2 High-Drift Modules

Prioritize style-system migration for:

- `TeamsRoute.module.css`
- `ChatCodingRoute.module.css`
- `MemoryRoute.module.css`
- `AgentsRoute.module.css`
- `ConversationView.module.css`
- `EvolutionRoute.module.css`
- `ConfigRoute.module.css`

### 2.3 Strategy

Adopt **shared visual primitives + gradual migration**.

| Approach | Decision | Reason |
| --- | --- | --- |
| Token cleanup only | Reject | It cannot stop pages from continuing to invent local button, card, and shadow rules |
| Full visual rewrite | Reject | Too much blast radius for a multi-session project |
| Shared primitive layer, then wave migration | Adopt | Lower risk, repeatable review, sustainable consistency |

## 3. Design Principles

### P1: AppShell Owns Global Background

`AppShell` is the only owner of global background images, theme backgrounds, and readability overlays.

Rules:

- Route pages must not create full-page opaque containers that hide the background.
- Main route surfaces should float over the background instead of replacing it.
- Readability issues should be solved through AppShell overlay, surface alpha, local tint, and text contrast before route-level full-screen covers.
- Page modules must not define body/page-level background images, strong gradients, or full-screen solid masks.

### P2: Hierarchy Comes From Semantic Surfaces, Not Heavy Shadows

Layer order:

1. app background;
2. readability overlay;
3. route workspace;
4. panel/card;
5. toolbar/input;
6. popover/modal;
7. focus/active/danger state.

Rules:

- Normal panels and cards do not use large shadows.
- Layering mainly uses alpha, border, spacing, status color, and restrained blur.
- Modal/popover depth may be stronger, but modal-level shadows must not become normal card style.

### P3: Density Is A Strength, Not Compression For Its Own Sake

Correct density:

- remove low-value explanatory copy, duplicate titles, and decorative card nesting;
- use stable grids, short labels, status chips, and right-side action clusters;
- keep critical data in the first viewport where possible;
- move secondary explanations into tooltips, details, popovers, or empty states.

Incorrect density:

- simply shrinking font size;
- simply reducing line-height;
- forcing unrelated actions into one row;
- stacking color and icons to simulate richness.

### P4: Buttons Are Quiet By Default, But State Must Be Clear

Buttons trigger actions; they are not decoration.

Rules:

- Default buttons use pale background, 1px border, and short labels.
- Each local region should have at most one soft primary action.
- Dangerous actions are calm by default, then become unmistakable in hover/focus or confirmation surfaces.
- Icon buttons require an accessible name and a tooltip when the icon is not self-evident.

### P5: Accessibility Overrides Thin-Line Aesthetics

Thin-line means ordinary visual boundaries, not every interaction affordance.

Rules:

- Keyboard focus must be clearly visible.
- Focus rings may use a 2px outline or dual ring because they are accessibility affordances, not decorative borders.
- Icon-only actions need accessible names.
- Important state cannot rely on color alone; combine text, icon, dot, chip, or structure.

## 4. Visual Language

### 4.1 Theme Direction: Light-First Operational Glass

The visual language is:

**Light-first Operational Glass**: light-first, background-integrated, translucent hierarchy, thin separators, low-noise controls, compact information architecture.

Glass is only a tool for background integration and hierarchy. It is not the visual protagonist.

### 4.2 Visual Signature

| Dimension | Prefer | Avoid |
| --- | --- | --- |
| Background | Custom background remains visible with readability overlay | Full-page white/black cards hiding the background |
| Surface | Translucent, low blur, thin border, light tint | High blur, glow, decorative glass |
| Boundary | 1px low-contrast hairline | 2px/3px borders, thick separators |
| Shadow | Very faint, only to assist separation | Large drop shadows and floating-card effects |
| Color | Neutral base, small accent usage, semantic states | Large high-saturation blocks |
| Layout | Workbench grids and dense grouping | Marketing whitespace and decorative card grids |
| Text | Short, precise, close to the object | Long descriptions, implementation details, repeated help copy |
| Motion | Micro feedback and state continuity | Bouncy, frequent, or distracting animation |

### 4.3 Color Strategy

Use **neutral + existing accents + semantic states**.

- Neutral: background, surface, text, borders, inputs.
- Existing accents: current project tokens such as `--accent-warm`, `--accent-cool`, and their variants.
- Semantic states: success, warning, error, info, running.
- Background sampling: when custom background exists, surface alpha and overlay must preserve readability.

Rules:

- Do not hard-code arbitrary hex values inside route modules.
- Do not create one route-specific theme color per page.
- Accent is for current position, action, or state; it should not fill large page areas.
- Danger should not become a high-saturation red block by default.

## 5. Token Architecture

### 5.1 Token Layers

| Layer | Purpose | Examples |
| --- | --- | --- |
| Foundation tokens | Raw design variables | color scale, spacing scale, radius, shadow, duration |
| Semantic tokens | Product meaning | `--surface-panel`, `--fg-secondary`, `--border-hairline` |
| Component tokens | Component-local contract | `--button-quiet-bg`, `--toolbar-height-dense`, `--row-height-dense` |

Routes should consume semantic/component tokens, not raw visual values.

### 5.2 Token Compatibility Rules

- Keep compatibility with the current token shape in `web/src/design/tokens.css`.
- Current accent tokens such as `--accent-warm`, `--accent-warm-2`, `--accent-cool`, and `--accent-cool-2` remain the first implementation target.
- Do not introduce names like `--accent-600` unless an explicit accent scale is added in the same implementation wave.
- Because current `:root` is dark-first and `[data-theme="light"]` overrides it, light-first values must be added under `[data-theme="light"]` or through neutral semantic aliases that are explicitly theme-aware.

### 5.3 Suggested Semantic Tokens

These names describe the target contract. Exact values must be tuned with real Launcher and Teams screenshots.

```css
/* Shared semantic shape; values are theme-specific. */
--surface-page
--surface-header
--surface-panel
--surface-panel-muted
--surface-panel-strong
--surface-card
--surface-card-muted
--surface-toolbar
--surface-input
--surface-overlay

--border-hairline
--border-soft
--border-strong
--border-accent-hairline

--shadow-hairline
--shadow-panel-faint
--shadow-overlay

--blur-page-max
--blur-panel-max
--blur-overlay-max

--control-height-sm
--control-height-md
--row-height-dense
--toolbar-height-dense

--duration-fast
--duration-normal
--ease-standard
```

### 5.4 Light Theme Starting Point

Do not paste these values blindly; use them as starting ranges for implementation.

```css
[data-theme="light"] {
  --surface-page: rgba(255, 255, 255, 0.58);
  --surface-panel: rgba(255, 255, 255, 0.66);
  --surface-card: rgba(255, 255, 255, 0.54);
  --surface-toolbar: rgba(255, 255, 255, 0.50);
  --surface-input: rgba(255, 255, 255, 0.68);
  --surface-overlay: rgba(255, 255, 255, 0.88);

  --border-hairline: rgba(15, 23, 42, 0.08);
  --border-soft: rgba(15, 23, 42, 0.10);
  --border-strong: rgba(15, 23, 42, 0.16);
  --border-accent-hairline: color-mix(in srgb, var(--accent-cool) 42%, transparent);

  --shadow-hairline: 0 1px 0 rgba(15, 23, 42, 0.04);
  --shadow-panel-faint: 0 8px 24px rgba(15, 23, 42, 0.055);
  --shadow-overlay: 0 18px 56px rgba(15, 23, 42, 0.14);

  --blur-page-max: 8px;
  --blur-panel-max: 10px;
  --blur-overlay-max: 18px;

  --control-height-sm: 28px;
  --control-height-md: 32px;
  --row-height-dense: 36px;
  --toolbar-height-dense: 40px;
}
```

### 5.5 Dark Theme Rules

Dark theme remains supported, but new polish is judged first in light mode.

Dark theme should:

- keep custom background visible with stronger overlay;
- use dark translucent surfaces;
- keep 1px borders with slightly stronger contrast;
- avoid pure black backgrounds and glow-heavy accents;
- avoid turning every action into a high-contrast filled button.

## 6. Surface System

### 6.1 Surface Types

| Surface | Use | Strength | Rules |
| --- | --- | --- | --- |
| `page` | route root workspace | medium-low | must not fully hide background |
| `panel` | primary content panel | medium | supports faint blur and hairline |
| `card` | repeated item, local module, metric | low | no decorative card nesting |
| `toolbar` | filter/action/nav row | low | stable height and compact controls |
| `input` | input/select/search | medium | readability first; not too transparent |
| `overlay` | popover/modal/dropdown | high | higher alpha and stronger shadow allowed |

### 6.2 Surface Constraints

- `page` and `panel` may use `backdrop-filter`, but blur is capped by tokens and must remain restrained.
- Long lists must not put `backdrop-filter` on every row because of performance and visual noise.
- `card` defaults to tint + border, not strong blur.
- `toolbar` should blend into the page and must not look like an oversized independent card.
- `overlay` should clearly sit above the page without leaving visual jumps after close.

### 6.3 Background Readability Order

When a custom background is complex:

1. adjust AppShell readability overlay;
2. adjust `--surface-page` / `--surface-panel` alpha;
3. add restrained local blur;
4. do not add route-owned full-screen opaque wrappers.

## 7. Layout And Information Density

### 7.1 Standard Route Structure

```text
RouteWorkspace
├─ RouteHeader
│  ├─ title / status / context chips
│  └─ compact actions
├─ RouteToolbar
│  ├─ search / filters / segmented view switch
│  └─ secondary actions
└─ RouteContent
   ├─ primary panel / list / table
   └─ optional inspector / side panel
```

### 7.2 Header Rules

Headers are for orientation and operation, not explanation.

Allowed:

- page title;
- current state;
- key metric chips;
- primary filter;
- short action cluster.

Avoid:

- multi-line introduction text;
- implementation detail explanation;
- hero-like areas;
- duplicate entry buttons.

### 7.3 Toolbar Rules

- Default height uses `--toolbar-height-dense`.
- Controls in the same toolbar keep consistent height.
- Search, filters, sorting, and view switching should stay on one row on desktop.
- Mobile may wrap into two rows or use an overflow menu, but should not turn every control into full-width buttons.

### 7.4 List And Table Rules

Rows should present the strongest identifiers first:

```text
Name / Primary identifier -> Status -> Model/Tag -> Time/Count -> Action entry
```

Rules:

- Use dense rows while keeping enough hit area.
- State uses dot/chip/tint, not thick borders.
- Hover uses a subtle background change only; no lift or resize.
- Right-side action clusters keep stable width to avoid layout shift.

### 7.5 Dense Grid Grouping

Dense grid grouping is allowed for multi-module workbench pages, but only as an information architecture tool.

Rules:

- grouping must help scanning and operation, not decorate the page;
- no card collage effect;
- gap, min width, and panel sizing use tokens;
- every block has a clear job: status, list, config, execution, log, inspection, or recovery.

## 8. Typography And Copy

### 8.1 Type Scale

| Level | Use | Recommendation |
| --- | --- | --- |
| Page title | route name | 16-20px, semibold |
| Section title | panel/section | 13-15px, medium/semibold |
| Body | text and rows | 13-14px |
| Meta | time, path, count, secondary info | 11-12px |
| Chip | status, tag, model | 11-12px, short text |

### 8.2 Copy Rules

- Object first, action second.
- State first, explanation second.
- Prefer short labels over sentences.
- Put ordinary explanations in tooltips, not in the primary UI.
- Use empty states for first-time explanation instead of repeating help text in normal states.

### 8.3 Copy Placement Matrix

| Copy Type | Persistent? | Placement |
| --- | --- | --- |
| Error/blocker reason | Yes | inline, near the affected object |
| Destructive action explanation | Yes | confirmation surface |
| Missing first-run configuration | Yes | empty/onboarding state |
| Ordinary button explanation | No | tooltip |
| Technical implementation detail | No | dev/debug details |
| Repeated flow explanation | No | docs or help popover |

## 9. Buttons And Controls

### 9.1 Button Families

| Type | Use | Visual | Rules |
| --- | --- | --- | --- |
| Quiet icon button | common clear command | pale background, 1px border, icon | non-obvious icons require tooltip |
| Quiet text button | secondary command | short label, pale or transparent | no explanatory sentence |
| Soft primary button | local main action | pale accent fill | at most one per local region |
| Danger button | delete/reset/destructive action | calm by default, stronger in confirmation | clear text or confirmation required |
| Toggle/segment | view switch/filter | light background, selected tint | no strong filled block |

### 9.2 Button States

All button families need stable:

- default;
- hover;
- focus-visible;
- active;
- disabled;
- loading;
- selected / pressed;
- destructive pending.

Rules:

- Hover does not change size or position.
- Loading reserves width or icon slot to avoid jump.
- Disabled remains visible but lower contrast.
- Selected state uses tint plus border or indicator, not thick border.

### 9.3 Size Guidance

| Context | Height | Notes |
| --- | --- | --- |
| dense toolbar | 28-32px | desktop workbench |
| standard form | 32-36px | settings/config pages |
| mobile touch | 36-44px | touch-priority regions |
| icon-only | 28-32px desktop, 36px+ mobile | needs label, tooltip, or aria-label |

## 10. State, Feedback, And System Information

### 10.1 State Expression

| State | Expression | Avoid |
| --- | --- | --- |
| idle | muted text / neutral dot | large gray card |
| running | subtle animated dot / progress chip | large flashing area |
| success | green-tinted chip / check icon | whole green block |
| warning | amber tint + short reason | color-only warning |
| error | red tint + recovery action | red border only |
| blocked | clear reason + next action | internal technical wording only |

### 10.2 Loading Rules

- Prefer local loading over full-page blocking spinners.
- Lists use skeleton rows or reserved space to avoid layout jump.
- Long tasks show running chip, stage name, and recent update time.
- Recoverable errors show recovery actions.

### 10.3 Toast And Inline Feedback

- Success feedback should be short toast or state update, not interruption.
- Errors and blockers are inline and close to the affected object.
- Irreversible or dangerous actions use confirmation surfaces.

## 11. Motion

### 11.1 Motion Principles

Motion is for feedback, continuity, and state change; not attention-grabbing.

Prefer:

- hover/focus transition: 120-180ms;
- popover/modal enter/exit: 160-240ms;
- low-intensity running feedback;
- small opacity/translate for list add/remove.

Avoid:

- bouncing, jelly effects, and long-distance movement;
- high-frequency flashing;
- card lift on every hover;
- large page transition scaling.

### 11.2 Reduced Motion

Support `prefers-reduced-motion`:

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    scroll-behavior: auto !important;
    animation-duration: 1ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 1ms !important;
  }
}
```

Critical state must not depend only on animation.

## 12. Accessibility And Usability

### 12.1 Focus

- Every interactive element supports `:focus-visible`.
- Focus ring may be stronger than normal borders.
- Focus must not be clipped by sticky headers, popovers, or `overflow: hidden`.
- Keyboard navigation must cover primary workflows.

### 12.2 Contrast

- Body text, labels, and critical values must remain readable.
- Muted text cannot be so low contrast that it disappears on image backgrounds.
- Transparent surfaces must be validated against real custom backgrounds, not only plain white.

### 12.3 Target Size

- Desktop dense controls may be compact but need enough hit area.
- Mobile icon-only controls should not fall below a 36px visual hit area.
- Very small icons need padding to provide the target size.

### 12.4 Tooltip

- Tooltips must be available by hover and focus.
- Tooltip content is concise.
- Tooltips do not carry critical errors or irreversible-action explanation.
- Tooltips do not replace accessible names.

## 13. Shared Primitive Targets

First establish shared visual primitives. Start with CSS tokens and shared classes. Promote to TypeScript components only when behavior or repeated structure appears in at least two migrated pages.

| Primitive | Purpose | First Form |
| --- | --- | --- |
| `RouteWorkspace` | route root layout and background-aware surface | CSS primitive first |
| `RouteHeader` | page title, state, main actions | CSS primitive first |
| `DenseToolbar` | search, filters, view switch, short actions | CSS primitive first |
| `GlassPanel` | primary content container | CSS primitive first |
| `GlassCard` | repeated item/local info block | CSS primitive first |
| `SectionHeader` | compact section title plus action | CSS primitive first |
| `DenseRow` | table/list row visual rule | CSS primitive first |
| `MetricChip` | small metric/status/count | CSS primitive first |
| `QuietIconButton` | icon-only action | CSS primitive first; TS later if behavior repeats |
| `QuietTextButton` | secondary text command | CSS primitive first |
| `SoftPrimaryButton` | local primary action | CSS primitive first |
| `FocusHintTooltip` | hover/focus explanation | TS component when behavior is shared |

Suggested class names:

```css
.uiWorkspace {}
.uiHeader {}
.uiToolbar {}
.uiPanel {}
.uiCard {}
.uiSectionHeader {}
.uiDenseRow {}
.uiMetricChip {}
.uiButtonQuiet {}
.uiButtonSoftPrimary {}
.uiIconButton {}
```

Rules:

- `ui*` means visual primitive, not business component.
- Route CSS modules may compose primitives and define local layout.
- Route CSS modules must not redefine the global button, card, shadow, or surface grammar.

## 14. Route Migration Strategy

### Wave 0: Foundation

Goal: establish the visual language without changing business workflows.

Scope:

- `web/src/design/tokens.css`
- `web/src/design/base.css`
- `web/src/app/AppShell.module.css`

Tasks:

- add background-aware surface tokens;
- add or align hairline, faint shadow, blur cap, radius, motion, and density tokens;
- unify focus-visible, disabled, and baseline control sizing;
- ensure custom background remains visible and readable in light theme;
- weaken AppShell styles that conflict with the new surface model.

Acceptance:

- background image remains visible;
- routes are not hidden by opaque page wrappers;
- normal boundaries are 1px;
- focus ring remains clear;
- `npm --prefix web run build` passes.

### Wave 1: Reference Pages

Goal: establish copyable page examples.

Scope:

- `web/src/routes/LauncherRoute.*`
- `web/src/routes/TeamsRoute.*`

LauncherRoute proves:

- shell, toolbar, button, and panel style are unified;
- the entry surface is light and clear on a custom background;
- custom background remains visible.

TeamsRoute proves:

- dense operational pages remain readable, scannable, and operable;
- lists, tables, states, and actions do not become cramped;
- thin lines and pale buttons are enough for complex workflows.

Acceptance:

- desktop and mobile screenshots become reference material for later pages;
- local route CSS no longer owns duplicate card/button/shadow rules where shared primitives cover them;
- no control text truncation or overlap in desktop and mobile-sized viewports.

### Wave 2: Management And Knowledge Pages

Scope:

- `AgentsRoute`
- `MemoryRoute`
- `GitRoute`

Focus:

- remove redundant explanatory copy;
- unify list/card/panel/button treatment;
- keep missing configuration, errors, and empty states visible;
- move ordinary explanations to tooltip/focus hint.

### Wave 3: Conversation Surfaces

Scope:

- `ChatCodingRoute`
- `ConversationView`

Focus:

- handle live updates, markdown, tool logs, and execution rows separately;
- prevent expand/collapse and long content from causing layout instability;
- keep running/error/blocked state clear;
- remove heavy chat panel nesting.

### Wave 4: Remaining Complex Pages

Scope:

- `ConfigRoute`
- `EvolutionRoute`
- `LogsRoute`
- `ResearchRoute`
- canvas-heavy pages.

Focus:

- migrate after reference pages are accepted;
- clean duplicate surface/button rules before local complex layout details.

## 15. Route-Level Governance

### 15.1 Route CSS May Define

- local grid/flex layout;
- route-specific column widths;
- business-state layout;
- responsive breakpoints;
- special content area dimensions.

### 15.2 Route CSS Must Not Define

- new generic button families;
- new generic card/panel shadow systems;
- full-page opaque wrappers;
- thick status borders;
- large colored backgrounds for ordinary emphasis;
- non-essential implementation explanations in primary UI.

### 15.3 Exceptions

Short-term exceptions are allowed only when they are explicit:

- third-party components cannot be covered directly by primitives;
- canvas/graph pages need special performance treatment;
- rich text or markdown content needs local typography rules;
- old pages keep local styles before their migration wave.

Exception comment format:

```css
/* style-system-exception: reason; remove after Wave N migration */
```

## 16. Testing And Review Contract

### 16.1 Required Checks

Every implementation wave must run:

```bash
npm --prefix web run build
```

and the narrowest relevant Vitest/layout tests.

### 16.2 Browser Screenshot Checks

Check at least:

- desktop viewport;
- mobile-sized viewport;
- light theme;
- dark theme smoke check;
- custom background enabled;
- default background enabled.

### 16.3 Visual Checklist

| Check | Passing Standard |
| --- | --- |
| Background visibility | route surfaces do not fully hide background |
| Readability | text remains clear on complex background |
| Thin-line system | normal borders/separators are 1px |
| Quiet buttons | no unnecessary large, full-width, or high-saturation buttons |
| Density | more useful first-viewport information without crowding |
| State clarity | running/error/blocked/success are easy to identify |
| Copy reduction | non-essential explanations moved to tooltip/focus hint |
| No layout jump | hover/loading/disabled do not resize controls |
| Visible focus | keyboard focus is clear and not clipped |
| Mobile usability | no truncation; hit areas remain usable |

### 16.4 Regression Risks

Watch for:

- custom background hidden again by opaque wrappers;
- local CSS reinventing card/button/shadow systems;
- density reducing readability or target size;
- tooltips carrying critical errors or destructive-operation instructions;
- focus rings clipped by overflow containers.

## 17. First Implementation Boundary

The first implementation plan covers only Wave 0 and Wave 1.

Included:

- `web/src/design/tokens.css`
- `web/src/design/base.css`
- `web/src/app/AppShell.module.css`
- `web/src/routes/LauncherRoute.*`
- `web/src/routes/TeamsRoute.*`
- focused layout tests for migrated pages.

Excluded:

- full-page migration;
- product workflow redesign;
- API contract changes;
- backend state changes;
- model binding changes;
- agent behavior changes;
- removal of critical errors, warnings, destructive confirmations, or blocker reasons.

## 18. Non-Goals

- Do not redesign product workflows in this style-system pass.
- Do not change API contracts, backend state, model bindings, or agent behavior.
- Do not remove critical errors, warnings, destructive confirmations, or blocked-state reasons.
- Do not migrate every page in one commit.
- Do not sacrifice readability, performance, or accessibility for glass styling.
- Do not make dark theme the primary acceptance target for new visual direction.

## 19. Definition Of Done

The style system is considered landed when:

- `tokens.css` contains stable semantic surface/control/status tokens;
- `base.css` defines shared focus, disabled, and control baselines;
- `AppShell.module.css` remains the single owner of background and overlay behavior;
- `LauncherRoute` and `TeamsRoute` are accepted as visual references;
- new pages stop creating local card/button/shadow systems;
- review can judge screenshots quickly against: light, thin, precise, dense, and background-integrated.

## 20. Decision Table

| Question | Decision |
| --- | --- |
| Default theme target | Light-first |
| Product feel | Quiet operational workbench |
| Background strategy | AppShell-owned; custom background must remain visible |
| Surface | translucent, low blur, low-contrast border |
| Border | normal boundary uses 1px hairline |
| Shadow | faint for normal panels; stronger only for overlays |
| Buttons | quiet icon / quiet text / soft primary |
| Copy | non-critical explanations move to tooltip/focus hint |
| Layout | dense toolbar + predictable grid grouping |
| State | dot/chip/tint/icon/text combination |
| Motion | micro feedback; reduced motion supported |
| Accessibility | visible focus has priority over thin-line aesthetics |
| Migration | Wave 0 + Wave 1 establish references first |
