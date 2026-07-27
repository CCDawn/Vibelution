/**
 * Facade for Agents workbench copy (structure C1 / dictionary charter C1.1–C1.2).
 * Nested tables: i18n/domains/agentsWorkbenchCopy.
 * High-frequency dual-read: mergeAgentsRouteCopyWithDictionary + dictionaryAgents.
 */
export {
  agentConfigPanes,
  agentsRouteCopy,
  type AgentsRouteCopy,
} from "../../i18n/domains/agentsWorkbenchCopy";
export { mergeAgentsRouteCopyWithDictionary } from "../../i18n/mergeAgentsWorkbenchCopy";
