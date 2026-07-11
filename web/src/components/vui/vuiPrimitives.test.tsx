import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Search } from "lucide-react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import {
  VButton,
  type VButtonProps,
  VChip,
  VIconButton,
  VNativeButton,
  VPanel,
  VSurface,
  VToolbar,
  VTooltip,
  type VTooltipTriggerRender,
} from "./index";
import { VibelutionHeroProvider } from "./renderers/heroui/HeroProvider";

describe("VUI foundation primitives", () => {
  it("keeps VUI button hover behavior owned by shared semantic slots", () => {
    const heroSlotsSource = readFileSync(
      resolve(import.meta.dirname, "renderers/heroui/heroSlots.ts"),
      "utf8",
    );

    expect(heroSlotsSource).toContain("vuiButtonHoverClass");
    expect(heroSlotsSource).toContain("hover:border-[var(--vui-control-hover-border)]");
    expect(heroSlotsSource).toContain("hover:bg-[var(--vui-control-hover-bg)]");
    expect(heroSlotsSource).toContain("hover:text-[var(--vui-control-hover-fg)]");
    expect(heroSlotsSource).not.toContain("hover:border-[var(--border-strong)]");
    expect(heroSlotsSource).not.toContain("hover:bg-[var(--vui-control-muted-hover)]");
  });

  it("scans Tailwind classes from the TSX surfaces replacing CSS modules", () => {
    const tailwindEntry = readFileSync(
      resolve(import.meta.dirname, "../../design/tailwind.css"),
      "utf8",
    );

    expect(tailwindEntry).toContain('@source "../app/**/*.{ts,tsx}";');
    expect(tailwindEntry).toContain('@source "../agent-thread/**/*.{ts,tsx}";');
    expect(tailwindEntry).toContain('@source "../components/**/*.{ts,tsx}";');
    expect(tailwindEntry).toContain('@source "../routes/**/*.{ts,tsx}";');
    expect(tailwindEntry).not.toContain(".test");
  });

  it("wraps children in the Vibelution HeroUI provider boundary", () => {
    const markup = renderToStaticMarkup(
      <VibelutionHeroProvider>
        <main data-test-id="inside-vui">content</main>
      </VibelutionHeroProvider>,
    );

    expect(markup).toContain('data-vui-provider="heroui"');
    expect(markup).toContain('data-test-id="inside-vui"');
  });

  it("renders compact VUI controls with stable data attributes", () => {
    const markup = renderToStaticMarkup(
      <VibelutionHeroProvider>
        <VToolbar ariaLabel="Agent actions">
          <VButton variant="secondary" icon={<Search size={14} />}>
            Search
          </VButton>
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

  it("renders project-owned surface tone and elevation contracts", () => {
    const markup = renderToStaticMarkup(
      <VSurface tone="rail" elevation="panel" ariaLabel="Status rail">
        Status
      </VSurface>,
    );

    expect(markup).toContain('data-tone="rail"');
    expect(markup).toContain('data-elevation="panel"');
    expect(markup).toContain("bg-vui-surface-rail");
    expect(markup).toContain("shadow-[var(--vui-elevation-panel)]");
    expect(markup).toContain("rounded-[var(--vui-radius-panel-soft)]");
  });

  it("gives every icon button a HeroUI tooltip trigger with an accessible name", () => {
    const markup = renderToStaticMarkup(
      <VibelutionHeroProvider>
        <VIconButton label="Refresh" tooltip="Refresh frontend data" icon={<Search size={14} />} />
      </VibelutionHeroProvider>,
    );

    expect(markup).toContain('data-slot="tooltip-trigger"');
    expect(markup).toContain('aria-label="Refresh"');
    expect(markup).toContain('data-vui="icon-button"');
    expect(markup.match(/<button\b/g)).toHaveLength(1);
    expect(markup.match(/tabindex="0"/g)).toHaveLength(1);
    expect(markup).toMatch(/<button(?=[^>]*data-slot="tooltip-trigger")[^>]*>/);
    expect(markup).not.toMatch(/<div[^>]*role="button"[^>]*>[\s\S]*<button/);
  });

  it("does not leave a focusable tooltip wrapper around a disabled icon button", () => {
    const markup = renderToStaticMarkup(
      <VibelutionHeroProvider>
        <VIconButton
          label="Refresh"
          tooltip="Refresh frontend data"
          icon={<Search size={14} />}
          isDisabled
        />
      </VibelutionHeroProvider>,
    );

    expect(markup.match(/<button\b/g)).toHaveLength(1);
    expect(markup).toContain('disabled=""');
    expect(markup).not.toContain('tabindex="0"');
    expect(markup).not.toMatch(/<div[^>]*role="button"[^>]*>[\s\S]*<button/);
  });

  it("composes icon button caller and tooltip trigger handlers and refs", () => {
    const callerClick = vi.fn();
    const tooltipClick = vi.fn();
    const callerRef = vi.fn();
    const tooltipRef = vi.fn();
    const tooltipElement = VIconButton({
      label: "Refresh",
      icon: <Search size={14} />,
      className: "caller-icon-class",
      onClick: callerClick,
      ref: callerRef,
    });
    const renderTrigger = tooltipElement.props.renderTrigger as VTooltipTriggerRender;
    const buttonElement = renderTrigger(
      {
        className: "tooltip-trigger-class",
        onClick: tooltipClick,
        ref: tooltipRef,
      },
      undefined,
    ) as React.ReactElement<VButtonProps>;

    buttonElement.props.onClick?.({} as never);

    expect(callerClick).toHaveBeenCalledTimes(1);
    expect(tooltipClick).toHaveBeenCalledTimes(1);
    expect(buttonElement.props.className).toContain("tooltip-trigger-class");
    expect(buttonElement.props.className).toContain("caller-icon-class");
    expect(buttonElement.props.ref).toEqual(expect.any(Function));

    const buttonNode = {} as HTMLButtonElement;
    (buttonElement.props.ref as React.RefCallback<HTMLButtonElement>)(buttonNode);

    expect(callerRef).toHaveBeenCalledTimes(1);
    expect(callerRef).toHaveBeenCalledWith(buttonNode);
    expect(tooltipRef).toHaveBeenCalledTimes(1);
    expect(tooltipRef).toHaveBeenCalledWith(buttonNode);
  });

  it("renders VButton content in explicit compact inline slots", () => {
    const markup = renderToStaticMarkup(
      <VButton
        icon={<Search size={14} />}
        trailingIcon={<span data-test-id="trailing">+</span>}
        title="Search docs"
      >
        Search
      </VButton>,
    );

    expect(markup).toContain('data-slot="vui-button-content"');
    expect(markup).toContain('data-slot="vui-button-icon"');
    expect(markup).toContain('data-slot="vui-button-label"');
    expect(markup).toContain('data-slot="vui-button-trailing-icon"');
    expect(markup).toContain('title="Search docs"');
    expect(markup).toContain(
      'class="inline-flex min-w-0 max-w-full items-center justify-center gap-1.5"',
    );
    expect(markup).toContain(
      'data-slot="vui-button-label" class="min-w-0 truncate whitespace-nowrap"',
    );
  });

  it("renders plain VButton card content without compact label wrappers", () => {
    const markup = renderToStaticMarkup(
      <VButton contentLayout="plain" className="grid">
        <div data-test-id="plain-card-child">Card body</div>
      </VButton>,
    );

    expect(markup).not.toContain('data-slot="vui-button-content"');
    expect(markup).not.toContain('data-slot="vui-button-label"');
    expect(markup).not.toContain("whitespace-nowrap");
    expect(markup).toContain('data-test-id="plain-card-child"');
  });

  it("keeps button geometry content-sized unless a caller opts into full width", () => {
    const compactMarkup = renderToStaticMarkup(
      <VToolbar ariaLabel="Button fit">
        <VButton icon={<Search size={14} />}>Search</VButton>
        <VIconButton label="Refresh" icon={<Search size={14} />} />
      </VToolbar>,
    );
    const fullWidthMarkup = renderToStaticMarkup(<VButton className="w-full">Expand row</VButton>);

    expect(compactMarkup).toContain("w-fit");
    expect(compactMarkup).toContain("justify-self-start");
    expect(compactMarkup).toContain("shrink-0");
    expect(compactMarkup).toContain("aspect-square");
    expect(compactMarkup).toContain("min-w-[var(--vui-control-height-sm)]");
    expect(fullWidthMarkup).not.toContain("w-fit");
    expect(fullWidthMarkup).toContain("w-full");
  });

  it("keeps native-only controls behind a VUI marker", () => {
    const markup = renderToStaticMarkup(
      <VNativeButton className="compact-native">Open</VNativeButton>,
    );

    expect(markup).toContain('data-vui="native-button"');
    expect(markup).toContain('type="button"');
    expect(markup).toContain("compact-native");
  });

  it("keeps native VUI buttons content-sized by default", () => {
    const markup = renderToStaticMarkup(<VNativeButton>Open</VNativeButton>);

    expect(markup).toContain("inline-flex");
    expect(markup).toContain("justify-self-start");
    expect(markup).toContain("whitespace-nowrap");
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

  it("renders tooltip trigger through the supported HeroUI wrapper structure", () => {
    const markup = renderToStaticMarkup(
      <VTooltip content="Agent health tip" isOpen>
        <button type="button">Hover</button>
      </VTooltip>,
    );

    expect(markup).toContain('data-slot="tooltip-trigger"');
    expect(markup).toContain('aria-describedby=');
    expect(markup).toContain('<button type="button">Hover</button>');
  });
});
