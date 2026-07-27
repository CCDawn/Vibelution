/**
 * Source-collection inject pure builders (workspace claim: SC controls/writeback).
 * Pure: no React / Query / DOM.
 */
import {
  sourceCollectionAgentRoleLabel,
  sourceCollectionStatusLabel,
  type SourceCollectionMode,
} from "./presentationModel";

export type SourceCollectionAssignmentLike = {
  assignmentId: string;
  agentRole?: string;
  status?: string;
};

export type SourceCollectionManualWritebackDraftLike = {
  assignmentId?: string;
  sourceType?: string;
  title?: string;
  url?: string;
  note?: string;
  content?: string;
};

export function sourceCollectionModeFieldOptions(
  lang: "zh" | "en",
  modeLabel: (mode: SourceCollectionMode, lang: "zh" | "en") => string,
) {
  return (["mixed", "web_search", "local_workspace"] as SourceCollectionMode[]).map((mode) => ({
    value: mode,
    label: modeLabel(mode, lang),
  }));
}

export function sourceCollectionModeFieldsVisible(knowledgeExpansionWorkflowTeamSelected: boolean) {
  return Boolean(knowledgeExpansionWorkflowTeamSelected);
}

export function shouldShowLocalScanRootsField(mode: SourceCollectionMode | string | undefined) {
  return String(mode || "mixed") !== "web_search";
}

export function buildSourceCollectionManualWritebackAssignmentOptions(
  assignments: SourceCollectionAssignmentLike[],
  lang: "zh" | "en",
) {
  return assignments.map((assignment) => ({
    id: assignment.assignmentId,
    label: `${sourceCollectionAgentRoleLabel(assignment.agentRole, lang)} · ${sourceCollectionStatusLabel(assignment.status, lang)}`,
  }));
}

export function resolveSourceCollectionManualWritebackAssignmentValue(
  draftAssignmentId: string | undefined,
  selectedAssignmentId: string | undefined,
) {
  return String(draftAssignmentId || selectedAssignmentId || "").trim();
}

export function canSubmitSourceCollectionManualWriteback(input: {
  teamId?: string;
  runId?: string;
  assignmentId?: string;
  hasRecord: boolean;
}) {
  return Boolean(
    String(input.teamId || "").trim()
    && String(input.runId || "").trim()
    && String(input.assignmentId || "").trim()
    && input.hasRecord,
  );
}

export function canStartSourceCollectionRun(input: {
  teamId?: string;
  canStart: boolean;
  startPending: boolean;
}) {
  return Boolean(String(input.teamId || "").trim() && input.canStart && !input.startPending);
}
