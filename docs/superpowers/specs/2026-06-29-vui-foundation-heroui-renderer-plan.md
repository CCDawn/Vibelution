# Vibelution UI Foundation + HeroUI Renderer Frontend Unification Plan

> Date: 2026-06-29
> Scope: project-level frontend architecture, style unification, and first-wave Agent Management migration
> Status: draft for user review
> Replaces: `2026-06-29-heroui-agent-management-refactor-plan.md`

## 1. Confirmed Direction

The frontend should be unified around one stable bottom layer before styling is pushed upward into pages.

The accepted architecture is:

```text
VUI-first, HeroUI-rendered
```

Meaning:

- Product pages and route files use Vibelution UI concepts.
- Vibelution UI Foundation is the only legal component and style decision layer.
- HeroUI is the first renderer implementation behind Vibelution UI, not the API used directly by pages.
- Tailwind CSS v4 is the styling engine for the renderer/theme/foundation layer.
- CSS Modules remain temporarily as a legacy layout bridge and are removed by migration wave.

This preserves the user's goal of using HeroUI for the first version while preventing long-term UI drift.

## 2. Product Design Contract

Vibelution remains a light, quiet, dense, background-aware AI workbench.

The unified bottom layer must enforce:

- light-first design;
- background-integrated surfaces;
- 1px hairline borders;
- compact pale controls;
- high information density;
- precise icon usage with accessible labels;
- explanatory text moved to hover, tooltip, detail, or empty state surfaces;
- no route-level decorative theme invention;
- no thick borders, heavy shadows, or marketing-style card layouts in core workbench pages.

HeroUI default appearance is not the product design source. It is an implementation input that must be adapted to Vibelution's visual language.

## 3. Current Codebase Context

Current frontend stack:

- Vite + React 19 + TypeScript.
- CSS Modules plus `web/src/design/tokens.css` and `web/src/design/base.css`.
- `lucide-react` is already the icon source.
- No current Tailwind, HeroUI, shadcn, or Radix dependencies in `web/package.json`.

Current styling pressure:

- 31 CSS Module files.
- Around 926 KB of CSS Module source.
- Largest high-drift files include:
  - `TeamsRoute.module.css`
  - `ChatCodingRoute.module.css`
  - `MemoryRoute.module.css`
  - `AgentsRoute.module.css`
  - `ConversationView.module.css`

The problem is not only component aesthetics. The deeper problem is that page-level CSS is currently allowed to invent local button, panel, chip, table, and layout grammar.

## 4. Architecture Overview

### 4.1 Layer Model

```text
Layer 1: Route / Page Layer
  Owns product flow, data binding, and page composition.
  Does not own component visual decisions.

Layer 2: Product Components
  Owns domain-specific structures such as AgentTable, AgentDetailPanel,
  MemoryGraphPanel, ChatStatusBar.
  Uses only VUI primitives and approved layout primitives.

Layer 3: Vibelution UI Foundation
  Owns the product UI API: VButton, VChip, VPanel, VField, VTooltip,
  VTabs, VTable, VModal, VMenu, VLayout.
  This is the single source of truth for component appearance and behavior.

Layer 4: Renderer Adapters
  First renderer: HeroUI.
  Uses Tailwind v4, HeroUI slots, HeroUI provider, React Aria behavior,
  and token bridges.

Layer 5: Design Tokens
  Owns semantic color, surface, density, radius, motion, and theme variables.
```

### 4.2 Single-source Rule

All UI decisions must enter through Layer 3.

Pages do not decide how a button, status chip, panel, table, tooltip, field, modal, or tab looks. Pages decide what the product surface means, then use VUI components to render it.

## 5. Hard Boundaries

### 5.1 Forbidden In Route Files

These are forbidden for new or migrated code under `web/src/routes/**`:

```ts
import { Button } from "@heroui/react";
import { Chip } from "@heroui/react";
import { Card } from "@heroui/react";
```

Also forbidden:

- arbitrary Tailwind visual styling in route business code;
- new route-local button/card/chip/table visual systems;
- new CSS Module classes that duplicate VUI primitive responsibilities;
- direct HeroUI slot override strings in route files;
- route-specific color systems.

### 5.2 Allowed In Route Files During Migration

Allowed:

- existing CSS Modules for untouched legacy surfaces;
- CSS Modules for complex page layout that has not migrated yet;
- product components such as `AgentManagementPage`, `AgentTable`, `AgentDetailPanel`;
- VUI primitives and approved layout primitives.

The route layer may keep legacy layout temporarily. It must not create new component visual grammar.

### 5.3 Allowed In VUI Foundation

Allowed under the approved VUI/foundation folders:

- HeroUI imports;
- HeroUI slot/classNames mapping;
- Tailwind utility classes;
- theme adapter logic;
- shared density, border, radius, focus, and state rules;
- thin wrappers that normalize Vibelution component APIs.

## 6. Proposed Directory Shape

Exact names may be refined during implementation, but ownership should follow this shape:

