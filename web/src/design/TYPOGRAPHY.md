# Vibelution workbench typography

## Goals

- One ladder for size / line-height / weight / tracking (desktop workbench density).
- Semantic roles for product UI (caption → display), not one-off `rem` literals.
- Compatible with Tailwind v4: font size via `[font-size:var(--…)]` only.

## References (mature systems)

| System | What we take |
|--------|----------------|
| **Material Type Scale** | Role names (label / body / title), paired size + line-height |
| **Apple HIG** | Caption / body / title hierarchy; system UI fonts on Windows |
| **Radix Themes** | Compact numeric ladder, regular/medium/bold weights |
| **shadcn / Tailwind** | Utility-first recipes; no fluid `clamp()` hero type in workbench |

## Tokens

Source of truth: `tokens.css`.

### Primitive sizes

`2xs` 12 · `xs` 14 · `sm` 15 · `md` 16 · `chat` 17 · `lg` 18 · `title` 19 · `xl` 22 (px @ 16 root)

### Roles (`--vui-type-*-size` / `line`)

| Role | Use |
|------|-----|
| caption | timestamps, dense meta |
| label | chips, uppercase eyebrows |
| control | buttons, menus, form chrome |
| body | panel prose |
| chat | conversation transcript |
| emphasis | empty states, short callouts |
| title | section / route titles |
| display | rare page titles only |

### Recipes

Import from `typographyRecipes.ts`:

```ts
import { vuiTypeBody, vuiTypeChat, vuiTypeTitle } from "../design/typographyRecipes";
```

## Rules

1. Prefer role recipes or `--vui-font-*` / `--vui-type-*` tokens.
2. Never `text-[var(--vui-font-sm)]` — Tailwind treats that as **color**.
3. Do not introduce viewport-scaled display type inside workbench routes.
4. Do not use display fonts in tables, logs, or dense controls (`DESIGN.md`).

## Contract tests

- `typographyTokenContract.test.ts` — forbids font-as-color trap
- `typographyRecipes.test.ts` — recipes stay token-backed
- `vuiThemeFoundation.test.tsx` — core size tokens present
