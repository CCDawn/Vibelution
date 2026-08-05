/**
 * SC stage agent binding / chat route helpers for Teams.
 * Phase R2-j extract from useTeamsWorkbenchModel (behavior-conserving).
 */
import type { NavigateFunction } from "react-router-dom";
import type { UseQueryResult } from "@tanstack/react-query";

import type { AgentConfigWorkspaceAgent, Team } from "../../api/types";
import { RESEARCH_TEAM_ID } from "../TeamsRoute.canvasData";
import { isChallengeCupResearchWorkflowTeam } from "./teamKindModel";
import type { ResearchStageAgentBinding } from "./researchStageAgentBindings";
import {
  researchStageAgentDirectChatRoute,
  researchStageSessionChatRoute,
} from "./researchStageAgentPresentation";
import { researchSourceCollectionRoute } from "./researchWorkspaceModel";
import { SOURCE_COLLECTION_STAGE_CHAT_LABELS } from "./teamRouteShellModel";
import {
  selectSourceCollectionStagePrimaryBinding,
  sourceCollectionStageAgentBindingsForStage,
  sourceCollectionStageChatReturnLabel as sourceCollectionStageChatReturnLabelPure,
  sourceCollectionStageReturnRoute as sourceCollectionStageReturnRoutePure,
  resolveSourceCollectionStageAgentChatState,
  type SourceCollectionStageAgentChatStatus,
} from "./teamSourceCollectionShellModel";
import type { SourceCollectionStageModuleId } from "./source-collection/stageProjection";

export type CreateSourceCollectionStageAgentHelpersOptions = {
  lang: "zh" | "en";
  selectedTeam: Team | null;
  knowledgeExpansionWorkflowTeamSelected: boolean;
  researchStageAgentBindingsByStage: {
    knowledge_collection?: ResearchStageAgentBinding[];
  };
  selectedSourceCollectionRunEffectiveId: string;
  sourceCollectionSummaryQuery: UseQueryResult<{
    latestTasks?: Partial<Record<string, { sessionId?: string }>>;
  } | null | undefined>;
  agentSummaryQuery: UseQueryResult<AgentConfigWorkspaceAgent[] | undefined>;
  seedSourceCollectionAgentSessionContextMutation: {
    mutateAsync: (payload: {
      teamId: string;
      runId: string;
      stageId: SourceCollectionStageModuleId;
      agentId: string;
      agentRole: string;
    }) => Promise<{ chatRoute?: string | null }>;
  };
  repairKnowledgeExpansionTeamAgentsMutation: {
    isPending: boolean;
    mutate: (teamId: string) => void;
  };
  repairChallengeCupTeamAgentsMutation: {
    isPending: boolean;
    mutate: (teamId: string) => void;
  };
  navigate: NavigateFunction;
};

