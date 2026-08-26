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
import type { HypothesisFirstStateV2 } from "../../../api/types/hypothesisFirst";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const selectionListProps = vi.hoisted(() => vi.fn());
const reviewFormProps = vi.hoisted(() => vi.fn());

vi.mock("../../../api/chat", () => ({
  fetchChatRoomDetail: vi.fn().mockResolvedValue({ rounds: [] }),
}));

vi.mock("../../../api/hypothesisFirst", () => ({
  recordCollectionHandoff: vi.fn().mockResolvedValue({}),
  openHypothesisCandidateGeneration: vi.fn().mockResolvedValue({}),
  executeHypothesisFirstCommand: vi.fn().mockResolvedValue({ result: {} }),
  isHypothesisFirstCommandStateConflict: vi.fn().mockReturnValue(false),
}));

vi.mock("../../../api/challengeQuestionRuns", () => ({
  getChallengeQuestionRunDetail: vi.fn(),
}));

vi.mock("../challenge-cup/ChallengeQuestionReviewForm", () => ({
  ChallengeQuestionReviewForm: (props: { detail: { selectedRunId: string }; allowLegacyMutation?: boolean }) => {
    reviewFormProps(props);
    return <div data-testid="program-review-form">review:{props.detail.selectedRunId}</div>;
  },
}));

import {
  executeHypothesisFirstCommand,
  recordCollectionHandoff,
} from "../../../api/hypothesisFirst";
import { fetchChatRoomDetail } from "../../../api/chat";
import { getChallengeQuestionRunDetail } from "../../../api/challengeQuestionRuns";
const mockedRecordCollectionHandoff = vi.mocked(recordCollectionHandoff);
const mockedExecuteCommand = vi.mocked(executeHypothesisFirstCommand);
const mockedFetchChatRoomDetail = vi.mocked(fetchChatRoomDetail);
const mockedGetChallengeQuestionRunDetail = vi.mocked(getChallengeQuestionRunDetail);

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

import {
  HypothesisFirstNodeInspector,
  inspectorNodeOwnsCurrentStep,
} from "./HypothesisFirstNodeInspector";
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

function scopeReviewLink(meetingRoundId: string, roundIndex: number) {
  return {
    schemaVersion: 1,
    recordKind: "hypothesis_first_review_round_link",
    linkId: `link-${meetingRoundId}`,
    meetingRoundId,
    previousMeetingRoundId: roundIndex > 1 ? `r${roundIndex - 1}` : "",
    selectionId: "sel-1",
    collectionRequestId: "",
    questionId: "Q-01",
    roundIndex,
    candidateId: "cand-1",
    createdAt: `2026-08-19T0${roundIndex}:00:01Z`,
  };
}

