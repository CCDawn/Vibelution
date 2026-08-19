/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ExperimentLaunchStatus,
  ResearchRunLaunchPanel,
  isLaunchBlockedByExperiment,
} from "./ResearchRunLaunchPanel";

function installPointerCaptureShims() {
  const proto = Element.prototype as unknown as Record<string, unknown>;
  if (typeof proto.hasPointerCapture !== "function") {
    proto.hasPointerCapture = function hasPointerCapture() {
      return false;
    };
  }
  if (typeof proto.setPointerCapture !== "function") {
    proto.setPointerCapture = function setPointerCapture() {
      return undefined;
    };
  }
  if (typeof proto.releasePointerCapture !== "function") {
    proto.releasePointerCapture = function releasePointerCapture() {
      return undefined;
    };
  }
}

installPointerCaptureShims();

type QueryState = {
  isPending: boolean;
  isError: boolean;
  error: Error | null;
  data: unknown;
  refetch: () => void;
};

type MutationMock = {
  isPending: boolean;
  isError: boolean;
  error: Error | null;
  isIdle: boolean;
  isSuccess: boolean;
  data: unknown;
  mutate: (variables?: unknown) => void;
  reset: () => void;
};

const queryState = vi.hoisted((): { current: QueryState } => ({
  current: {
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    refetch: () => {},
  },
}));

const mutationState = vi.hoisted(() => {
  const blank = (): MutationMock => ({
    isPending: false,
    isError: false,
    error: null,
    isIdle: true,
    isSuccess: false,
    data: undefined,
    mutate: () => {},
    reset: () => {},
  });
  const map: Record<string, MutationMock> = { default: blank() };
  return {
    get: (name: string) => map[name] ?? map.default,
    set: (name: string, patch: Partial<MutationMock>) => {
      Object.assign(map[name] ?? map.default, patch);
    },
    reset: () => {
      Object.assign(map.default, blank());
    },
  };
});

const queryClientMock = vi.hoisted(() => ({ invalidateQueries: vi.fn() }));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => queryState.current,
  useMutation: (options?: {
    mutationFn?: { name?: string };
    onSuccess?: (...args: unknown[]) => unknown;
    onError?: (...args: unknown[]) => unknown;
  }) => {
    const name = options?.mutationFn?.name ?? "default";
    const mock = mutationState.get(name);
    return {
      ...mock,
      mutate: (variables?: unknown) => {
        void (async () => {
          Object.assign(mock, { isPending: true, isIdle: false, isError: false, isSuccess: false });
          mock.mutate(variables);
          try {
            const onSuccessResult = options?.onSuccess?.({}, variables, undefined);
            await onSuccessResult;
            Object.assign(mock, { isPending: false, isIdle: false, isSuccess: true });
          } catch (reason) {
            Object.assign(mock, { isPending: false, isIdle: false, isError: true, error: reason });
            options?.onError?.(reason, variables, undefined);
          }
        })();
      },
    };
  },
  useQueryClient: () => queryClientMock,
}));

function experimentOption(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    experimentId: "EXP-GPU-OPERATOR-001",
    questionId: "SCI-091",
    name: "GPU 算子智能生成实验",
    themeId: "cc-gpu-operator-001",
    campaignId: "cc-campaign-gpu-operator-001",
    required: true,
    activated: false,
    activationStatus: "not_activated",
    activationAllowed: true,
    questionResultApproved: false,
    launchable: false,
    nextAction: "activate_campaign",
    blockers: ["question result is not formally approved"],
    activatedAt: "",
    ...overrides,
  };
}

function launchOptions(overrides: { questions?: unknown[]; experiments?: unknown[] } = {}) {
  return {
    workflowId: "challenge-cup-research",
    teamId: "team-1",
    questions: overrides.questions ?? [],
    experiments: overrides.experiments ?? [experimentOption()],
  };
}