export function createSourceCollectionStageAgentHelpers(
  options: CreateSourceCollectionStageAgentHelpersOptions,
) {
  const {
    lang,
    selectedTeam,
    knowledgeExpansionWorkflowTeamSelected,
    researchStageAgentBindingsByStage,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionSummaryQuery,
    agentSummaryQuery,
    seedSourceCollectionAgentSessionContextMutation,
    repairKnowledgeExpansionTeamAgentsMutation,
    repairChallengeCupTeamAgentsMutation,
    navigate,
  } = options;

  function sourceCollectionStageAgentBindings(stageId: SourceCollectionStageModuleId) {
    return sourceCollectionStageAgentBindingsForStage(
      stageId,
      researchStageAgentBindingsByStage.knowledge_collection ?? [],
    );
  }

  function sourceCollectionStagePrimaryAgentBinding(stageId: SourceCollectionStageModuleId) {
    return selectSourceCollectionStagePrimaryBinding(
      sourceCollectionStageAgentBindings(stageId),
      (agent) => Boolean(researchStageAgentDirectChatRoute(agent)),
    );
  }

  function sourceCollectionStageReturnRoute(stageId: SourceCollectionStageModuleId) {
    return sourceCollectionStageReturnRoutePure(
      selectedTeam?.teamId || RESEARCH_TEAM_ID,
      stageId,
      researchSourceCollectionRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID),
    );
  }

  function sourceCollectionStageChatReturnLabel(stageId: SourceCollectionStageModuleId) {
    return sourceCollectionStageChatReturnLabelPure(stageId, lang, SOURCE_COLLECTION_STAGE_CHAT_LABELS);
  }

  function sourceCollectionStageAgentChatState(stageId: SourceCollectionStageModuleId): {
    binding: ReturnType<typeof sourceCollectionStagePrimaryAgentBinding> | null;
    route: string;
    status: SourceCollectionStageAgentChatStatus;
  } {
    const binding = sourceCollectionStagePrimaryAgentBinding(stageId);
    const returnRoute = sourceCollectionStageReturnRoute(stageId);
    const returnLabel = sourceCollectionStageChatReturnLabel(stageId);
    const currentTaskSessionRoute = researchStageSessionChatRoute(
      sourceCollectionSummaryQuery.data?.latestTasks?.[stageId]?.sessionId,
      returnRoute,
      returnLabel,
    );
    const stageSessionPending = Boolean(
      selectedSourceCollectionRunEffectiveId
      && !sourceCollectionSummaryQuery.data
      && (sourceCollectionSummaryQuery.isPending || sourceCollectionSummaryQuery.isFetching),
    );
    const canCreateProjectSession = Boolean(
      selectedSourceCollectionRunEffectiveId
      && String(binding?.agent?.agentId || binding?.agentId || "").trim(),
    );
    const route = currentTaskSessionRoute;
    return resolveSourceCollectionStageAgentChatState({
      binding,
      route,
      stageSessionPending,
      canCreateProjectSession,
      projectRunAvailable: Boolean(selectedSourceCollectionRunEffectiveId),
      agentSummaryPending: agentSummaryQuery.isPending,
      agentSummaryFetching: agentSummaryQuery.isFetching,
      agentSummaryError: agentSummaryQuery.isError,
    });
  }

  function repairSelectedWorkflowTeamAgentsIfNeeded() {
    if (!selectedTeam?.teamId) {
      return;
    }
    if (knowledgeExpansionWorkflowTeamSelected && !repairKnowledgeExpansionTeamAgentsMutation.isPending) {
      repairKnowledgeExpansionTeamAgentsMutation.mutate(selectedTeam.teamId);
      return;
    }
    if (isChallengeCupResearchWorkflowTeam(selectedTeam) && !repairChallengeCupTeamAgentsMutation.isPending) {
      repairChallengeCupTeamAgentsMutation.mutate(selectedTeam.teamId);
    }
  }

  async function openSourceCollectionStageAgentChat(stageId: SourceCollectionStageModuleId) {
    const chatState = sourceCollectionStageAgentChatState(stageId);
    const binding = chatState.binding;
    const teamId = selectedTeam?.teamId || RESEARCH_TEAM_ID;
    const runId = selectedSourceCollectionRunEffectiveId;
    const agentId = String(binding?.agent?.agentId || binding?.agentId || "").trim();
    if (teamId && runId && agentId) {
      try {
        const payload = await seedSourceCollectionAgentSessionContextMutation.mutateAsync({
          teamId,
          runId,
          stageId,
          agentId,
          agentRole: binding?.key || "",
        });
        if (payload.chatRoute) {
          navigate(payload.chatRoute);
        }
      } catch (error) {
        console.warn("Failed to resolve source collection experiment session before navigation.", error);
      }
      return;
    }
    if (chatState.status === "repair") {
      repairSelectedWorkflowTeamAgentsIfNeeded();
    }
  }

  return {
    sourceCollectionStageAgentBindings,
    sourceCollectionStagePrimaryAgentBinding,
    sourceCollectionStageAgentChatState,
    sourceCollectionStageReturnRoute,
    sourceCollectionStageChatReturnLabel,
    repairSelectedWorkflowTeamAgentsIfNeeded,
    openSourceCollectionStageAgentChat,
  };
}
