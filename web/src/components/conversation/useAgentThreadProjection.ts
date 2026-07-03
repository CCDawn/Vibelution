import { useMemo, useRef } from "react";

import type { ConversationMessage } from "../../api/types";
import { conversationMessageToAgentMessage } from "../../agent-thread/adapters";
import type { AgentMessage, AgentThread } from "../../agent-thread/types";

export function useAgentThreadProjection(sessionId: string, messages: ConversationMessage[]): AgentThread {
  const agentMessageCacheRef = useRef<{
    messages: ConversationMessage[];
    agentMessages: AgentMessage[];
  }>({ messages: [], agentMessages: [] });

  return useMemo(() => {
    const previousMessages = agentMessageCacheRef.current.messages;
    const previousAgentMessages = agentMessageCacheRef.current.agentMessages;
    const agentMessages = messages.map((message, index) => {
      const previousAgentMessage = previousAgentMessages[index];
      if (previousMessages[index] === message && previousAgentMessage) {
        return previousAgentMessage;
      }
      return conversationMessageToAgentMessage(message);
    });
    agentMessageCacheRef.current = { messages, agentMessages };
    return {
      id: sessionId,
      source: { kind: "conversation-view", id: sessionId },
      status: agentMessages.some((message) => message.streaming) ? "streaming" : "idle",
      messages: agentMessages,
    };
  }, [messages, sessionId]);
}