```text
web/src/design/
  tokens.css
  base.css
  tailwind.css
  heroui-theme.css

web/src/components/vui/
  primitives/
    VButton.tsx
    VChip.tsx
    VPanel.tsx
    VField.tsx
    VTooltip.tsx
    VIconButton.tsx
  layout/
    VStack.tsx
    VHStack.tsx
    VToolbar.tsx
    VGrid.tsx
  renderers/
    heroui/
      HeroProvider.tsx
      heroSlots.ts
      heroTheme.ts
      heroVariants.ts
  product/
    agent-management/
      AgentTable.tsx
      AgentDetailPanel.tsx
      AgentSummaryStrip.tsx
```

The important rule is import direction:

```text
routes -> product components -> VUI primitives -> HeroUI renderer -> tokens
```

Never:

```text
routes -> HeroUI
routes -> arbitrary Tailwind visual classes
routes -> new component CSS system
```

## 7. Renderer Decisions

### 7.1 HeroUI

HeroUI is the first renderer implementation.

Rationale:

- It can quickly standardize components.
- It is React 19-compatible in the current HeroUI v3 direction.
- It is Tailwind v4-oriented.
- It provides accessible interaction behavior through React Aria.

Constraint:

- HeroUI is not the page-level component API.
- HeroUI defaults must be adapted to Vibelution's light, quiet, dense visual language.
- If HeroUI cannot express a required Vibelution behavior cleanly, the VUI API remains stable and the renderer implementation can change later.

### 7.2 Tailwind CSS v4

Tailwind v4 is the styling engine for the VUI foundation and renderer layer.

Allowed:

- token bridge utilities;
- layout primitives;
- HeroUI slot classes;
- shared density and state classes;
- approved component variants.

Not allowed:

- page-level arbitrary visual decisions;
- one-off route-specific color or shadow utilities;
- Tailwind as a replacement for product semantics.

### 7.3 CSS Modules

CSS Modules are a migration bridge.

Allowed:

- untouched legacy surfaces;
- complex page layout during transition;
- scoped compatibility wrappers while a page is half-migrated.

Not allowed:

- new button/card/chip/table styling;
- new visual systems;
- permanent fixes that should belong to VUI primitives.

## 8. VUI Primitive Rules

### 8.1 Thin Wrapper Rule

VUI primitives must be thin wrappers.

They may own:

- normalized props;
- variant mapping;
- accessibility defaults;
- density defaults;
- token/slot class wiring;
- consistent icon and tooltip behavior.

They must not own:

- Agent business rules;
- Memory-specific decisions;
- Chat-specific state logic;
- route-specific copy;
- complex conditional rendering that belongs to product components.

### 8.2 Initial Primitive Set

Wave 0 should establish only the primitives needed to prevent drift:

- `VButton`
- `VIconButton`
- `VChip`
- `VPanel`
- `VField`
- `VTooltip`
- `VToolbar`
- `VHStack` / `VStack`

Defer until needed:

- `VTable`
- `VTabs`
- `VModal`
- `VMenu`
- `VSelect`
- `VFormGrid`

This prevents building a wrapper framework before real migration pressure exists.

## 9. Product Components

Product components sit between routes and primitives.

For Agent Management:

```text
AgentsRoute.tsx
  -> AgentManagementPage
  -> AgentSummaryStrip
  -> AgentFilterRail
  -> AgentTable or AgentDenseList
  -> AgentDetailPanel
  -> AgentDangerZone
  -> VUI primitives
```

Responsibilities:

- Product components may know Agent domain concepts.
- Product components may decide which actions and fields appear.
- Product components must not decide base visual style.
- Product components must not import HeroUI directly.

## 10. First-wave Agent Management Plan

Agent Management remains the first migration page.

### 10.1 Wave 0: Foundation

Implement before route migration:

- install Tailwind v4;
- install HeroUI;
- add `HeroUIProvider`;
- add `tailwind.css`;
- add `heroui-theme.css`;
- create VUI primitive folder;
- create first primitives;
- add static import-boundary tests;
- add basic primitive render tests.

### 10.2 Wave 1A: Agent Management Header And Summary

Migrate:

- refresh/return actions;
- summary cards;
- count chips;
- health/runtime chips;
- compact toolbar layout.

Keep:

- existing data queries;
- existing navigation behavior;
- existing cache behavior.

### 10.3 Wave 1B: Agent List And Filters

Migrate:

- search input;
- filter sections;
- group buttons;
- selected/current/running/unread states;
- agent model/status/role chips.

Decision point:

- Use HeroUI `Table` only if it preserves current density and interaction.
- Otherwise build `AgentDenseList` using VUI panels, chips, and buttons.

### 10.4 Wave 1C: Agent Detail Panel

Migrate:

- detail tabs;
- form fields;
- select/switch/checkbox surfaces;
- action toolbars;
- reset/archive/purge sections;
- tooltip/detail placement for explanatory copy.

Keep:

- all Agent API contracts;
- all safety gates for archive/purge/reset;
- all existing save/reset behavior.

### 10.5 Wave 1D: CSS Cleanup

Remove only proven-dead CSS.

Do not delete CSS just because a section was partially migrated. Delete when:

- source search confirms the class is unused;
- route tests no longer assert it;
- screenshot validates the migrated replacement.

## 11. Testing Contract

Every wave must pass:

- `npm --prefix web run build`;
- focused Vitest tests for changed files;
- route layout/static tests if touched;
- browser screenshot of the changed page.

Add architecture tests:

- routes do not import `@heroui/react`;
- migrated routes import VUI/product components;
- HeroUI imports appear only in approved VUI renderer folders;
- Tailwind visual utility use in route files is forbidden or explicitly whitelisted;
- old button/card/chip CSS classes are not added to migrated sections.

Agent Management screenshot checks:

- default page;
- selected Agent detail view;
- running/current/unread state if available;
- danger/reset section if reachable;
- narrow viewport only when the changed surface is responsive-sensitive.

## 12. Rollback Plan

Rollback must be practical at each wave.

Rules:

- keep foundation and page migration separable if the dependency diff is large;
- do not delete old CSS in the same patch that first introduces replacement components unless the deletion is clearly mechanical;
- if Agent Management migration regresses density or layout, revert the page migration while keeping foundation work if it is stable;
- do not change API contracts during visual migration;
- do not mix visual migration with Agent behavior fixes.

## 13. Long-term Migration Order

After Agent Management:

1. Teams
2. Memory
3. Chat status and conversation chrome
4. Conversation content surfaces
5. Config / Launcher / Git / Logs
6. Remaining utility routes

Reasoning:

- Teams and Memory are high-density management surfaces and benefit most from VUI.
- Chat content surfaces are riskier because markdown, streaming, tool traces, and scroll behavior are tightly coupled.
- Utility routes can follow once primitives stabilize.

## 14. Risks And Mitigations

### Risk 1: Wrapper framework growth

Mitigation:

- keep primitives thin;
- move domain decisions into product components;
- add tests against API surface bloat where useful;
- do not create primitives before a page needs them.

### Risk 2: HeroUI visual defaults overpower Vibelution

Mitigation:

- centralize HeroUI theme overrides;
- use Vibelution tokens as the product source;
- validate screenshots against the style system document;
- avoid HeroUI page templates in core routes.

### Risk 3: Tailwind becomes a second visual system

Mitigation:

- allow Tailwind mainly in VUI/layout/theme layers;
- forbid route-level arbitrary visual utilities in migrated code;
- provide layout primitives for common spacing and grids.

### Risk 4: CSS Modules never disappear

Mitigation:

- mark CSS Modules as legacy bridge;
- remove dead CSS per wave;
- add architecture tests for migrated surfaces;
- keep a route-by-route migration checklist.

### Risk 5: Agent-generated UI drifts

Mitigation:

- document the VUI import contract;
- add static tests;
- later add lint rules;
- promote the rule into project standards after implementation proves it.

## 15. Implementation Readiness Checklist

Before implementation:

- create an isolated worktree;
- create/claim a frontend implementation scope;
- verify no active conflicting claim touches Agent Management or VUI foundation;
- inspect current Agent Management page in browser;
- run focused baseline tests for `AgentsRoute`;
- decide whether foundation and Agent header migration are one commit or separate commits;
- confirm dependency install command and package-lock change.

Initial write scopes:

- `web/package.json`
- `web/package-lock.json`
- `web/vite.config.ts`
- `web/src/design/**`
- `web/src/components/vui/**`
- `web/src/routes/AgentsRoute.tsx`
- `web/src/routes/AgentsRoute.module.css`
- `web/src/routes/AgentsRoute.layout.test.ts`
- related VUI tests

## 16. Open Decisions For User Review

1. Should the first implementation patch be foundation-only, or foundation plus Agent Management header/summary?
   - Recommended: foundation-only if dependency diff is large; otherwise foundation plus header/summary is acceptable.

2. Should Agent Management list use HeroUI `Table` or a VUI dense list?
   - Recommended: inspect in browser first. Use dense list if HeroUI `Table` reduces information density.

3. Should route-level Tailwind be fully forbidden immediately?
   - Recommended: forbid visual utilities immediately for migrated code, allow structural layout only through approved helpers during transition.

4. Should these rules be promoted into `AGENTS.md` or `DEVELOPMENT_STANDARD.md` now?
   - Recommended: not yet. First implement one wave, then promote the proven rules.

## 17. Source Notes

- Existing style spec: `docs/superpowers/specs/2026-06-26-frontend-style-system-design.md`.
- Current reviewed plan: this document replaces the earlier HeroUI-first wording with a VUI-first architecture.
- HeroUI remains the first renderer.
- Tailwind v4 remains the styling engine for the foundation layer.
- Vibelution UI Foundation is the single page-facing UI layer.
