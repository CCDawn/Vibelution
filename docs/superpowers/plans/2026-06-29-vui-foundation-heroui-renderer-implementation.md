# VUI Foundation HeroUI Renderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single Vibelution UI foundation layer, render it through HeroUI and Tailwind CSS v4, and migrate the first Agent Management surface without changing Agent business behavior.

**Architecture:** Pages use product components, product components use VUI primitives, VUI primitives map to HeroUI or native elements, and tokens remain the visual source of truth. HeroUI is the first renderer implementation, not a page-facing API. CSS Modules remain only as a temporary route layout bridge during migration.

**Tech Stack:** React 19, TypeScript, Vite 8, Vitest 3, Tailwind CSS 4.3.1, @tailwindcss/vite 4.3.1, @heroui/react 3.2.1, lucide-react.

## Global Constraints

- Implementation worktree: `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management`.
- Implementation branch: `codex/vui-foundation-heroui-agent-management`.
- Root checkout `C:\Users\17533\Desktop\Vibelution` must remain on `main`.
- Use a project-memory guard claim before editing implementation files.
- Page and route files must not import `@heroui/react`.
- Tailwind visual utilities are allowed in `web/src/design/**` and `web/src/components/vui/**`; route files should not gain Tailwind visual class strings.
- Product route behavior, API calls, query keys, optimistic archive/purge behavior, Agent lifecycle behavior, and Agent cache behavior must remain unchanged.
- Visible UI must remain light-first, background-integrated, high-density, and built with 1px hairline borders.
- Controls must be compact, pale, and sized to content unless the whole row is intentionally the action target.
- Inline explanatory copy must move to `title`, tooltip, detail disclosure, or existing critical warning surfaces; destructive or blocking warnings stay directly visible.
- Every implementation task ends with focused tests or a clearly scoped validation command.
- Final visual validation must include browser screenshots for `/agents` at desktop width and one narrow width.

---

## File Structure

Create or modify these files in the implementation branch.

**Create**

- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\design\tailwind.css`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\design\heroui-theme.css`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\index.ts`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\primitives\VButton.tsx`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\primitives\VChip.tsx`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\primitives\VIconButton.tsx`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\primitives\VPanel.tsx`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\primitives\VTooltip.tsx`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\layout\VHStack.tsx`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\layout\VStack.tsx`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\layout\VToolbar.tsx`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\renderers\heroui\HeroProvider.tsx`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\renderers\heroui\heroVariants.ts`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\renderers\heroui\heroSlots.ts`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\vuiImportBoundary.test.ts`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\vuiPrimitives.test.tsx`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\product\agent-management\AgentPageHeader.tsx`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\product\agent-management\AgentSummaryStrip.tsx`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\product\agent-management\index.ts`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\components\vui\product\agent-management\AgentManagementProduct.test.tsx`

**Modify**

- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\package.json`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\package-lock.json`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\vite.config.ts`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\main.tsx`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\routes\AgentsRoute.tsx`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\routes\AgentsRoute.module.css`
- `C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management\web\src\routes\AgentsRoute.layout.test.ts`

## Task 1: Create The Implementation Worktree And Guard Claim

**Files:**
- No source files are changed in this task.

**Interfaces:**
- Consumes: local `main`, project-memory guard.
- Produces: an isolated implementation branch and active claim for later tasks.

- [ ] **Step 1: Create worktree from local main**

Run:

```powershell
cd C:\Users\17533\Desktop\Vibelution
git worktree add C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management -b codex/vui-foundation-heroui-agent-management main
```

Expected: command succeeds and prints the new branch checkout.

- [ ] **Step 2: Verify root and worktree branches**

Run:

```powershell
git status --short --branch
git -C C:\Users\17533\Desktop\Vibelution-worktrees\vui-foundation-heroui-agent-management status --short --branch
```

Expected:

```text
## main...origin/main [ahead ...]
## codex/vui-foundation-heroui-agent-management
```

- [ ] **Step 3: Check scope conflicts**

Run:

```powershell
& "C:\Users\17533\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" check --lane web-workbench-surface --scope "web/package.json" --scope "web/package-lock.json" --scope "web/vite.config.ts" --scope "web/src/design/**" --scope "web/src/components/vui/**" --scope "web/src/main.tsx" --scope "web/src/routes/AgentsRoute.tsx" --scope "web/src/routes/AgentsRoute.module.css" --scope "web/src/routes/AgentsRoute.layout.test.ts" --json
```

Expected: JSON contains `"ok": true` and an empty `conflicts` array.

- [ ] **Step 4: Create implementation claim**

Run:

```powershell
& "C:\Users\17533\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" claim --lane web-workbench-surface --scope "web/package.json" --scope "web/package-lock.json" --scope "web/vite.config.ts" --scope "web/src/design/**" --scope "web/src/components/vui/**" --scope "web/src/main.tsx" --scope "web/src/routes/AgentsRoute.tsx" --scope "web/src/routes/AgentsRoute.module.css" --scope "web/src/routes/AgentsRoute.layout.test.ts" --agent "codex-vui-foundation-heroui-agent-management" --task "Implement VUI foundation and first Agent Management HeroUI renderer migration" --status active --ttl-minutes 360 --note "Implementation branch codex/vui-foundation-heroui-agent-management" --json
```

Expected: JSON contains `"ok": true` and a claim id.

- [ ] **Step 5: Commit**

No commit is made in this task.

## Task 2: Bootstrap Tailwind CSS v4 And HeroUI Provider

