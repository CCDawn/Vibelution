import { useContext, useEffect, useMemo } from "react";
import type { ConversationMessage } from "../../api/types";
import { projectActiveTurnLayerMessage } from "../chatActiveTurnLayer";
import { useActiveTurnLayerForSession } from "../chat/activeTurnLayersStore";
import { FinancialResearchBridgeContext } from "./FinancialResearchBridge";

/** Subscribe at the presentation edge; never stream a second transcript. */
export function FinancialResearchLiveProjection({ sessionId, agentId, messages }: { sessionId: string; agentId?: string; messages: ConversationMessage[] }) {
  const bridge = useContext(FinancialResearchBridgeContext);
  const layer = useActiveTurnLayerForSession(sessionId);
  const message = useMemo(() => projectActiveTurnLayerMessage(layer, messages), [layer, messages]);
  const publish = bridge?.onActiveTurn;
  useEffect(() => {
    if (agentId === bridge?.agentId && sessionId) publish?.(sessionId, message?.role === "assistant" ? message : null);
  }, [agentId, bridge?.agentId, message, publish, sessionId]);
  return null;
}
