import { describe, expect, it } from "vitest";

import appShellSource from "../app/AppShell.tsx?raw";
import routerSource from "../app/router.tsx?raw";
import routeSource from "./SkillsRoute.tsx?raw";
import stylesSource from "./SkillsRoute.styles.ts?raw";

function extractConstClass(name: string) {
  return stylesSource.match(new RegExp(`const ${name} = "([^"]+)"`))?.[1] ?? "";
}

describe("SkillsRoute layout contract", () => {
  it("is mounted as an Agent management section", () => {
    expect(routerSource).toContain('path: "agents/skills"');
    expect(routerSource).toContain("<SkillsRoute />");
    expect(routerSource).not.toContain('path: "skills"');
    expect(routerSource).not.toContain('to="/agents/skills" replace');
    expect(routeSource).toContain('<AgentManagementNav active="skills" className={styles.managementNavClass} />');
    expect(stylesSource).toContain("const managementNavClass");
    expect(routeSource.indexOf('<AgentManagementNav active="skills" className={styles.managementNavClass} />')).toBeGreaterThan(
      routeSource.indexOf("</VRouteHeader>"),
    );
    expect(routeSource.indexOf('<AgentManagementNav active="skills" className={styles.managementNavClass} />')).toBeLessThan(
      routeSource.indexOf("className={styles.summaryGridClass}"),
    );
    expect(appShellSource).not.toContain('to="/skills"');
  });

  it("uses shell language state without loading the full app dictionary", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const { lang } = useShellI18n()");
    expect(routeSource).not.toContain("useAppI18n");
  });

  it("uses read-only skill library APIs", () => {
    expect(routeSource).toContain('fetchJson<SkillLibraryPayload>("/api/skills")');
    expect(routeSource).toContain("fetchJson<SkillLibraryDetail>(`/api/skills/");
    expect(routeSource).not.toContain('method: "POST"');
    expect(routeSource).not.toContain('method: "PUT"');
    expect(routeSource).not.toContain('method: "PATCH"');
    expect(routeSource).not.toContain('method: "DELETE"');
  });

  it("surfaces slash command and SKILL.md preview", () => {
    expect(routeSource).toContain("copyCommand(activeSkill.command)");
    expect(routeSource).toContain("SKILL.md");
    expect(routeSource).toContain("activeSkill.preview");
    expect(routeSource).toContain("activeSkill.aliases.join");
  });

  it("adds bulk selection without breaking the read-only skill contract", () => {
    expect(routeSource).toContain("selectedSkillCommands");
    expect(routeSource).toContain("copySelectedSkillCommands");
    expect(routeSource).toContain("copy.bulkReadOnlyReason");
    expect(routeSource).toContain("<VNativeInput");
    expect(routeSource).not.toMatch(/<input\b/);
    expect(routeSource).not.toMatch(/<select\b/);
    expect(routeSource).not.toMatch(/<textarea\b/);
    expect(routeSource).toContain("bulkReadOnlyNoteClass");
    expect(routeSource).toContain("bulkActionBarClass");
    expect(routeSource).toContain("selectableRowClass");
    expect(routeSource).not.toContain('method: "POST"');
    expect(routeSource).not.toContain('method: "PUT"');
    expect(routeSource).not.toContain('method: "PATCH"');
    expect(routeSource).not.toContain('method: "DELETE"');
  });

  it("keeps the narrow skill workspace in normal document flow with compact empty details", () => {
    expect(routeSource).toContain("workspaceClass");
    expect(stylesSource).toContain("max-[920px]:grid-cols-1");
    expect(stylesSource).toContain("max-[920px]:content-start");
    expect(stylesSource).toContain("max-[920px]:overflow-auto");
    expect(routeSource).toContain("listPanelClass");
    expect(routeSource).toContain("detailPanelClass");
    expect(routeSource).toContain("emptyDetailClass");
    expect(stylesSource).toContain("min-h-24");
    expect(stylesSource).toContain("p-3");
  });

  it("keeps route and header chrome background-aware", () => {
    const routeClass = extractConstClass("routeClass");
    const headerClass = extractConstClass("headerClass");

    expect(routeClass).not.toContain("surface-page");
    expect(routeClass).not.toMatch(/\bbg-\[(?:var\(--surface-page\)|color-mix\(in_srgb,var\(--surface-page\))/);
    expect(headerClass).not.toContain("vui-gradient-route-soft");
    expect(headerClass).not.toMatch(/\bshadow-\[/);
    expect(headerClass).toContain("!bg-transparent");
    expect(headerClass).toContain("!shadow-none");
    expect(headerClass).toContain("!backdrop-blur-none");
  });

  it("keeps Skills surfaces lightweight instead of building nested opaque card walls", () => {
    const surfaceClasses = [
      extractConstClass("panelClass"),
      extractConstClass("commandPanelClass"),
      extractConstClass("metaGridClass"),
      extractConstClass("surfacePanelClass"),
      extractConstClass("emptyDetailClass"),
    ];

    expect(surfaceClasses).toHaveLength(5);
    surfaceClasses.forEach((className) => {
      expect(className).toContain("border-vui-border-soft");
      expect(className).not.toContain("bg-[var(--surface-panel)]");
      expect(className).not.toContain("bg-[var(--surface-card)]");
      expect(className).not.toContain("shadow-[");
    });
  });

  it("keeps toolbar buttons sized to their content while full-row skill buttons remain explicit", () => {
    const compactButtonClasses = [
      extractConstClass("filterButtonClass"),
      extractConstClass("primaryButtonClass"),
    ];
    const skillButtonBaseClass = stylesSource.match(/const skillButtonBaseClass = \[([\s\S]*?)\]\.join/)?.[1] ?? "";

    compactButtonClasses.forEach((className) => {
      expect(className).toContain("inline-flex");
      expect(className).toContain("w-fit");
      expect(className).toContain("max-w-full");
      expect(className.split(/\s+/)).not.toContain("w-full");
    });
    expect(skillButtonBaseClass).toContain("w-full");
    expect(skillButtonBaseClass).toContain("[&_[data-slot=vui-button-content]]:w-full");
  });

  it("keeps detail chrome and command rows responsive on narrow viewports", () => {
    expect(extractConstClass("detailHeaderClass")).toContain("max-[720px]:flex-wrap");
    expect(extractConstClass("contentHeaderClass")).toContain("max-[720px]:flex-wrap");
    expect(extractConstClass("commandPanelClass")).toContain("max-[720px]:grid-cols-[auto_minmax(0,1fr)]");
    expect(extractConstClass("rootRowClass")).toContain("max-[720px]:grid-cols-1");
  });
});