**Files:**
- Modify: `web/package.json`
- Modify: `web/package-lock.json`
- Modify: `web/vite.config.ts`
- Modify: `web/src/main.tsx`
- Create: `web/src/design/tailwind.css`
- Create: `web/src/design/heroui-theme.css`
- Create: `web/src/components/vui/renderers/heroui/HeroProvider.tsx`
- Create: `web/src/components/vui/renderers/heroui/heroVariants.ts`
- Test: `web/src/components/vui/vuiPrimitives.test.tsx`

**Interfaces:**
- Consumes: current React root in `web/src/main.tsx`.
- Produces: `VibelutionHeroProvider`, global Tailwind import, and HeroUI token bridge.

- [ ] **Step 1: Install dependencies**

Run:

```powershell
npm --prefix web install @heroui/react@3.2.1 tailwindcss@4.3.1 @tailwindcss/vite@4.3.1
```

Expected: `web/package.json` and `web/package-lock.json` include the three dependencies.

- [ ] **Step 2: Write the failing provider contract test**

Create `web/src/components/vui/vuiPrimitives.test.tsx` with this first test:

```tsx
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VibelutionHeroProvider } from "./renderers/heroui/HeroProvider";

describe("VUI foundation primitives", () => {
  it("wraps children in the Vibelution HeroUI provider boundary", () => {
    const markup = renderToStaticMarkup(
      <VibelutionHeroProvider>
        <main data-test-id="inside-vui">content</main>
      </VibelutionHeroProvider>,
    );

    expect(markup).toContain('data-vui-provider="heroui"');
    expect(markup).toContain('data-test-id="inside-vui"');
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run:

```powershell
npm --prefix web run test -- vuiPrimitives.test.tsx
```

Expected: FAIL because `./renderers/heroui/HeroProvider` does not exist.

- [ ] **Step 4: Add Tailwind plugin to Vite**

Modify `web/vite.config.ts`.

Change imports to:

```ts
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
```

Change the plugin list to:

```ts
plugins: [tailwindcss(), react()],
```

- [ ] **Step 5: Create Tailwind entry CSS**

Create `web/src/design/tailwind.css`:

```css
@import "tailwindcss";

@source "../app/**/*.{ts,tsx}";
@source "../components/vui/**/*.{ts,tsx}";
@source "../routes/**/*.{ts,tsx}";

@theme {
  --font-sans: var(--font-body);
  --color-vui-bg-canvas: var(--bg-canvas);
  --color-vui-surface-page: var(--surface-page);
  --color-vui-surface-panel: var(--surface-panel);
  --color-vui-surface-card: var(--surface-card);
  --color-vui-fg-primary: var(--fg-primary);
  --color-vui-fg-secondary: var(--fg-secondary);
  --color-vui-fg-tertiary: var(--fg-tertiary);
  --color-vui-border-hairline: var(--border-hairline);
  --color-vui-border-soft: var(--border-soft);
  --color-vui-accent-cool: var(--accent-cool);
  --color-vui-accent-warm: var(--accent-warm);
  --radius-vui-control: var(--radius-control);
  --radius-vui-panel: var(--radius-panel);
}
```

- [ ] **Step 6: Create HeroUI theme bridge CSS**

Create `web/src/design/heroui-theme.css`:

```css
:root {
  --vui-control-height-sm: 26px;
  --vui-control-height-md: 30px;
  --vui-focus-ring: 0 0 0 2px color-mix(in srgb, var(--accent-cool) 22%, transparent);
}

[data-vui-provider="heroui"] {
  color: var(--fg-primary);
  font-family: var(--font-body);
}

[data-vui-provider="heroui"] [data-focus-visible="true"] {
  outline: 1px solid color-mix(in srgb, var(--accent-cool) 58%, transparent);
  outline-offset: 1px;
  box-shadow: var(--vui-focus-ring);
}
```

- [ ] **Step 7: Create HeroUI variant helpers**

Create `web/src/components/vui/renderers/heroui/heroVariants.ts`:

```ts
export type VuiTone = "neutral" | "accent" | "success" | "warning" | "danger";
export type VuiDensity = "compact" | "normal";
export type VuiButtonVariant = "primary" | "secondary" | "ghost" | "danger";

export function vuiControlHeight(density: VuiDensity | undefined): "sm" | "md" {
  return density === "normal" ? "md" : "sm";
}

export function vuiToneClass(tone: VuiTone | undefined): string {
  return `vui-tone-${tone ?? "neutral"}`;
}
```

Create `web/src/components/vui/renderers/heroui/heroSlots.ts`:

```ts
export const vuiButtonBaseClass =
  "border border-vui-border-soft bg-vui-surface-card text-vui-fg-secondary shadow-none";

export const vuiButtonPrimaryClass =
  "border-vui-accent-cool bg-vui-surface-panel text-vui-fg-primary";

export const vuiButtonDangerClass =
  "border-red-300/70 bg-red-50/70 text-red-700";

export const vuiChipBaseClass =
  "border border-vui-border-soft bg-vui-surface-panel text-vui-fg-secondary";
```

- [ ] **Step 8: Create HeroUI provider wrapper**

Create `web/src/components/vui/renderers/heroui/HeroProvider.tsx`:

```tsx
import { HeroUIProvider } from "@heroui/react";
import { type ReactNode } from "react";

type VibelutionHeroProviderProps = {
  children: ReactNode;
};

