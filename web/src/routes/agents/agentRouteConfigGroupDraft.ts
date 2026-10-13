/**
 * Agent core config draft grouping for independent save/reset and source sync.
 * Pure: no React hooks / Query / DOM.
 */
import type { AgentConfigDraft } from "../AgentCoreConfigPanel";
import {
  sameAgentLlmBindings,
  sameAgentReasoningEffortBySlot,
} from "./agentRouteLlmModel";
import { contextCompressionDraftEqualsDraft } from "./agentRouteDraftModel";

export type AgentConfigSaveGroup = "models" | "basic";

export function sameAgentConfigDraftGroup(
  left: AgentConfigDraft,
  right: AgentConfigDraft,
  group: AgentConfigSaveGroup,
) {
  if (group === "models") {
    return sameAgentLlmBindings(left.llmBindings, right.llmBindings)
      && sameAgentReasoningEffortBySlot(left.reasoningEffortBySlot, right.reasoningEffortBySlot);
  }
  return left.displayName === right.displayName
    && left.promptTemplateId === right.promptTemplateId
    && left.toolPolicyId === right.toolPolicyId
    && left.memoryPolicyId === right.memoryPolicyId
    && left.permissionPreset === right.permissionPreset
    && contextCompressionDraftEqualsDraft(left.contextCompressionPolicy, right.contextCompressionPolicy)
    && left.status === right.status;
}

export function mergeAgentConfigDraftGroup(
  current: AgentConfigDraft,
  source: AgentConfigDraft,
  group: AgentConfigSaveGroup,
): AgentConfigDraft {
  if (group === "models") {
    return {
      ...current,
      llmBindings: source.llmBindings,
      reasoningEffortBySlot: source.reasoningEffortBySlot,
    };
  }
  return {
    ...current,
    displayName: source.displayName,
    promptTemplateId: source.promptTemplateId,
    toolPolicyId: source.toolPolicyId,
    memoryPolicyId: source.memoryPolicyId,
    permissionPreset: source.permissionPreset,
    contextCompressionPolicy: source.contextCompressionPolicy,
    status: source.status,
  };
}

/**
 * Adopt new server values only for groups that were clean against the previous
 * source. Dirty groups remain local while clean groups continue to refresh.
 */
export function mergeCleanAgentConfigDraftGroups(
  current: AgentConfigDraft,
  previousSource: AgentConfigDraft,
  nextSource: AgentConfigDraft,
): AgentConfigDraft {
  let next = current;
  for (const group of ["models", "basic"] as const) {
    if (sameAgentConfigDraftGroup(current, previousSource, group)) {
      next = mergeAgentConfigDraftGroup(next, nextSource, group);
    }
  }
  return next;
}
