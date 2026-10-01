import { describe, expect, it } from "vitest";

import apiSource from "./teams.ts?raw";
import createDialogSource from "../routes/teams/TeamCreateDialog.tsx?raw";
import createActionsSource from "../routes/teams/useTeamCreateActions.ts?raw";

describe("teams API", () => {
  it("owns the team template transports and paths", () => {
    expect(apiSource).toContain("export function listTeamTemplates");
    expect(apiSource).toContain("export function instantiateTeamTemplate");
    expect(apiSource).toContain('"/api/team-templates"');
    expect(apiSource).toContain(
      "/api/team-templates/${encodeURIComponent(templateId)}/instantiate",
    );
  });

  it("keeps the existing team shell endpoints in the same domain module", () => {
    expect(apiSource).toContain("export function createTeam");
    expect(apiSource).toContain('"/api/teams"');
  });

  it("keeps team-create route surfaces free of JSON paths", () => {
    for (const source of [createDialogSource, createActionsSource]) {
      expect(source).not.toMatch(/['"`]\/api\/team-templates/);
      expect(source).not.toMatch(/\bfetchJson\s*(?:<|\()/);
    }
    expect(createDialogSource).toContain("listTeamTemplates(");
    expect(createActionsSource).toContain("instantiateTeamTemplate(");
    expect(createActionsSource).toContain("createTeam(");
  });
});
