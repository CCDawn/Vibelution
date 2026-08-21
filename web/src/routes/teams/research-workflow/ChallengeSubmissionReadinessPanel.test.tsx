/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const queryState = vi.hoisted(() => ({
  isPending: false,
  isError: false,
  error: null,
  data: undefined as unknown,
  refetch: vi.fn(),
}));
const mutationState = vi.hoisted(() => ({
  isPending: false,
  mutate: vi.fn(),
  shouldFail: false,
  error: new Error("export failed"),
  result: { status: "blocked", blockers: [] as Array<{ code: string; message: string }> },
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => queryState,
  useMutation: (options: {
    onSuccess?: (result: unknown) => void;
    onError?: (error: unknown) => void;
  }) => ({
    isPending: mutationState.isPending,
    mutate: (variables?: unknown) => {
      mutationState.mutate(variables);
      if (mutationState.shouldFail) {
        options.onError?.(mutationState.error);
      } else {
        options.onSuccess?.(mutationState.result);
      }
    },
  }),
}));
vi.mock("../../../api/teamExperiment", () => ({ fetchChallengeSubmissionReadiness: vi.fn() }));
vi.mock("../../../api/teamResearchOps", () => ({ exportResearchDeliverables: vi.fn() }));

import { ChallengeSubmissionReadinessPanel } from "./ChallengeSubmissionReadinessPanel";

function readiness(overrides: Record<string, unknown> = {}) {
  return {
    schemaVersion: 1,
    teamId: "team-1",
    status: "blocked",
    readyCount: 0,
    requiredCount: 5,
    blockerCount: 1,
    artifacts: [
      { key: "full_catalog_results", label: "后端标签", required: true, status: "blocked", detail: "", blocker: "full_catalog_results_incomplete", primaryAction: { kind: "repair", target: "full-catalog-results", label: "后端动作", questionId: "SCI-042" } },
      { key: "unknown_artifact", label: "内部标签", required: false, status: "optional", detail: "", blocker: "", primaryAction: { kind: "inspect", target: "submission-package", label: "后端动作" } },
    ],
    blockers: [{ code: "full_catalog_results_incomplete", label: "后端标签", action: { kind: "repair", target: "full-catalog-results", label: "后端动作", questionId: "SCI-042" } }],
    programSummary: { title: "", questionCount: 125, approvedQuestionCount: 0, deepExperimentCount: 2, approvedDeepExperimentCount: 0 },
    ...overrides,
  };
}

function findButton(container: HTMLElement, text: string): HTMLButtonElement | undefined {
  return Array.from(container.querySelectorAll("button")).find((button) => button.textContent?.includes(text)) as HTMLButtonElement | undefined;
}

describe("ChallengeSubmissionReadinessPanel", () => {
  beforeEach(() => {
    Object.assign(queryState, { isPending: false, isError: false, error: null, data: readiness(), refetch: vi.fn() });
    Object.assign(mutationState, {
      isPending: false,
      shouldFail: false,
      error: new Error("export failed"),
      result: { status: "blocked", blockers: [] },
      mutate: vi.fn(),
    });
  });

  it("renders the low-density readiness surface and localizes unknown values", () => {
    const markup = renderToStaticMarkup(<ChallengeSubmissionReadinessPanel teamId="team-1" lang="en" onOpenQuestion={vi.fn()} />);
    expect(markup).toContain('data-vui="challenge-submission-readiness"');
    expect(markup).toContain("125-question results");
    expect(markup).toContain("Submission item");
    expect(markup).toContain("Some 125-question results are incomplete");
    expect(markup).not.toContain("unknown_artifact");
    expect(markup).not.toContain("后端标签");
  });

  it("opens the canonical question and falls back to inspection when navigation is unavailable", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const onOpenQuestion = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => root.render(<ChallengeSubmissionReadinessPanel teamId="team-1" onOpenQuestion={onOpenQuestion} />));
    await act(async () => findButton(container, "修复缺失结果")!.click());
    expect(onOpenQuestion).toHaveBeenCalledWith("SCI-042");

    queryState.data = readiness({ blockers: [{ code: "submission_direction_requirements_not_captured", label: "内部", action: { kind: "repair", target: "submission-requirements", label: "内部" } }] });
    await act(async () => root.render(<ChallengeSubmissionReadinessPanel teamId="team-1" onOpenQuestion={onOpenQuestion} />));
    await act(async () => findButton(container, "检查交付材料")!.click());
    expect(mutationState.mutate).toHaveBeenCalledTimes(1);
    await act(async () => root.unmount());
    container.remove();
  });

  it("shows the returned inspection status and blocker count", async () => {
    mutationState.result = { status: "blocked", blockers: [{ code: "a", message: "a" }, { code: "b", message: "b" }] };
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => root.render(<ChallengeSubmissionReadinessPanel teamId="team-1" onOpenQuestion={vi.fn()} />));
    queryState.data = readiness({ blockers: [{ code: "x", label: "内部", action: { kind: "inspect", target: "submission-package", label: "内部" } }] });
    await act(async () => root.render(<ChallengeSubmissionReadinessPanel teamId="team-1" onOpenQuestion={vi.fn()} />));
    await act(async () => findButton(container, "检查交付材料")!.click());
    expect(container.textContent).toContain("交付材料检查：有阻塞，2 项阻塞");
    await act(async () => root.unmount());
    container.remove();
  });

  it("surfaces export failures and leaves the action retryable", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    mutationState.shouldFail = true;
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => root.render(<ChallengeSubmissionReadinessPanel teamId="team-1" onOpenQuestion={vi.fn()} />));
    queryState.data = readiness({
      blockers: [{
        code: "submission_direction_requirements_not_captured",
        label: "内部",
        action: { kind: "inspect", target: "submission-package", label: "内部" },
      }],
    });
    await act(async () => root.render(<ChallengeSubmissionReadinessPanel teamId="team-1" onOpenQuestion={vi.fn()} />));
    await act(async () => findButton(container, "检查交付材料")!.click());
    expect(container.querySelector('[data-testid="submission-export-error"]')?.textContent).toContain("交付材料导出失败");
    expect(findButton(container, "检查交付材料")).toBeTruthy();
    await act(async () => root.unmount());
    container.remove();
  });
});
