import { beforeEach, expect, it, vi } from "vitest";
import { postBrowserTelemetry } from "../../app/browserTelemetry";
import { conversationStreamingFrameIdentity } from "../../components/conversation/conversationStreamingMetrics";
import { activeTurnLayerToConversationMessage, bindActiveTurnLayerToTurnId, type ActiveTurnLayerState } from "../chatActiveTurnLayer";
import { recordConversationStreamingFramePaint } from "./recordConversationStreamingFramePaint";

vi.mock("../../app/browserTelemetry", () => ({ postBrowserTelemetry: vi.fn() }));
beforeEach(() => vi.clearAllMocks());

function frame() {
  const layer: ActiveTurnLayerState = {
    id: "active", sessionId: "session", turnId: "turn", updatedAt: "", status: "running",
    turnItems: [], ledgerSeq: 10,
    clientDeltaTiming: { turnId: "turn", ledgerSeq: 10, appliedAtMs: 100 },
  };
  const metrics = {
    sessionId: "session", paintedAtMs: 125, streamingMessageCount: 1, renderedTextLength: 0, scrollSignal: "stream",
    ...conversationStreamingFrameIdentity(activeTurnLayerToConversationMessage(layer)),
  };
  return {
    layer,
    input: {
      metrics, activeSessionId: "session", activeTurnLayersBySessionRef: { current: { session: layer } },
      paintedRunningToolIdsBySessionRef: { current: {} }, firstPaintedRunningToolAtBySessionRef: { current: {} },
      lastConversationStreamingFrameTelemetryAtRef: { current: {} },
      lastAssistantDeltaAppliedAtRef: { current: { session: -3_887_000 } },
    },
  };
}

function fields() { return vi.mocked(postBrowserTelemetry).mock.calls.at(-1)?.[0].fields; }

it("measures the rendered frame and ignores an old session timestamp", () => {
  const { input } = frame();
  recordConversationStreamingFramePaint(input);
  expect(fields()).toMatchObject({ turnId: "turn", ledgerSeq: 10, applyToPaintObserved: true, applyToPaintMs: 25 });
});

it.each(["session", "turn", "sequence"])("rejects a stale painted %s", mismatch => {
  const { input } = frame();
  if (mismatch === "session") input.metrics.sessionId = "old-session";
  if (mismatch === "turn") input.metrics.turnId = "old-turn";
  if (mismatch === "sequence") input.metrics.ledgerSeq = 9;
  recordConversationStreamingFramePaint(input);
  expect(postBrowserTelemetry).not.toHaveBeenCalled();
});

it("does not invent zero latency for a frame without its own delta anchor", () => {
  const { input, layer } = frame();
  delete layer.clientDeltaTiming;
  recordConversationStreamingFramePaint(input);
  expect(fields()).toMatchObject({ applyToPaintObserved: false });
  expect(fields()).not.toHaveProperty("applyToPaintMs");
  expect(fields()).not.toHaveProperty("lastAssistantDeltaAppliedAtMs");
});

it("does not carry a timing anchor across optimistic turn-id rebinding", () => {
  const { layer, input } = frame();
  const rebound = bindActiveTurnLayerToTurnId(layer, "new-turn")!;
  input.activeTurnLayersBySessionRef.current.session = rebound;
  input.metrics = { ...input.metrics, ...conversationStreamingFrameIdentity(activeTurnLayerToConversationMessage(rebound)) };
  recordConversationStreamingFramePaint(input);
  expect(fields()).toMatchObject({ turnId: "new-turn", applyToPaintObserved: false });
  expect(fields()).not.toHaveProperty("applyToPaintMs");
});

it.each([NaN, Infinity, 200])("omits invalid or future timing anchors (%s)", appliedAtMs => {
  const { layer, input } = frame();
  layer.clientDeltaTiming!.appliedAtMs = appliedAtMs;
  input.metrics.assistantDeltaAppliedAtMs = appliedAtMs;
  recordConversationStreamingFramePaint(input);
  expect(fields()).not.toHaveProperty("applyToPaintMs");
});

it("reports the first paint once, including when the event was initially throttled", () => {
  const { input } = frame();
  input.lastConversationStreamingFrameTelemetryAtRef.current = { session: Date.now() };
  recordConversationStreamingFramePaint(input);
  expect(postBrowserTelemetry).not.toHaveBeenCalled();
  input.lastConversationStreamingFrameTelemetryAtRef.current = {};
  input.metrics.paintedAtMs = 5000;
  recordConversationStreamingFramePaint(input);
  expect(fields()).toMatchObject({ applyToPaintMs: 25 });
  input.lastConversationStreamingFrameTelemetryAtRef.current = {};
  recordConversationStreamingFramePaint(input);
  expect(fields()).toMatchObject({ applyToPaintObserved: false });
  expect(fields()).not.toHaveProperty("applyToPaintMs");
});
