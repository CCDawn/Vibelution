import { postBrowserTelemetry } from "./browserTelemetry";
import { getPageInstanceId } from "./pageInstance";

export type ChatStartupMilestone = "dataReady" | "transcriptPresented" | "composerReady";

type Measurement = {
  pageInstanceId: string;
  sessionId: string;
  milestones: Partial<Record<ChatStartupMilestone, number>>;
  interactiveReported: boolean;
};

// One initial native-session target per document. A later session switch must
// never complete an earlier session's startup measurement.
let measurement: Measurement | undefined;

export function chatStartupCorrelationFields(sessionId: string) {
  return {
    measurementVersion: 2,
    pageInstanceId: getPageInstanceId(),
    navigationTimeOriginMs: performance.timeOrigin,
    sessionId,
  };
}

export function recordChatStartupMilestone(
  sessionId: string,
  milestone: ChatStartupMilestone,
  observedAtMs = performance.now(),
) {
  if (!sessionId || !Number.isFinite(observedAtMs) || observedAtMs < 0) return;
  const pageInstanceId = getPageInstanceId();
  if (!measurement || measurement.pageInstanceId !== pageInstanceId) {
    measurement = { pageInstanceId, sessionId, milestones: {}, interactiveReported: false };
  }
  if (measurement.sessionId !== sessionId || measurement.milestones[milestone] !== undefined) return;
  measurement.milestones[milestone] = observedAtMs;
  const correlation = chatStartupCorrelationFields(sessionId);
  const markName = {
    dataReady: "data_ready", transcriptPresented: "transcript_presented", composerReady: "composer_ready",
  }[milestone];
  performance.mark(`vibelution.chat.startup.${markName}`, { startTime: observedAtMs, detail: correlation });
  if (milestone !== "dataReady") {
    postBrowserTelemetry({
      phase: "navigation",
      eventCode: milestone === "transcriptPresented"
        ? "browser.chat_route.startup_transcript_presented"
        : "browser.chat_route.startup_composer_ready",
      message: milestone === "transcriptPresented"
        ? "The native session transcript has a visible frame after an animation-frame boundary."
        : "The native session composer is visible and editable after an animation-frame boundary.",
      fields: { ...correlation, observedAtMs, presentationMethod: "visible_dom_after_animation_frame" },
    });
  }
  const { dataReady, transcriptPresented, composerReady } = measurement.milestones;
  if (measurement.interactiveReported || dataReady === undefined
    || transcriptPresented === undefined || composerReady === undefined) return;
  measurement.interactiveReported = true;
  const interactiveMs = Math.max(dataReady, transcriptPresented, composerReady);
  const fields = {
    ...correlation,
    dataReadyMs: dataReady,
    transcriptPresentedMs: transcriptPresented,
    composerReadyMs: composerReady,
    interactiveMs,
    dataReadyToInteractiveMs: interactiveMs - dataReady,
    presentationMethod: "visible_dom_after_animation_frame",
  };
  performance.mark("vibelution.chat.startup.interactive", { startTime: interactiveMs, detail: fields });
  postBrowserTelemetry({
    phase: "navigation",
    eventCode: "browser.chat_route.startup_interactive",
    message: "Native session data, visible transcript frame, and editable composer are ready.",
    fields,
  });
}
