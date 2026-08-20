export type TokenUsageAnomaly = {
  stageId: string;
  message: string;
};

export type TokenUsageStage = {
  stageId: string;
  totalTokens: number;
  callCount: number;
};

export type TokenUsageQuestion = {
  questionId: string;
  totalTokens: number;
  callCount: number;
  inputTokens: number;
  outputTokens: number;
  stages: TokenUsageStage[];
  anomaly: TokenUsageAnomaly | null;
};

export type TokenUsageOverview = {
  schemaVersion: number;
  teamId: string;
  generatedAt: string;
  unit: "tokens";
  priced: boolean;
  program: {
    totalTokens: number;
    callCount: number;
    inputTokens: number;
    outputTokens: number;
  };
  questions: TokenUsageQuestion[];
};

export function isTokenUsageOverview(value: unknown): value is TokenUsageOverview {
  if (!value || typeof value !== "object") return false;
  const record = value as TokenUsageOverview;
  return record.unit === "tokens" && Array.isArray(record.questions) && Boolean(record.program);
}

export function questionTokenUsage(
  overview: TokenUsageOverview | null | undefined,
  questionId: string,
): TokenUsageQuestion | null {
  if (!overview) return null;
  return overview.questions.find((row) => row.questionId === questionId) ?? null;
}

export function tokenUsageCountLabel(
  totalTokens: number,
  callCount: number,
  zh: boolean,
): string {
  return zh
    ? `${totalTokens} token · ${callCount} 次调用 · token 计`
    : `${totalTokens} tokens · ${callCount} calls · token-counted`;
}
