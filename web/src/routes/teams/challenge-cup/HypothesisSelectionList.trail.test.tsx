/** @vitest-environment happy-dom */
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../api/hypothesisFirst", () => ({
  fetchHypothesisSelectionContext: vi.fn(),
  fetchCandidateEvidenceTrail: vi.fn(),
  recordHypothesisSelection: vi.fn(),
}));
vi.mock("../../../api/queryKeys", () => ({
  queryKeys: {
    hypothesisFirstSelectionContext: () => ["selection-context"],
    teamMeetingRound: () => ["meeting-round"],
    chatRoom: () => ["chat-room"],
  },
}));

import {
  fetchCandidateEvidenceTrail,
  fetchHypothesisSelectionContext,
} from "../../../api/hypothesisFirst";
import { HypothesisSelectionList } from "./HypothesisSelectionList";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const mockedContext = vi.mocked(fetchHypothesisSelectionContext);
const mockedTrail = vi.mocked(fetchCandidateEvidenceTrail);

function candidateContext() {
  return {
    schemaVersion: 1,
    teamId: "team-1",
    questionId: "SCI-001",
    scope: {
      program: "p",
      theme: "t",
      campaign: "c",
      question: "SCI-001",
      branch: "main",
      workflow: "hypothesis_first",
    },
    mode: "dev",
    candidates: [
      {
        hypothesis_id: "sci-001-x",
        statement: "素数是整数乘法的原子单元",
        mechanism: "算术基本定理保证唯一分解",
        novelty_basis: "",
        falsifiability: "",
        predictions: [],
        supporting_evidence_refs: [],
        challenging_evidence_refs: [],
        boundary_conditions: [],
      },
    ],
    defaultSelectedCandidateIds: [],
    latestSelection: null,
  } as never;
}

