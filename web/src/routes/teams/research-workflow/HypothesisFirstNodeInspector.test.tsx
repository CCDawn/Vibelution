/**
 * HypothesisFirstNodeInspector: live task surface for generation / selection /
 * review / collection / recovery. Toolbar navigation copy must not appear as
 * the write command.
 *
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const selectionListProps = vi.hoisted(() => vi.fn());

vi.mock("../../../api/chat", () => ({
  fetchChatRoomDetail: vi.fn().mockResolvedValue({ rounds: [] }),
}));

vi.mock("../../../api/hypothesisFirst", () => ({
  recordCollectionHandoff: vi.fn().mockResolvedValue({}),
  openHypothesisCandidateGeneration: vi.fn().mockResolvedValue({}),
}));

import { recordCollectionHandoff } from "../../../api/hypothesisFirst";
const mockedRecordCollectionHandoff = vi.mocked(recordCollectionHandoff);

vi.mock("./HypothesisFirstMeetingOps", () => ({
  HypothesisFirstMeetingOps: (props: {
    lang?: "zh" | "en";
    meetingRoundId?: string;
    nextAction: { commandLabel?: string; stage: string; disabledReason?: string };
  }) => (
    <div data-testid="meeting-ops">
      {props.lang === "en" ? "Review operations" : (props.nextAction.commandLabel || props.nextAction.stage)}
      {props.nextAction.disabledReason ? <span>{props.nextAction.disabledReason}</span> : null}
      {props.meetingRoundId ? <span data-testid="meeting-round-id">{props.meetingRoundId}</span> : null}
    </div>
  ),
}));

vi.mock("../challenge-cup/HypothesisSelectionList", () => ({
  HypothesisSelectionList: (props: { compact?: boolean; lang?: "zh" | "en" }) => {
    selectionListProps(props);
    return <div data-testid="selection-list">{props.lang === "en" ? "Record selection & start review" : "记录选择并开启评审"}</div>;
  },
}));

import { HypothesisFirstNodeInspector } from "./HypothesisFirstNodeInspector";
import {
  useHypothesisFirstChain,
  type HypothesisFirstChainData,
} from "./useHypothesisFirstChain";

vi.mock("./useHypothesisFirstChain", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./useHypothesisFirstChain")>();
  return {
    ...actual,
    useHypothesisFirstChain: vi.fn(),
  };
});

const mockedChain = vi.mocked(useHypothesisFirstChain);

function chainData(overrides: Partial<HypothesisFirstChainData> = {}): HypothesisFirstChainData {
  return {
    chainState: null,
    selection: null,
    meetings: [],
    collectionRequests: [],
    reviewRoundLinks: [],
    loading: false,
    error: null,
    ...overrides,
  };
}

function scopeMeeting(overrides: Record<string, unknown> = {}) {
  return {
    program: "p",
    theme: "t",
    campaign: "c",
    question: "Q-01",
    branch: "b",
    workflow: "w",
    agentId: "a",
    schemaVersion: 1,
    meetingRoundId: "hf-gen-1",
    meetingType: "hypothesis_candidate_generation",
    mode: "generation",
    scopeHash: "sh",
    participants: ["agent-1"],
    status: "open",
    startedAt: "2026-08-19T01:00:00Z",
    ...overrides,
  };
}

let container: HTMLDivElement;
let root: Root;

function render(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() => {
    root.render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  });
}

describe("HypothesisFirstNodeInspector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it("opens generation from an empty chain", () => {
    mockedChain.mockReturnValue(chainData());
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_generation"
        runId="run-1"
        onOpenQuestion={() => {}}
      />,
    );
    expect(container.textContent).toContain("候选假说生成");
    expect(container.textContent).toContain("生成候选假说");
    expect(container.textContent).not.toContain("前往候选生成");
  });

  it("renders the empty inspector state in English without Chinese chrome", () => {
    mockedChain.mockReturnValue(chainData());
    render(
      <HypothesisFirstNodeInspector
        lang="en"
        teamId="team-1"
        questionId=""
        nodeId="hf_generation"
        onOpenQuestion={() => {}}
      />,
    );

    expect(container.textContent).toContain("Question context required");
    expect(container.textContent).toContain("Next: choose a challenge question");
    expect(container.textContent).not.toMatch(/[\u4e00-\u9fff]/);
  });

  it("gives an actionable next step for an empty inspector context", () => {
    mockedChain.mockReturnValue(chainData());
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId=""
        nodeId="hf_generation"
        onOpenQuestion={() => {}}
      />,
    );

    expect(container.textContent).toContain("缺少题目上下文");
    expect(container.textContent).toContain("下一步：先从题目总览选择一道赛题");
  });

  it("offers an in-place retry when the chain fails to load", async () => {
    const refetchQueries = vi.spyOn(QueryClient.prototype, "refetchQueries").mockResolvedValue([]);
    mockedChain.mockReturnValue(chainData({ error: "network unavailable" }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_generation"
        runId="run-1"
        onOpenQuestion={() => {}}
      />,
    );
    expect(container.textContent).toContain("假说先行链加载失败：network unavailable");
    const retry = Array.from(container.querySelectorAll("button")).find((button) => button.textContent === "重试");
    expect(retry).toBeTruthy();
    await act(async () => {
      retry?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(refetchQueries).toHaveBeenCalledWith(expect.objectContaining({
      queryKey: ["teams", "team-1", "hypothesis-first"],
      type: "active",
    }));
    refetchQueries.mockRestore();
  });

  it("shows meeting ops for a generation round ready to confirm", () => {
    mockedChain.mockReturnValue(chainData({
      meetings: [scopeMeeting({
        status: "awaiting_approval",
        digestDraft: { summary: "候选清单", proposedCandidates: [{ candidateId: "c1" }], contentHash: "h1" },
      })],
      chainState: { candidateCount: 0 } as HypothesisFirstChainData["chainState"],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_generation"
        runId="run-1"
        onOpenQuestion={() => {}}
      />,
    );
    expect(container.textContent).toContain("确认候选清单");
    expect(container.textContent).not.toContain("前往确认候选");
  });

  it("shows the r5 review operation when no formal run id exists yet", () => {
    mockedChain.mockReturnValue(chainData({
      chainState: {
        hypothesisConverged: true,
        selectionId: "sel-1",
        candidateCount: 1,
      } as HypothesisFirstChainData["chainState"],
      selection: {
        selectionId: "sel-1",
        selectedCandidateIds: ["c1"],
      } as HypothesisFirstChainData["selection"],
      meetings: [scopeMeeting({
        meetingRoundId: "r5",
        roundIndex: 5,
        meetingType: "hypothesis_review",
        status: "open",
        boundChatRoundsTerminal: true,
      })],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_meeting_5"
        onOpenQuestion={() => {}}
      />,
    );

    expect(container.querySelector('[data-testid="meeting-ops"]')?.textContent).toContain("整理本轮结论");
    expect(container.querySelector('[data-testid="meeting-round-id"]')?.textContent).toBe("r5");
    expect(container.textContent).not.toContain("选择题目开始研究");
  });

  it("does not let another question's later meeting mask the current r5 inspector", () => {
    mockedChain.mockReturnValue(chainData({
      chainState: {
        questionId: "Q-01",
        hypothesisConverged: true,
        selectionId: "sel-1",
        candidateCount: 1,
      } as HypothesisFirstChainData["chainState"],
      selection: {
        selectionId: "sel-1",
        selectedCandidateIds: ["c1"],
      } as HypothesisFirstChainData["selection"],
      meetings: [
        scopeMeeting({
          question: "Q-01",
          meetingRoundId: "r5-current",
          roundIndex: 5,
          meetingType: "hypothesis_review",
          status: "open",
          boundChatRoundsTerminal: true,
        }),
        scopeMeeting({
          question: "Q-02",
          meetingRoundId: "r6-other-question",
          roundIndex: 6,
          meetingType: "hypothesis_review",
          status: "closed",
        }),
      ],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_meeting_5"
        onOpenQuestion={() => {}}
      />,
    );

    expect(container.querySelector('[data-testid="meeting-ops"]')?.textContent).toContain("整理本轮结论");
    expect(container.querySelector('[data-testid="meeting-round-id"]')?.textContent).toBe("r5-current");
  });

  it("offers regeneration when the confirmed generation meeting produced no candidates", () => {
    mockedChain.mockReturnValue(chainData({
      meetings: [scopeMeeting({
        status: "closed",
        closedAt: "2026-08-19T02:00:00Z",
        digestDraft: { summary: "空候选清单", proposedCandidates: [], contentHash: "h-empty" },
      })],
      chainState: { candidateCount: 0 } as HypothesisFirstChainData["chainState"],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_generation"
        runId="run-1"
        onOpenQuestion={() => {}}
      />,
    );
    expect(container.textContent).toContain("重新生成候选假说");
    expect(container.querySelector('[data-testid="meeting-ops"]')).toBeNull();
  });

  it("binds generation ops to the latest attempt after a stale failed/open one", () => {
    mockedChain.mockReturnValue(chainData({
      meetings: [
        scopeMeeting({
          meetingRoundId: "hf-gen-stale",
          roundIndex: 0,
          startedAt: "2026-08-19T01:00:00Z",
          status: "open",
        }),
        scopeMeeting({
          meetingRoundId: "hf-gen-current",
          roundIndex: 1,
          startedAt: "2026-08-19T02:00:00Z",
          status: "awaiting_approval",
          digestDraft: { summary: "候选清单", proposedCandidates: [{ candidateId: "c2" }], contentHash: "h2" },
        }),
      ],
      chainState: { candidateCount: 0 } as HypothesisFirstChainData["chainState"],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_generation"
        runId="run-1"
        onOpenQuestion={() => {}}
      />,
    );
    const ops = container.querySelector('[data-testid="meeting-ops"]');
    expect(ops).toBeTruthy();
    expect(ops?.querySelector('[data-testid="meeting-round-id"]')?.textContent).toBe("hf-gen-current");
    expect(container.textContent).toContain("确认候选清单");
  });

  it("embeds the selection list on the selection card", () => {
    mockedChain.mockReturnValue(chainData({
      chainState: { candidateCount: 2 } as HypothesisFirstChainData["chainState"],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_selection"
        runId="run-1"
        onOpenQuestion={() => {}}
      />,
    );
    expect(container.textContent).toContain("假说选择");
    expect(container.querySelector('[data-testid="selection-list"]')?.textContent).toContain("记录选择并开启评审");
    expect(selectionListProps.mock.calls[0]?.[0]).toEqual(expect.objectContaining({ compact: true }));
    expect(container.textContent).toContain("打开赛题详情");
  });

  it("shows 资料搜集中 without a start-collection command", () => {
    mockedChain.mockReturnValue(chainData({
      selection: {
        program: "p", theme: "t", campaign: "c", question: "Q-01", branch: "b", workflow: "w", agentId: "a",
        schemaVersion: 1,
        selectionId: "sel-1",
        selectionHash: "h",
        mode: "manual",
        scopeHash: "sh",
        questionId: "Q-01",
        selectedCandidateIds: ["cand-1"],
        previousSelectionId: "",
        decidedBy: "leader",
        createdAt: "2026-08-19T00:00:00Z",
      },
      meetings: [scopeMeeting({
        meetingRoundId: "hf-review-1",
        meetingType: "hypothesis_review",
        status: "closed",
        roundIndex: 1,
      })],
      collectionRequests: [{
        program: "p", theme: "t", campaign: "c", question: "Q-01", branch: "b", workflow: "w", agentId: "a",
        schemaVersion: 1,
        recordKind: "hypothesis_first_collection_request",
        requestId: "req-1",
        requestHash: "rh",
        status: "running",
        meetingRoundId: "hf-review-1",
        decisionId: "dec-1",
        questionId: "Q-01",
        mode: "review",
        scopeHash: "sh",
        searchEnvelope: {},
        requirements: {},
        writebackPolicy: {},
        collectionRunId: "run-collect-1",
        createdAt: "2026-08-19T02:00:00Z",
      }],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_collection_req-1"
        runId="run-1"
        collectionChildStatus="running"
        onOpenQuestion={() => {}}
      />,
    );
    expect(container.textContent).toContain("资料搜集中");
    expect(container.textContent).not.toContain("开始资料搜集");
    expect(container.textContent).not.toContain("启动资料寻找");
    expect(container.querySelector('[role="status"]')).toBeTruthy();
  });

  it("offers handoff recovery after the child run completed", () => {
    mockedChain.mockReturnValue(chainData({
      selection: {
        program: "p", theme: "t", campaign: "c", question: "Q-01", branch: "b", workflow: "w", agentId: "a",
        schemaVersion: 1,
        selectionId: "sel-1",
        selectionHash: "h",
        mode: "manual",
        scopeHash: "sh",
        questionId: "Q-01",
        selectedCandidateIds: ["cand-1"],
        previousSelectionId: "",
        decidedBy: "leader",
        createdAt: "2026-08-19T00:00:00Z",
      },
      meetings: [scopeMeeting({
        meetingRoundId: "hf-review-1",
        meetingType: "hypothesis_review",
        status: "closed",
        roundIndex: 1,
      })],
      collectionRequests: [{
        program: "p", theme: "t", campaign: "c", question: "Q-01", branch: "b", workflow: "w", agentId: "a",
        schemaVersion: 1,
        recordKind: "hypothesis_first_collection_request",
        requestId: "req-1",
        requestHash: "rh",
        status: "completed",
        meetingRoundId: "hf-review-1",
        decisionId: "dec-1",
        questionId: "Q-01",
        mode: "review",
        scopeHash: "sh",
        searchEnvelope: {},
        requirements: {},
        writebackPolicy: {},
        collectionRunId: "run-collect-1",
        createdAt: "2026-08-19T02:00:00Z",
      }],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_collection_req-1"
        runId="run-1"
        collectionChildStatus="completed"
        onOpenQuestion={() => {}}
      />,
    );
    expect(container.textContent).toContain("重试自动交接");
  });

  it("builds retry handoff ref from the real collectionRunId, never requestId or unknown", async () => {
    mockedChain.mockReturnValue(chainData({
      selection: {
        program: "p", theme: "t", campaign: "c", question: "Q-01", branch: "b", workflow: "w", agentId: "a",
        schemaVersion: 1,
        selectionId: "sel-1",
        selectionHash: "h",
        mode: "manual",
        scopeHash: "sh",
        questionId: "Q-01",
        selectedCandidateIds: ["cand-1"],
        previousSelectionId: "",
        decidedBy: "leader",
        createdAt: "2026-08-19T00:00:00Z",
      },
      meetings: [scopeMeeting({
        meetingRoundId: "hf-review-1",
        meetingType: "hypothesis_review",
        status: "closed",
        roundIndex: 1,
      })],
      collectionRequests: [{
        program: "p", theme: "t", campaign: "c", question: "Q-01", branch: "b", workflow: "w", agentId: "a",
        schemaVersion: 1,
        recordKind: "hypothesis_first_collection_request",
        requestId: "req-1",
        requestHash: "rh",
        status: "completed",
        meetingRoundId: "hf-review-1",
        decisionId: "dec-1",
        questionId: "Q-01",
        mode: "review",
        scopeHash: "sh",
        searchEnvelope: {},
        requirements: {},
        writebackPolicy: {},
        collectionRunId: "run-collect-99",
        createdAt: "2026-08-19T02:00:00Z",
      }],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_collection_req-1"
        runId="run-1"
        collectionChildStatus="completed"
        onOpenQuestion={() => {}}
      />,
    );
    const button = [...container.querySelectorAll("button")].find((el) => el.textContent?.includes("重试自动交接"));
    expect(button).toBeTruthy();
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    expect(mockedRecordCollectionHandoff).toHaveBeenCalledTimes(1);
    const [teamId, requestId, body] = mockedRecordCollectionHandoff.mock.calls[0];
    expect(teamId).toBe("team-1");
    expect(requestId).toBe("req-1");
    expect(body.handoffRef).toBe("source_collection_run:run-collect-99");
    expect(body.handoffRef).not.toContain("req-1");
    expect(body.handoffRef).not.toContain("unknown");
  });

  it("does not issue a misleading handoff when no collection run is bound", () => {
    mockedChain.mockReturnValue(chainData({
      selection: {
        program: "p", theme: "t", campaign: "c", question: "Q-01", branch: "b", workflow: "w", agentId: "a",
        schemaVersion: 1,
        selectionId: "sel-1",
        selectionHash: "h",
        mode: "manual",
        scopeHash: "sh",
        questionId: "Q-01",
        selectedCandidateIds: ["cand-1"],
        previousSelectionId: "",
        decidedBy: "leader",
        createdAt: "2026-08-19T00:00:00Z",
      },
      meetings: [scopeMeeting({
        meetingRoundId: "hf-review-1",
        meetingType: "hypothesis_review",
        status: "closed",
        roundIndex: 1,
      })],
      collectionRequests: [{
        program: "p", theme: "t", campaign: "c", question: "Q-01", branch: "b", workflow: "w", agentId: "a",
        schemaVersion: 1,
        recordKind: "hypothesis_first_collection_request",
        requestId: "req-1",
        requestHash: "rh",
        status: "completed",
        meetingRoundId: "hf-review-1",
        decisionId: "dec-1",
        questionId: "Q-01",
        mode: "review",
        scopeHash: "sh",
        searchEnvelope: {},
        requirements: {},
        writebackPolicy: {},
        collectionRunId: "",
        createdAt: "2026-08-19T02:00:00Z",
      }],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_collection_req-1"
        runId="run-1"
        collectionChildStatus="completed"
        onOpenQuestion={() => {}}
      />,
    );
    const button = [...container.querySelectorAll("button")].find((el) => el.textContent?.includes("重试自动交接"));
    expect(button).toBeUndefined();
    expect(container.textContent).toContain("缺少子运行标识");
    expect(mockedRecordCollectionHandoff).not.toHaveBeenCalled();
  });

  it("surfaces human adjudication on the convergence gate", () => {
    mockedChain.mockReturnValue(chainData({
      chainState: {
        schemaVersion: 1,
        teamId: "team-1",
        questionId: "Q-01",
        selectionId: "sel-1",
        meetingCount: 3,
        firstMeetingId: "hf-review-1",
        firstMeetingClosed: true,
        openMeetingIds: [],
        collectionRequests: [],
        collectionRequestCount: 0,
        pendingCollectionCount: 0,
        collectionReady: false,
        hypothesisRoundCount: 2,
        latestHypothesisRoundId: "hr-2",
        hypothesisConverged: false,
        convergenceDetail: "",
        roundBudget: 3,
        budgetExhausted: true,
        templateBaselineExists: false,
        templateBaselineIds: [],
      },
    }));
    const onOpenQuestion = vi.fn();
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_convergence_gate"
        runId="run-1"
        onOpenQuestion={onOpenQuestion}
      />,
    );
    expect(container.textContent).toContain("假说收敛门");
    expect(container.textContent).toContain("人工裁决");
    expect(container.querySelector('[role="status"]')).toBeTruthy();
  });

  it("keeps future-node inspectors scoped and routes back to the actual current step", async () => {
    mockedChain.mockReturnValue(chainData({
      meetings: [scopeMeeting({ status: "open" })],
      chainState: { candidateCount: 0 } as HypothesisFirstChainData["chainState"],
    }));
    const onNavigateToNode = vi.fn();
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_convergence_gate"
        runId="run-1"
        onOpenQuestion={() => {}}
        onNavigateToNode={onNavigateToNode}
      />,
    );
    expect(container.textContent).toContain("假说收敛门");
    expect(container.textContent).toContain("前序任务尚未完成");
    expect(container.textContent).toContain("前往当前步骤");
    expect(container.textContent).not.toContain("讨论进行中");
    expect(container.querySelector('[data-testid="meeting-ops"]')).toBeNull();

    const button = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes("前往当前步骤"));
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onNavigateToNode).toHaveBeenCalledWith("hf_generation");
  });

  it("shows the loading surface while the chain is loading", () => {
    mockedChain.mockReturnValue(chainData({ loading: true }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_selection"
        onOpenQuestion={() => {}}
      />,
    );
    expect(container.textContent).toContain("加载假说先行任务");
  });
});
