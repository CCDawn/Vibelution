/**
 * C1.2 dual-read: overlay high-frequency flat dictionaryAgents keys onto nested workbench copy.
 * Falls back to nested table when dictionary domain is not loaded (t returns the key itself).
 */
import type { TranslationKey } from "./dictionaryTypes";
import type { AgentsRouteCopy } from "./domains/agentsWorkbenchCopy";

export type AgentsWorkbenchDictionaryPick = (key: TranslationKey) => string;

function pickDictionaryValue(
  t: AgentsWorkbenchDictionaryPick,
  key: TranslationKey,
  fallback: string,
) {
  const value = t(key);
  // useAppI18n returns the key string when the domain table is empty/unloaded.
  if (!value || value === key) {
    return fallback;
  }
  return value;
}

/**
 * High-frequency workbench fields only — do not expand to the full nested table here.
 */
export function mergeAgentsRouteCopyWithDictionary(
  base: AgentsRouteCopy,
  t: AgentsWorkbenchDictionaryPick,
): AgentsRouteCopy {
  return {
    ...base,
    title: pickDictionaryValue(t, "agentsWorkbenchTitle", base.title),
    subtitle: pickDictionaryValue(t, "agentsWorkbenchSubtitle", base.subtitle),
    refresh: pickDictionaryValue(t, "agentsWorkbenchRefresh", base.refresh),
    loading: pickDictionaryValue(t, "agentsWorkbenchLoading", base.loading),
    loadFailed: pickDictionaryValue(t, "agentsWorkbenchLoadFailed", base.loadFailed),
    search: pickDictionaryValue(t, "agentsWorkbenchSearch", base.search),
    createAgent: pickDictionaryValue(t, "agentsWorkbenchCreateAgent", base.createAgent),
    bulkSelected: pickDictionaryValue(t, "agentsWorkbenchBulkSelected", base.bulkSelected),
    bulkClear: pickDictionaryValue(t, "agentsWorkbenchBulkClear", base.bulkClear),
    bulkNoSelection: pickDictionaryValue(t, "agentsWorkbenchBulkNoSelection", base.bulkNoSelection),
    bulkWorking: pickDictionaryValue(t, "agentsWorkbenchBulkWorking", base.bulkWorking),
    bulkNoPrompt: pickDictionaryValue(t, "agentsWorkbenchBulkNoPrompt", base.bulkNoPrompt),
    bulkNoConfigFields: pickDictionaryValue(t, "agentsWorkbenchBulkNoConfigFields", base.bulkNoConfigFields),
    overviewPane: pickDictionaryValue(t, "agentsWorkbenchOverviewPane", base.overviewPane),
    configTitle: pickDictionaryValue(t, "agentsWorkbenchConfigTitle", base.configTitle),
    // C1.3 mid-frequency bulk / filter / management dual-read
    bulkSelectVisible: pickDictionaryValue(t, "agentsWorkbenchBulkSelectVisible", base.bulkSelectVisible),
    bulkApplyPrompt: pickDictionaryValue(t, "agentsWorkbenchBulkApplyPrompt", base.bulkApplyPrompt),
    bulkArchive: pickDictionaryValue(t, "agentsWorkbenchBulkArchive", base.bulkArchive),
    bulkPurge: pickDictionaryValue(t, "agentsWorkbenchBulkPurge", base.bulkPurge),
    bulkArchiveResult: pickDictionaryValue(t, "agentsWorkbenchBulkArchiveResult", base.bulkArchiveResult),
    bulkPurgeResult: pickDictionaryValue(t, "agentsWorkbenchBulkPurgeResult", base.bulkPurgeResult),
    bulkPromptResult: pickDictionaryValue(t, "agentsWorkbenchBulkPromptResult", base.bulkPromptResult),
    bulkConfigResult: pickDictionaryValue(t, "agentsWorkbenchBulkConfigResult", base.bulkConfigResult),
    bulkSkippedArchived: pickDictionaryValue(t, "agentsWorkbenchBulkSkippedArchived", base.bulkSkippedArchived),
    bulkSkippedActive: pickDictionaryValue(t, "agentsWorkbenchBulkSkippedActive", base.bulkSkippedActive),
    bulkSkippedProtected: pickDictionaryValue(t, "agentsWorkbenchBulkSkippedProtected", base.bulkSkippedProtected),
    managementBriefTitle: pickDictionaryValue(t, "agentsWorkbenchManagementBriefTitle", base.managementBriefTitle),
    managementBriefHint: pickDictionaryValue(t, "agentsWorkbenchManagementBriefHint", base.managementBriefHint),
    moreFilters: pickDictionaryValue(t, "agentsWorkbenchMoreFilters", base.moreFilters),
    filterSections: {
      ...base.filterSections,
      status: pickDictionaryValue(t, "agentsWorkbenchFilterStatus", base.filterSections.status),
      boundary: pickDictionaryValue(t, "agentsWorkbenchFilterBoundary", base.filterSections.boundary),
      team_index: pickDictionaryValue(t, "agentsWorkbenchFilterTeamIndex", base.filterSections.team_index),
      source_scope: pickDictionaryValue(t, "agentsWorkbenchFilterSourceScope", base.filterSections.source_scope),
      mode: pickDictionaryValue(t, "agentsWorkbenchFilterMode", base.filterSections.mode),
      reference: pickDictionaryValue(t, "agentsWorkbenchFilterReference", base.filterSections.reference),
      management: pickDictionaryValue(t, "agentsWorkbenchFilterManagement", base.filterSections.management),
    },
    // C1.4 group labels / descriptions + management filter titles
    groupLabels: {
      ...base.groupLabels,
      active: pickDictionaryValue(t, "agentsWorkbenchGroupActive", base.groupLabels.active),
      needs_review: pickDictionaryValue(t, "agentsWorkbenchGroupNeedsReview", base.groupLabels.needs_review),
      archived: pickDictionaryValue(t, "agentsWorkbenchGroupArchived", base.groupLabels.archived),
      work_session: pickDictionaryValue(t, "agentsWorkbenchGroupWorkSession", base.groupLabels.work_session),
      team_role: pickDictionaryValue(t, "agentsWorkbenchGroupTeamRole", base.groupLabels.team_role),
      system_role: pickDictionaryValue(t, "agentsWorkbenchGroupSystemRole", base.groupLabels.system_role),
      service_role: pickDictionaryValue(t, "agentsWorkbenchGroupServiceRole", base.groupLabels.service_role),
      chat: pickDictionaryValue(t, "agentsWorkbenchGroupChat", base.groupLabels.chat),
      research: pickDictionaryValue(t, "agentsWorkbenchGroupResearch", base.groupLabels.research),
      supervised_evolution: pickDictionaryValue(t, "agentsWorkbenchGroupSupervisedEvolution", base.groupLabels.supervised_evolution),
      self_evolution: pickDictionaryValue(t, "agentsWorkbenchGroupSelfEvolution", base.groupLabels.self_evolution),
      group_chat: pickDictionaryValue(t, "agentsWorkbenchGroupGroupChat", base.groupLabels.group_chat),
      team: pickDictionaryValue(t, "agentsWorkbenchGroupTeam", base.groupLabels.team),
    },
    groupDescriptions: {
      ...base.groupDescriptions,
      active: pickDictionaryValue(t, "agentsWorkbenchGroupDescActive", base.groupDescriptions.active),
      needs_review: pickDictionaryValue(t, "agentsWorkbenchGroupDescNeedsReview", base.groupDescriptions.needs_review),
      archived: pickDictionaryValue(t, "agentsWorkbenchGroupDescArchived", base.groupDescriptions.archived),
      work_session: pickDictionaryValue(t, "agentsWorkbenchGroupDescWorkSession", base.groupDescriptions.work_session),
      team_role: pickDictionaryValue(t, "agentsWorkbenchGroupDescTeamRole", base.groupDescriptions.team_role),
      system_role: pickDictionaryValue(t, "agentsWorkbenchGroupDescSystemRole", base.groupDescriptions.system_role),
      service_role: pickDictionaryValue(t, "agentsWorkbenchGroupDescServiceRole", base.groupDescriptions.service_role),
      group_chat: pickDictionaryValue(t, "agentsWorkbenchGroupDescGroupChat", base.groupDescriptions.group_chat),
      team: pickDictionaryValue(t, "agentsWorkbenchGroupDescTeam", base.groupDescriptions.team),
    },
    managementFilterMissingPersona: pickDictionaryValue(t, "agentsWorkbenchFilterMissingPersona", base.managementFilterMissingPersona),
    managementFilterMissingTask: pickDictionaryValue(t, "agentsWorkbenchFilterMissingTask", base.managementFilterMissingTask),
    managementFilterMissingTools: pickDictionaryValue(t, "agentsWorkbenchFilterMissingTools", base.managementFilterMissingTools),
    managementFilterNoTeam: pickDictionaryValue(t, "agentsWorkbenchFilterNoTeam", base.managementFilterNoTeam),
    managementFilterPendingInbox: pickDictionaryValue(t, "agentsWorkbenchFilterPendingInbox", base.managementFilterPendingInbox),
    managementFilterMaintenance: pickDictionaryValue(t, "agentsWorkbenchFilterMaintenance", base.managementFilterMaintenance),
  };
}