describe("candidate evidence trail expansion", () => {
  let container: HTMLDivElement;
  let root: Root;
  let queryClient: QueryClient;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, structuralSharing: false }, mutations: { retry: false } },
    });
    mockedContext.mockResolvedValue(candidateContext());
    mockedTrail.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      questionId: "SCI-001",
      trails: [
        {
          candidateId: "sci-001-x",
          entries: [
            {
              meetingRoundId: "mr-1",
              meetingLabel: "评审 r1",
              messageId: "m-1",
              speaker: "A016",
              excerpt: "sci-001-x 的机制锚点可追溯（Hardy & Wright 第1章）",
              createdAt: "2026-08-20T01:00:00Z",
            },
          ],
        },
      ],
    } as never);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    queryClient.clear();
    vi.clearAllMocks();
  });

  it("expands a cited discussion trail from the candidate card", async () => {
    act(() => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <HypothesisSelectionList teamId="team-1" questionId="SCI-001" />
        </QueryClientProvider>,
      );
    });
    await act(async () => {
      await vi.waitFor(() =>
        expect(container.textContent).toContain("素数是整数乘法的原子单元"),
      );
      await vi.waitFor(() =>
        expect(container.textContent).toContain("查看证据轨迹"),
      );
    });
    expect(container.textContent).not.toContain("Hardy & Wright");

    const toggle = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("查看证据轨迹"),
    );
    expect(toggle).toBeDefined();
    await act(async () => {
      toggle?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await vi.waitFor(() =>
        expect(container.textContent).toContain("Hardy & Wright"),
      );
    });
    expect(mockedTrail).toHaveBeenCalledWith("team-1", "SCI-001", expect.anything());
    expect(container.textContent).toContain("评审 r1 · A016");
  });

  it("restores saved candidate ids as whole values without delimiter splitting", async () => {
    const savedId = `sci-001-${String.fromCharCode(1)}-x`;
    const base = candidateContext() as any;
    mockedContext.mockResolvedValue({
      ...base,
      candidates: [
        { ...base.candidates[0], hypothesis_id: savedId },
        { ...base.candidates[0], hypothesis_id: "sci-001-y", statement: "第二条保存的假说" },
      ],
      defaultSelectedCandidateIds: [savedId, "sci-001-y"],
    } as never);

    act(() => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <HypothesisSelectionList teamId="team-1" questionId="SCI-001" />
        </QueryClientProvider>,
      );
    });
    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("第二条保存的假说"));
    });

    expect(container.querySelectorAll('article[data-selected="true"]')).toHaveLength(2);
    const submit = [...container.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("记录选择并开启评审"));
    expect(submit?.disabled).toBe(true);
  });

  it("keeps a dirty local selection through a same-value server refresh", async () => {
    const base = candidateContext() as any;
    mockedContext.mockImplementation(async () => ({
      ...base,
      candidates: [
        { ...base.candidates[0], hypothesis_id: "candidate-a", statement: "候选 A" },
        { ...base.candidates[0], hypothesis_id: "candidate-b", statement: "候选 B" },
        { ...base.candidates[0], hypothesis_id: "candidate-c", statement: "候选 C" },
      ],
      defaultSelectedCandidateIds: ["candidate-a", "candidate-b"],
    } as never));

    act(() => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <HypothesisSelectionList teamId="team-1" questionId="SCI-001" />
        </QueryClientProvider>,
      );
    });
    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("候选 C"));
    });

    const thirdChoice = container.querySelector('input[aria-label="选择假说 candidate-c"]') as HTMLInputElement;
    await act(async () => {
      thirdChoice.click();
    });
    expect(container.querySelectorAll('article[data-selected="true"]')).toHaveLength(3);

    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ["selection-context"] });
      await vi.waitFor(() => expect(mockedContext).toHaveBeenCalledTimes(2));
    });

    expect(container.querySelectorAll('article[data-selected="true"]')).toHaveLength(3);
    expect(thirdChoice.checked).toBe(true);
  });

  it("keeps compact candidates scan-friendly with only one detail open", async () => {
    const base = candidateContext() as any;
    mockedContext.mockResolvedValue({
      ...base,
      candidates: [
        { ...base.candidates[0], hypothesis_id: "candidate-a", statement: "候选 A", mechanism: "机制 A" },
        { ...base.candidates[0], hypothesis_id: "candidate-b", statement: "候选 B", mechanism: "机制 B" },
        { ...base.candidates[0], hypothesis_id: "candidate-c", statement: "候选 C", mechanism: "机制 C" },
      ],
      defaultSelectedCandidateIds: ["candidate-a", "candidate-b"],
      reviewMeeting: { meetingRoundId: "review-1", status: "open" },
    } as never);
    mockedTrail.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      questionId: "SCI-001",
      trails: [],
    } as never);

    act(() => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <HypothesisSelectionList compact teamId="team-1" questionId="SCI-001" />
        </QueryClientProvider>,
      );
    });
    await act(async () => {
      await vi.waitFor(() =>
        expect(container.querySelector('article[data-expanded="true"]')?.textContent).toContain("候选 A"),
      );
    });

    expect(container.querySelectorAll('article[data-expanded="true"]')).toHaveLength(1);
    expect(container.textContent).toContain("机制 A");
    expect(container.textContent).not.toContain("机制 B");

    const expandSecond = container.querySelector('button[aria-label="展开候选 candidate-b"]');
    await act(async () => {
      expandSecond?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.querySelectorAll('article[data-expanded="true"]')).toHaveLength(1);
    expect(container.querySelector('article[data-expanded="true"]')?.textContent).toContain("候选 B");
    expect(container.textContent).not.toContain("机制 A");
    expect(container.textContent).toContain("机制 B");
  });

  it("explains why removing a selection at the minimum is blocked", async () => {
    const base = candidateContext() as any;
    mockedContext.mockResolvedValue({
      ...base,
      candidates: [
        { ...base.candidates[0], hypothesis_id: "candidate-a", statement: "候选 A" },
        { ...base.candidates[0], hypothesis_id: "candidate-b", statement: "候选 B" },
        { ...base.candidates[0], hypothesis_id: "candidate-c", statement: "候选 C" },
      ],
      defaultSelectedCandidateIds: ["candidate-a", "candidate-b"],
    } as never);
    mockedTrail.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", questionId: "SCI-001", trails: [] } as never);

    act(() => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <HypothesisSelectionList teamId="team-1" questionId="SCI-001" />
        </QueryClientProvider>,
      );
    });
    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("候选 C"));
    });

    expect(container.querySelector('[data-testid="hypothesis-selection-minimum-hint"]')?.textContent)
      .toContain("已达到最低选择数");
    const firstChoice = container.querySelector('input[aria-label="选择假说 candidate-a"]') as HTMLInputElement;
    expect(firstChoice.disabled).toBe(true);
    await act(async () => {
      firstChoice.click();
    });
    expect(container.querySelectorAll('article[data-selected="true"]')).toHaveLength(2);
    expect(container.textContent).toContain("如需更换，请先勾选另一条");
  });

  it("turns a closed review into a read-only final-selection archive", async () => {
    const base = candidateContext() as any;
    mockedContext.mockResolvedValue({
      ...base,
      candidates: [
        { ...base.candidates[0], hypothesis_id: "candidate-a", statement: "候选 A" },
        { ...base.candidates[0], hypothesis_id: "candidate-b", statement: "候选 B" },
        { ...base.candidates[0], hypothesis_id: "candidate-c", statement: "候选 C" },
      ],
      defaultSelectedCandidateIds: [],
      latestSelection: {
        selectionId: "selection-1",
        selectedCandidateIds: ["candidate-a", "candidate-c"],
      },
      reviewMeeting: { meetingRoundId: "review-1", status: "closed" },
    } as never);
    mockedTrail.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      questionId: "SCI-001",
      trails: [],
    } as never);

    act(() => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <HypothesisSelectionList compact teamId="team-1" questionId="SCI-001" />
        </QueryClientProvider>,
      );
    });
    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("候选 C"));
    });

    expect(container.textContent).toContain("最终采用");
    expect(container.textContent).toContain("2 条");
    expect(container.textContent).not.toContain("候选 B");
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
    expect(container.textContent).not.toContain("全选送审");
    expect(container.textContent).not.toContain("记录选择并开启评审");
  });

  it("omits zero predictions and empty evidence controls", async () => {
    const base = candidateContext() as any;
    mockedContext.mockResolvedValue({
      ...base,
      candidates: [
        { ...base.candidates[0], hypothesis_id: "candidate-a", statement: "候选 A" },
        { ...base.candidates[0], hypothesis_id: "candidate-b", statement: "候选 B" },
      ],
      defaultSelectedCandidateIds: ["candidate-a", "candidate-b"],
    } as never);
    mockedTrail.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      questionId: "SCI-001",
      trails: [{
        candidateId: "candidate-b",
        entries: [{
          meetingRoundId: "mr-2",
          meetingLabel: "评审 r2",
          messageId: "m-2",
          speaker: "A017",
          excerpt: "候选 B 的证据锚点",
          createdAt: "2026-08-20T02:00:00Z",
        }],
      }],
    } as never);

    act(() => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <HypothesisSelectionList teamId="team-1" questionId="SCI-001" />
        </QueryClientProvider>,
      );
    });
    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("查看证据轨迹"));
    });

    expect(container.textContent).not.toContain("预测 0 条");
    expect(container.textContent).not.toContain("尚无讨论发言引用该候选");
    expect([...container.querySelectorAll("button")]
      .filter((button) => button.textContent?.includes("查看证据轨迹"))).toHaveLength(1);
  });
});
