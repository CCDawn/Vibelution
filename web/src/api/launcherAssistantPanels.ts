import { launcherAssistantBridge, type LauncherAssistantRequest } from "./launcherAssistant";
import type * as affairsApi from "./personalAffairs";
import type * as settingsApi from "./personalAssistant";
import type * as dialogueApi from "./virtualHumanLife";

/** All operations are fixed to the resident identity; no URL or credential enters the renderer. */
export function createLauncherAssistantPanelTransport(agentId: string) {
  if (!agentId.trim()) throw new Error("Launcher 个人助理身份不可用。");
  function guard(id: string) {
    if (id !== agentId) throw new Error("Launcher 个人助理身份不匹配。");
  }
  async function call<T>(request: LauncherAssistantRequest, signal?: AbortSignal): Promise<T> {
    signal?.throwIfAborted();
    const result = await launcherAssistantBridge().invoke(request);
    signal?.throwIfAborted();
    if (!result || typeof result !== "object" || Array.isArray(result)) throw new Error("Launcher 返回的数据不可用。");
    if ("agentId" in result && result.agentId !== agentId) throw new Error("Launcher 个人助理身份不匹配。");
    return result as T;
  }
  const affairs: Pick<typeof affairsApi, "fetchPersonalAffairs" | "addPersonalAffair" | "completePersonalAffair" | "cancelPersonalAffair" | "reopenPersonalAffair" | "setPersonalAffairDue"> = {
    fetchPersonalAffairs: (id, options) => { guard(id); return call({ operation: "panelAffairs", kind: options?.kind ?? "", status: options?.status ?? "" }, options?.signal); },
    addPersonalAffair: (id, payload) => { guard(id); if (payload.sourceTurnId) throw new Error("无法指定来源轮次。"); return call({ operation: "panelAffairAdd", payload: { kind: payload.kind, title: payload.title, ...(payload.note !== undefined ? { note: payload.note } : {}), ...(payload.dueAt !== undefined ? { dueAt: payload.dueAt } : {}) } }); },
    completePersonalAffair: (id, itemId) => { guard(id); return call({ operation: "panelAffairComplete", itemId }); },
    cancelPersonalAffair: (id, itemId) => { guard(id); return call({ operation: "panelAffairCancel", itemId }); },
    reopenPersonalAffair: (id, itemId) => { guard(id); return call({ operation: "panelAffairReopen", itemId }); },
    setPersonalAffairDue: (id, itemId, dueAt) => { guard(id); return call({ operation: "panelAffairDue", itemId, payload: { dueAt } }); },
  };
  const preferences: Pick<typeof dialogueApi, "fetchVirtualHumanDialogueSettings" | "updateVirtualHumanDialogueSettings" | "fetchVirtualHumanPreferenceProposals" | "acceptVirtualHumanPreferenceProposal" | "rejectVirtualHumanPreferenceProposal"> = {
    fetchVirtualHumanDialogueSettings: (id, options) => { guard(id); return call({ operation: "panelDialogue" }, options?.signal); },
    updateVirtualHumanDialogueSettings: (id, payload, options) => { guard(id); return call({ operation: "panelDialogueUpdate", payload }, options?.signal); },
    fetchVirtualHumanPreferenceProposals: (id, options) => { guard(id); if (options?.status) throw new Error("此筛选不可用。"); return call({ operation: "panelProposals" }, options?.signal); },
    acceptVirtualHumanPreferenceProposal: (id, proposalId, options) => { guard(id); return call({ operation: "panelProposalAccept", proposalId }, options?.signal); },
    rejectVirtualHumanPreferenceProposal: (id, proposalId, options) => { guard(id); return call({ operation: "panelProposalReject", proposalId }, options?.signal); },
  };
  const settings: Pick<typeof settingsApi, "fetchPersonalAssistantSettings" | "updatePersonalAssistantSettings" | "updatePersonalAssistantModel"> = {
    fetchPersonalAssistantSettings: options => call({ operation: "panelSettings" }, options?.signal),
    updatePersonalAssistantSettings: payload => call({ operation: "panelSettingsUpdate", payload }),
    updatePersonalAssistantModel: modelId => call({ operation: "panelModelUpdate", payload: { modelId } }),
  };
  return { scope: "launcher" as const, cacheKey: ["launcher-assistant", agentId] as const, affairs, preferences, settings };
}

export type LauncherAssistantPanelTransport = ReturnType<typeof createLauncherAssistantPanelTransport>;
