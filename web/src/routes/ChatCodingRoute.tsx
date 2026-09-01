import { ChatCodingRouteWorkbench } from "./chat/ChatCodingRouteWorkbench";
import { CompanionChatRouteGate } from "./companions/CompanionChatRouteGate";

/** Companion routes prove the Agent/Session binding before Chat mounts. */
export function ChatCodingRoute() {
  return (
    <CompanionChatRouteGate>
      <ChatCodingRouteWorkbench />
    </CompanionChatRouteGate>
  );
}

export type { CliAgentRunView, CliAgentTerminalSession } from "./chat/cliAgentRunModel";
export { canInputTerminal } from "./chat/cliAgentRunModel";
