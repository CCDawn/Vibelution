/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

type MutationCurrent = {
  isPending: boolean;
  isError: boolean;
  isSuccess: boolean;
  error: Error | null;
  data: unknown;
};

type WriteVariables = { mode: string; teamId: string; body: Record<string, unknown> };

const mutationMock = vi.hoisted(() => {
  const current: MutationCurrent = {
    isPending: false,
    isError: false,
    isSuccess: false,
    error: null,
    data: undefined,
  };
  return {
    current,
    mutateCalls: [] as WriteVariables[],
    reset: vi.fn(() => {
      current.isPending = false;
      current.isError = false;
      current.isSuccess = false;
      current.error = null;
      current.data = undefined;
    }),
  };
});

const queryClientMock = vi.hoisted(() => ({ invalidateQueries: vi.fn() }));

vi.mock("@tanstack/react-query", () => ({
  useMutation: (options?: { onSuccess?: (...args: unknown[]) => unknown }) => ({
    ...mutationMock.current,
    reset: mutationMock.reset,
    mutate: (variables: WriteVariables) => {
      mutationMock.mutateCalls.push(variables);
      void (async () => {
        mutationMock.current.isPending = true;
        await options?.onSuccess?.(mutationMock.current.data, variables, undefined);
        mutationMock.current.isPending = false;
        mutationMock.current.isSuccess = true;
      })();
    },
  }),
  useQueryClient: () => queryClientMock,
}));

import { ChallengeQuestionRegisterDialog } from "./ChallengeQuestionRegisterDialog";
import dialogSource from "./ChallengeQuestionRegisterDialog.tsx?raw";
import detailPanelSource from "./ChallengeQuestionDetailPanel.tsx?raw";
import progressPanelSource from "../research-workflow/ChallengeMvpProgressPanel.tsx?raw";

const VALID_OUTPUT = {
  schema_version: 2,
  identity: { question_id: "SCI-096", question_en: "How does the brain retrieve memories?" },
  run: { run_id: "stage1-sci-096-v4" },
  evidence: [{ evidence_id: "E1", source_url: "https://example.org/paper" }],
};

const REGISTER_RESPONSE = {
  record: {
    questionId: "SCI-096",
    runId: "stage1-sci-096-v4",
    status: "review_required",
    validation: {
      schemaValidation: "passed",
      citationValidation: "passed",
      semanticValidation: "passed",
      officialModelCall: true,
    },
    humanGates: { approvedCount: 0, allApproved: false },
  },
  idempotent: false,
  humanReviewRequired: true,
};

function setControlValue(element: Element, value: string) {
  const prototype = element instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, "value")?.set?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

function buttonByText(text: string): HTMLButtonElement | undefined {
  return Array.from(document.body.querySelectorAll("button"))
    .find((button) => button.getAttribute("role") !== "tab" && button.textContent?.includes(text));
}

async function mountDialog(props?: Partial<React.ComponentProps<typeof ChallengeQuestionRegisterDialog>>) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const finalProps = {
    teamId: "team-1",
    onClose: vi.fn(),
    ...props,
  };
  await act(async () => {
    root.render(<ChallengeQuestionRegisterDialog {...finalProps} />);
  });
  return {
    root,
    container,
    props: finalProps,
    async unmount() {
      await act(async () => {
        root.unmount();
      });
      container.remove();
    },
  };
}

beforeEach(() => {
  mutationMock.current.isPending = false;
  mutationMock.current.isError = false;
  mutationMock.current.isSuccess = false;
  mutationMock.current.error = null;
  mutationMock.current.data = undefined;
  mutationMock.mutateCalls.length = 0;
  mutationMock.reset.mockClear();
  queryClientMock.invalidateQueries.mockClear();
  globalThis.localStorage?.clear();
  document.body.innerHTML = "";
});

