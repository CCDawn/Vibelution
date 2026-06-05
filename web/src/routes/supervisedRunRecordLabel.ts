import { EvolutionRun } from "../api/types";

type RunRecordLanguage = "zh" | "en";

export type SupervisedRunRecordDisplay = {
  title: string;
  subtitle: string;
  timeLabel: string;
  sourceLabel: string;
  idLabel: string;
};

function clean(value: unknown): string {
  return String(value ?? "").trim();
}

function parseTimestampFromRunId(runId: string): Date | null {
  const match = clean(runId).match(/(?:^|_)(20\d{6})[_-](\d{6})(?:$|_)/);
  if (!match) {
    return null;
  }
  const [, datePart, timePart] = match;
  const year = Number(datePart.slice(0, 4));
  const month = Number(datePart.slice(4, 6));
  const day = Number(datePart.slice(6, 8));
  const hour = Number(timePart.slice(0, 2));
  const minute = Number(timePart.slice(2, 4));
  const second = Number(timePart.slice(4, 6));
  const parsed = new Date(year, month - 1, day, hour, minute, second);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed;
}

function parseRunTimestamp(run: Pick<EvolutionRun, "id" | "endedAt">): Date | null {
  const endedAt = clean(run.endedAt);
  if (endedAt) {
    const parsed = new Date(endedAt);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed;
    }
  }
  return parseTimestampFromRunId(run.id);
}

function formatRunTimestamp(run: Pick<EvolutionRun, "id" | "endedAt">, lang: RunRecordLanguage): string {
  const parsed = parseRunTimestamp(run);
  if (!parsed) {
    return lang === "zh" ? "时间未知" : "time unknown";
  }
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(parsed);
}

function sourceLabel(run: Pick<EvolutionRun, "bundleName" | "summary">, lang: RunRecordLanguage): string {
  const bundleName = clean(run.bundleName);
  if (bundleName) {
    return bundleName;
  }
  const summary = clean(run.summary);
  if (summary) {
    return summary;
  }
  return lang === "zh" ? "评测来源未知" : "unknown source";
}

export function buildSupervisedRunRecordDisplay(
  run: Pick<EvolutionRun, "id" | "endedAt" | "bundleName" | "summary" | "decision" | "status" | "baselineScore" | "candidateScore">,
  lang: RunRecordLanguage,
  labels: {
    statusLabel: (status: string) => string;
    decisionLabel: (decision: string) => string;
  },
): SupervisedRunRecordDisplay {
  const timeLabel = formatRunTimestamp(run, lang);
  const source = sourceLabel(run, lang);
  const decision = clean(run.decision);
  const status = clean(run.status);
  const decisionText = decision ? labels.decisionLabel(decision) : labels.statusLabel(status);
  const scoreText = `baseline ${run.baselineScore} / candidate ${run.candidateScore}`;
  return {
    title: `${timeLabel} · ${source}`,
    subtitle: `${decisionText || "--"} · ${scoreText}`,
    timeLabel,
    sourceLabel: source,
    idLabel: run.id,
  };
}
