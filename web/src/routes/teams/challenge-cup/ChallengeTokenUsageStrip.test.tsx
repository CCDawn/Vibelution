import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChallengeQuestionTokenUsage, ChallengeTokenUsageStrip } from "./ChallengeTokenUsageStrip";
import { tokenUsageCountLabel, type TokenUsageOverview } from "./challengeTokenUsageModel";

const overview: TokenUsageOverview = {
  schemaVersion: 1,
  teamId: "team-1",
  generatedAt: "2026-08-20T00:00:00Z",
  unit: "tokens",
  priced: false,
  program: { totalTokens: 52, callCount: 3, inputTokens: 40, outputTokens: 12 },
  questions: [
    {
      questionId: "SCI-001",
      totalTokens: 40,
      callCount: 1,
      inputTokens: 30,
      outputTokens: 10,
      stages: [{ stageId: "hypothesis_design", totalTokens: 40, callCount: 1 }],
      anomaly: { stageId: "hypothesis_design", message: "hypothesis_design token 消耗超过同阶段中位数 3 倍" },
    },
  ],
};

describe("ChallengeTokenUsageStrip", () => {
  it("renders token counts and never invents an amount", () => {
    const markup = renderToStaticMarkup(
      <ChallengeTokenUsageStrip
        totalTokens={overview.program.totalTokens}
        callCount={overview.program.callCount}
        inputTokens={overview.program.inputTokens}
        outputTokens={overview.program.outputTokens}
      />,
    );
    expect(markup).toContain("token 计");
    expect(markup).toContain(tokenUsageCountLabel(52, 3, true));
    expect(markup).not.toContain("$");
    expect(markup).not.toContain("USD");
    expect(markup).not.toContain("totalCost");
  });

  it("shows the server anomaly message on the question collapse", () => {
    const markup = renderToStaticMarkup(
      <ChallengeQuestionTokenUsage usage={overview.questions[0] ?? null} />,
    );
    expect(markup).toContain("本题 token 消耗");
    expect(markup).toContain("hypothesis_design token 消耗超过同阶段中位数 3 倍");
    expect(markup).toContain("hypothesis_design: 40 token");
  });

  it("does not present zeroes while question usage is pending or unavailable", () => {
    const pendingMarkup = renderToStaticMarkup(
      <ChallengeQuestionTokenUsage usage={null} state="pending" />,
    );
    expect(pendingMarkup).toContain("读取中");
    expect(pendingMarkup).toContain("open=\"\"");
    expect(pendingMarkup).not.toContain("0 token");

    const errorMarkup = renderToStaticMarkup(
      <ChallengeQuestionTokenUsage usage={null} state="error" />,
    );
    expect(errorMarkup).toContain("不可用");
    expect(errorMarkup).toContain("open=\"\"");
    expect(errorMarkup).not.toContain("0 token");
  });

  it("shows zeroes only after a successful response with no row for the question", () => {
    const markup = renderToStaticMarkup(
      <ChallengeQuestionTokenUsage usage={null} state="success" />,
    );
    expect(markup).toContain("0 token");
    expect(markup).toContain("0 次调用");
  });
});
