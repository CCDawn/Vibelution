/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

const previewMock = vi.hoisted(() => ({
  current: {
    schemaVersion: 1,
    teamId: "research-team",
    questionId: "SCI-004",
    canReset: true,
    blockingReason: "",
    impact: {
      candidateCount: 3,
      selectionCount: 1,
      meetingCount: 2,
      hypothesisRoundCount: 1,
      collectionRequestCount: 1,
      collectionRunCount: 1,
    },
  },
}));

const apiMock = vi.hoisted(() => ({
  fetchQuestionRunResetPreview: vi.fn(),
  resetQuestionRun: vi.fn(async () => ({
    schemaVersion: 1,
    teamId: "research-team",
    questionId: "SCI-004",
    removed: previewMock.current.impact,
    nextAction: { targetNodeId: "hf_generation", label: "生成候选假说" },
  })),
}));

const queryClientMock = vi.hoisted(() => ({ invalidateQueries: vi.fn() }));

vi.mock("../../../api/hypothesisFirst", () => apiMock);
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: previewMock.current, isPending: false, error: null }),
  useQueryClient: () => queryClientMock,
  useMutation: (options: { mutationFn: () => Promise<unknown>; onSuccess?: (result: any) => Promise<void> }) => ({
    isPending: false,
    error: null,
    mutate: () => {
      void (async () => {
        const result = await options.mutationFn();
        await options.onSuccess?.(result);
      })();
    },
  }),
}));

import { ChallengeQuestionRunResetDialog } from "./ChallengeQuestionRunResetDialog";

function setInputValue(input: HTMLInputElement, value: string) {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function actionButton(label: string): HTMLButtonElement {
  const button = Array.from(document.body.querySelectorAll("button"))
    .find((item) => item.textContent?.trim() === label);
  if (!button) throw new Error(`Expected ${label} button`);
  return button;
}

async function mountDialog() {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const onOpenChange = vi.fn();
  const onCompleted = vi.fn();
  await act(async () => {
    root.render(
      <ChallengeQuestionRunResetDialog
        open
        onOpenChange={onOpenChange}
        teamId="research-team"
        questionId="SCI-004"
        onCompleted={onCompleted}
      />,
    );
  });
  return {
    onOpenChange,
    onCompleted,
    async unmount() {
      await act(async () => root.unmount());
      container.remove();
    },
  };
}

beforeEach(() => {
  previewMock.current = {
    schemaVersion: 1,
    teamId: "research-team",
    questionId: "SCI-004",
    canReset: true,
    blockingReason: "",
    impact: {
      candidateCount: 3,
      selectionCount: 1,
      meetingCount: 2,
      hypothesisRoundCount: 1,
      collectionRequestCount: 1,
      collectionRunCount: 1,
    },
  };
  apiMock.fetchQuestionRunResetPreview.mockClear();
  apiMock.resetQuestionRun.mockClear();
  queryClientMock.invalidateQueries.mockClear();
  document.body.innerHTML = "";
});

describe("ChallengeQuestionRunResetDialog", () => {
  it("requires the current question id before clearing the displayed scope", async () => {
    const view = await mountDialog();
    const confirm = actionButton("重置本题运行");
    const input = document.body.querySelector('input[aria-label="输入 SCI-004 确认重置"]') as HTMLInputElement;

    expect(document.body.textContent).toContain("候选假说");
    expect(document.body.textContent).toContain("资料搜集运行");
    expect(document.body.textContent).toContain("请输入 SCI-004 以解锁重置操作。");
    expect(confirm.disabled).toBe(true);

    await act(async () => setInputValue(input, "sci-004"));

    expect(confirm.disabled).toBe(false);
    await view.unmount();
  });

  it("keeps the confirmation unavailable when the server reports active work", async () => {
    previewMock.current = {
      ...previewMock.current,
      canReset: false,
      blockingReason: "本题的资料搜集仍在进行，请等待结束或先停止任务。",
    };
    const view = await mountDialog();
    const input = document.body.querySelector('input[aria-label="输入 SCI-004 确认重置"]') as HTMLInputElement;

    await act(async () => setInputValue(input, "SCI-004"));

    expect(document.body.textContent).toContain("资料搜集仍在进行");
    expect(actionButton("重置本题运行").disabled).toBe(true);
    await view.unmount();
  });

  it("clears then returns the user to candidate generation", async () => {
    const view = await mountDialog();
    const input = document.body.querySelector('input[aria-label="输入 SCI-004 确认重置"]') as HTMLInputElement;

    await act(async () => {
      setInputValue(input, "SCI-004");
      actionButton("重置本题运行").click();
      await Promise.resolve();
    });

    expect(apiMock.resetQuestionRun).toHaveBeenCalledWith("research-team", "SCI-004", "SCI-004");
    expect(view.onOpenChange).toHaveBeenCalledWith(false);
    expect(view.onCompleted).toHaveBeenCalledWith("hf_generation");
    await view.unmount();
  });
});