export function VibelutionHeroProvider({ children }: VibelutionHeroProviderProps) {
  return (
    <HeroUIProvider>
      <div data-vui-provider="heroui">{children}</div>
    </HeroUIProvider>
  );
}
```

- [ ] **Step 9: Wire provider into the React root**

Modify `web/src/main.tsx`.

Imports become:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";
import { redirectToCanonicalWorkbenchHost } from "./app/canonicalWorkbenchHost";
import { VibelutionHeroProvider } from "./components/vui/renderers/heroui/HeroProvider";
import "./design/tokens.css";
import "./design/base.css";
import "./design/tailwind.css";
import "./design/heroui-theme.css";
```

Render block becomes:

```tsx
if (!redirectToCanonicalWorkbenchHost()) {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <VibelutionHeroProvider>
        <App />
      </VibelutionHeroProvider>
    </React.StrictMode>,
  );
}
```

- [ ] **Step 10: Run test to verify it passes**

Run:

```powershell
npm --prefix web run test -- vuiPrimitives.test.tsx
```

Expected: PASS.

- [ ] **Step 11: Run build**

Run:

```powershell
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 12: Commit**

Run:

```powershell
git status --short
git add web/package.json web/package-lock.json web/vite.config.ts web/src/main.tsx web/src/design/tailwind.css web/src/design/heroui-theme.css web/src/components/vui/renderers/heroui/HeroProvider.tsx web/src/components/vui/renderers/heroui/heroVariants.ts web/src/components/vui/renderers/heroui/heroSlots.ts web/src/components/vui/vuiPrimitives.test.tsx
git commit -m "feat(web): add VUI HeroUI renderer foundation"
```

Expected: commit succeeds.

## Task 3: Add The Minimal VUI Primitive Layer

**Files:**
- Create: `web/src/components/vui/index.ts`
- Create: `web/src/components/vui/primitives/VButton.tsx`
- Create: `web/src/components/vui/primitives/VIconButton.tsx`
- Create: `web/src/components/vui/primitives/VChip.tsx`
- Create: `web/src/components/vui/primitives/VPanel.tsx`
- Create: `web/src/components/vui/primitives/VTooltip.tsx`
- Create: `web/src/components/vui/layout/VHStack.tsx`
- Create: `web/src/components/vui/layout/VStack.tsx`
- Create: `web/src/components/vui/layout/VToolbar.tsx`
- Modify: `web/src/components/vui/vuiPrimitives.test.tsx`

**Interfaces:**
- Consumes: `VuiTone`, `VuiDensity`, and HeroUI renderer helpers from Task 2.
- Produces: page-facing VUI API.

- [ ] **Step 1: Extend the primitive test**

Append these tests to `web/src/components/vui/vuiPrimitives.test.tsx`:

```tsx
import { Search } from "lucide-react";
import { VButton, VChip, VIconButton, VPanel, VToolbar } from "./index";

it("renders compact VUI controls with stable data attributes", () => {
  const markup = renderToStaticMarkup(
    <VibelutionHeroProvider>
      <VToolbar ariaLabel="Agent actions">
        <VButton variant="secondary" icon={<Search size={14} />}>Search</VButton>
        <VIconButton label="Refresh" icon={<Search size={14} />} />
        <VChip tone="accent">mimo-v2.5</VChip>
      </VToolbar>
    </VibelutionHeroProvider>,
  );

  expect(markup).toContain('data-vui="button"');
  expect(markup).toContain('data-vui="icon-button"');
  expect(markup).toContain('data-vui="chip"');
  expect(markup).toContain('aria-label="Refresh"');
  expect(markup).toContain("mimo-v2.5");
});

