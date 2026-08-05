# ADR 0004 · Product UI Uses VUI + shadcn/Radix Only

## Status

Accepted (codified 2026-08-05 from root `AGENTS.md` §2 red line and development-standard §9.1).

## Context

The workbench historically accumulated parallel UI stacks (custom CSS, HeroUI, ad-hoc Radix/shadcn trees). Parallel systems caused:

- inconsistent density and focus behavior;
- route-level reimplementation of dialogs/menus;
- high migration cost and dual test surfaces;
- Agent confusion about which import path is legal.

HeroUI has been removed from product dependencies. A single product API (`V*`) with a single interactive renderer family is required for maintainability and contract tests.

## Decision

1. All **user-visible** product UI under `web/` must use the **VUI product API** (`web/src/components/vui` exports and `product/`).
2. Interactive control **implementation** lives only under `web/src/components/vui/renderers/shadcn` (Radix-backed patterns).
3. Routes and business components **MUST NOT**:
   - import `@heroui/react`;
   - import `renderers/shadcn/*` directly;
   - introduce a second design-system root (e.g. parallel `components/ui` product tree).
4. New `V*` / product surfaces require design notes under `web/src/components/vui/designs/` and INDEX registration.
5. Layout width/height memory uses `WORKBENCH_LAYOUT_IDS` + shared pane persistence only.
6. Machine gates include `vuiShadcnRouteContract.test.ts` and `vuiComponentDesignContract.test.ts`.

## Consequences

- Feature work that touches UI cannot ship a “temporary non-VUI path” as complete.
- Extending renderer is preferred over new primitives; new primitives need multi-callsite justification (see development-standard §9.1).
- Historical HeroUI / aesthetic plans live under `docs/archive/superpowers/` and are not authority.
- Product register principles (tone, bans) live in `docs/product/design-register.md`; component tables live in VUI designs.

## Related

- root `AGENTS.md` §2 frontend red line
- `docs/standards/development-standard.md` §9.1
- `web/src/components/vui/README.md`
- `docs/product/design-register.md`
