import { useCallback, useMemo } from "react";

import type { AgentInstance, ConversationMessage } from "../../api/types";
import { isAgentInboxMessage } from "../../components/conversation/conversationMessagePredicates";
import type { TurnAvatarResolution } from "../../components/conversation/conversationTurnAvatar";
import { buildChatMentionTargets, type ChatMentionTarget } from "../chatMentionTokens";
import {
  avatarImageUrlFrom,
  avatarInitials,
  conversationMetadataText,
} from "./chatRoutePresentation";
import {
  buildAgentsByCode,
  buildAgentsById,
  buildArchiveVisibleAgents,
} from "./chatAgentDirectoryMaps";

export type UseChatAgentDirectoryMapsInput = {
  agents: readonly AgentInstance[] | undefined;
  pendingArchiveAgentIds: ReadonlySet<string>;
};

export type UseChatAgentDirectoryMapsResult = {
  agentsById: Map<string, AgentInstance>;
  agentsByCode: Map<string, AgentInstance>;
  archiveVisibleAgents: AgentInstance[];
  chatMentionTargets: ChatMentionTarget[];
  resolveConversationTurnAvatar: (message: ConversationMessage) => TurnAvatarResolution | undefined;
};

export function useChatAgentDirectoryMaps({
  agents,
  pendingArchiveAgentIds,
}: UseChatAgentDirectoryMapsInput): UseChatAgentDirectoryMapsResult {
  const agentsById = useMemo(() => buildAgentsById(agents), [agents]);
  const agentsByCode = useMemo(() => buildAgentsByCode(agents), [agents]);
  const archiveVisibleAgents = useMemo(
    () => buildArchiveVisibleAgents(agents, pendingArchiveAgentIds),
    [agents, pendingArchiveAgentIds],
  );

  const resolveConversationTurnAvatar = useCallback((message: ConversationMessage): TurnAvatarResolution | undefined => {
    if (!isAgentInboxMessage(message)) {
      return undefined;
    }
    const metadata = message.metadata;
    const sourceAgentId = conversationMetadataText(metadata, "sourceAgentId");
    const sourceAgentCode = conversationMetadataText(metadata, "sourceAgentCode");
    const sourceAgentName = conversationMetadataText(metadata, "sourceAgentName");
    const agent =
      (sourceAgentId ? agentsById.get(sourceAgentId) : undefined)
      ?? (sourceAgentCode ? agentsByCode.get(sourceAgentCode) : undefined);
    return {
      imageUrl: avatarImageUrlFrom(agent),
      fallback: avatarInitials(sourceAgentCode, sourceAgentName),
    };
  }, [agentsByCode, agentsById]);

  const chatMentionTargets = useMemo(
    () => buildChatMentionTargets(archiveVisibleAgents),
    [archiveVisibleAgents],
  );

  return {
    agentsById,
    agentsByCode,
    archiveVisibleAgents,
    chatMentionTargets,
    resolveConversationTurnAvatar,
  };
}
