import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

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
});
