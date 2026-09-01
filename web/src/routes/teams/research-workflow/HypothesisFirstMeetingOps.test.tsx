/**
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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
  command: "draft_summary",
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
  command: "approve_review_digest",
  commandLabel: "确认并结束本轮",
  canonicalAction: APPROVE_SUMMARY_ACTION,
};

let container: HTMLDivElement;
let root: Root;
let queryClient: QueryClient;

function render(nextAction: HypothesisFirstNextAction) {
  act(() => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <HypothesisFirstMeetingOps
          teamId="team-1"
          questionId="Q-01"
          meetingRoundId="meeting-1"
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
  beforeEach(() => {
    vi.clearAllMocks();
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

  it("starts safe organization once for a completed discussion and removes the redundant button", async () => {
    render(AUTO_ACTION);
    await act(async () => {
      await vi.waitFor(() => expect(mockedDraftMeetingSummary).toHaveBeenCalledTimes(1));
    });
    expect(mockedDraftMeetingSummary).toHaveBeenCalledWith(
      "team-1",
      "meeting-1",
      { actor: "operator", force: false },
    );
    expect(container.textContent).toContain("正在整理");
    expect(container.textContent).not.toContain("讨论中");

    render({ ...AUTO_ACTION });
    await act(async () => Promise.resolve());
    expect(mockedDraftMeetingSummary).toHaveBeenCalledTimes(1);
    expect(container.textContent).not.toContain("生成纪要");
    expect([...container.querySelectorAll("button")].some((button) => button.textContent?.includes("整理候选清单"))).toBe(false);
  });

  it("surfaces approve validation errors when the API keeps the round open", async () => {
    const mockedApprove = vi.mocked(approveHypothesisDigest);
    mockedApprove.mockResolvedValueOnce({
      closed: false,
      validationErrors: [{ code: "invalid_keywords", message: "证据请求缺少有效搜集关键词" }],
    } as never);
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: meetingRound("awaiting_approval"),
    });
    render({
      ...AUTO_ACTION,
      stage: "review_awaiting_approval",
      command: "approve_review_digest",
      commandLabel: "确认并结束本轮",
    });
    await act(async () => {
      await vi.waitFor(() => {
        const button = [...container.querySelectorAll("button")]
          .find((item) => item.textContent?.includes("确认并结束本轮"));
        expect(button).toBeTruthy();
        button?.click();
      });
      await vi.waitFor(() => expect(mockedApprove).toHaveBeenCalledTimes(1));
    });
    expect(container.textContent).toContain("本轮结论未被确认");
    expect(container.textContent).toContain("证据请求缺少有效搜集关键词");
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
      command: "approve_review_digest",
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
      command: "approve_review_digest",
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

  it("surfaces close-correction failures and disables competing actions while closing", async () => {
    const mockedApprove = vi.mocked(approveHypothesisDigest);
    mockedApprove.mockResolvedValueOnce({
      closed: false,
      validationErrors: [{ code: "invalid_keywords", message: "证据请求缺少有效搜集关键词" }],
    } as never);
    mockedCloseReviewMeeting.mockRejectedValueOnce(new Error("close correction failed"));
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: meetingRound("awaiting_approval"),
    });
    render({
      ...AUTO_ACTION,
      stage: "review_awaiting_approval",
      command: "approve_review_digest",
      commandLabel: "确认并结束本轮",
    });

    await act(async () => {
      await vi.waitFor(() => {
        const button = [...container.querySelectorAll("button")]
          .find((item) => item.textContent?.includes("确认并结束本轮"));
        expect(button).toBeTruthy();
        button?.click();
      });
      await vi.waitFor(() => expect(mockedApprove).toHaveBeenCalledTimes(1));
    });

    const close = [...container.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("按现有结论关闭本轮"));
    expect(close).toBeTruthy();
    await act(async () => {
      close?.click();
      await vi.waitFor(() => expect(mockedCloseReviewMeeting).toHaveBeenCalledTimes(1));
    });
    expect(container.textContent).toContain("close correction failed");
  });

  it("disables the competing reject action while close correction is pending", async () => {
    const mockedApprove = vi.mocked(approveHypothesisDigest);
    mockedApprove.mockResolvedValueOnce({
      closed: false,
      validationErrors: [{ code: "invalid_keywords", message: "证据请求缺少有效搜集关键词" }],
    } as never);
    let resolveClose: (value: unknown) => void = () => undefined;
    mockedCloseReviewMeeting.mockImplementationOnce(
      () => new Promise((resolve) => { resolveClose = resolve; }) as never,
    );
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: meetingRound("awaiting_approval"),
    });
    render({
      ...AUTO_ACTION,
      stage: "review_awaiting_approval",
      command: "approve_review_digest",
      commandLabel: "确认并结束本轮",
    });

    await act(async () => {
      await vi.waitFor(() => {
        const button = [...container.querySelectorAll("button")]
          .find((item) => item.textContent?.includes("确认并结束本轮"));
        expect(button).toBeTruthy();
        button?.click();
      });
      await vi.waitFor(() => expect(mockedApprove).toHaveBeenCalledTimes(1));
    });
    const close = [...container.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("按现有结论关闭本轮"));
    const reject = [...container.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("退回重新整理"));
    expect(close).toBeTruthy();
    expect(reject).toBeTruthy();

    await act(async () => {
      close?.click();
      await vi.waitFor(() => expect(mockedCloseReviewMeeting).toHaveBeenCalledTimes(1));
    });
    const pendingClose = [...container.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("按现有结论关闭本轮"));
    const pendingReject = [...container.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("退回重新整理"));
    expect((pendingClose as HTMLButtonElement).disabled).toBe(true);
    expect((pendingReject as HTMLButtonElement).disabled).toBe(true);

    await act(async () => {
      resolveClose({});
      await Promise.resolve();
    });
  });

  it("keeps retries manual after automatic organization fails", async () => {
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: { ...meetingRound("summarizing"), summaryError: "timeout" },
    });
    render({
      ...AUTO_ACTION,
      stage: "generation_summarizing",
      command: undefined,
      commandLabel: undefined,
      recovery: {
        command: "retry_draft_summary",
        label: "重试整理候选清单",
        reason: "自动整理未完成",
      },
    });
    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("重试整理候选清单"));
    });
    expect(mockedDraftMeetingSummary).not.toHaveBeenCalled();

    const retry = [...container.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("重试整理候选清单"));
    await act(async () => {
      retry?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    expect(mockedDraftMeetingSummary).toHaveBeenCalledTimes(1);
  });

  it("restarts a review discussion when every speaker failed", async () => {
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: { ...meetingRound("open"), meetingType: "hypothesis_review" },
    });
    mockedFetchMessages.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRoundId: "meeting-1",
      messageCount: 2,
      messages: [
        { messageId: "m-1", status: "failed", content: "network_error: litellm.InternalServerError" },
        { messageId: "m-2", status: "failed", content: "network_error: litellm.InternalServerError" },
      ],
    });

    render({
      ...AUTO_ACTION,
      stage: "review_ready_to_summarize",
      command: "draft_summary",
      commandLabel: "整理本轮结论",
    });
    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("重新发起评审讨论"));
    });
    expect(mockedDraftMeetingSummary).not.toHaveBeenCalled();

    const restart = [...container.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("重新发起评审讨论"));
    await act(async () => {
      restart?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await vi.waitFor(() => expect(mockedReopenReview).toHaveBeenCalledTimes(1));
    });
    expect(mockedReopenReview).toHaveBeenCalledWith("team-1", "meeting-1");
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
      command: "retry_draft_summary",
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

  it("restarts a candidate discussion when every speaker failed", async () => {
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: meetingRound("summarizing"),
    });
    mockedFetchMessages.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRoundId: "meeting-1",
      messageCount: 1,
      messages: [{ messageId: "m-1", status: "failed", content: "protocol_error" }],
    });

    render({
      ...AUTO_ACTION,
      stage: "generation_summarizing",
      command: undefined,
      commandLabel: undefined,
    });
    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("重新发起候选讨论"));
    });
    expect(mockedDraftMeetingSummary).not.toHaveBeenCalled();

    const restart = [...container.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("重新发起候选讨论"));
    await act(async () => {
      restart?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await vi.waitFor(() => expect(mockedOpenGeneration).toHaveBeenCalledTimes(1));
    });
    expect(mockedOpenGeneration).toHaveBeenCalledWith("team-1", "Q-01", undefined);
  });

  it("offers one manual retry when meeting creation was interrupted before chat binding", async () => {
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: { ...meetingRound("open"), chatRoomRoundIds: [] },
    });
    mockedFetchMessages.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRoundId: "meeting-1",
      messageCount: 0,
      messages: [],
    });

    render({
      ...AUTO_ACTION,
      stage: "generation_discussing",
      command: undefined,
      commandLabel: undefined,
    });
    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("重试启动候选讨论"));
    });
    expect(mockedOpenGeneration).not.toHaveBeenCalled();

    const retry = [...container.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("重试启动候选讨论"));
    await act(async () => {
      retry?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await vi.waitFor(() => expect(mockedOpenGeneration).toHaveBeenCalledTimes(1));
    });
    expect(mockedOpenGeneration).toHaveBeenCalledWith("team-1", "Q-01", undefined);
  });

  it("does not auto-loop when the request fails and exposes one manual retry", async () => {
    mockedDraftMeetingSummary
      .mockRejectedValueOnce(new Error("network unavailable"))
      .mockResolvedValueOnce({
        schemaVersion: 1,
        teamId: "team-1",
        status: "summarizing",
        meetingRound: meetingRound("summarizing"),
      });
    render(AUTO_ACTION);
    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain("重试整理候选清单"));
    });
    expect(mockedDraftMeetingSummary).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("整理失败");

    const retry = [...container.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("重试整理候选清单"));
    await act(async () => {
      retry?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    expect(mockedDraftMeetingSummary).toHaveBeenCalledTimes(2);
  });

  it("surfaces skipped evidence requests with readable reasons on a successful close", async () => {
    const mockedApprove = vi.mocked(approveHypothesisDigest);
    mockedApprove.mockResolvedValueOnce({
      closed: true,
      collection: {
        skipped: [
          { decisionId: "d-1", reason: "search_envelope_missing" },
          { decisionId: "d-2", reason: "collection_payload_invalid" },
        ],
      },
      hypothesisRound: { roundId: "r-1", status: "open" },
    } as never);
    mockedFetchMeetingRound.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingRound: meetingRound("awaiting_approval"),
    });
    render({
      ...AUTO_ACTION,
      stage: "review_awaiting_approval",
      command: "approve_review_digest",
      commandLabel: "确认并结束本轮",
    });

    await act(async () => {
      await vi.waitFor(() => {
        const button = [...container.querySelectorAll("button")]
          .find((item) => item.textContent?.includes("确认并结束本轮"));
        expect(button).toBeTruthy();
        button?.click();
      });
      await vi.waitFor(() => expect(mockedApprove).toHaveBeenCalledTimes(1));
    });

    const notice = container.querySelector('[data-testid="dropped-request-notice"]');
    expect(notice?.textContent).toContain("2 条证据请求被跳过");
    expect(notice?.textContent).toContain("缺少检索关键词");
    expect(notice?.textContent).toContain("搜集要求无效");
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
});
