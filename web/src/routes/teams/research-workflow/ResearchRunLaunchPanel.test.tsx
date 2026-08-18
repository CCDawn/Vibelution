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

  it("waits for the canonical launch list instead of exposing manual contract fields", () => {
    Object.assign(queryState.current, { isPending: true });
    const markup = renderPanel();

    expect(markup).toContain("加载可启动题目");
    expect(markup).not.toContain("高级运行合同");
    expect(markup).not.toContain("研究简报 Hash");
    expect(markup).not.toContain("数据集引用");
  });

  it("keeps experiments visible when the approved-question list is empty", () => {
    Object.assign(queryState.current, { data: launchOptions({ questions: [] }) });
    const markup = renderPanel();

    expect(markup).not.toContain("暂无可启动题目");
    expect(markup).toContain("选择深度实验");
    expect(markup).toContain("创建运行");
  });

  it("starts with the explicit empty experiment state and never auto-selects", () => {
    Object.assign(queryState.current, {
      data: launchOptions({
        questions: [
          {
            questionId: "SCI-091",
            title: "GPU 算子实验",
            scope: "scope",
            catalogId: "science-125-questions-2021",
            reviewRunId: "stage1-sci-091-v1",
            artifactSha256: "b".repeat(64),
          },
        ],
      }),
    });
    const markup = renderPanel();

    expect(markup).toContain("不选择深度实验");
    expect(markup).toContain("不选择已审核题目");
    expect(markup).toContain("选择深度实验");
    expect(markup).not.toContain("激活正式 Campaign");
    expect(markup).not.toContain("EXP-GPU-OPERATOR-001");
  });

  it("renders the empty state only when both questions and experiments are absent", () => {
    Object.assign(queryState.current, {
      data: launchOptions({ questions: [], experiments: [] }),
    });
    const markup = renderPanel();

    expect(markup).toContain("暂无可启动题目");
  });

  it("renders the experiment selector before the approved-question selector", () => {
    Object.assign(queryState.current, {
      data: launchOptions({
        questions: [
          {
            questionId: "SCI-042",
            title: "Ordinary approved question",
            scope: "scope",
            catalogId: "science-125-questions-2021",
            reviewRunId: "stage1-sci-042-v1",
            artifactSha256: "a".repeat(64),
          },
        ],
      }),
    });
    const markup = renderPanel();

    expect(markup).toContain("选择深度实验");
    expect(markup).toContain("选择已审核题目");
    expect(markup.indexOf("选择深度实验")).toBeLessThan(markup.indexOf("选择已审核题目"));
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

  it("activates a deep experiment through the rendered panel and invalidates launch options", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    Object.assign(queryState.current, {
      data: launchOptions({
        questions: [
          {
            questionId: "SCI-091",
            title: "GPU 算子实验",
            scope: "scope",
            catalogId: "science-125-questions-2021",
            reviewRunId: "stage1-sci-091-v1",
            artifactSha256: "b".repeat(64),
          },
        ],
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
        />,
      );
    });

    expect(container.textContent).toContain("不选择深度实验");
    expect(container.textContent).not.toContain("激活正式 Campaign");

    const experimentTrigger = container.querySelector(
      '[aria-label="选择深度实验"]',
    ) as HTMLButtonElement | null;
    expect(experimentTrigger).toBeTruthy();
    const options = await openExperimentSelect(experimentTrigger!);

    const experimentOption = Array.from(options)
      .find((option) => option.textContent?.includes("EXP-GPU-OPERATOR-001")) as HTMLElement | undefined;
    expect(experimentOption).toBeTruthy();
    await act(async () => {
      experimentOption!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const activateButton = findButton(container, "激活正式 Campaign");
    expect(activateButton).toBeTruthy();
    await act(async () => {
      activateButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const confirmButton = findButton(document.body, "确认激活");
    expect(confirmButton).toBeTruthy();
    await act(async () => {
      confirmButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(queryClientMock.invalidateQueries).toHaveBeenCalledWith({
      queryKey: [
        "research-workflow",
        "challenge-cup-research",
        "team-1",
        "launch-options",
      ],
    });
    expect(mutationState.get("default").isSuccess).toBe(true);
    expect(container.textContent).toContain("EXP-GPU-OPERATOR-001");
    expect(document.body.textContent).not.toContain("确认激活");

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });
});
