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
  };
}
