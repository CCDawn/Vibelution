/**
 * Pure presentation mapping for SC stage Agent cards (controls rail).
 */
import type { AgentConfigWorkspaceAgent } from "../../../api/types";
import { agentCenterMemoryRoute } from "../../agentCenterRoutes";
import { agentDisplayInfo } from "../../agentDisplay";
import type {
  TeamSourceCollectionStageAgentCard,
  TeamSourceCollectionStageAgentTone,
} from "../../TeamSourceCollectionStageAgentsPanel";
import {
  researchStageAgentConfigStatusLabel,
  researchStageAgentConfigTone,
  researchStageAgentManagementRoute,
  researchStageAgentModelLabel,
} from "../researchStageAgentPresentation";
import type { SourceCollectionStageModuleId } from "./stageProjection";

export type SourceCollectionStageAgentBindingLike = {
  key: string;
  agentId?: string;
  agent?: AgentConfigWorkspaceAgent | null;
  bindingLabel?: string;
  zh: string;
  en: string;
};

export function buildSourceCollectionStageAgentCards(input: {
  stageId: SourceCollectionStageModuleId | string;
  bindings: SourceCollectionStageAgentBindingLike[];
  lang: "zh" | "en";
  agentSummaryPending: boolean;
  agentSummaryFetching: boolean;
  agentSummaryError: boolean;
  teamId?: string;
  returnTo: string;
}): TeamSourceCollectionStageAgentCard[] {
  const {
    stageId,
    bindings,
    lang,
    agentSummaryPending,
    agentSummaryFetching,
    agentSummaryError,
    teamId,
    returnTo,
  } = input;

  return bindings.map((binding) => {
    const agentHydrationPending = Boolean(
      binding.agentId
      && !binding.agent
      && (agentSummaryPending || agentSummaryFetching),
    );
    const tone: TeamSourceCollectionStageAgentTone = binding.agent
      ? researchStageAgentConfigTone(binding.agent)
      : binding.agentId
        ? "blocked"
        : "missing";
    const info = agentDisplayInfo(binding.agent, lang, {
      name: binding.bindingLabel || (lang === "zh" ? binding.zh : binding.en),
    });
    const agentName = binding.agent
      ? info.name
      : binding.agentId
        ? binding.agentId
        : (lang === "zh" ? "未绑定" : "Not bound");
    const statusLabel = binding.agent
      ? researchStageAgentConfigStatusLabel(binding.agent, lang)
      : binding.agentId
        ? agentHydrationPending
          ? (lang === "zh" ? "加载中" : "loading")
          : agentSummaryError
            ? (lang === "zh" ? "Agent 加载失败" : "Agent load failed")
            : (lang === "zh" ? "引用失效" : "missing reference")
        : (lang === "zh" ? "待绑定" : "missing");
    const agentMemoryRoute = binding.agentId
      ? agentCenterMemoryRoute({
          agentId: binding.agentId,
          teamId,
          view: "agents",
          returnLabel: "teams",
          returnTo,
        })
      : "";
    return {
      id: `source-step-${stageId}-${binding.key}`,
      tone,
      roleLabel: lang === "zh" ? binding.zh : binding.en,
      agentName,
      modelLabel: researchStageAgentModelLabel(binding.agent, lang),
      statusLabel,
      memoryRoute: agentMemoryRoute,
      configRoute: binding.agentId ? researchStageAgentManagementRoute(binding.agentId) : "/agents",
      configLabel: binding.agent ? (lang === "zh" ? "配置" : "Configure") : (lang === "zh" ? "绑定" : "Bind"),
    };
  });
}
