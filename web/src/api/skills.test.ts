import { describe, expect, it } from "vitest";

import apiSource from "./skills.ts?raw";
import routeSource from "../routes/SkillsRoute.tsx?raw";

describe("skills catalog API", () => {
  it("owns skill library read transports", () => {
    expect(apiSource).toContain("export function fetchSkillLibrary");
    expect(apiSource).toContain("export function fetchSkillLibraryDetail");
    expect(apiSource).toContain('"/api/skills"');
    expect(apiSource).toContain("/api/skills/${encodeURIComponent(command)}");
  });

  it("keeps SkillsRoute free of skills JSON paths", () => {
    expect(routeSource).toContain("fetchSkillLibrary(");
    expect(routeSource).toContain("fetchSkillLibraryDetail(");
    expect(routeSource).not.toMatch(/[`'"]\/api\/skills/);
  });
});