it("renders panels as background-integrated native surfaces", () => {
  const markup = renderToStaticMarkup(
    <VPanel ariaLabel="Agent summary">
      <strong>11</strong>
    </VPanel>,
  );

  expect(markup).toContain('data-vui="panel"');
  expect(markup).toContain('aria-label="Agent summary"');
  expect(markup).toContain("<strong>11</strong>");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
npm --prefix web run test -- vuiPrimitives.test.tsx
```

Expected: FAIL because VUI primitives do not exist.

- [ ] **Step 3: Implement VButton**

Create `web/src/components/vui/primitives/VButton.tsx`:

```tsx
import { Button, type ButtonProps } from "@heroui/react";
import { type ReactNode } from "react";

import { vuiButtonBaseClass, vuiButtonDangerClass, vuiButtonPrimaryClass } from "../renderers/heroui/heroSlots";
import { type VuiButtonVariant, type VuiDensity, vuiControlHeight } from "../renderers/heroui/heroVariants";

export type VButtonProps = Omit<ButtonProps, "variant" | "color" | "size" | "startContent" | "endContent"> & {
  variant?: VuiButtonVariant;
  density?: VuiDensity;
  icon?: ReactNode;
  trailingIcon?: ReactNode;
};

function variantClass(variant: VuiButtonVariant | undefined): string {
  if (variant === "primary") {
    return `${vuiButtonBaseClass} ${vuiButtonPrimaryClass}`;
  }
  if (variant === "danger") {
    return `${vuiButtonBaseClass} ${vuiButtonDangerClass}`;
  }
  if (variant === "ghost") {
    return "border border-transparent bg-transparent text-vui-fg-secondary shadow-none";
  }
  return vuiButtonBaseClass;
}

export function VButton({
  variant = "secondary",
  density = "compact",
  icon,
  trailingIcon,
  className,
  children,
  ...props
}: VButtonProps) {
  return (
    <Button
      {...props}
      data-vui="button"
      size={vuiControlHeight(density)}
      radius="sm"
      variant="bordered"
      startContent={icon}
      endContent={trailingIcon}
      className={[variantClass(variant), "min-w-0 px-2 font-semibold", className].filter(Boolean).join(" ")}
    >
      {children}
    </Button>
  );
}
```

- [ ] **Step 4: Implement VIconButton**

Create `web/src/components/vui/primitives/VIconButton.tsx`:

```tsx
import { type ReactNode } from "react";

import { VButton, type VButtonProps } from "./VButton";

export type VIconButtonProps = Omit<VButtonProps, "children" | "icon" | "isIconOnly" | "aria-label"> & {
  label: string;
  icon: ReactNode;
};

export function VIconButton({ label, icon, title, ...props }: VIconButtonProps) {
  return (
    <VButton
      {...props}
      data-vui="icon-button"
      isIconOnly
      aria-label={label}
      title={title ?? label}
      className={["h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] min-w-0 px-0", props.className]
        .filter(Boolean)
        .join(" ")}
    >
      {icon}
    </VButton>
  );
}
```

- [ ] **Step 5: Implement VChip**

Create `web/src/components/vui/primitives/VChip.tsx`:

```tsx
import { Chip, type ChipProps } from "@heroui/react";

import { vuiChipBaseClass } from "../renderers/heroui/heroSlots";
import { type VuiTone, vuiToneClass } from "../renderers/heroui/heroVariants";

export type VChipProps = Omit<ChipProps, "variant" | "color" | "size"> & {
  tone?: VuiTone;
};

export function VChip({ tone = "neutral", className, children, ...props }: VChipProps) {
  return (
    <Chip
      {...props}
      data-vui="chip"
      size="sm"
      radius="sm"
      variant="bordered"
      className={[vuiChipBaseClass, vuiToneClass(tone), "h-[22px] max-w-full px-1.5 text-[0.68rem] font-semibold", className]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </Chip>
  );
}
```

- [ ] **Step 6: Implement VPanel**

Create `web/src/components/vui/primitives/VPanel.tsx`:

```tsx
import { type ComponentPropsWithoutRef, type ReactNode } from "react";

export type VPanelProps = ComponentPropsWithoutRef<"section"> & {
  ariaLabel?: string;
  children: ReactNode;
};

export function VPanel({ ariaLabel, className, children, ...props }: VPanelProps) {
  return (
    <section
      {...props}
      data-vui="panel"
      aria-label={ariaLabel}
      className={[
        "min-w-0 rounded-[var(--radius-panel)] border border-vui-border-hairline bg-vui-surface-panel/82",
        "shadow-none backdrop-blur-[1px]",
        className,
      ].filter(Boolean).join(" ")}
    >
      {children}
    </section>
  );
}
```

- [ ] **Step 7: Implement VTooltip**

Create `web/src/components/vui/primitives/VTooltip.tsx`:

```tsx
import { Tooltip, type TooltipProps } from "@heroui/react";

export type VTooltipProps = TooltipProps;

export function VTooltip({ delay = 250, closeDelay = 80, className, ...props }: VTooltipProps) {
  return (
    <Tooltip
      {...props}
      delay={delay}
      closeDelay={closeDelay}
      className={["max-w-72 border border-vui-border-soft bg-vui-surface-card px-2 py-1 text-xs text-vui-fg-secondary", className]
        .filter(Boolean)
        .join(" ")}
    />
  );
}
```

- [ ] **Step 8: Implement layout primitives**

Create `web/src/components/vui/layout/VHStack.tsx`:

```tsx
import { type ComponentPropsWithoutRef } from "react";

export type VHStackProps = ComponentPropsWithoutRef<"div">;

export function VHStack({ className, ...props }: VHStackProps) {
  return <div {...props} data-vui="hstack" className={["flex min-w-0 items-center gap-1.5", className].filter(Boolean).join(" ")} />;
}
```

Create `web/src/components/vui/layout/VStack.tsx`:

```tsx
import { type ComponentPropsWithoutRef } from "react";

export type VStackProps = ComponentPropsWithoutRef<"div">;

export function VStack({ className, ...props }: VStackProps) {
  return <div {...props} data-vui="vstack" className={["grid min-w-0 gap-1.5", className].filter(Boolean).join(" ")} />;
}
```

Create `web/src/components/vui/layout/VToolbar.tsx`:

```tsx
import { type ComponentPropsWithoutRef } from "react";

export type VToolbarProps = ComponentPropsWithoutRef<"div"> & {
  ariaLabel: string;
};

export function VToolbar({ ariaLabel, className, ...props }: VToolbarProps) {
  return (
    <div
      {...props}
      data-vui="toolbar"
      role="toolbar"
      aria-label={ariaLabel}
      className={["flex min-w-0 flex-wrap items-center gap-1.5", className].filter(Boolean).join(" ")}
    />
  );
}
```

- [ ] **Step 9: Add VUI exports**

Create `web/src/components/vui/index.ts`:

```ts
export { VButton, type VButtonProps } from "./primitives/VButton";
export { VChip, type VChipProps } from "./primitives/VChip";
export { VIconButton, type VIconButtonProps } from "./primitives/VIconButton";
export { VPanel, type VPanelProps } from "./primitives/VPanel";
export { VTooltip, type VTooltipProps } from "./primitives/VTooltip";
export { VHStack, type VHStackProps } from "./layout/VHStack";
export { VStack, type VStackProps } from "./layout/VStack";
export { VToolbar, type VToolbarProps } from "./layout/VToolbar";
```

- [ ] **Step 10: Run primitive tests**

Run:

```powershell
npm --prefix web run test -- vuiPrimitives.test.tsx
```

Expected: PASS.

- [ ] **Step 11: Run build**

Run:

```powershell
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 12: Commit**

Run:

```powershell
git status --short
git add web/src/components/vui/index.ts web/src/components/vui/primitives/VButton.tsx web/src/components/vui/primitives/VChip.tsx web/src/components/vui/primitives/VIconButton.tsx web/src/components/vui/primitives/VPanel.tsx web/src/components/vui/primitives/VTooltip.tsx web/src/components/vui/layout/VHStack.tsx web/src/components/vui/layout/VStack.tsx web/src/components/vui/layout/VToolbar.tsx web/src/components/vui/vuiPrimitives.test.tsx
git commit -m "feat(web): add minimal VUI primitives"
```

Expected: commit succeeds.

## Task 4: Add Architecture Boundary Tests

**Files:**
- Create: `web/src/components/vui/vuiImportBoundary.test.ts`

**Interfaces:**
- Consumes: route files and VUI renderer folder.
- Produces: regression lock that prevents pages from bypassing VUI.

- [ ] **Step 1: Write the failing boundary test**

Create `web/src/components/vui/vuiImportBoundary.test.ts`:

```ts
import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readdirSync, readFileSync, statSync } from "node:fs";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { join, relative } from "node:path";

const sourceRoot = new URL("../../", import.meta.url);

function walkFiles(dir: string): string[] {
  const entries = readdirSync(dir);
  return entries.flatMap((entry) => {
    const fullPath = join(dir, entry);
    const stats = statSync(fullPath);
    if (stats.isDirectory()) {
      return walkFiles(fullPath);
    }
    return /\.(ts|tsx|css)$/.test(entry) ? [fullPath] : [];
  });
}

function readText(file: string): string {
  return readFileSync(file, "utf-8");
}

describe("VUI architecture boundary", () => {
  it("keeps HeroUI imports inside the VUI renderer layer", () => {
    const files = walkFiles(sourceRoot.pathname);
    const offenders = files
      .filter((file) => readText(file).includes("@heroui/react"))
      .map((file) => relative(sourceRoot.pathname, file).replace(/\\/g, "/"))
      .filter((file) => !file.startsWith("components/vui/"));

    expect(offenders).toEqual([]);
  });

  it("keeps route files from adding Tailwind visual utility strings", () => {
    const routeFiles = walkFiles(join(sourceRoot.pathname, "routes"));
    const utilityPattern = /className=["'`][^"'`]*(?:bg-|text-|border-|rounded-|shadow-|px-|py-|gap-|grid|flex)[^"'`]*["'`]/;
    const offenders = routeFiles
      .filter((file) => utilityPattern.test(readText(file)))
      .map((file) => relative(sourceRoot.pathname, file).replace(/\\/g, "/"));

    expect(offenders).toEqual([]);
  });
});
```

- [ ] **Step 2: Run boundary test**

Run:

```powershell
npm --prefix web run test -- vuiImportBoundary.test.ts
```

Expected: PASS. If it fails on current route-local CSS Module usage, adjust only the regex to target Tailwind utility strings inside literal `className` attributes and do not weaken the HeroUI import assertion.

- [ ] **Step 3: Run build**

Run:

```powershell
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 4: Commit**

Run:

```powershell
git status --short
git add web/src/components/vui/vuiImportBoundary.test.ts
git commit -m "test(web): lock VUI import boundaries"
```

Expected: commit succeeds.

## Task 5: Create Agent Management Product Components

**Files:**
- Create: `web/src/components/vui/product/agent-management/AgentPageHeader.tsx`
- Create: `web/src/components/vui/product/agent-management/AgentSummaryStrip.tsx`
- Create: `web/src/components/vui/product/agent-management/index.ts`
- Create: `web/src/components/vui/product/agent-management/AgentManagementProduct.test.tsx`

**Interfaces:**
- Consumes: VUI primitives from Task 3.
- Produces: route-facing Agent Management header and summary components.

- [ ] **Step 1: Write product component tests**

Create `web/src/components/vui/product/agent-management/AgentManagementProduct.test.tsx`:

```tsx
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { RefreshCw } from "lucide-react";

import { VibelutionHeroProvider } from "../../renderers/heroui/HeroProvider";
import { AgentPageHeader, AgentSummaryStrip, type AgentSummaryMetric } from "./index";

describe("Agent Management VUI product components", () => {
  it("renders a compact page header without inline explanatory prose", () => {
    const markup = renderToStaticMarkup(
      <VibelutionHeroProvider>
        <AgentPageHeader
          eyebrow="Agent Center"
          title="Agent Management"
          actions={[
            {
              id: "refresh",
              label: "Refresh",
              icon: <RefreshCw size={14} />,
              onPress: () => undefined,
            },
          ]}
        />
      </VibelutionHeroProvider>,
    );

    expect(markup).toContain("Agent Management");
    expect(markup).toContain('role="toolbar"');
    expect(markup).toContain('aria-label="Refresh"');
    expect(markup).not.toContain("<p>");
  });

  it("renders summary metrics as one dense strip", () => {
    const metrics: AgentSummaryMetric[] = [
      { id: "agents", label: "Agents", value: "11", detail: "Total agents" },
      { id: "issues", label: "Issues", value: "0", tone: "success", detail: "No blocking issues" },
    ];

    const markup = renderToStaticMarkup(
      <AgentSummaryStrip ariaLabel="Agent summary" metrics={metrics} />,
    );

    expect(markup).toContain('data-vui-product="agent-summary-strip"');
    expect(markup).toContain("Agents");
    expect(markup).toContain("11");
    expect(markup).toContain('title="Total agents"');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
npm --prefix web run test -- AgentManagementProduct.test.tsx
```

Expected: FAIL because product components do not exist.

- [ ] **Step 3: Implement AgentPageHeader**

Create `web/src/components/vui/product/agent-management/AgentPageHeader.tsx`:

```tsx
import { type ReactNode } from "react";

import { VButton, VIconButton, VHStack, VToolbar } from "../../index";

export type AgentPageHeaderAction = {
  id: string;
  label: string;
  icon?: ReactNode;
  onPress?: () => void;
  href?: string;
  disabled?: boolean;
};

export type AgentPageHeaderProps = {
  eyebrow: string;
  title: string;
  actions?: AgentPageHeaderAction[];
};

export function AgentPageHeader({ eyebrow, title, actions = [] }: AgentPageHeaderProps) {
  return (
    <header
      data-vui-product="agent-page-header"
      className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 border-b border-vui-border-hairline bg-vui-surface-page/76 px-3 py-1"
    >
      <div className="grid min-w-0 gap-0.5">
        <span className="truncate text-[0.64rem] font-semibold uppercase tracking-[0.06em] text-vui-fg-tertiary">{eyebrow}</span>
        <h1 className="m-0 truncate text-[0.95rem] font-bold leading-tight text-vui-fg-primary">{title}</h1>
      </div>
      <VToolbar ariaLabel={`${title} actions`} className="justify-end">
        {actions.map((action) => (
          <VHStack key={action.id}>
            {action.icon ? (
              <VIconButton
                label={action.label}
                icon={action.icon}
                onPress={action.onPress}
                isDisabled={action.disabled}
              />
            ) : (
              <VButton onPress={action.onPress} isDisabled={action.disabled}>
                {action.label}
              </VButton>
            )}
          </VHStack>
        ))}
      </VToolbar>
    </header>
  );
}
```

- [ ] **Step 4: Implement AgentSummaryStrip**

Create `web/src/components/vui/product/agent-management/AgentSummaryStrip.tsx`:

```tsx
import { type VuiTone } from "../../renderers/heroui/heroVariants";

export type AgentSummaryMetric = {
  id: string;
  label: string;
  value: string | number;
  detail?: string;
  tone?: VuiTone;
};

export type AgentSummaryStripProps = {
  ariaLabel: string;
  metrics: AgentSummaryMetric[];
};

function metricToneClass(tone: VuiTone | undefined): string {
  if (tone === "success") {
    return "text-emerald-700";
  }
  if (tone === "warning") {
    return "text-amber-700";
  }
  if (tone === "danger") {
    return "text-red-700";
  }
  if (tone === "accent") {
    return "text-vui-accent-cool";
  }
  return "text-vui-fg-primary";
}

export function AgentSummaryStrip({ ariaLabel, metrics }: AgentSummaryStripProps) {
  return (
    <section
      data-vui-product="agent-summary-strip"
      aria-label={ariaLabel}
      className="grid min-w-0 grid-flow-col auto-cols-[minmax(72px,1fr)] overflow-hidden rounded-[var(--radius-control)] border border-vui-border-hairline bg-vui-surface-panel/80"
    >
      {metrics.map((metric, index) => (
        <div
          key={metric.id}
          title={metric.detail}
          className={[
            "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-baseline gap-1 px-2 py-1",
            index === metrics.length - 1 ? "" : "border-r border-vui-border-hairline",
          ].filter(Boolean).join(" ")}
        >
          <span className="truncate text-[0.63rem] font-semibold uppercase tracking-[0.04em] text-vui-fg-tertiary">{metric.label}</span>
          <strong className={["truncate text-[0.8rem] leading-none", metricToneClass(metric.tone)].join(" ")}>{metric.value}</strong>
        </div>
      ))}
    </section>
  );
}
```

- [ ] **Step 5: Export product components**

Create `web/src/components/vui/product/agent-management/index.ts`:

```ts
export { AgentPageHeader, type AgentPageHeaderAction, type AgentPageHeaderProps } from "./AgentPageHeader";
export { AgentSummaryStrip, type AgentSummaryMetric, type AgentSummaryStripProps } from "./AgentSummaryStrip";
```

- [ ] **Step 6: Run product tests**

Run:

```powershell
npm --prefix web run test -- AgentManagementProduct.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Run architecture boundary test**

Run:

```powershell
npm --prefix web run test -- vuiImportBoundary.test.ts
```

Expected: PASS, including the rule that only `components/vui/**` imports HeroUI.

- [ ] **Step 8: Run build**

Run:

```powershell
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 9: Commit**

Run:

```powershell
git status --short
git add web/src/components/vui/product/agent-management/AgentPageHeader.tsx web/src/components/vui/product/agent-management/AgentSummaryStrip.tsx web/src/components/vui/product/agent-management/index.ts web/src/components/vui/product/agent-management/AgentManagementProduct.test.tsx
git commit -m "feat(web): add Agent Management VUI product components"
```

Expected: commit succeeds.

## Task 6: Migrate Agent Management Header And Summary Strip

**Files:**
- Modify: `web/src/routes/AgentsRoute.tsx`
- Modify: `web/src/routes/AgentsRoute.module.css`
- Modify: `web/src/routes/AgentsRoute.layout.test.ts`

**Interfaces:**
- Consumes: `AgentPageHeader`, `AgentSummaryStrip`, existing Agent route copy, summary values, refresh handler, return banner behavior, and `AgentManagementNav`.
- Produces: first route section rendered through product components while preserving existing data behavior.

- [ ] **Step 1: Add failing route contract assertions**

Modify `web/src/routes/AgentsRoute.layout.test.ts`.

Add this test near the existing layout tests:

```ts
it("uses VUI product components for the Agent management header and summary strip", () => {
  expect(routeSource).toContain("AgentPageHeader");
  expect(routeSource).toContain("AgentSummaryStrip");
  expect(routeSource).toContain("agentSummaryMetrics");
  expect(routeSource).not.toContain("styles.summaryCard");
  expect(routeSource).not.toContain("styles.refreshButton");
  expect(routeSource).not.toContain('import { Button } from "@heroui/react"');
});
```

- [ ] **Step 2: Run route test to verify it fails**

Run:

```powershell
npm --prefix web run test -- AgentsRoute.layout.test.ts
```

Expected: FAIL because route still uses old header and summary CSS classes.

- [ ] **Step 3: Import product components**

Modify imports in `web/src/routes/AgentsRoute.tsx`.

Add:

```tsx
import {
  AgentPageHeader,
  AgentSummaryStrip,
  type AgentSummaryMetric,
} from "../components/vui/product/agent-management";
```

- [ ] **Step 4: Add summary metric mapping**

In `AgentsRoute.tsx`, after the existing summary values are available, add:

```tsx
const agentSummaryMetrics: AgentSummaryMetric[] = [
  {
    id: "agents",
    label: copy.totalAgents,
    value: summary?.agentCount ?? workspace.agents.length,
    detail: copy.totalAgents,
  },
  {
    id: "active",
    label: copy.activeAgents,
    value: summary?.activeAgentCount ?? workspace.agents.filter((agent) => agent.status !== "archived").length,
    detail: copy.activeAgents,
    tone: "accent",
  },
  {
    id: "archived",
    label: copy.archivedAgents,
    value: summary?.archivedAgentCount ?? workspace.agents.filter((agent) => agent.status === "archived").length,
    detail: copy.archivedAgents,
  },
  {
    id: "issues",
    label: copy.healthIssues,
    value: summary?.healthIssueCount ?? 0,
    detail: workspaceHealthStatusDescription(healthStatus, summary, lang),
    tone: (summary?.blockingIssueCount ?? 0) > 0 ? "danger" : (summary?.warningIssueCount ?? 0) > 0 ? "warning" : "success",
  },
  {
    id: "models",
    label: copy.model,
    value: workspace.agentModelChoices?.length ?? 0,
    detail: copy.model,
  },
  {
    id: "tools",
    label: copy.tools,
    value: workspace.toolBundles?.length ?? 0,
    detail: copy.tools,
  },
];
```

If exact copy keys differ in current source, use the existing visible labels that already appear in the old summary strip. Do not introduce new explanatory sentences.

- [ ] **Step 5: Replace old header markup**

Replace the old `styles.header` section with:

```tsx
<AgentPageHeader
  eyebrow={copy.eyebrow}
  title={copy.title}
  actions={[
    {
      id: "refresh",
      label: copy.refresh,
      icon: <RefreshCw size={14} />,
      onPress: () => void refreshWorkspace(),
      disabled: workspaceQuery.isFetching,
    },
  ]}
/>
```

Keep any existing return banner immediately below this header if it exists. Do not move return behavior into the VUI header in this task.

- [ ] **Step 6: Replace old summary markup**

Replace the old `styles.summaryGrid` block with:

```tsx
<AgentSummaryStrip ariaLabel={copy.workspaceSummary} metrics={agentSummaryMetrics} />
```

Keep `AgentManagementNav` in its existing route order. The first wave changes surface rendering, not navigation structure.

- [ ] **Step 7: Remove dead header and summary CSS only after source search**

Run:

```powershell
rg -n "summaryCard|summaryGrid|refreshButton|header" web/src/routes/AgentsRoute.tsx web/src/routes/AgentsRoute.module.css web/src/routes/AgentsRoute.layout.test.ts
```

Expected before CSS cleanup: matches remain in CSS and test source.

Remove from `web/src/routes/AgentsRoute.module.css` only these classes if no longer referenced from `AgentsRoute.tsx`:

```css
.header { ... }
.header > div { ... }
.refreshButton { ... }
.refreshButton:hover { ... }
.summaryGrid { ... }
.summaryCard { ... }
.summaryCard:last-child { ... }
.summaryCard span { ... }
.summaryCard strong { ... }
```

Do not remove unrelated layout classes in the same step.

- [ ] **Step 8: Run route tests**

Run:

```powershell
npm --prefix web run test -- AgentsRoute.layout.test.ts vuiImportBoundary.test.ts AgentManagementProduct.test.tsx vuiPrimitives.test.tsx
```

Expected: PASS.

- [ ] **Step 9: Run build**

Run:

```powershell
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 10: Commit**

Run:

```powershell
git status --short
git add web/src/routes/AgentsRoute.tsx web/src/routes/AgentsRoute.module.css web/src/routes/AgentsRoute.layout.test.ts
git commit -m "feat(web): migrate Agent Management header to VUI"
```

Expected: commit succeeds.

## Task 7: Browser Visual Verification And Density Review

**Files:**
- No source files are changed unless the screenshot exposes a concrete layout bug.

**Interfaces:**
- Consumes: running Vibelution frontend.
- Produces: screenshot evidence and final adjustment list.

- [ ] **Step 1: Start or refresh the local workbench frontend through the project launcher path**

If the runtime is already open, use the existing browser URL. If a refresh is needed for the built frontend, use the Launcher refresh route preferred by the project rules rather than raw process killing.

Expected: `/agents` loads from the running workbench.

- [ ] **Step 2: Capture desktop screenshot**

Open:

```text
http://127.0.0.1:<current-frontend-port>/agents
```

Capture a screenshot at `2560x1600`.

Visual acceptance:

- header height remains compact;
- summary metrics are one horizontal strip;
- no thick border appears around the new VUI surfaces;
- buttons hug content or are icon-only;
- background image still reads through the workbench shell without lowering text contrast;
- no route-level explanatory sentence appears in the migrated header and summary area.

- [ ] **Step 3: Capture narrow screenshot**

Capture a screenshot at a narrow width near `1024x768`.

Visual acceptance:

- summary strip does not overlap or push the Agent list below the first useful viewport;
- refresh action remains accessible;
- text truncates deliberately instead of wrapping into awkward multi-line controls;
- no horizontal scroll is required for the header and summary area.

- [ ] **Step 4: Fix only concrete visual defects**

If screenshots show a real issue, adjust only the smallest responsible file:

- `AgentPageHeader.tsx` for header geometry;
- `AgentSummaryStrip.tsx` for metric strip geometry;
- `heroui-theme.css` for renderer-level focus or token issues;
- `AgentsRoute.module.css` only for route layout bridge issues.

Then rerun:

```powershell
npm --prefix web run test -- AgentsRoute.layout.test.ts vuiImportBoundary.test.ts AgentManagementProduct.test.tsx vuiPrimitives.test.tsx
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 5: Commit visual adjustments**

If Step 4 changed files, run:

```powershell
git status --short
git add web/src/components/vui web/src/design web/src/routes/AgentsRoute.module.css web/src/routes/AgentsRoute.layout.test.ts
git commit -m "fix(web): tune Agent Management VUI density"
```

Expected: commit succeeds. If there were no visual defects, skip this commit and record that no screenshot adjustment was needed.

## Task 8: Final Self-Review, Claim Closure, And Merge Decision

**Files:**
- No source files are changed unless self-review finds a defect.

**Interfaces:**
- Consumes: all commits from Tasks 2 through 7.
- Produces: ready-for-merge or blocked handoff.

- [ ] **Step 1: Review changed files**

Run:

```powershell
git status --short --branch
git diff --stat main...HEAD
git diff --check main...HEAD
```

Expected:

```text
git diff --check main...HEAD
```

prints no whitespace errors.

- [ ] **Step 2: Run final validation**

Run:

```powershell
npm --prefix web run test -- AgentsRoute.layout.test.ts vuiImportBoundary.test.ts AgentManagementProduct.test.tsx vuiPrimitives.test.tsx
npm --prefix web run build
```

Expected: all commands PASS.

- [ ] **Step 3: Confirm architecture boundaries**

Run:

```powershell
rg -n "@heroui/react" web/src
rg -n "className=[\"'`][^\"'`]*(bg-|text-|border-|rounded-|shadow-|px-|py-)" web/src/routes -g "*.tsx"
```

Expected:

- `@heroui/react` matches appear only under `web/src/components/vui/**`.
- Route-level visual utility matches are either absent or restricted to legacy strings already present before this branch.

- [ ] **Step 4: Resolve the active implementation claim id**

Run:

```powershell
$claimsPath = "C:\Users\17533\Desktop\Vibelution\.docs\project-memory\agent-claims.json"
$claims = Get-Content -LiteralPath $claimsPath -Raw | ConvertFrom-Json
$claimId = ($claims.claims |
  Where-Object {
    $_.agent -eq "codex-vui-foundation-heroui-agent-management" -and
    $_.task -eq "Implement VUI foundation and first Agent Management HeroUI renderer migration" -and
    $_.status -eq "active"
  } |
  Select-Object -First 1 -ExpandProperty id)
if (-not $claimId) { throw "No active VUI implementation claim found." }
$claimId
```

Expected: PowerShell prints the active claim id created in Task 1.

- [ ] **Step 5: Release or mark claim**

If validation passes:

```powershell
& "C:\Users\17533\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" release --claim-id $claimId --status completed --reason "VUI foundation plus Agent Management header migration complete; tests and build passed; browser screenshots reviewed."
```

If validation fails and cannot be fixed in the same round:

```powershell
$failureReason = "Blocked by validation failure recorded in the final report."
& "C:\Users\17533\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" release --claim-id $claimId --status blocked --reason $failureReason
```

Expected: guard records the final state.

- [ ] **Step 6: Final report**

Report:

- branch and worktree;
- claim id and final claim state;
- commits created;
- changed files;
- validation commands and results;
- screenshot surfaces checked;
- Launcher refresh decision;
- version impact recommendation.

## Self-Review

**Spec coverage:** This plan implements the accepted `VUI-first, HeroUI-rendered` architecture, adds Tailwind CSS v4 and HeroUI behind a Vibelution UI layer, blocks direct HeroUI route imports, keeps CSS Modules as a migration bridge, and starts with Agent Management header and summary rather than risky Agent lifecycle logic.

**Placeholder scan:** The plan uses concrete commands, concrete paths, concrete dependency versions, and a PowerShell claim-id lookup for runtime guard release.

**Type consistency:** `VuiTone`, `VuiDensity`, `VuiButtonVariant`, `AgentSummaryMetric`, and `AgentPageHeaderAction` are defined before route migration uses them.

**Test strategy:** The plan protects the new layer with server-render tests, static architecture tests, existing route layout tests, `npm --prefix web run build`, and browser screenshots.

**Logging decision:** No runtime logging is added because this is a visual architecture migration with no backend state transition, tool execution, or Agent lifecycle behavior change.

**Developer-mode decision:** Parity preserved. The frontend provider and VUI primitives are loaded through the same React entry for developer and formal modes.
