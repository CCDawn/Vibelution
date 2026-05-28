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
    expect(routeSource).toContain('<AgentManagementNav active="skills" className={styles.managementNav} />');
    expect(routeSource.indexOf('<AgentManagementNav active="skills" className={styles.managementNav} />')).toBeGreaterThan(
      routeSource.indexOf("</header>"),
    );
    expect(routeSource.indexOf('<AgentManagementNav active="skills" className={styles.managementNav} />')).toBeLessThan(
      routeSource.indexOf("styles.summaryGrid"),
    );
    expect(appShellSource).not.toContain('to="/skills"');
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
});
