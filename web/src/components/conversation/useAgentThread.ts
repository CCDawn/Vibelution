import { useMemo } from "react";

import type { AgentMessage, AgentThread } from "../../agent-thread/types";

export function useAgentThread(sessionId: string, agentMessages: AgentMessage[]): AgentThread {
  return useMemo(() => {
    return {
      id: sessionId,
      source: { kind: "conversation-view", id: sessionId },
      status: agentMessages.some((message) => message.streaming) ? "streaming" : "idle",
      messages: agentMessages,
    };
  }, [agentMessages, sessionId]);
}
