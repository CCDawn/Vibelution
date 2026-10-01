/**
 * Team create flow pure logic: draft state, readiness validation, template
 * options, and the Teams-route picker visibility rule (fixed board teams ∪
 * user-created teams, evolution system teams stay hidden).
 * No React, no transport — see TeamCreateDialog / useTeamCreateActions.
 */
import type { Team, TeamTemplateSummary } from "../../api/types";
import { isEvolutionSystemTeam } from "./teamKindModel";

/** Max team name length accepted by POST /api/teams and template instantiate. */
export const TEAM_NAME_MAX_LENGTH = 160;

/** Option id of the virtual "blank team" entry (no template). */
export const BLANK_TEAM_OPTION_ID = "";

export type TeamCreateStep = "select" | "name" | "success";

export type TeamCreateDraft = {
  step: TeamCreateStep;
  /** Selected template id; "" = blank team. */
  templateId: string;
  name: string;
};

export function createTeamCreateDraft(): TeamCreateDraft {
  return { step: "select", templateId: BLANK_TEAM_OPTION_ID, name: "" };
}

export type TeamCreateTemplateOption = {
  /** Selection key handed back through TeamCreateDraft.templateId. */
  templateId: string;
  /** Template display name; "" for the blank entry (dialog fills copy). */
  name: string;
  description: string;
  roleCount: number;
  defaultTeamName: string;
  blank: boolean;
};

/** Template cards for the picker, with the virtual "blank team" entry first. */
export function resolveTemplateOptions(
  templates: readonly TeamTemplateSummary[],
): TeamCreateTemplateOption[] {
  return [
    {
      templateId: BLANK_TEAM_OPTION_ID,
      name: "",
      description: "",
      roleCount: 0,
      defaultTeamName: "",
      blank: true,
    },
    ...templates.map((template) => ({
      templateId: template.templateId,
      name: template.name,
      description: template.description,
      roleCount: template.roleCount,
      defaultTeamName: template.defaultTeamName,
      blank: false,
    })),
  ];
}

/** Name field prefill for the chosen option (template default or empty). */
export function defaultTeamNameForOption(
  templateId: string,
  templates: readonly TeamTemplateSummary[],
): string {
  return templates.find((template) => template.templateId === templateId)?.defaultTeamName ?? "";
}

/**
 * Create is enabled once a template (or blank) is chosen and the name is
 * non-empty and within the backend limit. Blank teams only need the name.
 */
export function teamCreateReady(
  draft: Pick<TeamCreateDraft, "templateId" | "name">,
  templates: readonly TeamTemplateSummary[] = [],
): boolean {
  const name = draft.name.trim();
  if (!name || name.length > TEAM_NAME_MAX_LENGTH) {
    return false;
  }
  if (draft.templateId === BLANK_TEAM_OPTION_ID) {
    return true;
  }
  return templates.some((template) => template.templateId === draft.templateId);
}

/**
 * Teams shown in the route picker: the three fixed board teams plus
 * user-created teams (manual/custom blank teams and template-instantiated
 * demo teams). Evolution and other workflow-owned teams stay hidden.
 * Picker teams keep their fixed rail order; user teams follow list order.
 */
export function isVisibleRouteTeam(team: Team, pickerTeamIds: readonly string[]): boolean {
  if (isEvolutionSystemTeam(team)) {
    return false;
  }
  if (pickerTeamIds.includes(team.teamId)) {
    return true;
  }
  return (
    team.teamSource === "manual"
    || team.teamKind === "custom"
    || team.teamSource === "team_template"
    || team.teamKind === "template_demo"
  );
}

export function selectVisibleTeams(
  teams: readonly Team[],
  pickerTeamIds: readonly string[],
): Team[] {
  const pickerIndex = new Map(pickerTeamIds.map((teamId, index) => [teamId, index]));
  return teams
    .filter((team) => isVisibleRouteTeam(team, pickerTeamIds))
    .sort((a, b) => {
      const aIndex = pickerIndex.get(a.teamId);
      const bIndex = pickerIndex.get(b.teamId);
      if (aIndex != null && bIndex != null) return aIndex - bIndex;
      if (aIndex != null) return -1;
      if (bIndex != null) return 1;
      return 0;
    });
}