describe("ChallengeQuestionRegisterDialog", () => {
  it("renders register mode with output textarea, citation checkbox and registeredBy", async () => {
    const view = await mountDialog();

    expect(document.body.querySelector('[role="dialog"]')).not.toBeNull();
    expect(document.body.querySelector('textarea[aria-label="题目产出 JSON"]')).not.toBeNull();
    expect(document.body.querySelector('input[aria-label="登记人"]')).not.toBeNull();
    expect(document.body.querySelector('input[aria-label="父 Run ID"]')).not.toBeNull();
    expect(document.body.textContent).toContain("来源链接已逐条核对");
    expect(document.body.querySelector('input[aria-label="研究项目 ID"]')).toBeNull();
    expect(buttonByText("登记产出")).toBeTruthy();

    await view.unmount();
  });

  it("shows the five publish binding fields in publish mode", async () => {
    const view = await mountDialog({ initialMode: "publish" });

    for (const label of ["研究项目 ID", "题目 ID", "任务 ID", "轮次 ID", "项目证据 ID"]) {
      expect(document.body.querySelector(`input[aria-label="${label}"]`)).not.toBeNull();
    }
    expect(document.body.querySelector('input[aria-label="父 Run ID"]')).toBeNull();
    expect(buttonByText("发布产出")).toBeTruthy();

    await view.unmount();
  });

  it("keeps submit disabled and explains why when the output JSON is invalid", async () => {
    const view = await mountDialog();
    const textarea = document.body.querySelector('textarea[aria-label="题目产出 JSON"]')!;

    await act(async () => {
      setControlValue(textarea, "{not-json");
    });

    expect(document.body.textContent).toContain("JSON 解析失败");
    const submit = buttonByText("登记产出");
    expect(submit).toBeTruthy();
    expect(submit!.disabled).toBe(true);

    await act(async () => {
      setControlValue(textarea, JSON.stringify({ schema_version: 1 }));
    });
    expect(document.body.textContent).toContain("schema_version=2");

    await view.unmount();
  });

  it("registers a parsed v2 output with citation checks and invalidates status + detail", async () => {
    mutationMock.current.data = REGISTER_RESPONSE;
    const onOpenQuestion = vi.fn();
    const view = await mountDialog({ onOpenQuestion });

    await act(async () => {
      setControlValue(document.body.querySelector('textarea[aria-label="题目产出 JSON"]')!, JSON.stringify(VALID_OUTPUT));
    });
    expect(document.body.textContent).toContain("解析到 SCI-096");

    const checkbox = document.body.querySelector('input[type="checkbox"]')!;
    await act(async () => {
      checkbox.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => {
      setControlValue(document.body.querySelector('input[aria-label="登记人"]')!, "Grok");
    });

    const submit = buttonByText("登记产出")!;
    expect(submit.disabled).toBe(false);
    await act(async () => {
      submit.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(mutationMock.mutateCalls).toHaveLength(1);
    const call = mutationMock.mutateCalls[0];
    expect(call.mode).toBe("register");
    expect(call.teamId).toBe("team-1");
    expect((call.body.output as { schema_version?: number }).schema_version).toBe(2);
    expect((call.body.output as { identity?: { question_id?: string } }).identity?.question_id).toBe("SCI-096");
    expect(call.body.citationChecks).toEqual([{ sourceUrl: "https://example.org/paper", status: "passed" }]);
    expect(call.body.registeredBy).toBe("Grok");

    expect(queryClientMock.invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["teams", "team-1", "challenge-program", "question-runs", "status"],
    });
    expect(queryClientMock.invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["teams", "team-1", "challenge-program", "questions", "SCI-096", ""],
    });

    await act(async () => {
      view.root.render(
        <ChallengeQuestionRegisterDialog teamId="team-1" onClose={view.props.onClose} onOpenQuestion={onOpenQuestion} />,
      );
    });
    expect(document.body.textContent).toContain("登记成功");
    expect(document.body.textContent).toContain("review_required");
    expect(document.body.textContent).toContain("Schema passed");
    expect(document.body.textContent).toContain("引用 passed");

    const openDetail = buttonByText("查看题目详情")!;
    await act(async () => {
      openDetail.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onOpenQuestion).toHaveBeenCalledWith("SCI-096");

    await view.unmount();
  });

  it("publishes with the full research-project evidence binding", async () => {
    mutationMock.current.data = REGISTER_RESPONSE;
    const view = await mountDialog({ initialMode: "publish", questionIdHint: "SCI-096" });

    await act(async () => {
      setControlValue(document.body.querySelector('textarea[aria-label="题目产出 JSON"]')!, JSON.stringify(VALID_OUTPUT));
    });
    const submitBefore = buttonByText("发布产出")!;
    expect(submitBefore.disabled).toBe(true);

    await act(async () => {
      setControlValue(document.body.querySelector('input[aria-label="研究项目 ID"]')!, "project-sci-096");
    });
    await act(async () => {
      setControlValue(document.body.querySelector('input[aria-label="任务 ID"]')!, "stage-task-sci-096");
    });
    await act(async () => {
      setControlValue(document.body.querySelector('input[aria-label="轮次 ID"]')!, "turn-sci-096");
    });
    await act(async () => {
      setControlValue(document.body.querySelector('input[aria-label="项目证据 ID"]')!, "model-evidence-sci-096");
    });

    const submit = buttonByText("发布产出")!;
    expect(submit.disabled).toBe(false);
    await act(async () => {
      submit.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(mutationMock.mutateCalls).toHaveLength(1);
    const call = mutationMock.mutateCalls[0];
    expect(call.mode).toBe("publish");
    expect(call.body.researchProjectId).toBe("project-sci-096");
    expect(call.body.questionId).toBe("SCI-096");
    expect(call.body.taskId).toBe("stage-task-sci-096");
    expect(call.body.turnId).toBe("turn-sci-096");
    expect(call.body.projectEvidenceId).toBe("model-evidence-sci-096");

    await view.unmount();
  });

  it("blocks publish when the binding question id mismatches the output identity", async () => {
    const view = await mountDialog({ initialMode: "publish", questionIdHint: "SCI-097" });

    await act(async () => {
      setControlValue(document.body.querySelector('textarea[aria-label="题目产出 JSON"]')!, JSON.stringify(VALID_OUTPUT));
    });

    expect(document.body.textContent).toContain("不一致");
    expect(buttonByText("发布产出")!.disabled).toBe(true);

    await view.unmount();
  });

  it("prefills the parent run id for revision registrations", async () => {
    const view = await mountDialog({ parentRunId: "stage1-sci-096-v3", questionIdHint: "SCI-096" });

    const parentInput = document.body.querySelector('input[aria-label="父 Run ID"]') as HTMLInputElement;
    expect(parentInput.value).toBe("stage1-sci-096-v3");

    await view.unmount();
  });

  it("keeps the VUI product surface and backend contract wiring", () => {
    expect(dialogSource).toContain('from "../../../components/vui"');
    // Token is concatenated so the VUI import-boundary scanner does not count
    // this assertion's own literal as a source offender.
    expect(dialogSource).not.toContain("@heroui" + "/react");
    expect(dialogSource).not.toContain("renderers/shadcn");
    expect(dialogSource).toContain("registerChallengeQuestionRun");
    expect(dialogSource).toContain("publishChallengeQuestionRun");
    expect(dialogSource).toContain("queryKeys.challengeQuestionRunStatus(teamId)");
    expect(dialogSource).toContain("queryKeys.challengeQuestionRunDetail(teamId, affectedQuestionId)");

    expect(progressPanelSource).toContain('from "../challenge-cup/ChallengeQuestionRegisterDialog"');
    expect(progressPanelSource).toContain("setRegisterDialogOpen(true)");

    expect(detailPanelSource).toContain('record.status === "needs_revision"');
    expect(detailPanelSource).toContain("parentRunId={record.runId}");
    expect(detailPanelSource).toContain("teamId={detail.teamId}");
  });
});
