import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Search } from "lucide-react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VButton, VChip, VIconButton, VNativeButton, VPanel, VToolbar, VTooltip } from "./index";
import { VibelutionHeroProvider } from "./renderers/heroui/HeroProvider";

describe("VUI foundation primitives", () => {
  it("limits Tailwind source scanning to the VUI bootstrap areas", () => {
    const tailwindEntry = readFileSync(
      resolve(import.meta.dirname, "../../design/tailwind.css"),
      "utf8",
    );

    expect(tailwindEntry).toContain('@source "../app/**/*.{ts,tsx}";');
    expect(tailwindEntry).toContain('@source "../components/vui/**/*.{ts,tsx}";');
    expect(tailwindEntry).not.toContain("../routes/");
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
    expect(markup).toContain('class="inline-flex items-center gap-1.5"');
  });

  it("keeps native-only controls behind a VUI marker", () => {
    const markup = renderToStaticMarkup(
      <VNativeButton className="compact-native">Open</VNativeButton>,
    );

    expect(markup).toContain('data-vui="native-button"');
    expect(markup).toContain('type="button"');
    expect(markup).toContain('class="compact-native"');
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
