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

vi.mock("../../../api/chat", () => ({
  fetchChatRoomDetail: vi.fn().mockResolvedValue({ rounds: [] }),
}));

vi.mock("./HypothesisFirstMeetingOps", () => ({
  HypothesisFirstMeetingOps: (props: { nextAction: { commandLabel?: string; stage: string; disabledReason?: string } }) => (
    <div data-testid="meeting-ops">
      {props.nextAction.commandLabel || props.nextAction.stage}
      {props.nextAction.disabledReason ? <span>{props.nextAction.disabledReason}</span> : null}
    </div>
  ),
}));

vi.mock("../challenge-cup/HypothesisSelectionList", () => ({
  HypothesisSelectionList: () => <div data-testid="selection-list">记录选择并开启评审</div>,
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
