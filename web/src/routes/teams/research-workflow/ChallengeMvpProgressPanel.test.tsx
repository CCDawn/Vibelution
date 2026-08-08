/**
 * ChallengeMvpProgressPanel contracts:
 * - renders the read-only MVP summary (valid/validated/approved) and the
 *   validated-question rows with a detail action per question;
 * - surfaces empty and error states instead of faking results.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryState } from "./__testHelpers/mvpProgressQueryState";
import { ChallengeMvpProgressPanel } from "./ChallengeMvpProgressPanel";

vi.mock("@tanstack/react-query", () => ({ useQuery: () => queryState.current() }));

describe("ChallengeMvpProgressPanel", () => {
  afterEach(() => {
    queryState.reset();
  });

  it("renders summary counts and question rows with detail actions", () => {
    queryState.set({
      isPending: false,
      isError: false,
      error: null,
      data: {
        teamId: "team-1",
        storePath: "path",
        summary: {
          recordCount: 3,
          validCandidateCount: 2,
          validatedQuestionCount: 1,
          validatedQuestionIds: ["Q1"],
          validatedOutcomeCounts: { approved: 1 },
          validatedQuestionResults: [
            {
              questionId: "Q1",
              runId: "run-9",
              status: "approved",
              validation: { schemaValidation: "passed" },
              humanGates: { allApproved: true },
              outputSha256: "sha",
              artifactPath: "artifact",
            },
          ],
          completedCount: 1,
          completedQuestionIds: ["Q1"],
          latestCandidate: null,
        },
      },
      refetch: vi.fn(),
    });
    const onOpenQuestion = vi.fn();
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={onOpenQuestion} />,
    );
    expect(markup).toContain("MVP 验收进度");
    expect(markup).toContain("有效候选");
    expect(markup).toContain("2");
    expect(markup).toContain("已验证题");
    expect(markup).toContain("已批准");
    expect(markup).toContain("Q1");
    expect(markup).toContain("run-9");
    expect(markup).toContain("详情");
  });

  it("explains the empty validated-questions state", () => {
    queryState.set({
      isPending: false,
      isError: false,
      error: null,
      data: {
        teamId: "team-1",
        storePath: "path",
        summary: {
          recordCount: 0,
          validCandidateCount: 0,
          validatedQuestionCount: 0,
          validatedQuestionIds: [],
          validatedOutcomeCounts: {},
          validatedQuestionResults: [],
          completedCount: 0,
          completedQuestionIds: [],
          latestCandidate: null,
        },
      },
      refetch: vi.fn(),
    });
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("暂无已验证题目");
  });

  it("surfaces the load error with a retry action", () => {
    queryState.set({
      isPending: false,
      isError: true,
      error: new Error("question status unavailable"),
      data: undefined,
      refetch: vi.fn(),
    });
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("question status unavailable");
    expect(markup).toContain("重试");
  });
});
