/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import { ChallengeQuestionReviewForm } from "./ChallengeQuestionReviewForm";

const reviewMock = vi.hoisted(() => vi.fn(async () => ({})));

vi.mock("../../../api/teamExperiment", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  reviewChallengeQuestionRun: reviewMock,
}));

function installPointerCaptureShims() {
  const proto = Element.prototype as unknown as Record<string, unknown>;
  if (typeof proto.hasPointerCapture !== "function") {
    proto.hasPointerCapture = () => false;
    proto.setPointerCapture = () => undefined;
    proto.releasePointerCapture = () => undefined;
  }
}

installPointerCaptureShims();

function pendingDetail(): ChallengeQuestionRunDetailPayload {
  const gate = { required: true as const, decision: "pending" as const, rationale: "" };
  return {
    teamId: "research-team",
    questionId: "SCI-096",
    selectedRunId: "stage1-sci-096-v3",
    record: {
      recordId: "record-sci-096",
      questionId: "SCI-096",
      runId: "stage1-sci-096-v3",
      status: "pending_review",
      validation: { officialModelCall: true },
    },
    output: {
      problem_understanding: { human_gate: gate },
      selection: { human_gate: gate },
      research_plan: { human_gate: gate },
      audit: { human_review_status: "pending" },
    },
  } as unknown as ChallengeQuestionRunDetailPayload;
}

function approvedDetail(decidedAt: string): ChallengeQuestionRunDetailPayload {
  const detail = pendingDetail();
  return {
    ...detail,
    record: { ...detail.record, status: "approved" },
    output: {
      ...detail.output,
      review: {
        reviewer: "Grok",
        decided_at: decidedAt,
        rationale: "已完成审核。",
      },
    },
  } as unknown as ChallengeQuestionRunDetailPayload;
}

function setNativeValue(element: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  setter?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

function findButton(scope: ParentNode, text: string): HTMLButtonElement | undefined {
  return Array.from(scope.querySelectorAll("button"))
    .find((button) => button.textContent?.includes(text)) as HTMLButtonElement | undefined;
}

async function chooseDecision(container: ParentNode, ariaLabel: string, label: string) {
  const select = container.querySelector(`[aria-label="${ariaLabel}"]`) as HTMLButtonElement;
  expect(select).toBeTruthy();
  await act(async () => {
    select.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0 }));
  });
  let options = document.body.querySelectorAll('[role="option"]');
  if (!options.length) {
    await act(async () => {
      select.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    options = document.body.querySelectorAll('[role="option"]');
  }
  const option = Array.from(options).find((item) => item.textContent?.includes(label)) as HTMLElement | undefined;
  expect(option).toBeTruthy();
  await act(async () => {
    option!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

async function renderForm(detail: ChallengeQuestionRunDetailPayload = pendingDetail()) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={new QueryClient()}>
        <ChallengeQuestionReviewForm detail={detail} />
      </QueryClientProvider>,
    );
  });
  return { container, root };
}

describe("ChallengeQuestionReviewForm", () => {
  beforeEach(() => {
    reviewMock.mockClear();
    globalThis.localStorage?.clear();
  });

  it("submits all four gate decisions with reviewer and rationale", async () => {
    const { container, root } = await renderForm();

    const submit = findButton(container, "提交审核结论");
    expect(submit).toBeTruthy();
    expect(submit!.disabled).toBe(true);
    expect(container.textContent).toContain("待定");

    await act(async () => {
      setNativeValue(container.querySelector('input[aria-label="审核人"]') as HTMLInputElement, "Grok");
      setNativeValue(container.querySelector('textarea[aria-label="审核意见"]') as HTMLTextAreaElement, "边界清晰，可以进入正式流程。");
    });

    expect(findButton(container, "提交审核结论")!.disabled).toBe(true);
    await chooseDecision(container, "H1 问题理解 审核结论", "通过");
    await chooseDecision(container, "H2 假设选择 审核结论", "通过");
    await chooseDecision(container, "H3 研究计划 审核结论", "通过");
    await chooseDecision(container, "H4 外部产出 审核结论", "通过");

    const enabledSubmit = findButton(container, "提交审核结论");
    expect(enabledSubmit!.disabled).toBe(false);
    await act(async () => {
      enabledSubmit!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(reviewMock).toHaveBeenCalledTimes(1);
    expect(reviewMock).toHaveBeenCalledWith("research-team", "SCI-096", "stage1-sci-096-v3", {
      reviewer: "Grok",
      rationale: "边界清晰，可以进入正式流程。",
      decisions: {
        H1_problem_understanding: "approved",
        H2_hypothesis_selection: "approved",
        H3_research_plan: "approved",
        H4_external_output: "approved",
      },
    });

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("locks the form after a submitted request for changes", async () => {
    const { container, root } = await renderForm();

    await chooseDecision(container, "H1 问题理解 审核结论", "通过");
    await chooseDecision(container, "H2 假设选择 审核结论", "通过");
    await chooseDecision(container, "H3 研究计划 审核结论", "通过");
    await chooseDecision(container, "H4 外部产出 审核结论", "需修改");

    await act(async () => {
      setNativeValue(container.querySelector('input[aria-label="审核人"]') as HTMLInputElement, "Grok");
      setNativeValue(container.querySelector('textarea[aria-label="审核意见"]') as HTMLTextAreaElement, "外部产出不达标。");
    });

    const submit = findButton(container, "提交审核结论");
    expect(submit!.disabled).toBe(false);
    await act(async () => {
      submit!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(reviewMock).toHaveBeenCalledWith("research-team", "SCI-096", "stage1-sci-096-v3", expect.objectContaining({
      decisions: expect.objectContaining({ H4_external_output: "revision_requested" }),
    }));
    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("审核结论已提交"));
    });
    expect(findButton(container, "提交审核结论")!.disabled).toBe(true);
    await act(async () => {
      findButton(container, "提交审核结论")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(reviewMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("formats an approved decision timestamp for the active language and locale", async () => {
    const decidedAt = "2026-08-21T08:15:23.123456+00:00";
    const { container, root } = await renderForm(approvedDetail(decidedAt));

    expect(container.textContent).toContain("审核人 Grok");
    expect(container.textContent).toContain("2026");
    expect(container.textContent).not.toContain(decidedAt);

    await act(async () => root.unmount());
    container.remove();
  });

  it("falls back to the original timestamp when it cannot be parsed", async () => {
    const decidedAt = "timestamp-not-parseable";
    const { container, root } = await renderForm(approvedDetail(decidedAt));

    expect(container.textContent).toContain(decidedAt);

    await act(async () => root.unmount());
    container.remove();
  });
});
