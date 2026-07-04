import type { AgentMentalPart, AgentMentalSnapshot } from "../../agent-thread/types";
import type { AgentMessageProcessSection } from "./agentMessageSections";

export type MentalStateRow = {
  label: string;
  value: string;
};

export type MentalStateLabels = {
  feeling: string;
  summary: string;
  feelingSummary: string;
  mood: string;
  cognitiveState: string;
  source: string;
  confidence: string;
  samples: string;
  lastUpdated: string;
  whisper: string;
  intervention: string;
  cognitiveStateUnknown: string;
  cognitiveStateNormal: string;
  cognitiveStateProductive: string;
  cognitiveStateLooping: string;
  cognitiveStateThrashing: string;
  cognitiveStateTunnelVision: string;
  cognitiveStateDisoriented: string;
  sourceState: string;
  sourceDiagnosis: string;
  sourceRuntime: string;
};

export type MentalStateFormatters = {
  compactPreview: (value: string) => string;
  formatTimestamp: (timestamp: string) => string;
};

type CognitiveStateLabelKey =
  | "cognitiveStateUnknown"
  | "cognitiveStateNormal"
  | "cognitiveStateProductive"
  | "cognitiveStateLooping"
  | "cognitiveStateThrashing"
  | "cognitiveStateTunnelVision"
  | "cognitiveStateDisoriented";

const COGNITIVE_STATE_LABEL_BY_VALUE: Record<string, CognitiveStateLabelKey> = {
  unknown: "cognitiveStateUnknown",
  normal: "cognitiveStateNormal",
  productive: "cognitiveStateProductive",
  looping: "cognitiveStateLooping",
  thrashing: "cognitiveStateThrashing",
  tunnel_vision: "cognitiveStateTunnelVision",
  disoriented: "cognitiveStateDisoriented",
};

type MentalSourceLabelKey = "sourceState" | "sourceDiagnosis" | "sourceRuntime";

const MENTAL_SOURCE_LABEL_BY_VALUE: Record<string, MentalSourceLabelKey> = {
  state: "sourceState",
  diagnosis: "sourceDiagnosis",
  runtime: "sourceRuntime",
};

export function cognitiveStateLabel(
  snapshot: AgentMentalSnapshot | undefined,
  labels: Pick<MentalStateLabels, CognitiveStateLabelKey>,
) {
  const value = String(snapshot?.cognitiveState ?? "").trim().toLowerCase() || "unknown";
  const key = COGNITIVE_STATE_LABEL_BY_VALUE[value];
  return key ? labels[key] : snapshot?.cognitiveState ?? "";
}

export function mentalSourceLabel(
  source: string | undefined,
  labels: Pick<MentalStateLabels, MentalSourceLabelKey>,
) {
  const value = String(source ?? "").trim().toLowerCase();
  const key = MENTAL_SOURCE_LABEL_BY_VALUE[value];
  return key ? labels[key] : source ?? "";
}

export function mentalSnapshotPreview(
  snapshot: AgentMentalSnapshot | undefined,
  labels: Pick<MentalStateLabels, CognitiveStateLabelKey>,
  formatters: Pick<MentalStateFormatters, "compactPreview">,
) {
  if (!snapshot) {
    return "";
  }
  const preview = [
    snapshot.feeling,
    snapshot.summary,
    snapshot.whisper,
    snapshot.intervention,
    snapshot.cognitiveState ? cognitiveStateLabel(snapshot, labels) : "",
  ].map((item) => String(item ?? "").trim()).find(Boolean) ?? "";

  return formatters.compactPreview(preview);
}

export function mentalFeelingSummaryRow(
  snapshot: AgentMentalSnapshot | undefined,
  labels: Pick<MentalStateLabels, "feeling" | "summary" | "feelingSummary">,
): MentalStateRow | null {
  const feeling = String(snapshot?.feeling ?? "").trim();
  const summary = String(snapshot?.summary ?? "").trim();
  if (!feeling && !summary) {
    return null;
  }
  if (!summary || feeling === summary) {
    return { label: labels.feeling, value: feeling || summary };
  }
  if (!feeling) {
    return { label: labels.summary, value: summary };
  }
  return { label: labels.feelingSummary, value: `${feeling}\n${summary}` };
}

export function buildMentalMetaRows(
  snapshot: AgentMentalSnapshot | undefined,
  labels: Pick<MentalStateLabels,
    | "mood"
    | "cognitiveState"
    | "source"
    | "confidence"
    | "samples"
    | "lastUpdated"
    | CognitiveStateLabelKey
    | MentalSourceLabelKey
  >,
  formatters: Pick<MentalStateFormatters, "formatTimestamp">,
): MentalStateRow[] {
  if (!snapshot) {
    return [];
  }
  return [
    snapshot.mood ? { label: labels.mood, value: snapshot.mood } : null,
    snapshot.cognitiveState ? { label: labels.cognitiveState, value: cognitiveStateLabel(snapshot, labels) } : null,
    snapshot.source ? { label: labels.source, value: mentalSourceLabel(snapshot.source, labels) } : null,
    Number.isFinite(snapshot.confidence) && Number(snapshot.confidence) > 0
      ? { label: labels.confidence, value: `${Math.round(Number(snapshot.confidence) * 100)}%` }
      : null,
    Number(snapshot.sampleSize) > 0 ? { label: labels.samples, value: String(snapshot.sampleSize) } : null,
    snapshot.updatedAt ? { label: labels.lastUpdated, value: formatters.formatTimestamp(snapshot.updatedAt) } : null,
  ].filter((row): row is MentalStateRow => Boolean(row));
}

export function buildMentalBodyRows(
  snapshot: AgentMentalSnapshot | undefined,
  labels: Pick<MentalStateLabels, "feeling" | "summary" | "feelingSummary" | "whisper" | "intervention">,
): MentalStateRow[] {
  if (!snapshot) {
    return [];
  }
  return [
    mentalFeelingSummaryRow(snapshot, labels),
    snapshot.whisper ? { label: labels.whisper, value: snapshot.whisper } : null,
    snapshot.intervention ? { label: labels.intervention, value: snapshot.intervention } : null,
  ].filter((row): row is MentalStateRow => Boolean(row));
}

export function latestAgentMentalPart(sections: AgentMessageProcessSection[]): AgentMentalPart | undefined {
  return sections
    .flatMap((section) => section.parts)
    .filter((part): part is AgentMentalPart => part.type === "mental")
    .at(-1);
}
