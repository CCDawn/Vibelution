import { describe, expect, it } from "vitest";

import appShellSource from "../app/AppShell.tsx?raw";
import routerSource from "../app/router.tsx?raw";
import routeSource from "./SkillsRoute.tsx?raw";

describe("SkillsRoute layout contract", () => {
  it("is mounted as an Agent management section", () => {
    expect(routerSource).toContain('path: "agents/skills"');
    expect(routerSource).toContain("<SkillsRoute />");
    expect(routerSource).not.toContain('path: "skills"');
    expect(routerSource).not.toContain('to="/agents/skills" replace');
    expect(routeSource).toContain('<AgentManagementNav active="skills" className={managementNavClass} />');
    expect(routeSource.indexOf('<AgentManagementNav active="skills" className={managementNavClass} />')).toBeGreaterThan(
      routeSource.indexOf("</VRouteHeader>"),
    );
    expect(routeSource.indexOf('<AgentManagementNav active="skills" className={managementNavClass} />')).toBeLessThan(
      routeSource.indexOf("className={summaryGridClass}"),
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
    expect(routeSource).toContain("max-[920px]:grid-cols-1");
    expect(routeSource).toContain("max-[920px]:content-start");
    expect(routeSource).toContain("max-[920px]:overflow-auto");
    expect(routeSource).toContain("listPanelClass");
    expect(routeSource).toContain("detailPanelClass");
    expect(routeSource).toContain("emptyDetailClass");
    expect(routeSource).toContain("min-h-24");
    expect(routeSource).toContain("p-3");
  });
});
