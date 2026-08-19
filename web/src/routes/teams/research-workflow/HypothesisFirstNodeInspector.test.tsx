/**
 * HypothesisFirstNodeInspector (HFC-4): summary facts per region card kind and
 * the deep link into the question detail panel.
 *
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import { HypothesisFirstNodeInspector } from "./HypothesisFirstNodeInspector";
import {
  useHypothesisFirstChain,
  type HypothesisFirstChainData,
} from "./useHypothesisFirstChain";

vi.mock("./useHypothesisFirstChain", () => ({
  useHypothesisFirstChain: vi.fn(),
}));

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

let container: HTMLDivElement;
let root: Root;

function render(ui: React.ReactElement) {
  act(() => {
    root.render(ui);
  });
}

describe("HypothesisFirstNodeInspector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  it("summarizes the selection card and deep-links to the question detail", () => {
    mockedChain.mockReturnValue(chainData({
      selection: {
        program: "p", theme: "t", campaign: "c", question: "Q-01", branch: "b", workflow: "w", agentId: "a",
        schemaVersion: 1,
        selectionId: "sel-1",
        selectionHash: "h",
        mode: "manual",
        scopeHash: "sh",
        questionId: "Q-01",
        selectedCandidateIds: ["cand-1", "cand-2", "cand-3"],
        previousSelectionId: "",
        decidedBy: "leader",
        createdAt: "2026-08-19T00:00:00Z",
      },
    }));
    const onOpenQuestion = vi.fn();
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_selection"
        onOpenQuestion={onOpenQuestion}
      />,
    );

    expect(container.textContent).toContain("假说选择");
    expect(container.textContent).toContain("已选候选：3 个");
    expect(container.textContent).toContain("决策人：leader");

    const button = container.querySelector("button")!;
    expect(button.textContent).toContain("打开赛题详情");
    act(() => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onOpenQuestion).toHaveBeenCalledWith("Q-01");
  });

  it("summarizes a meeting card with its status and digest state", () => {
    mockedChain.mockReturnValue(chainData({
      meetings: [{
        program: "p", theme: "t", campaign: "c", question: "Q-01", branch: "b", workflow: "w", agentId: "a",
        schemaVersion: 1,
        meetingRoundId: "hf-review-sel-1-r2",
        meetingType: "hypothesis_review",
        mode: "review",
        scopeHash: "sh",
        participants: ["agent-1", "agent-2"],
        status: "awaiting_approval",
        startedAt: "2026-08-19T01:00:00Z",
        roundIndex: 2,
      }],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_meeting_2"
        onOpenQuestion={() => {}}
      />,
    );

    expect(container.textContent).toContain("第 2 轮讨论·评审");
    expect(container.textContent).toContain("等待人工确认闭环");
    expect(container.textContent).toContain("参与 Agent：2 个");
    expect(container.textContent).toContain("纪要：未生成");
  });

  it("summarizes a collection card with run and handoff facts", () => {
    mockedChain.mockReturnValue(chainData({
      collectionRequests: [{
        program: "p", theme: "t", campaign: "c", question: "Q-01", branch: "b", workflow: "w", agentId: "a",
        schemaVersion: 1,
        recordKind: "hypothesis_first_collection_request",
        requestId: "req-1",
        requestHash: "rh",
        status: "handed_off",
        meetingRoundId: "hf-review-sel-1-r1",
        decisionId: "dec-1",
        questionId: "Q-01",
        mode: "review",
        scopeHash: "sh",
        searchEnvelope: { gap: "缺少对比实验" },
        requirements: {},
        writebackPolicy: {},
        collectionRunId: "run-collect-1",
        createdAt: "2026-08-19T02:00:00Z",
        handedOffAt: "2026-08-19T03:00:00Z",
        handoffRef: "kp-1",
      }],
    }));
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_collection_req-1"
        onOpenQuestion={() => {}}
      />,
    );

    expect(container.textContent).toContain("资料搜集");
    expect(container.textContent).toContain("已交接");
    expect(container.textContent).toContain("run-collect-1");
    expect(container.textContent).toContain("缺少对比实验");
  });

  it("summarizes the convergence gate with budget exhaustion", () => {
    mockedChain.mockReturnValue(chainData({
      chainState: {
        schemaVersion: 1,
        teamId: "team-1",
        questionId: "Q-01",
        selectionId: "sel-1",
        meetingCount: 3,
        firstMeetingId: "hf-review-sel-1-r1",
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
    render(
      <HypothesisFirstNodeInspector
        teamId="team-1"
        questionId="Q-01"
        nodeId="hf_convergence_gate"
        onOpenQuestion={() => {}}
      />,
    );

    expect(container.textContent).toContain("假说收敛门");
    expect(container.textContent).toContain("轮次预算耗尽，等待人工决策");
    expect(container.textContent).toContain("讨论轮次：3 / 预算 3");
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
    expect(container.textContent).toContain("加载假说先行链");
  });
});
