import React from "react";
import { command } from "./hypothesisFirstV2.fixture";
/**
 * @vitest-environment happy-dom
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../api/hypothesisFirst", () => ({
  approveHypothesisDigest: vi.fn().mockResolvedValue({}),
  closeReviewMeeting: vi.fn().mockResolvedValue({}),
  draftMeetingSummary: vi.fn().mockResolvedValue({}),
  executeHypothesisFirstCommand: vi.fn().mockResolvedValue({ result: {} }),
  fetchMeetingRound: vi.fn(),
  fetchMeetingRoundSourceMessages: vi.fn().mockResolvedValue({ messages: [] }),
  isHypothesisFirstCommandStateConflict: vi.fn().mockReturnValue(false),
  openHypothesisCandidateGeneration: vi.fn().mockResolvedValue({}),
  recordCollectionHandoff: vi.fn().mockResolvedValue({}),
  rejectMeetingDigestDraft: vi.fn().mockResolvedValue({}),
  reopenHypothesisReviewMeeting: vi.fn().mockResolvedValue({}),
}));

import {
  approveHypothesisDigest,
  closeReviewMeeting,
  draftMeetingSummary,
  executeHypothesisFirstCommand,
  fetchMeetingRound,
  fetchMeetingRoundSourceMessages,
  openHypothesisCandidateGeneration,
  reopenHypothesisReviewMeeting,
} from "../../../api/hypothesisFirst";
import { HypothesisFirstMeetingOps } from "./HypothesisFirstMeetingOps";
import type { HypothesisFirstV2NextAction } from "./hypothesisFirstStateV2Adapter";
import type { HypothesisFirstNextAction } from "./hypothesisFirstNextAction";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const mockedDraftMeetingSummary = vi.mocked(draftMeetingSummary);
const mockedExecuteCommand = vi.mocked(executeHypothesisFirstCommand);
const mockedFetchMeetingRound = vi.mocked(fetchMeetingRound);
const mockedFetchMessages = vi.mocked(fetchMeetingRoundSourceMessages);
const mockedOpenGeneration = vi.mocked(openHypothesisCandidateGeneration);
const mockedReopenReview = vi.mocked(reopenHypothesisReviewMeeting);
const mockedCloseReviewMeeting = vi.mocked(closeReviewMeeting);

function meetingRound(status: string) {
  return {
    program: "p",
    theme: "t",
    campaign: "c",
    question: "Q-01",
    branch: "b",
    workflow: "w",
    agentId: "a",
    schemaVersion: 1,
    meetingRoundId: "meeting-1",
    meetingType: "hypothesis_candidate_generation",
    mode: "generation",
    scopeHash: "scope",
    participants: ["agent-1"],
    status,
    startedAt: "2026-08-19T01:00:00Z",
  };
}

const AUTO_ACTION: HypothesisFirstNextAction = {
  stage: "generation_ready_to_summarize",
  targetNodeId: "hf_generation",
  navigationLabel: "前往候选生成",
  command: "regenerate_summary",
  commandLabel: "整理候选清单",
  statusMessage: "团队讨论已结束，系统正在整理候选清单",
  meetingRoundId: "meeting-1",
  recovery: null,
};

const APPROVE_SUMMARY_ACTION = {
  kind: "command" as const,
  actionId: "approve-summary:meeting-1",
  label: "确认本轮结论",
  enabled: true,
  disabledReason: null,
  targetPhase: "review" as const,
  targetNodeId: "hf_review",
  command: "approve_summary" as const,
  payload: { meetingRoundId: "meeting-1" },
  inputSchemaRef: "hypothesis-first/approve-summary/v1",
  idempotencyKey: "hf2:approve-summary:meeting-1",
  expectedStateVersion: "hf2-action:origin:current",
  requiresConfirmation: false,
  confirmationText: null,
};

const AWAITING_REVIEW_ACTION: HypothesisFirstNextAction = {
  ...AUTO_ACTION,
  stateSource: "v2_canonical",
  stage: "review_awaiting_approval",
  command: "approve_summary",
  commandLabel: "确认并结束本轮",
  canonicalAction: APPROVE_SUMMARY_ACTION,
};

// Two candidate review rooms can sit in awaiting_approval at the same time;
// the selection-level nextAction then aggregates the FIRST room while the
// sibling panel must stay operable through its own canonicalActions entry.
const APPROVE_ACTION_A = {
  ...APPROVE_SUMMARY_ACTION,
  actionId: "approve-summary:candidate-a",
  idempotencyKey: "hf2:approve-summary:candidate-a",
};
const APPROVE_ACTION_B = {
  ...APPROVE_SUMMARY_ACTION,
  actionId: "approve-summary:candidate-b",
  idempotencyKey: "hf2:approve-summary:candidate-b",
  payload: { meetingRoundId: "meeting-2" },
};
const DUAL_ROOM_ACTION: HypothesisFirstV2NextAction = {
  ...AWAITING_REVIEW_ACTION,
  meetingRoundId: "meeting-1",
  canonicalAction: APPROVE_ACTION_A,
  canonicalActions: [APPROVE_ACTION_A, APPROVE_ACTION_B],
};

let container: HTMLDivElement;
let root: Root;
let queryClient: QueryClient;

function render(nextAction: HypothesisFirstNextAction, meetingRoundId = "meeting-1") {
  act(() => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <HypothesisFirstMeetingOps
          teamId="team-1"
          questionId="Q-01"
          meetingRoundId={meetingRoundId}
          nextAction={nextAction}
          compact
        />
      </QueryClientProvider>,
    );
  });
}

function renderScoped(nextAction: HypothesisFirstNextAction, runId: string) {
  act(() => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <HypothesisFirstMeetingOps
          teamId="team-1"
          questionId="Q-01"
          runId={runId}
          meetingRoundId="meeting-1"
          nextAction={nextAction}
          compact
        />
      </QueryClientProvider>,
    );
  });
}

function renderApproved(nextAction: HypothesisFirstNextAction, onApproved: () => void) {
  act(() => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <HypothesisFirstMeetingOps
          teamId="team-1"
          questionId="Q-01"
          meetingRoundId="meeting-1"
          nextAction={nextAction}
          compact
          onApproved={onApproved}
        />
      </QueryClientProvider>,
    );
  });
}

function commandReceipt(result: Record<string, unknown>) {
  return {
    schemaVersion: 2,
    teamId: "team-1",
    questionId: "Q-01",
    command: "approve_summary",
    actionId: "approve-summary:meeting-1",
    idempotencyKey: "hf2:approve-summary:meeting-1",
    acceptedStateVersion: "hf2-action:origin:current",
    result,
  } as never;
}

describe("HypothesisFirstMeetingOps automatic organization", () => {
  it("organizes once using the signed V2 action", async () => {
    const canonicalAction = command({command: "regenerate_summary", payload: {meetingRoundId: "meeting-1"}}, "整理候选清单");
    render({...AUTO_ACTION, canonicalAction});
    await act(async () => { await vi.waitFor(() => expect(mockedExecuteCommand).toHaveBeenCalledTimes(1)); });
    expect(mockedExecuteCommand).toHaveBeenCalledWith("team-1", "Q-01", canonicalAction, undefined, {runId: undefined});
    expect(mockedDraftMeetingSummary).not.toHaveBeenCalled();
    render({...AUTO_ACTION, canonicalAction});
    expect(mockedExecuteCommand).toHaveBeenCalledTimes(1);
  });

  it("shows a V2 summary failure and leaves retry to the operator", async () => {
    mockedExecuteCommand.mockRejectedValueOnce(new Error("worker lock timeout"));
    render({...AUTO_ACTION, canonicalAction: command({command: "regenerate_summary", payload: {meetingRoundId: "meeting-1"}}, "整理候选清单")});
    await act(async () => { await vi.waitFor(() => expect(container.textContent).toContain("worker lock timeout")); });
    expect(mockedExecuteCommand).toHaveBeenCalledTimes(1);
    expect(mockedDraftMeetingSummary).not.toHaveBeenCalled();
  });

  it("does not dispatch an unsigned operation from a completed discussion", async () => {
    render(AUTO_ACTION);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
    expect(mockedExecuteCommand).not.toHaveBeenCalled();
    expect(mockedDraftMeetingSummary).not.toHaveBeenCalled();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mockedExecuteCommand.mockReset().mockResolvedValue(commandReceipt({}));
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: meetingRound("open"),
    });
    mockedFetchMessages.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRoundId: "meeting-1",
      messageCount: 1,
      messages: [{ messageId: "m-ok", status: "completed", content: "CANDIDATE: c1 | claim" }],
    });
    mockedDraftMeetingSummary.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      status: "summarizing",
      meetingRound: meetingRound("summarizing"),
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    queryClient.clear();
    container.remove();
  });

  it("does not regenerate the digest twice after a canonical rejection", async () => {
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: { ...meetingRound("awaiting_approval"), meetingType: "hypothesis_review" },
    });
    render({
      ...AUTO_ACTION,
      stage: "review_awaiting_approval",
      command: "approve_summary",
      commandLabel: "确认并结束本轮",
      canonicalAction: {
        kind: "command",
        actionId: "approve-summary:candidate-1",
        label: "确认候选纪要",
        enabled: true,
        disabledReason: null,
        targetPhase: "review",
        targetNodeId: "hf_review",
        command: "approve_summary",
        payload: { meetingRoundId: "meeting-1" },
        inputSchemaRef: "hypothesis-first/approve-summary/v1",
        idempotencyKey: "hf2:approve-summary:candidate-1",
        expectedStateVersion: "hf2-action:origin:current",
        requiresConfirmation: false,
        confirmationText: null,
      },
    });

    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("退回重新整理"));
      const reject = [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("退回重新整理"));
      reject?.click();
      await vi.waitFor(() => expect(mockedExecuteCommand).toHaveBeenCalledTimes(1));
    });

    expect(mockedDraftMeetingSummary).not.toHaveBeenCalled();
  });

  it("does not expose legacy approval writes when canonical state has no signed action", async () => {
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: { ...meetingRound("awaiting_approval"), meetingType: "hypothesis_review" },
    });
    render({
      ...AUTO_ACTION,
      stateSource: "v2_canonical",
      stage: "review_awaiting_approval",
      command: "approve_summary",
      commandLabel: "确认并结束本轮",
      canonicalAction: undefined,
    });

    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("meeting-1"));
    });

    expect([...container.querySelectorAll("button")]
      .some((button) => button.textContent?.includes("确认并结束本轮"))).toBe(false);
    expect([...container.querySelectorAll("button")]
      .some((button) => button.textContent?.includes("退回重新整理"))).toBe(false);
    expect(approveHypothesisDigest).not.toHaveBeenCalled();
  });

  it("executes the canonical reopen command for an orphaned review round", async () => {
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: { ...meetingRound("stopped"), meetingType: "hypothesis_review" },
    });
    mockedFetchMessages.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRoundId: "meeting-1",
      messageCount: 0,
      messages: [],
    });
    const canonicalAction = {
      kind: "command" as const,
      actionId: "reopen-review:meeting-1",
      label: "重新发起评审讨论",
      enabled: true,
      disabledReason: null,
      targetPhase: "review" as const,
      targetNodeId: "hf_review",
      command: "reopen_review" as const,
      payload: { meetingRoundId: "meeting-1" },
      inputSchemaRef: "hypothesis-first/reopen-review/v1",
      idempotencyKey: "hf2:reopen-review:meeting-1",
      expectedStateVersion: "hf2-action:origin:current",
      requiresConfirmation: false,
      confirmationText: null,
    };

    mockedExecuteCommand.mockResolvedValueOnce({result: {openStatus: "budget_exhausted"}} as never);
    render({
      ...AUTO_ACTION,
      stage: "blocked",
      stateSource: "v2_canonical",
      command: "reopen_review",
      commandLabel: "重新发起评审讨论",
      meetingRoundId: "meeting-1",
      canonicalAction,
      canonicalActions: [canonicalAction],
    });

    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("重新发起评审讨论"));
      const reopen = [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("重新发起评审讨论"));
      expect((reopen as HTMLButtonElement).disabled).toBe(false);
      reopen?.click();
      await vi.waitFor(() => expect(mockedExecuteCommand).toHaveBeenCalledTimes(1));
    });

    expect(mockedExecuteCommand).toHaveBeenCalledWith(
      "team-1",
      "Q-01",
      canonicalAction,
      undefined,
      { runId: undefined },
    );
    expect(mockedReopenReview).not.toHaveBeenCalled();
    expect(container.textContent).toContain("已达到评审硬上限");
  });

  it("passes the active workflow run to canonical meeting commands", async () => {
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: { ...meetingRound("stopped"), meetingType: "hypothesis_review" },
    });
    mockedFetchMessages.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRoundId: "meeting-1",
      messageCount: 0,
      messages: [],
    });
    const canonicalAction = {
      kind: "command" as const,
      actionId: "reopen-review:meeting-1",
      label: "重新发起评审讨论",
      enabled: true,
      disabledReason: null,
      targetPhase: "review" as const,
      targetNodeId: "hf_review",
      command: "reopen_review" as const,
      payload: { meetingRoundId: "meeting-1", workflowRunId: "run-current" },
      inputSchemaRef: "hypothesis-first/reopen-review/v1",
      idempotencyKey: "hf2:reopen-review:meeting-1",
      expectedStateVersion: "hf2-action:origin:current",
      requiresConfirmation: false,
      confirmationText: null,
    };

    renderScoped({
      ...AUTO_ACTION,
      stage: "blocked",
      stateSource: "v2_canonical",
      command: "reopen_review",
      commandLabel: "重新发起评审讨论",
      meetingRoundId: "meeting-1",
      canonicalAction,
      canonicalActions: [canonicalAction],
    }, "run-current");

    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("重新发起评审讨论"));
      const reopen = [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("重新发起评审讨论"));
      reopen?.click();
      await vi.waitFor(() => expect(mockedExecuteCommand).toHaveBeenCalledTimes(1));
    });

    expect(mockedExecuteCommand).toHaveBeenCalledWith(
      "team-1",
      "Q-01",
      canonicalAction,
      undefined,
      { runId: "run-current" },
    );
  });

  it("executes the canonical summary retry for the selected failed candidate", async () => {
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: {
        ...meetingRound("summarizing"),
        meetingType: "hypothesis_review",
        summaryError: "Service temporarily unavailable",
      },
    });
    const canonicalAction = {
      kind: "command" as const,
      actionId: "regenerate-summary:meeting-1",
      label: "重试生成纪要",
      enabled: true,
      disabledReason: null,
      targetPhase: "review" as const,
      targetNodeId: "hf_review",
      command: "regenerate_summary" as const,
      payload: { meetingRoundId: "meeting-1" },
      inputSchemaRef: null,
      idempotencyKey: "hf2:regenerate-summary:meeting-1",
      expectedStateVersion: "hf2-action:origin:current",
      requiresConfirmation: false,
      confirmationText: null,
    };

    render({
      ...AUTO_ACTION,
      stage: "blocked",
      stateSource: "v2_canonical",
      command: "regenerate_summary",
      commandLabel: "重试生成纪要",
      meetingRoundId: "meeting-1",
      canonicalAction,
      canonicalActions: [canonicalAction],
    });

    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("重试生成纪要"));
      const retry = [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("重试生成纪要"));
      expect((retry as HTMLButtonElement).disabled).toBe(false);
      retry?.click();
      await vi.waitFor(() => expect(mockedExecuteCommand).toHaveBeenCalledTimes(1));
    });

    expect(mockedExecuteCommand).toHaveBeenCalledWith(
      "team-1",
      "Q-01",
      canonicalAction,
      undefined,
      { runId: undefined },
    );
    expect(mockedDraftMeetingSummary).not.toHaveBeenCalled();
  });

  it("treats a canonical rejection as a redraft instead of an approval", async () => {
    const onApproved = vi.fn();
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: { ...meetingRound("awaiting_approval"), meetingType: "hypothesis_review" },
    });
    mockedExecuteCommand.mockResolvedValueOnce(commandReceipt({
      schemaVersion: 1,
      teamId: "team-1",
      status: "summarizing",
      meetingRound: meetingRound("summarizing"),
    }));
    renderApproved(AWAITING_REVIEW_ACTION, onApproved);

    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("退回重新整理"));
      const reject = [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("退回重新整理"));
      reject?.click();
      await vi.waitFor(() => expect(mockedExecuteCommand).toHaveBeenCalledTimes(1));
    });

    expect(mockedExecuteCommand).toHaveBeenCalledWith(
      "team-1",
      "Q-01",
      APPROVE_SUMMARY_ACTION,
      { decision: "rejected" },
      { runId: undefined },
    );
    const notice = container.querySelector('[data-testid="reject-notice"]');
    expect(notice?.textContent).toContain("已退回");
    expect(notice?.textContent).toContain("重新整理");
    expect(mockedDraftMeetingSummary).not.toHaveBeenCalled();
    expect(onApproved).not.toHaveBeenCalled();
  });

  it("surfaces the prepare blocker when a rejection cannot re-organize the draft", async () => {
    const onApproved = vi.fn();
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: { ...meetingRound("awaiting_approval"), meetingType: "hypothesis_review" },
    });
    mockedExecuteCommand.mockResolvedValueOnce(commandReceipt({
      schemaVersion: 1,
      teamId: "team-1",
      status: "blocked",
      blocker: {
        code: "discussion_has_no_completed_messages",
        message: "讨论未产出可引用的成功发言，不能生成纪要",
      },
      meetingRound: meetingRound("awaiting_approval"),
    }));
    renderApproved(AWAITING_REVIEW_ACTION, onApproved);

    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("退回重新整理"));
      const reject = [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("退回重新整理"));
      reject?.click();
      await vi.waitFor(() => expect(mockedExecuteCommand).toHaveBeenCalledTimes(1));
    });

    const notice = container.querySelector('[data-testid="reject-notice"]');
    expect(notice?.textContent).toContain("已退回");
    expect(notice?.textContent).toContain("不能重新整理结论");
    expect(onApproved).not.toHaveBeenCalled();
  });

  it("still triggers onApproved after a canonical confirmation succeeds", async () => {
    const onApproved = vi.fn();
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: { ...meetingRound("awaiting_approval"), meetingType: "hypothesis_review" },
    });
    mockedExecuteCommand.mockResolvedValueOnce(commandReceipt({
      closed: true,
      collection: { requests: [], skipped: [] },
      hypothesisRound: { roundId: "r-1", status: "open" },
      meetingRound: meetingRound("closed"),
      digest: {},
      decisions: [],
    }));
    renderApproved(AWAITING_REVIEW_ACTION, onApproved);

    await act(async () => {
      await vi.waitFor(() => {
        const button = [...container.querySelectorAll("button")]
          .find((item) => item.textContent?.includes("确认并结束本轮"));
        expect(button).toBeTruthy();
        button?.click();
      });
      await vi.waitFor(() => expect(onApproved).toHaveBeenCalledTimes(1));
    });

    expect(mockedExecuteCommand).toHaveBeenCalledWith(
      "team-1",
      "Q-01",
      APPROVE_SUMMARY_ACTION,
      { decision: "accepted" },
      { runId: undefined },
    );
  });

  it("renders and dispatches a canonical-only command that has no legacy equivalent", async () => {
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: { ...meetingRound("open"), meetingType: "hypothesis_review" },
    });
    const canonicalAction = {
      kind: "command" as const,
      actionId: "stop-collection:req-1",
      label: "停止资料搜集",
      enabled: true,
      disabledReason: null,
      targetPhase: "collection" as const,
      targetNodeId: "hf_collection_req-1",
      command: "stop_collection" as const,
      payload: { requestId: "req-1", childRunId: "child-1" },
      inputSchemaRef: null,
      idempotencyKey: "hf2:stop-collection:req-1",
      expectedStateVersion: "hf2-action:origin:current",
      requiresConfirmation: false,
      confirmationText: null,
    };

    render({
      ...AUTO_ACTION,
      stage: "collecting",
      stateSource: "v2_canonical",
      command: undefined,
      commandLabel: "停止资料搜集",
      commandDetail: "停止后可重新发起搜集",
      meetingRoundId: "meeting-1",
      canonicalAction,
      canonicalActions: [canonicalAction],
    });

    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("停止资料搜集"));
      const stop = [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("停止资料搜集"));
      expect(stop).toBeTruthy();
      expect((stop as HTMLButtonElement).disabled).toBe(false);
      stop?.click();
      await vi.waitFor(() => expect(mockedExecuteCommand).toHaveBeenCalledTimes(1));
    });

    expect(mockedExecuteCommand).toHaveBeenCalledWith(
      "team-1",
      "Q-01",
      canonicalAction,
      undefined,
      { runId: undefined },
    );
    expect(mockedDraftMeetingSummary).not.toHaveBeenCalled();
    expect(container.textContent).toContain("停止后可重新发起搜集");
  });

  it("keeps a sibling awaiting room operable from its own canonical action", async () => {
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: {
        ...meetingRound("awaiting_approval"),
        meetingRoundId: "meeting-2",
        meetingType: "hypothesis_review",
      },
    });

    render(DUAL_ROOM_ACTION, "meeting-2");

    await act(async () => {
      // The sibling room's primary label comes from its own canonical action,
      // not the selection-level commandLabel (which describes room A).
      await vi.waitFor(() => expect(container.textContent).toContain("确认本轮结论"));
      const approve = [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("确认本轮结论"));
      const reject = [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("退回重新整理"));
      expect(approve).toBeTruthy();
      expect(reject).toBeTruthy();
      expect((approve as HTMLButtonElement).disabled).toBe(false);
      expect((reject as HTMLButtonElement).disabled).toBe(false);
      reject?.click();
      await vi.waitFor(() => expect(mockedExecuteCommand).toHaveBeenCalledTimes(1));
    });

    expect(mockedExecuteCommand).toHaveBeenCalledWith(
      "team-1",
      "Q-01",
      APPROVE_ACTION_B,
      { decision: "rejected" },
      { runId: undefined },
    );
  });

  it("explains a swallowed click while a panel action is pending", async () => {
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: { ...meetingRound("awaiting_approval"), meetingType: "hypothesis_review" },
    });
    mockedExecuteCommand.mockImplementationOnce(() => new Promise(() => {}));

    render(AWAITING_REVIEW_ACTION);

    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("退回重新整理"));
      const reject = [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("退回重新整理"));
      reject?.click();
      await vi.waitFor(() => expect(mockedExecuteCommand).toHaveBeenCalledTimes(1));
    });
    await act(async () => {
      await vi.waitFor(() => {
        const reasons = [...container.querySelectorAll('[data-vui="disabled-tooltip-trigger"]')]
          .map((trigger) => trigger.getAttribute("aria-label") ?? "");
        expect(reasons.some((reason) => reason.includes("操作进行中"))).toBe(true);
      });
      // The pending gate must also swallow further clicks silently.
      const reject = [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("退回重新整理"));
      reject?.click();
    });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
    expect(mockedExecuteCommand).toHaveBeenCalledTimes(1);
  });
});
