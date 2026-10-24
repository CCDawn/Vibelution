import { ACTIVITY_CONTRACT } from "../../api/generated/activityContract";
import { activityPhase } from "../sessionActivityState";

function decodeJsonFragment(raw: string): string {
  try {
    return JSON.parse(`"${raw}"`) as string;
  } catch {
    return raw
      .replace(/\\u([0-9a-fA-F]{4})/g, (_, hex: string) => String.fromCharCode(parseInt(hex, 16)))
      .replace(/\\n/g, " ")
      .replace(/\\r/g, " ")
      .replace(/\\t/g, " ")
      .replace(/\\"/g, '"')
      .replace(/\\\\/g, "\\");
  }
}

/**
 * Best-effort conclusion from a structured summary truncated before the JSON
 * closes. Returns the decoded conclusion plus an ellipsis when the string was
 * cut, or "" when the payload has no readable conclusion.
 */
function truncatedConclusion(text: string): string {
  const match = /"conclusion"\s*:\s*"((?:[^"\\]|\\.)*)("?)/.exec(text);
  if (!match) return "";
  const value = decodeJsonFragment(match[1]).trim();
  if (!value) return "";
  return match[2] ? value : `${value}…`;
}

/** Display projection only; preserve ordinary summaries and unknown payloads. */
export function agentRunSummary(summary: string | undefined): string {
  const text = summary || "";
  if (!text.trimStart().startsWith("{")) return text;
  try {
    const payload = JSON.parse(text);
    // The same display contract used by ChatGroupMessagePresentation.
    if (payload?.schemaVersion === 1 && typeof payload.display?.conclusion === "string") {
      return payload.display.conclusion.trim() || text;
    }
  } catch {
    // Backend summaries are length-capped, so structured payloads often arrive
    // truncated and unparsable; fall back to the readable conclusion slice.
    const conclusion = truncatedConclusion(text);
    if (conclusion) return conclusion;
  }
  return text;
}

function lookup(table: Readonly<Record<string, string>>, value: string): string {
  return Object.prototype.hasOwnProperty.call(table, value) ? table[value] : "";
}

export function agentRunStatusLabel(status: string | undefined, lang: "zh" | "en"): string {
  const value = String(status ?? "").trim().toLowerCase();
  const contract = ACTIVITY_CONTRACT.agentRun;
  const normalized = lookup(contract.labels, value) ? value : lookup(contract.aliases, value) || "unknown";
  return lookup(lang === "zh" ? contract.labels : contract.labelsEn, normalized);
}

export function agentRunPhaseLabel(value: string | undefined, lang: "zh" | "en"): string {
  const phase = activityPhase(value);
  return lookup(lang === "zh" ? ACTIVITY_CONTRACT.session.phaseLabels : ACTIVITY_CONTRACT.session.phaseLabelsEn, phase);
}

export function agentRunReasonLabel(value: string | undefined, lang: "zh" | "en"): string {
  if (!value) return "";
  const reason = value.trim().toLowerCase();
  return lang === "zh"
    ? lookup(ACTIVITY_CONTRACT.agentRun.reasonLabels, reason) || agentRunStatusLabel(reason, lang)
    : lookup(ACTIVITY_CONTRACT.agentRun.reasonLabelsEn, reason) || agentRunStatusLabel(reason, lang);
}
