import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  VUI_TYPE_ROLES,
  vuiTypeBody,
  vuiTypeByRole,
  vuiTypeCaption,
  vuiTypeChat,
  vuiTypeControl,
  vuiTypeDisplay,
  vuiTypeEmphasis,
  vuiTypeLabel,
  vuiTypeMono,
  vuiTypeTitle,
} from "./typographyRecipes";

describe("typographyRecipes", () => {
  it("exports every documented role", () => {
    expect(VUI_TYPE_ROLES.length).toBe(9);
    for (const role of VUI_TYPE_ROLES) {
      expect(vuiTypeByRole[role]).toBeTypeOf("string");
      expect(vuiTypeByRole[role].length).toBeGreaterThan(20);
    }
  });

  it("keeps recipes on CSS variables (no font-as-color trap)", () => {
    const recipes = [
      vuiTypeCaption,
      vuiTypeLabel,
      vuiTypeControl,
      vuiTypeBody,
      vuiTypeChat,
      vuiTypeEmphasis,
      vuiTypeTitle,
      vuiTypeDisplay,
      vuiTypeMono,
    ];
    for (const recipe of recipes) {
      expect(recipe).toMatch(/\[font-size:var\(--vui-/);
      expect(recipe).not.toMatch(/(?<!\[font-size:)text-\[var\(--vui-font-/);
    }
  });

  it("documents the system in TYPOGRAPHY.md and tokens.css", () => {
    const tokens = readFileSync(resolve(import.meta.dirname, "tokens.css"), "utf8");
    const guide = readFileSync(resolve(import.meta.dirname, "TYPOGRAPHY.md"), "utf8");
    for (const token of [
      "--vui-font-2xs",
      "--vui-font-lg",
      "--vui-font-xl",
      "--vui-type-body-size",
      "--vui-type-chat-size",
      "--vui-weight-semibold",
      "--vui-tracking-label",
    ]) {
      expect(tokens).toContain(token);
    }
    expect(guide).toContain("Semantic roles");
    expect(guide).toContain("typographyRecipes.ts");
  });
});