function renderPanel() {
  return renderToStaticMarkup(
    <ResearchRunLaunchPanel
      teamId="team-1"
      busy={false}
      onSubmit={async () => undefined}
      onCancel={() => undefined}
    />,
  );
}

function findButton(scope: ParentNode, text: string): HTMLButtonElement | undefined {
  return Array.from(scope.querySelectorAll("button"))
    .find((button) => button.textContent?.includes(text)) as HTMLButtonElement | undefined;
}

async function openExperimentSelect(trigger: HTMLElement): Promise<NodeListOf<Element>> {
  await act(async () => {
    trigger.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0 }));
  });
  let options = document.body.querySelectorAll('[role="option"]');
  if (!options.length) {
    await act(async () => {
      trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    options = document.body.querySelectorAll('[role="option"]');
  }
  return options;
}

describe("ResearchRunLaunchPanel", () => {
  beforeEach(() => {
    Object.assign(queryState.current, {
      isPending: false,
      isError: false,
      error: null,
      data: undefined,
      refetch: () => {},
    });
    mutationState.reset();
    queryClientMock.invalidateQueries.mockReset();
  });

  it("waits for the catalog instead of exposing manual contract fields", () => {
    Object.assign(queryState.current, { isPending: true });
    const markup = renderPanel();

    expect(markup).toContain("加载 125 题目录");
    expect(markup).not.toContain("高级运行合同");
    expect(markup).not.toContain("研究简报 Hash");
    expect(markup).not.toContain("数据集引用");
  });

  it("productizes the launch-options load error with retry and collapsible technical details", () => {
    Object.assign(queryState.current, {
      isPending: false,
      isError: true,
      error: new Error("TypeError: fetch failed at /api/launch-options"),
      data: undefined,
      refetch: vi.fn(),
    });
    const markup = renderPanel();

    expect(markup).toContain("题目目录加载失败");
    expect(markup).toContain("暂时无法读取 125 题目录");
    expect(markup).toContain("重试");
    expect(markup).toContain("技术细节");
    expect(markup).toContain("<details");
    expect(markup).toContain("TypeError: fetch failed at /api/launch-options");
  });

  it("lists catalog questions without requiring prior approval", () => {
    Object.assign(queryState.current, {
      data: launchOptions({
        questions: [
          {
            questionId: "SCI-003",
            title: "Is the Riemann hypothesis true?",
            scope: "mathematical_sciences",
            domain: "mathematical_sciences",
            catalogId: "science-125-questions-2021",
            reviewRunId: "",
            artifactSha256: "",
            source: "catalog",
            launchable: true,
          },
        ],
        experiments: [],
      }),
    });
    const markup = renderPanel();

    expect(markup).toContain("选择题目并开始实验");
    expect(markup).toContain("SCI-003");
    expect(markup).toContain("开始实验");
    expect(markup).not.toContain("选择深度实验");
    expect(markup).not.toContain("激活正式 Campaign");
  });

  it("shows the selected question checkpoint immediately", () => {
    Object.assign(queryState.current, {
      data: launchOptions({
        questions: [
          {
            questionId: "SCI-003",
            title: "Is the Riemann hypothesis true?",
            scope: "mathematical_sciences",
            domain: "mathematical_sciences",
            catalogId: "science-125-questions-2021",
            reviewRunId: "",
            artifactSha256: "",
            source: "catalog",
            launchable: true,
            checkpoint: {
              runId: "run-3",
              status: "waiting_human",
              currentNodeId: "protocol_design",
              currentNodeLabel: "协议设计",
              completedCount: 6,
              totalSteps: 16,
              resumable: true,
            },
          },
        ],
        experiments: [],
      }),
    });
    const markup = renderToStaticMarkup(
      <ResearchRunLaunchPanel
        teamId="team-1"
        busy={false}
        initialQuestionId="SCI-003"
        onSubmit={async () => undefined}
        onCancel={() => undefined}
      />,
    );

    expect(markup).toContain("当前 checkpoint：协议设计");
    expect(markup).toContain("6/16");
    expect(markup).toContain("继续运行");
  });

  it("shows checkpoint progress and continues the existing run", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const onContinueRun = vi.fn();
    Object.assign(queryState.current, {
      data: launchOptions({
        questions: [
          {
            questionId: "SCI-003",
            title: "Is the Riemann hypothesis true?",
            scope: "mathematical_sciences",
            domain: "mathematical_sciences",
            catalogId: "science-125-questions-2021",
            reviewRunId: "",
            artifactSha256: "",
            source: "catalog",
            launchable: true,
            checkpoint: {
              runId: "run-3",
              status: "waiting_human",
              currentNodeId: "protocol_design",
              currentNodeLabel: "协议设计",
              completedCount: 7,
              totalSteps: 16,
              resumable: true,
            },
          },
        ],
        experiments: [],
      }),
    });
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ResearchRunLaunchPanel
          teamId="team-1"
          busy={false}
          onSubmit={async () => undefined}
          onCancel={() => undefined}
          onContinueRun={onContinueRun}
        />,
      );
    });

    const trigger = container.querySelector('[aria-label="选择 125 题"]') as HTMLElement | null;
    expect(trigger).toBeTruthy();
    const options = await openExperimentSelect(trigger!);
    const questionOption = Array.from(options).find((option) => option.textContent?.includes("SCI-003")) as HTMLElement | undefined;
    expect(questionOption).toBeTruthy();
    await act(async () => {
      questionOption!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.textContent).toContain("当前 checkpoint：协议设计");
    expect(container.textContent).toContain("7/16");
    const continueButton = findButton(container, "继续运行");
    expect(continueButton).toBeTruthy();
    await act(async () => {
      continueButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onContinueRun).toHaveBeenCalledWith({
      runId: "run-3",
      nodeId: "protocol_design",
      questionId: "SCI-003",
    });

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("renders the empty catalog state when no questions are available", () => {
    Object.assign(queryState.current, {
      data: launchOptions({ questions: [], experiments: [] }),
    });
    const markup = renderPanel();

    expect(markup).toContain("暂无题目目录");
  });

  it("shows activation CTA and next action when the experiment may be activated", () => {
    const experiment = experimentOption();
    const markup = renderToStaticMarkup(
      <ExperimentLaunchStatus
        experiment={experiment}
        busy={false}
        activationPending={false}
        onActivate={() => undefined}
      />,
    );

    expect(markup).toContain("EXP-GPU-OPERATOR-001");
    expect(markup).toContain("GPU 算子智能生成实验");
    expect(markup).toContain("未激活");
    expect(markup).toContain("下一动作：激活正式 Campaign");
    expect(markup).toContain("激活正式 Campaign");
    expect(markup).toContain("question result is not formally approved");
  });

  it("explains the DEV blocker and hides the activation CTA before DEV completion", () => {
    const experiment = experimentOption({
      activationAllowed: false,
      nextAction: "await_dev_readiness",
      blockers: [
        "DEV fixtures are not complete; real Qwen/GPU work is not authorized",
        "question result is not formally approved",
      ],
    });
    const markup = renderToStaticMarkup(
      <ExperimentLaunchStatus
        experiment={experiment}
        busy={false}
        activationPending={false}
        onActivate={() => undefined}
        onOpenProgress={() => undefined}
      />,
    );

    expect(markup).toContain("DEV fixtures are not complete");
    expect(markup).toContain("完成 DEV readiness / dev-1 / dev-5 fixture");
    expect(markup).not.toContain("激活正式 Campaign");
    expect(markup).toContain("等待 DEV 流程完成");
    expect(markup).toContain("去完成平台准备检查");
    expect(markup).toContain('data-vui="experiment-next-action"');
  });

  it("navigates to the progress panel from the blocked next-action CTA", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const onOpenProgress = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <ExperimentLaunchStatus
          experiment={experimentOption({
            activationAllowed: false,
            nextAction: "await_dev_readiness",
            blockers: ["DEV fixtures are not complete; real Qwen/GPU work is not authorized"],
          })}
          busy={false}
          activationPending={false}
          onActivate={() => undefined}
          onOpenProgress={onOpenProgress}
        />,
      );
    });

    const cta = findButton(container, "去完成平台准备检查");
    expect(cta).toBeTruthy();
    await act(async () => {
      cta!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onOpenProgress).toHaveBeenCalledTimes(1);

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("offers a review CTA when the experiment waits on formal question approval", () => {
    const experiment = experimentOption({
      activated: true,
      activationStatus: "active",
      activationAllowed: false,
      launchable: false,
      nextAction: "await_formal_question_approval",
      blockers: ["question result is not formally approved"],
      activatedAt: "2026-08-18T00:00:00Z",
    });
    const markup = renderToStaticMarkup(
      <ExperimentLaunchStatus
        experiment={experiment}
        busy={false}
        activationPending={false}
        onActivate={() => undefined}
        onOpenProgress={() => undefined}
      />,
    );

    expect(markup).toContain("等待正式题目审核通过");
    expect(markup).toContain("去审核题目结果");
    expect(markup).not.toContain("激活正式 Campaign");
  });

  it("keeps blocked states text-only when no navigation handler is provided", () => {
    const experiment = experimentOption({
      activationAllowed: false,
      nextAction: "await_dev_readiness",
      blockers: ["DEV fixtures are not complete; real Qwen/GPU work is not authorized"],
    });
    const markup = renderToStaticMarkup(
      <ExperimentLaunchStatus
        experiment={experiment}
        busy={false}
        activationPending={false}
        onActivate={() => undefined}
      />,
    );

    expect(markup).toContain("等待 DEV 流程完成");
    expect(markup).not.toContain('data-vui="experiment-next-action"');
  });

  it("keeps Create Run disabled for a selected deep experiment until it is launchable", () => {
    const notLaunchable = experimentOption({
      activated: true,
      activationStatus: "active",
      activationAllowed: false,
      questionResultApproved: false,
      launchable: false,
      nextAction: "await_formal_question_approval",
      blockers: ["question result is not formally approved"],
      activatedAt: "2026-08-18T00:00:00Z",
    });
    expect(isLaunchBlockedByExperiment([notLaunchable], "SCI-091")).toBe(true);

    const launchable = experimentOption({
      activated: true,
      activationStatus: "active",
      activationAllowed: false,
      questionResultApproved: true,
      launchable: true,
      nextAction: "create_run",
      blockers: [],
      activatedAt: "2026-08-18T00:00:00Z",
    });
    expect(isLaunchBlockedByExperiment([launchable], "SCI-091")).toBe(false);

    const activatedStatus = renderToStaticMarkup(
      <ExperimentLaunchStatus
        experiment={launchable}
        busy={false}
        activationPending={false}
        onActivate={() => undefined}
      />,
    );
    expect(activatedStatus).toContain("已激活");
    expect(activatedStatus).toContain("下一动作：可创建运行");
  });

  it("does not block unrelated ordinary approved questions", () => {
    const deep = experimentOption();
    expect(isLaunchBlockedByExperiment([deep], "SCI-042")).toBe(false);
    expect(isLaunchBlockedByExperiment([], "SCI-042")).toBe(false);
  });

  it("blocks a mismatched ordinary question while a deep experiment is selected", () => {
    const deep = experimentOption({
      activated: true,
      activationStatus: "active",
      questionResultApproved: true,
      launchable: true,
      nextAction: "create_run",
      blockers: [],
    });

    expect(
      isLaunchBlockedByExperiment([deep], "SCI-042", "EXP-GPU-OPERATOR-001"),
    ).toBe(true);
    expect(
      isLaunchBlockedByExperiment([deep], "SCI-091", "EXP-GPU-OPERATOR-001"),
    ).toBe(false);
  });
});