function programState(
  currentPhase: "program_delivery" | "completed",
  overrides: Partial<HypothesisFirstStateV2["programDelivery"]> = {},
): HypothesisFirstStateV2 {
  return {
    currentPhase,
    generation: { generationMeetingId: null },
    review: { candidates: [], aggregate: { total: 0, completed: 0, pending: 0, failed: 0, blocked: 0 } },
    collection: { requests: [] },
    allowedActions: [],
    problems: [],
    programDelivery: {
      lifecycle: currentPhase === "completed" ? "completed" : "waiting_human",
      outcome: currentPhase === "completed" ? "succeeded" : "none",
      actionability: currentPhase === "completed" ? "terminal" : "waiting_user",
      attempt: null,
      updatedAt: null,
      problems: [],
      deliveryStatus: "succeeded",
      deliveryArtifactRef: "artifact:delivery-1",
      handoffStatus: "registered",
      outputRecordId: "record-1",
      outputRunId: "run-output-1",
      humanReviewStatus: currentPhase === "completed" ? "approved" : "waiting_human",
      humanGates: {
        decisions: {
          H1_problem_understanding: currentPhase === "completed" ? "approved" : "pending",
          H2_hypothesis_selection: currentPhase === "completed" ? "approved" : "pending",
          H3_research_plan: currentPhase === "completed" ? "approved" : "pending",
          H4_external_output: currentPhase === "completed" ? "approved" : "pending",
        },
        reviewer: null,
        rationale: null,
        decidedAt: null,
      },
      approvedGateCount: currentPhase === "completed" ? 4 : 0,
      requiredGateCount: 4,
      ...overrides,
    },
  } as HypothesisFirstStateV2;
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
  it("fails closed when the current task target cannot be resolved", () => {
    expect(inspectorNodeOwnsCurrentStep("hf_meeting_1", null)).toBe(false);
    expect(inspectorNodeOwnsCurrentStep("hf_meeting_1", "hf_meeting_1")).toBe(true);
    expect(inspectorNodeOwnsCurrentStep("hf_meeting_1", "hf_collection_1")).toBe(false);
    expect(inspectorNodeOwnsCurrentStep("hf_review", "hf_meeting_5")).toBe(true);
    expect(inspectorNodeOwnsCurrentStep("hf_collection", "source_finding")).toBe(true);
  });

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

  it("loads only the server-authored scoped room and never the meeting fallback room", async () => {
    mockedChain.mockReturnValue(chainData({
      meetings: [scopeMeeting({ linkedChatRoomId: "team-public-room" })],
      chainState: { candidateCount: 0 } as HypothesisFirstChainData["chainState"],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_generation"
        runId="run-1"
        discussionModel={{
          status: "ready",
          degradedReason: "",
          scope: {
            version: 1,
            kind: "question_generation",
            teamId: "team-1",
            researchProjectId: "project-1",
            workflowRunId: "run-1",
            workflowNodeId: "hf_generation",
            questionId: "Q-01",
          },
          scopeHash: "scope-hash",
          roomId: "scoped-room-1",
          meetingRoundId: "hf-gen-1",
          questionId: "Q-01",
          selectionId: "",
          candidateId: "",
          query: { kind: "room", room: "scoped-room-1" },
          search: "?room=scoped-room-1",
          deepLink: "/chat?room=scoped-room-1",
          selectedRoundId: "",
        }}
        onOpenQuestion={() => {}}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    const queriedRoomIds = mockedFetchChatRoomDetail.mock.calls.map(([roomId]) => roomId);
    expect(queriedRoomIds).toContain("scoped-room-1");
    expect(queriedRoomIds).not.toContain("team-public-room");
  });

  it("does not read any room when the canonical anchor is degraded", async () => {
    mockedChain.mockReturnValue(chainData({
      meetings: [scopeMeeting({ linkedChatRoomId: "team-public-room" })],
      chainState: { candidateCount: 0 } as HypothesisFirstChainData["chainState"],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_generation"
        runId="run-1"
        discussionModel={{
          status: "degraded",
          degradedReason: "active_discussion_room_missing",
          scope: null,
          scopeHash: "",
          roomId: "",
          meetingRoundId: "",
          questionId: "Q-01",
          selectionId: "",
          candidateId: "",
          query: null,
          search: "",
          deepLink: "",
          selectedRoundId: "",
        }}
        onOpenQuestion={() => {}}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(mockedFetchChatRoomDetail).not.toHaveBeenCalled();
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
        meetingType: "hypothesis_review",
        status: "open",
        boundChatRoundsTerminal: true,
      })],
      reviewRoundLinks: [scopeReviewLink("r5", 5)],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_meeting_5_cand-1"
        onOpenQuestion={() => {}}
      />,
    );

    expect(container.querySelector('[data-testid="meeting-ops"]')?.textContent).toContain("整理本轮结论");
    expect(container.querySelector('[data-testid="meeting-round-id"]')?.textContent).toBe("r5");
    expect(container.textContent).not.toContain("选择题目开始研究");
  });

  it("keeps the review inspector on the current selection lineage", () => {
    mockedChain.mockReturnValue(chainData({
      chainState: {
        hypothesisConverged: true,
        selectionId: "sel-2",
        candidateCount: 1,
      } as HypothesisFirstChainData["chainState"],
      selection: { selectionId: "sel-2", selectedCandidateIds: ["c2"] } as HypothesisFirstChainData["selection"],
      meetings: [
        scopeMeeting({
          meetingRoundId: "old-r9",
          meetingType: "hypothesis_review",
          selectionId: "sel-1",
          roundIndex: 9,
          status: "open",
        }),
        scopeMeeting({
          meetingRoundId: "current-r2",
          meetingType: "hypothesis_review",
          selectionId: "sel-2",
          roundIndex: 2,
          status: "open",
        }),
      ],
      reviewRoundLinks: [
        scopeReviewLink("old-r9", 9),
        { ...scopeReviewLink("current-r2", 2), selectionId: "sel-2" },
      ],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_meeting_2_cand-1"
        onOpenQuestion={() => {}}
      />,
    );

    expect(container.querySelector('[data-testid="meeting-round-id"]')?.textContent).toBe("current-r2");
  });

  it("keeps every candidate confirmation visible after one sibling closes", () => {
    const onNavigateToNode = vi.fn();
    mockedChain.mockReturnValue(chainData({
      chainState: {
        selectionId: "sel-1",
        candidateCount: 2,
      } as HypothesisFirstChainData["chainState"],
      selection: {
        selectionId: "sel-1",
        selectedCandidateIds: ["cand-a", "cand-b"],
      } as HypothesisFirstChainData["selection"],
      meetings: [
        scopeMeeting({ meetingRoundId: "r4-old", meetingType: "hypothesis_review", roundIndex: 4, status: "closed" }),
        scopeMeeting({ meetingRoundId: "r5-a", meetingType: "hypothesis_review", roundIndex: 5, status: "closed" }),
        scopeMeeting({ meetingRoundId: "r5-b", meetingType: "hypothesis_review", roundIndex: 5, status: "awaiting_approval" }),
      ],
      reviewRoundLinks: [
        { ...scopeReviewLink("r4-old", 4), candidateId: "cand-old" },
        { ...scopeReviewLink("r5-a", 5), candidateId: "cand-a" },
        { ...scopeReviewLink("r5-b", 5), candidateId: "cand-b" },
      ],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_review"
        onOpenQuestion={() => {}}
        onNavigateToNode={onNavigateToNode}
      />,
    );

    expect(container.querySelector('[data-testid="candidate-confirmation-checklist"]')?.textContent).toContain("共 2 · 已确认 1 · 待确认 1");
    expect(container.textContent).toContain("候选 cand-a");
    expect(container.textContent).toContain("候选 cand-b");
    expect(container.querySelector('[data-testid="candidate-confirmation-checklist"]')?.textContent).not.toContain("cand-old");
    const candidateButtons = Array.from(container.querySelectorAll("button"))
      .filter((button) => button.textContent === "查看该候选评审");
    act(() => {
      candidateButtons[0]?.click();
    });
    expect(onNavigateToNode).toHaveBeenCalledWith("hf_meeting_5_cand-a");
  });

  it("renders the candidate checklist directly from canonical V2 without legacy meeting projection", () => {
    const basePhase = {
      lifecycle: "waiting_human" as const,
      outcome: "none" as const,
      actionability: "waiting_user" as const,
      attempt: null,
      updatedAt: null,
      problems: [],
    };
    const candidate = (candidateId: string, completed: boolean) => ({
      ...basePhase,
      lifecycle: completed ? "completed" as const : "waiting_human" as const,
      outcome: completed ? "succeeded" as const : "none" as const,
      actionability: completed ? "terminal" as const : "waiting_user" as const,
      candidateId,
      candidateOrder: candidateId === "cand-a" ? 1 : 2,
      selectionId: "selection-v2",
      roundIndex: 5,
      meetingRoundId: `meeting-${candidateId}`,
      discussionAnchor: null,
      discussion: { ...basePhase, lifecycle: "completed" as const, outcome: "succeeded" as const, actionability: "terminal" as const },
      summarization: { ...basePhase, lifecycle: "completed" as const, outcome: "succeeded" as const, actionability: "terminal" as const },
      approval: completed
        ? { ...basePhase, lifecycle: "completed" as const, outcome: "succeeded" as const, actionability: "terminal" as const }
        : basePhase,
    });
    mockedChain.mockReturnValue(chainData({
      stateV2: {
        currentPhase: "review",
        generation: { generationMeetingId: null },
        review: {
          ...basePhase,
          activeRoundIndex: 5,
          aggregate: { total: 2, completed: 1, pending: 1, failed: 0, blocked: 0 },
          candidates: [candidate("cand-a", true), candidate("cand-b", false)],
        },
        collection: { requests: [] },
        allowedActions: [],
        problems: [],
      } as HypothesisFirstStateV2,
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_review"
        onOpenQuestion={() => {}}
        onNavigateToNode={() => {}}
      />,
    );
    const checklist = container.querySelector('[data-testid="candidate-confirmation-checklist"]');
    expect(checklist?.textContent).toContain("候选 cand-a");
    expect(checklist?.textContent).toContain("候选 cand-b");
    expect(checklist?.textContent).toContain("共 2 · 已确认 1 · 待确认 1");
    expect(container.querySelector('[data-testid="meeting-round-id"]')?.textContent).toContain("meeting-cand-b");
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
    expect(selectionListProps.mock.calls[0]?.[0]).toEqual(expect.objectContaining({
      compact: true,
      allowLegacyMutation: true,
    }));
    expect(container.textContent).toContain("打开题目档案");
  });

  it("shows effective review rounds as read-only history on the semantic review node", () => {
    mockedChain.mockReturnValue(chainData({
      chainState: {
        questionId: "Q-01",
        selectionId: "sel-1",
        hypothesisConverged: true,
      } as HypothesisFirstChainData["chainState"],
      selection: {
        questionId: "Q-01",
        selectionId: "sel-1",
        selectedCandidateIds: ["c1"],
      } as HypothesisFirstChainData["selection"],
      meetings: [
        scopeMeeting({ meetingRoundId: "r1", meetingType: "hypothesis_review", status: "closed", roundIndex: 1, digestId: "d1" }),
        scopeMeeting({ meetingRoundId: "r2", meetingType: "hypothesis_review", status: "closed", roundIndex: 2, recoveryReason: "discussion_has_no_completed_messages" }),
        scopeMeeting({ meetingRoundId: "r3", meetingType: "hypothesis_review", status: "closed", roundIndex: 3, digestId: "d3" }),
      ] as HypothesisFirstChainData["meetings"],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_review"
        runId="run-1"
        onOpenQuestion={() => {}}
      />,
    );

    expect(container.textContent).toContain("2 轮有效评审");
    expect(container.textContent).toContain("1 次失败重试");
    expect(container.textContent).toContain("第 1 轮");
    expect(container.textContent).toContain("第 3 轮");
    expect(container.textContent).not.toContain("第 2 轮");
  });

  it("groups parallel candidate meetings into one review round", () => {
    mockedChain.mockReturnValue(chainData({
      chainState: {
        questionId: "Q-01",
        selectionId: "sel-1",
      } as HypothesisFirstChainData["chainState"],
      selection: {
        questionId: "Q-01",
        selectionId: "sel-1",
        selectedCandidateIds: ["cand-a", "cand-b"],
      } as HypothesisFirstChainData["selection"],
      meetings: [
        scopeMeeting({ meetingRoundId: "r1-a", meetingType: "hypothesis_review", status: "closed", roundIndex: 1, digestId: "d1-a" }),
        scopeMeeting({ meetingRoundId: "r1-b", meetingType: "hypothesis_review", status: "open", roundIndex: 1 }),
      ] as HypothesisFirstChainData["meetings"],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_review"
        runId="run-1"
        onOpenQuestion={() => {}}
      />,
    );

    expect(container.textContent).toContain("1 轮有效评审");
    expect(container.textContent?.match(/第 1 轮/g)).toHaveLength(1);
    expect(container.textContent).toContain("本轮 2 个候选评审，已归档 1/2");
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

  it("opens the created formal run from the signed convergence command result", async () => {
    const phase = {
      lifecycle: "completed",
      outcome: "succeeded",
      actionability: "terminal",
      attempt: null,
      updatedAt: null,
      problems: [],
    } as const;
    const action = {
      kind: "command",
      actionId: "create-formal-run:round-1",
      label: "创建正式研究运行",
      enabled: true,
      disabledReason: null,
      targetPhase: "formal_runtime",
      targetNodeId: "formal_runtime",
      command: "create_formal_run",
      payload: { questionId: "Q-01", hypothesisRoundId: "round-1" },
      inputSchemaRef: null,
      idempotencyKey: "hf2:create-formal-run:round-1",
      expectedStateVersion: "hf2-state:before-create",
      requiresConfirmation: false,
      confirmationText: null,
    } as const;
    mockedExecuteCommand.mockResolvedValueOnce({
      schemaVersion: 2,
      teamId: "team-1",
      questionId: "Q-01",
      command: "create_formal_run",
      actionId: action.actionId,
      idempotencyKey: action.idempotencyKey,
      acceptedStateVersion: action.expectedStateVersion,
      result: { runId: "run-formal-1", activeNodeId: "problem_understanding" },
    });
    mockedChain.mockReturnValue(chainData({
      stateV2: {
        currentPhase: "formal_runtime",
        generation: { generationMeetingId: null },
        review: { candidates: [], aggregate: { total: 0, completed: 0, pending: 0, failed: 0, blocked: 0 } },
        collection: { requests: [] },
        convergence: { ...phase, accepted: true, latestHypothesisRoundId: "round-1", roundIndex: 1, roundBudget: 3 },
        formalRuntime: {
          lifecycle: "not_started",
          outcome: "none",
          actionability: "available",
          attempt: null,
          updatedAt: null,
          problems: [],
          runId: null,
          runVersion: null,
          runStatus: "not_started",
          completionKind: null,
          lineageDisposition: "none",
          isCurrentRevision: false,
          parentRunId: null,
          childRunIds: [],
          currentNodeIds: [],
        },
        allowedActions: [action],
        problems: [],
      } as HypothesisFirstStateV2,
    }));
    const onFormalRunCreated = vi.fn();
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_convergence_gate"
        onOpenQuestion={() => {}}
        onFormalRunCreated={onFormalRunCreated}
      />,
    );

    const button = [...container.querySelectorAll("button")]
      .find((item) => item.textContent?.includes("创建正式研究运行"));
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await vi.waitFor(() => expect(onFormalRunCreated).toHaveBeenCalledTimes(1));
    });

    expect(mockedExecuteCommand).toHaveBeenCalledWith("team-1", "Q-01", action);
    expect(onFormalRunCreated).toHaveBeenCalledWith({
      runId: "run-formal-1",
      nodeId: "problem_understanding",
      questionId: "Q-01",
    });
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

  it("loads the registered output and renders H1-H4 review in program delivery", async () => {
    mockedGetChallengeQuestionRunDetail.mockResolvedValue({ selectedRunId: "run-output-1" } as never);
    mockedChain.mockReturnValue(chainData({ stateV2: programState("program_delivery") }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_convergence_gate"
        onOpenQuestion={() => {}}
      />,
    );
    await act(async () => {
      await new Promise((resolve) => globalThis.setTimeout(resolve, 0));
    });
    expect(mockedGetChallengeQuestionRunDetail).toHaveBeenCalledWith("team-1", "Q-01", "run-output-1");
    expect(container.querySelector('[data-testid="program-review-form"]')?.textContent).toContain("run-output-1");
    expect(reviewFormProps.mock.calls[0]?.[0]).toEqual(expect.objectContaining({
      allowLegacyMutation: false,
    }));
  });

  it("shows the canonical program delivery problem instead of falling back upstream", () => {
    mockedChain.mockReturnValue(chainData({
      stateV2: programState("program_delivery", {
        actionability: "blocked",
        lifecycle: "failed",
        problems: [{
          code: "program_candidate_handoff_needs_context",
          category: "dependency",
          severity: "error",
          message: "正式结果缺少交付上下文",
          recoverable: true,
          sourceKind: "delivery",
          sourceId: "run-output-1",
          detectedAt: "2026-08-25T00:00:00Z",
        }],
      }),
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_convergence_gate"
        onOpenQuestion={() => {}}
      />,
    );
    expect(container.textContent).toContain("正式结果缺少交付上下文");
    expect(container.querySelector('[data-testid="program-review-form"]')).toBeNull();
  });

  it("shows all formal runtime recovery actions on the current task inspector", async () => {
    const phase = {
      lifecycle: "waiting_user" as const,
      outcome: "none" as const,
      actionability: "blocked" as const,
      attempt: null,
      updatedAt: null,
      problems: [],
    };
    const reconcile = {
      kind: "command" as const,
      actionId: "formal:reconcile",
      label: "核对正式运行状态",
      enabled: true,
      disabledReason: null,
      targetPhase: "formal_runtime" as const,
      targetNodeId: null,
      command: "reconcile_formal_run" as const,
      payload: { runId: "formal-run-1" },
      inputSchemaRef: null,
      idempotencyKey: "formal:reconcile:1",
      expectedStateVersion: "state-1",
      requiresConfirmation: false,
      confirmationText: null,
    };
    const stop = {
      ...reconcile,
      actionId: "formal:stop",
      label: "停止正式运行",
      command: "stop_discussion" as const,
      payload: { meetingRoundId: "formal-run-1" },
      requiresConfirmation: true,
      confirmationText: "停止后需要重新确认正式运行状态。",
    };
    const archive = {
      ...reconcile,
      actionId: "formal:archive",
      label: "归档正式运行",
      command: "archive_run" as const,
      payload: { runId: "formal-run-1" },
      requiresConfirmation: true,
      confirmationText: "归档后可重新创建正式运行。",
    };
    mockedChain.mockReturnValue(chainData({
      stateV2: {
        currentPhase: "formal_runtime",
        generation: { generationMeetingId: null },
        review: { candidates: [], aggregate: { total: 0, completed: 0, pending: 0, failed: 0, blocked: 0 } },
        collection: { requests: [] },
        convergence: { ...phase, accepted: true, latestHypothesisRoundId: "round-1", roundIndex: 1, roundBudget: 3 },
        formalRuntime: {
          ...phase,
          runId: "formal-run-1",
          runVersion: 2,
          runStatus: "reconciliation_required",
          completionKind: null,
          lineageDisposition: "current",
          isCurrentRevision: true,
          parentRunId: null,
          childRunIds: [],
          currentNodeIds: ["protocol_design"],
        },
        allowedActions: [reconcile, stop, archive],
        problems: [],
      } as HypothesisFirstStateV2,
    }));

    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="protocol_design"
        runId="formal-run-1"
        formalRuntime
        onOpenQuestion={() => {}}
      />,
    );

    const actionList = container.querySelector('[data-testid="canonical-command-action-list"]');
    expect(actionList).toBeTruthy();
    expect(actionList?.textContent).toContain("核对正式运行状态");
    expect(actionList?.textContent).toContain("停止正式运行");
    expect(actionList?.textContent).toContain("归档正式运行");
    expect(container.textContent).toContain("状态待确认");

    const archiveButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent?.includes("归档正式运行"));
    await act(async () => {
      archiveButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(mockedExecuteCommand).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain("归档后可重新创建正式运行。");

    const confirmButton = Array.from(document.body.querySelectorAll("button"))
      .find((button) => button.textContent?.includes("确认执行"));
    await act(async () => {
      confirmButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(mockedExecuteCommand).toHaveBeenCalledWith("team-1", "Q-01", archive);
  });

  it("renders every formal delivery problem instead of only the first message", () => {
    mockedChain.mockReturnValue(chainData({
      stateV2: programState("program_delivery", {
        actionability: "blocked",
        lifecycle: "failed",
        problems: [
          {
            code: "missing-context",
            category: "dependency",
            severity: "error",
            message: "正式结果缺少交付上下文",
            recoverable: true,
            sourceKind: "delivery",
            sourceId: "run-output-1",
            detectedAt: "2026-08-25T00:00:00Z",
          },
          {
            code: "missing-receipt",
            category: "integrity",
            severity: "error",
            message: "缺少正式模型调用凭证",
            recoverable: true,
            sourceKind: "delivery",
            sourceId: "run-output-1",
            detectedAt: "2026-08-25T00:00:00Z",
          },
        ],
      }),
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_convergence_gate"
        onOpenQuestion={() => {}}
      />,
    );

    const summary = container.querySelector('[data-vui="error-summary"]');
    expect(summary?.textContent).toContain("正式结果缺少交付上下文");
    expect(summary?.textContent).toContain("缺少正式模型调用凭证");
    expect(summary?.querySelectorAll("li")).toHaveLength(2);
  });

  it("shows a terminal closure after all four program gates are approved", () => {
    mockedChain.mockReturnValue(chainData({ stateV2: programState("completed") }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_convergence_gate"
        onOpenQuestion={() => {}}
      />,
    );
    expect(container.querySelector('[data-testid="challenge-cup-workflow-completed"]')).toBeTruthy();
    expect(container.textContent).toContain("H1–H4 四项审核全部通过");
  });
});
