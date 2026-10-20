import { useEffect, useMemo, useRef, useState } from "react";
import { ConversationTokenSpeedIndicator } from "../../components/conversation/ConversationTokenSpeedIndicator";
import { estimateGeneratedTokens, tokenSpeedTextFromLayer, tokenSpeedValueAt, updateTokenSpeedTracker, type TokenSpeedTrackerState } from "../chatTokenSpeed";
import { useActiveTurnLayerForSession } from "./activeTurnLayersStore";

export function ChatTokenSpeedIndicator({ sessionId, lang, disconnected = false }: {
  sessionId: string;
  lang: "zh" | "en";
  disconnected?: boolean;
}) {
  const layer = useActiveTurnLayerForSession(sessionId);
  const output = useMemo(() => disconnected ? null : tokenSpeedTextFromLayer(layer), [layer, disconnected]);
  const [tracker, setTracker] = useState<TokenSpeedTrackerState | null>(null);
  const previousOutput = useRef<typeof output>(null);
  const initialLayer = useRef(layer);
  const receivedFreshLayer = useRef(false);
  const [now, setNow] = useState(() => performance.now());

  useEffect(() => {
    if (disconnected) {
      initialLayer.current = layer;
      receivedFreshLayer.current = false;
    }
    // A remounted/reconnected subscriber may see cached pre-disconnect text.
    // Wait for a fresh store frame and baseline that frame before measuring.
    if (!receivedFreshLayer.current && layer !== initialLayer.current) receivedFreshLayer.current = true;
    if (disconnected || !receivedFreshLayer.current) {
      previousOutput.current = null;
      setTracker(null);
      return;
    }
    const previous = previousOutput.current;
    previousOutput.current = output;
    const timestampMs = performance.now();
    setTracker(current => updateTokenSpeedTracker(
      previous && output && output.key === previous.key && output.text.startsWith(previous.text) ? current : null,
      output ? { sessionId, messageId: output.key, tokenCount: estimateGeneratedTokens(output.text), timestampMs } : null,
    ));
    setNow(timestampMs);
  }, [output, sessionId, disconnected, layer]);

  useEffect(() => {
    if (!output) return;
    const timer = window.setInterval(() => setNow(performance.now()), 500);
    return () => window.clearInterval(timer);
  }, [Boolean(output)]);

  const speed = output && tracker?.sessionId === sessionId && tracker.messageId === output.key
    ? tokenSpeedValueAt(tracker, now) : null;
  return <ConversationTokenSpeedIndicator tokensPerSecond={speed} lang={lang} />;
}