describe("ResearchRunLaunchPanel session draft", () => {
  const DRAFT_KEY = "vibelution.research-run-launch.team-1";

  const catalogQuestion = (questionId: string, title: string) => ({
    questionId,
    title,
    scope: "mathematical_sciences",
    domain: "mathematical_sciences",
    catalogId: "science-125-questions-2021",
    reviewRunId: "",
    artifactSha256: "",
    source: "catalog",
    launchable: true,
  });

  beforeEach(() => {
    window.sessionStorage.clear();
    Object.assign(queryState.current, {
      isPending: false,
      isError: false,
      error: null,
      data: launchOptions({
        questions: [
          catalogQuestion("SCI-003", "Is the Riemann hypothesis true?"),
          catalogQuestion("SCI-007", "What is the Navier-Stokes existence problem?"),
        ],
        experiments: [],
      }),
      refetch: () => {},
    });
  });

  it("restores the remembered question and search query when no deep-link is given", () => {
    window.sessionStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({
        questionId: "SCI-003",
        query: "Riemann",
        safetyBudget: {
          stageTokens: {
            knowledge_collection: 250000,
            experiment_design: 250000,
            execution_iteration: 250000,
          },
          toolCalls: 300,
          wallClockSeconds: 21600,
          maxRetries: 2,
        },
      }),
    );
    const markup = renderToStaticMarkup(
      <ResearchRunLaunchPanel
        teamId="team-1"
        busy={false}
        onSubmit={async () => undefined}
        onCancel={() => undefined}
      />,
    );

    expect(markup).toContain("SCI-003 · Is the Riemann hypothesis true?");
    expect(markup).toContain('value="Riemann"');
  });

  it("prefers the explicit deep-link question over the remembered draft", () => {
    window.sessionStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({ questionId: "SCI-003", query: "", safetyBudget: null }),
    );
    const markup = renderToStaticMarkup(
      <ResearchRunLaunchPanel
        teamId="team-1"
        busy={false}
        initialQuestionId="SCI-007"
        onSubmit={async () => undefined}
        onCancel={() => undefined}
      />,
    );

    expect(markup).toContain("SCI-007 · What is the Navier-Stokes existence problem?");
    expect(markup).not.toContain("SCI-003 · Is the Riemann hypothesis true?");
  });

  it("persists selection changes into the per-team draft", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ResearchRunLaunchPanel
          teamId="team-1"
          busy={false}
          onSubmit={async () => undefined}
          onCancel={() => undefined}
        />,
      );
    });

    const trigger = container.querySelector('[aria-label="选择 125 题"]') as HTMLElement | null;
    expect(trigger).toBeTruthy();
    const options = await openExperimentSelect(trigger!);
    const questionOption = Array.from(options).find((option) => option.textContent?.includes("SCI-007")) as HTMLElement | undefined;
    expect(questionOption).toBeTruthy();
    await act(async () => {
      questionOption!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const stored = window.sessionStorage.getItem(DRAFT_KEY);
    expect(stored).toBeTruthy();
    expect(JSON.parse(stored!)).toMatchObject({ questionId: "SCI-007" });

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("clears the remembered draft after a run is created successfully", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    window.sessionStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({ questionId: "SCI-003", query: "", safetyBudget: null }),
    );
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ResearchRunLaunchPanel
          teamId="team-1"
          busy={false}
          onSubmit={async () => undefined}
          onCancel={() => undefined}
        />,
      );
    });
    // Mount persists the restored draft; it must still be there before submit.
    expect(window.sessionStorage.getItem(DRAFT_KEY)).toBeTruthy();

    const submitButton = findButton(container, "开始实验");
    expect(submitButton).toBeTruthy();
    await act(async () => {
      submitButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(window.sessionStorage.getItem(DRAFT_KEY)).toBeNull();

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });
});
