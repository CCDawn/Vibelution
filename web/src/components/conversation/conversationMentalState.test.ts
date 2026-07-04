import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import type { AgentMentalSnapshot } from "../../agent-thread/types";
import type { AgentMessageProcessSection } from "./agentMessageSections";
import {
  buildMentalBodyRows,
  buildMentalMetaRows,
  cognitiveStateLabel,
  latestAgentMentalPart,
  mentalFeelingSummaryRow,
  mentalSourceLabel,
  mentalSnapshotPreview,
  type MentalStateFormatters,
  type MentalStateLabels,
} from "./conversationMentalState";

const labels: MentalStateLabels = {
  feeling: "Feeling",
  summary: "Summary",
  feelingSummary: "Feeling / Summary",
  mood: "Mood",
  cognitiveState: "Cognitive state",
  source: "Source",
  confidence: "Confidence",
  samples: "Samples",
  lastUpdated: "Last updated",
  whisper: "Whisper",
  intervention: "Intervention",
  cognitiveStateUnknown: "Unclassified",
  cognitiveStateNormal: "Stable",
  cognitiveStateProductive: "Productive",
  cognitiveStateLooping: "Looping",
  cognitiveStateThrashing: "Thrashing",
  cognitiveStateTunnelVision: "Tunnel vision",
  cognitiveStateDisoriented: "Disoriented",
  sourceState: "Live state",
  sourceDiagnosis: "Rule diagnosis",
  sourceRuntime: "Runtime",
};

const formatters: MentalStateFormatters = {
  compactPreview: (value) => `compact:${value}`,
  formatTimestamp: (timestamp) => `time:${timestamp}`,
};

function mentalSnapshot(overrides: Partial<AgentMentalSnapshot> = {}): AgentMentalSnapshot {
  return {
    mood: "",
    feeling: "",
    whisper: "",
    summary: "",
    cognitiveState: "",
    confidence: 0,
    sampleSize: 0,
    interventionCount: 0,
    updatedAt: "",
    source: "",
    ...overrides,
  };
}

describe("conversation mental state helpers", () => {
  it("keeps mental-state pure helpers out of ConversationView", () => {
    const source = readFileSync(new URL("./ConversationView.tsx", import.meta.url), "utf8");

    expect(source).toContain('from "./conversationMentalState"');
    expect(source).not.toMatch(/function mentalSnapshotPreview\(/);
    expect(source).not.toMatch(/function mentalFeelingSummaryRow\(/);
    expect(source).not.toMatch(/function latestAgentMentalPart\(/);
    expect(source).not.toMatch(/\bcognitiveStateLabel\b/);
    expect(source).not.toMatch(/\bmentalSourceLabel\b/);
  });

  it("labels cognitive state values inside the mental-state helper boundary", () => {
    expect(cognitiveStateLabel(undefined, labels)).toBe("Unclassified");
    expect(cognitiveStateLabel(mentalSnapshot({ cognitiveState: "normal" }), labels)).toBe("Stable");
    expect(cognitiveStateLabel(mentalSnapshot({ cognitiveState: " productive " }), labels)).toBe("Productive");
    expect(cognitiveStateLabel(mentalSnapshot({ cognitiveState: "tunnel_vision" }), labels)).toBe("Tunnel vision");
    expect(cognitiveStateLabel(mentalSnapshot({ cognitiveState: "custom_state" }), labels)).toBe("custom_state");
  });

  it("labels mental source values inside the mental-state helper boundary", () => {
    expect(mentalSourceLabel(undefined, labels)).toBe("");
    expect(mentalSourceLabel("state", labels)).toBe("Live state");
    expect(mentalSourceLabel("diagnosis", labels)).toBe("Rule diagnosis");
    expect(mentalSourceLabel("runtime", labels)).toBe("Runtime");
    expect(mentalSourceLabel("custom", labels)).toBe("custom");
  });

  it("builds collapsed previews from the first available mental snapshot field", () => {
    expect(mentalSnapshotPreview(undefined, labels, formatters)).toBe("");
    expect(mentalSnapshotPreview(mentalSnapshot({ feeling: " calm ", summary: "ignored" }), labels, formatters))
      .toBe("compact:calm");
    expect(mentalSnapshotPreview(mentalSnapshot({ summary: " ready " }), labels, formatters)).toBe("compact:ready");
    expect(mentalSnapshotPreview(mentalSnapshot({ cognitiveState: "productive" }), labels, formatters))
      .toBe("compact:Productive");
  });

  it("builds the feeling and summary row without duplicating identical content", () => {
    expect(mentalFeelingSummaryRow(undefined, labels)).toBeNull();
    expect(mentalFeelingSummaryRow(mentalSnapshot({ feeling: " steady " }), labels))
      .toEqual({ label: "Feeling", value: "steady" });
    expect(mentalFeelingSummaryRow(mentalSnapshot({ summary: "ready" }), labels))
      .toEqual({ label: "Summary", value: "ready" });
    expect(mentalFeelingSummaryRow(mentalSnapshot({ feeling: "same", summary: "same" }), labels))
      .toEqual({ label: "Feeling", value: "same" });
    expect(mentalFeelingSummaryRow(mentalSnapshot({ feeling: "uneasy", summary: "needs input" }), labels))
      .toEqual({ label: "Feeling / Summary", value: "uneasy\nneeds input" });
  });

  it("builds mental metadata rows with helper-owned semantic labels", () => {
    expect(buildMentalMetaRows(mentalSnapshot(), labels, formatters)).toEqual([]);
    expect(buildMentalMetaRows(
      mentalSnapshot({
        mood: "focused",
        cognitiveState: "productive",
        source: "runtime",
        confidence: 0.724,
        sampleSize: 5,
        updatedAt: "2026-07-04T01:02:03Z",
      }),
      labels,
      formatters,
    )).toEqual([
      { label: "Mood", value: "focused" },
      { label: "Cognitive state", value: "Productive" },
      { label: "Source", value: "Runtime" },
      { label: "Confidence", value: "72%" },
      { label: "Samples", value: "5" },
      { label: "Last updated", value: "time:2026-07-04T01:02:03Z" },
    ]);
  });

  it("builds mental body rows from feeling summary, whisper, and intervention", () => {
    expect(buildMentalBodyRows(
      mentalSnapshot({
        feeling: "curious",
        summary: "tracking the task",
        whisper: "check the boundary",
        intervention: "slow down",
      }),
      labels,
    )).toEqual([
      { label: "Feeling / Summary", value: "curious\ntracking the task" },
      { label: "Whisper", value: "check the boundary" },
      { label: "Intervention", value: "slow down" },
    ]);
  });

  it("selects the latest mental part from process sections", () => {
    const sections: AgentMessageProcessSection[] = [
      {
        id: "process-a",
        kind: "process",
        parts: [
          { id: "thought-a", type: "thought", text: "thinking", status: "done" },
          { id: "mental-a", type: "mental", status: "done", summary: "older" },
        ],
      },
      {
        id: "process-b",
        kind: "process",
        parts: [
          { id: "mental-b", type: "mental", status: "done", summary: "newer" },
        ],
      },
    ];

    expect(latestAgentMentalPart(sections)?.id).toBe("mental-b");
  });
});
