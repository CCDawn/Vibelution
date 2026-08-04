import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Forced frontend contract: routes compose VUI product API only.
 * shadcn/Radix lives under components/vui/renderers/shadcn — never imported from routes.
 */
const webSrc = resolve(import.meta.dirname, "../..");
const routesDir = resolve(webSrc, "routes");

const FORBIDDEN_IMPORT_PATTERNS: Array<{ label: string; re: RegExp }> = [
  { label: "@heroui/react", re: /from\s+["']@heroui\/react["']/ },
  { label: "renderers/shadcn direct", re: /from\s+["'][^"']*renderers\/shadcn[^"']*["']/ },
  { label: "components/ui shadcn bypass", re: /from\s+["'][^"']*\/components\/ui\// },
];

function walkTsFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      walkTsFiles(full, out);
      continue;
    }
    if (/\.(tsx|ts)$/.test(name) && !name.includes(".test.") && !name.includes(".styles.")) {
      out.push(full);
    }
  }
  return out;
}

describe("VUI shadcn route contract", () => {
  it("forbids routes from importing HeroUI or shadcn renderers directly", () => {
    const files = walkTsFiles(routesDir);
    const offenders: string[] = [];

    for (const file of files) {
      const text = readFileSync(file, "utf-8");
      for (const rule of FORBIDDEN_IMPORT_PATTERNS) {
        if (rule.re.test(text)) {
          offenders.push(`${relative(webSrc, file)}: ${rule.label}`);
        }
      }
    }

    expect(offenders, `Forbidden imports in routes:\n${offenders.join("\n")}`).toEqual([]);
  });

  it("keeps Teams shell on VSplitWorkspace + WORKBENCH_LAYOUT_IDS.teams", () => {
    const teams = readFileSync(resolve(routesDir, "TeamsRoute.tsx"), "utf-8");
    expect(teams).toContain("VSplitWorkspace");
    expect(teams).toContain("WORKBENCH_LAYOUT_IDS.teams");
    expect(teams).toContain('data-vui-domain-recipe="teams-organization-workbench"');
    expect(teams).toContain("TeamShellRail");
    expect(teams).not.toMatch(/from\s+["']@heroui\/react["']/);
    expect(teams).not.toMatch(/renderers\/shadcn/);
  });
});
