/** @vitest-environment happy-dom */
import { describe, expect, it, vi } from "vitest";

import type { Team } from "../../api/types";
import { createResearchStageLaunchHandlers } from "./createResearchStageLaunchHandlers";
import type { ResearchPrimaryAction } from "./researchPrimaryActionModel";

function buildAction(overrides: Partial<ResearchPrimaryAction> = {}): ResearchPrimaryAction {
  return {
    kind: "start_experiment",
    labelZh: "进入实验设计",
    labelEn: "Start experiment",
    detailZh: "",
    detailEn: "",
    navigateView: "experiment",
    launchStageType: "experiment",
    launchMode: "continue_or_start",
    blocked: false,
    ...overrides,
  };
}

function buildHandlers(options: {
  mutateAsync?: (payload: unknown) => Promise<unknown>;
  startTask?: () => Promise<{ chatRoute?: string | null }>;
  challengeCupResearchTeamSelected?: boolean;
}) {
  const navigate = vi.fn();
  const selectResearchWorkspaceView = vi.fn();
  const setResearchAdvanceNotice = vi.fn();
  const handlers = createResearchStageLaunchHandlers({
    lang: "zh",
    selectedTeam: { teamId: "team-a" } as Team,
    sourceCollectionDraft: {} as never,
    getSelectedTeamStartResearchStagePending: () => false,
    getResearchStageCanLaunch: () => true,
    challengeCupResearchTeamSelected: options.challengeCupResearchTeamSelected ?? false,
    researchStageProjectAgentTasks: {
      startTask: options.startTask ?? (async () => ({ chatRoute: null })),
    },
    startResearchStageRoundMutation: {
      mutateAsync: options.mutateAsync ?? (async () => ({})),
    },
    navigate,
    selectResearchWorkspaceView,
    setResearchAdvanceNotice,
  });
  return { handlers, navigate, selectResearchWorkspaceView, setResearchAdvanceNotice };
}

describe("createResearchStageLaunchHandlers", () => {
  it("keeps the user on the initiating surface when the stage launch fails", async () => {
    const { handlers, selectResearchWorkspaceView } = buildHandlers({
      mutateAsync: async () => {
        throw new Error("backend unavailable");
      },
    });

    const completed = await handlers.handleResearchPrimaryAction(buildAction());

    expect(completed).toBe(false);
    expect(selectResearchWorkspaceView).not.toHaveBeenCalled();
  });

  it("navigates to the target view after a successful launch", async () => {
    const { handlers, selectResearchWorkspaceView } = buildHandlers({});

    const completed = await handlers.handleResearchPrimaryAction(buildAction());

    expect(completed).toBe(true);
    expect(selectResearchWorkspaceView).toHaveBeenCalledWith("experiment");
  });

  it("does not re-assert the workspace view when the launch already navigated to a chat route", async () => {
    const { handlers, navigate, selectResearchWorkspaceView } = buildHandlers({
      challengeCupResearchTeamSelected: true,
      startTask: async () => ({ chatRoute: "/chat?session=s-1" }),
    });

    const completed = await handlers.handleResearchPrimaryAction(buildAction());

    expect(completed).toBe(true);
    expect(navigate).toHaveBeenCalledWith("/chat?session=s-1");
    expect(selectResearchWorkspaceView).not.toHaveBeenCalled();
  });

  it("suppresses the advance success notice when the underlying action failed", async () => {
    const { handlers, setResearchAdvanceNotice } = buildHandlers({
      mutateAsync: async () => {
        throw new Error("boom");
      },
    });

    await handlers.handleResearchAdvanceAction(buildAction());

    expect(setResearchAdvanceNotice).not.toHaveBeenCalled();
  });

  it("shows the advance success notice only after a completed action", async () => {
    vi.useFakeTimers();
    try {
      const { handlers, setResearchAdvanceNotice } = buildHandlers({});

      await handlers.handleResearchAdvanceAction(buildAction());

      expect(setResearchAdvanceNotice).toHaveBeenCalledWith(expect.stringContaining("实验设计"));
    } finally {
      vi.useRealTimers();
    }
  });

  it("still navigates without a launch when the action has no stage to start", async () => {
    const { handlers, selectResearchWorkspaceView } = buildHandlers({});
    const action = buildAction({ launchStageType: undefined, launchMode: undefined });

    const completed = await handlers.handleResearchPrimaryAction(action);

    expect(completed).toBe(true);
    expect(selectResearchWorkspaceView).toHaveBeenCalledWith("experiment");
  });
});
