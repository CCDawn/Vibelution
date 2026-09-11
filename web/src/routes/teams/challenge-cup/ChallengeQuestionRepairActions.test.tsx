import React from "react";
/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import { queryKeys } from "../../../api/queryKeys";
import { ChallengeQuestionRepairActions } from "./ChallengeQuestionRepairActions";

const reverifyMock = vi.hoisted(() => vi.fn(async () => ({
  status: "reverified",
  record: {},
  verification: { verifiedSourceUrls: {}, attemptedCount: 0, verifiedCount: 0 },
})));
const repairMock = vi.hoisted(() => vi.fn(async () => ({
  teamId: "research-team",
  questionId: "SCI-096",
  runId: "stage1-sci-096-v3",
  repaired: true,
  officialModelCall: true,
  record: {},
})));

vi.mock("../../../api/challengeQuestionRuns", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  reverifyChallengeQuestionCitations: reverifyMock,
  repairChallengeQuestionRegistration: repairMock,
}));

function repairDetail(validation: Record<string, unknown>): ChallengeQuestionRunDetailPayload {
  return {
    teamId: "research-team",
    questionId: "SCI-096",
    selectedRunId: "stage1-sci-096-v3",
    record: {
      recordId: "record-sci-096",
      questionId: "SCI-096",
      runId: "stage1-sci-096-v3",
      status: "pending_review",
      validation,
    },
    output: {},
    runs: [],
    artifact: { path: "p", sha256: "a", immutable: true },
  } as unknown as ChallengeQuestionRunDetailPayload;
}

function findButton(scope: ParentNode, testId: string): HTMLButtonElement | undefined {
  return scope.querySelector(`button[data-testid="${testId}"]`) as HTMLButtonElement | undefined;
}

async function renderActions(detail: ChallengeQuestionRunDetailPayload) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const client = new QueryClient();
  const invalidateSpy = vi.spyOn(client, "invalidateQueries").mockResolvedValue(undefined as never);
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <ChallengeQuestionRepairActions detail={detail} lang="zh" />
      </QueryClientProvider>,
    );
  });
  return { container, root, invalidateSpy };
}

describe("ChallengeQuestionRepairActions", () => {
  beforeEach(() => {
    reverifyMock.mockClear();
    repairMock.mockClear();
  });

  it("offers both repairs for a record whose citation and official-call gates failed", async () => {
    const { container, root } = await renderActions(repairDetail({
      citationValidation: "failed",
      officialModelCall: false,
    }));

    expect(findButton(container, "challenge-question-reverify-citations")).toBeTruthy();
    expect(findButton(container, "challenge-question-repair-registration")).toBeTruthy();

    await act(async () => root.unmount());
    container.remove();
  });

  it("hides both repairs once citations passed and the official call is recorded", async () => {
    const { container, root } = await renderActions(repairDetail({
      citationValidation: "passed",
      officialModelCall: true,
    }));

    expect(findButton(container, "challenge-question-reverify-citations")).toBeNull();
    expect(findButton(container, "challenge-question-repair-registration")).toBeNull();

    await act(async () => root.unmount());
    container.remove();
  });

  it("reverifies citations through the sanctioned endpoint and refetches the result", async () => {
    const { container, root, invalidateSpy } = await renderActions(repairDetail({
      citationValidation: "failed",
      officialModelCall: true,
    }));

    const button = findButton(container, "challenge-question-reverify-citations");
    expect(button).toBeTruthy();
    await act(async () => {
      button!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(reverifyMock).toHaveBeenCalledTimes(1);
    expect(reverifyMock).toHaveBeenCalledWith("research-team", "SCI-096", "stage1-sci-096-v3");
    expect(repairMock).not.toHaveBeenCalled();
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.challengeQuestionRunDetail("research-team", "SCI-096"),
    });

    await act(async () => root.unmount());
    container.remove();
  });

  it("repairs the result-package registration and refetches the result", async () => {
    const { container, root, invalidateSpy } = await renderActions(repairDetail({
      officialModelCall: false,
    }));

    const button = findButton(container, "challenge-question-repair-registration");
    expect(button).toBeTruthy();
    await act(async () => {
      button!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(repairMock).toHaveBeenCalledTimes(1);
    expect(repairMock).toHaveBeenCalledWith("research-team", "SCI-096", "stage1-sci-096-v3");
    expect(reverifyMock).not.toHaveBeenCalled();
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.challengeQuestionRunDetail("research-team", "SCI-096"),
    });

    await act(async () => root.unmount());
    container.remove();
  });

  it("keeps the run record untouched and reports the failure when the repair is rejected", async () => {
    repairMock.mockRejectedValueOnce(new Error("challenge_question_run_repair_unsupported"));
    const { container, root } = await renderActions(repairDetail({
      officialModelCall: false,
    }));

    const button = findButton(container, "challenge-question-repair-registration");
    await act(async () => {
      button!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await act(async () => {
      await vi.waitFor(() => {
        expect(
          container.querySelector('[data-testid="challenge-question-repair-actions-error"]'),
        ).toBeTruthy();
      });
    });
    expect(container.textContent).toContain("challenge_question_run_repair_unsupported");

    await act(async () => root.unmount());
    container.remove();
  });
});
