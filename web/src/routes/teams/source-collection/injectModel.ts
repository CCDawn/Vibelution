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

/** Recommended next-step copy for the screening workspace (pure presentation). */
export function resolveSourceCollectionScreeningRecommendedNextHint(input: {
  lang: "zh" | "en";
  needsAgentMaterial: boolean;
  pendingScreeningCount: number;
  projectedApprovedCount: number;
  screeningButtonText: string;
}): string | null {
  const zh = input.lang === "zh";
  if (input.needsAgentMaterial) {
    return zh
      ? "推荐下一步：右侧主按钮「补材料」→ 完成后再质量审查。不要只点审查。"
      : "Recommended: right-stage primary “repair materials”, then quality review. Do not review alone.";
  }
  if (input.pendingScreeningCount > 0) {
    return zh
      ? `推荐下一步：点「${input.screeningButtonText}」推进审查。`
      : `Recommended: run “${input.screeningButtonText}”.`;
  }
  if (input.projectedApprovedCount > 0 && input.pendingScreeningCount <= 0) {
    return zh
      ? "推荐下一步：右侧主按钮「进入关系整理」。"
      : "Recommended: right-stage primary “Go to relations”.";
  }
  return null;
}

export type SourceCollectionFilterBarOption<Key extends string = string> = {
  key: Key;
  label: string;
  count: number | string;
  selected: boolean;
};

export function buildSourceCollectionFilterBarOptions<Key extends string>(input: {
  filters: readonly Key[];
  counts: Partial<Record<Key, number>>;
  selected: Key;
  loading?: boolean;
  loadingAllText: string;
  loadingOtherText?: string;
  labelFor: (filter: Key) => string;
}): Array<SourceCollectionFilterBarOption<Key>> {
  const loadingOtherText = input.loadingOtherText ?? "...";
  return input.filters.map((filter) => ({
    key: filter,
    label: input.labelFor(filter),
    count: input.loading
      ? (filter === ("all" as Key) ? input.loadingAllText : loadingOtherText)
      : input.counts[filter] ?? 0,
    selected: input.selected === filter,
  }));
}

export function resolveSourceCollectionPaginationView(input: {
  total: number;
  page: number;
  pageSize: number;
}) {
  const pageCount = Math.max(1, Math.ceil(input.total / input.pageSize));
  if (pageCount <= 1) {
    return null;
  }
  const page = Math.min(Math.max(1, input.page), pageCount);
  return {
    page,
    pageCount,
    pageSize: input.pageSize,
    total: input.total,
  };
}
