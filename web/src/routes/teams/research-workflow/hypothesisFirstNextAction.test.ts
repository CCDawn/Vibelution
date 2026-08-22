import { describe, expect, it } from "vitest";

import type {
  CollectionRequestRecord,
  HypothesisFirstChainState,
  HypothesisSelectionRecord,
  MeetingRoundRecord,
} from "../../../api/types/hypothesisFirst";
import {
  boundChatRoundsAreTerminal,
  focusNodeFromNextAction,
  hasValidEvidenceRequestKeywords,
  resolveHypothesisFirstNextAction,
  reviewDigestConfirmBlocker,
  shouldHideSourceFindingStart,
} from "./hypothesisFirstNextAction";

function scope() {
  return {
    program: "p",
    theme: "t",
    campaign: "c",
    question: "SCI-002",
    branch: "b",
    workflow: "w",
    agentId: "a",
  };
}

function chain(overrides: Partial<HypothesisFirstChainState> = {}): HypothesisFirstChainState {
  return {
    schemaVersion: 1,
    teamId: "team-1",
    questionId: "SCI-002",
    selectionId: "",
    meetingCount: 0,
    firstMeetingId: "",
    firstMeetingClosed: false,
    openMeetingIds: [],
    collectionRequests: [],
    collectionRequestCount: 0,
    pendingCollectionCount: 0,
    collectionReady: false,
    hypothesisRoundCount: 0,
    latestHypothesisRoundId: "",
    hypothesisConverged: false,
    convergenceDetail: "",
    roundBudget: 3,
    budgetExhausted: false,
    templateBaselineExists: false,
    templateBaselineIds: [],
    candidateCount: 0,
    ...overrides,
  };
}

function meeting(overrides: Partial<MeetingRoundRecord> = {}): MeetingRoundRecord {
  return {
    ...scope(),
    meetingRoundId: "mtg-1",
    meetingType: "hypothesis_review",
    mode: "review",
    scopeHash: "sh",
    participants: ["agent-1"],
    status: "open",
    startedAt: "2026-08-19T01:00:00Z",
    roundIndex: 1,
    ...overrides,
  };
}

function selection(overrides: Partial<HypothesisSelectionRecord> = {}): HypothesisSelectionRecord {
  return {
    ...scope(),
    schemaVersion: 1,
    selectionId: "sel-1",
    selectionHash: "h",
    mode: "manual",
    scopeHash: "sh",
    questionId: "SCI-002",
    selectedCandidateIds: ["cand-1"],
    previousSelectionId: "",
    decidedBy: "operator",
    createdAt: "2026-08-19T00:30:00Z",
    ...overrides,
  };
}

function request(overrides: Partial<CollectionRequestRecord> = {}): CollectionRequestRecord {
  return {
    ...scope(),
    schemaVersion: 1,
    recordKind: "hypothesis_first_collection_request",
    requestId: "req-1",
    requestHash: "rh",
    status: "pending",
    meetingRoundId: "mtg-1",
    decisionId: "dec-1",
    questionId: "SCI-002",
    mode: "review",
    scopeHash: "sh",
    searchEnvelope: { keywords: ["spike"] },
    requirements: {},
    writebackPolicy: {},
    collectionRunId: "run-collect-1",
    createdAt: "2026-08-19T02:00:00Z",
    ...overrides,
  };
}

describe("resolveHypothesisFirstNextAction", () => {
  it("asks to create a run when none exists", () => {
    const next = resolveHypothesisFirstNextAction({ run: null });
    expect(next.stage).toBe("no_run");
    expect(next.command).toBe("create_run");
    expect(next.commandLabel).toBe("选择题目开始研究");
    expect(next.navigationLabel).toBe("选择题目开始研究");
    expect(next.targetNodeId).toBeNull();
  });

  it("opens candidate generation when there is no meeting and no candidates", () => {
    const next = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      chainState: chain(),
      meetings: [],
    });
    expect(next.stage).toBe("generation_missing");
    expect(next.targetNodeId).toBe("hf_generation");
    expect(next.navigationLabel).toBe("前往候选生成");
    expect(next.command).toBe("open_generation");
    expect(next.commandLabel).toBe("生成候选假说");
    expect(next.navigationLabel).not.toBe(next.commandLabel);
  });

  it("shows discussion in progress while the generation meeting is open and chat is live", () => {
    const next = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      chainState: chain({ generationMeetingId: "gen-1", generationMeetingStatus: "open" }),
      meetings: [meeting({
        meetingRoundId: "gen-1",
        meetingType: "hypothesis_candidate_generation",
        status: "open",
      })],
      boundChatRoundsTerminal: false,
    });
    expect(next.stage).toBe("generation_running");
    expect(next.targetNodeId).toBe("hf_generation");
    expect(next.command).toBeUndefined();
    expect(next.commandLabel).toBeUndefined();
    expect(next.navigationLabel).toBe("查看候选生成讨论");
    expect(next.statusMessage).toBe("讨论进行中");
  });

  it("starts automatic candidate-list organization only after bound chat rounds are terminal", () => {
    const next = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      meetings: [meeting({
        meetingRoundId: "gen-1",
        meetingType: "hypothesis_candidate_generation",
        status: "open",
      })],
      boundChatRoundsTerminal: true,
    });
    expect(next.stage).toBe("generation_ready_to_summarize");
    expect(next.command).toBe("draft_summary");
    expect(next.commandLabel).toBe("整理候选清单");
    expect(next.statusMessage).toBe("团队讨论已结束，系统正在整理候选清单");
    expect(next.statusMessage).not.toContain("纪要");
    expect(next.navigationLabel).toBe("前往候选生成");
    expect(next.navigationLabel).not.toBe(next.commandLabel);
  });

  it("waits while summarizing and exposes retry when draft failed", () => {
    const waiting = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      meetings: [meeting({
        meetingType: "hypothesis_candidate_generation",
        status: "summarizing",
      })],
    });
    expect(waiting.stage).toBe("generation_summarizing");
    expect(waiting.command).toBeUndefined();
    expect(waiting.statusMessage).toBe("团队讨论已结束，系统正在整理候选清单");

    const failed = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      meetings: [meeting({
        meetingType: "hypothesis_candidate_generation",
        status: "summarizing",
        summaryError: "drafter timeout",
      })],
    });
    expect(failed.recovery?.command).toBe("retry_draft_summary");
    expect(failed.recovery?.label).toBe("重试整理候选清单");
    expect(failed.recovery?.reason).toBe("自动整理未完成");
    expect(failed.statusMessage).toBe("自动整理失败，可手动重试");
  });

  it("confirms the generation candidate list at awaiting_approval", () => {
    const next = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      meetings: [meeting({
        meetingType: "hypothesis_candidate_generation",
        status: "awaiting_approval",
        digestDraft: {
          summary: "候选清单",
          proposedCandidates: [{ candidateId: "c1", statement: "claim" }],
          contentHash: "hash-1",
        },
      })],
    });
    expect(next.stage).toBe("generation_awaiting_approval");
    expect(next.navigationLabel).toBe("前往确认候选");
    expect(next.commandLabel).toBe("确认候选清单");
    expect(next.command).toBe("approve_generation_digest");
    expect(next.navigationLabel).not.toBe(next.commandLabel);
  });

  it("requires selection after candidates exist", () => {
    const next = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      chainState: chain({ candidateCount: 3 }),
      meetings: [meeting({
        meetingType: "hypothesis_candidate_generation",
        status: "closed",
      })],
    });
    expect(next.stage).toBe("selection_required");
    expect(next.targetNodeId).toBe("hf_selection");
    expect(next.command).toBe("record_selection");
    expect(next.commandLabel).toBe("记录选择并开启评审");
    expect(next.navigationLabel).toBe("前往假说选择");
  });

  it("covers review running, ready-to-summarize, summarizing, and approval", () => {
    const base = {
      run: { runId: "run-1" },
      chainState: chain({ candidateCount: 2, selectionId: "sel-1" }),
      selection: selection(),
    };
    const running = resolveHypothesisFirstNextAction({
      ...base,
      meetings: [meeting({ status: "open" })],
      boundChatRoundsTerminal: false,
    });
    expect(running.stage).toBe("review_running");
    expect(running.targetNodeId).toBe("hf_meeting_1");
    expect(running.command).toBeUndefined();

    const ready = resolveHypothesisFirstNextAction({
      ...base,
      meetings: [meeting({ status: "open" })],
      boundChatRoundsTerminal: true,
    });
    expect(ready.stage).toBe("review_ready_to_summarize");
    expect(ready.commandLabel).toBe("整理本轮结论");
    expect(ready.statusMessage).toBe("本轮评审已结束，系统正在整理结论");

    const summarizing = resolveHypothesisFirstNextAction({
      ...base,
      meetings: [meeting({ status: "summarizing" })],
    });
    expect(summarizing.stage).toBe("review_summarizing");
    expect(summarizing.statusMessage).toBe("本轮评审已结束，系统正在整理结论");

    const approval = resolveHypothesisFirstNextAction({
      ...base,
      meetings: [meeting({
        status: "awaiting_approval",
        digestDraft: {
          summary: "本轮结论",
          contentHash: "h2",
          evidenceRequests: [{
            rationale: "need papers",
            candidateRefs: ["cand-1"],
            searchEnvelope: { keywords: ["spike train"], sourceTypes: ["paper"], evidenceLevels: ["primary"] },
          }],
        },
      })],
    });
    expect(approval.stage).toBe("review_awaiting_approval");
    expect(approval.command).toBe("approve_review_digest");
    expect(approval.commandLabel).toBe("确认并结束本轮");
    expect(approval.navigationLabel).toBe("前往确认本轮");
    expect(approval.disabledReason).toBeUndefined();
  });

  it("disables review confirm when evidence requests have no keywords", () => {
    const next = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      selection: selection(),
      chainState: chain({ selectionId: "sel-1", candidateCount: 1 }),
      meetings: [meeting({
        status: "awaiting_approval",
        digestDraft: {
          summary: "空关键词",
          evidenceRequests: [{ searchEnvelope: { keywords: ["  "] } }],
        },
      })],
    });
    expect(next.disabledReason).toContain("有效搜集关键词");
    expect(next.commandLabel).toBe("确认并结束本轮");
  });

  it("shows 资料搜集中 after a child run is bound", () => {
    const next = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      selection: selection(),
      chainState: chain({ selectionId: "sel-1", collectionReady: true }),
      meetings: [meeting({ status: "closed" })],
      collectionRequests: [request({ status: "running" })],
      collectionChildStatus: "running",
    });
    expect(next.stage).toBe("collecting");
    expect(next.targetNodeId).toBe("source_finding");
    expect(next.statusMessage).toBe("资料搜集中");
    expect(next.command).toBeUndefined();
    expect(next.navigationLabel).toBe("查看资料搜集");
    expect(shouldHideSourceFindingStart(next.stage)).toBe(true);
  });

  it("enters collection recovery for failed or needs_continue child runs", () => {
    const failed = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      selection: selection(),
      meetings: [meeting({ status: "closed" })],
      collectionRequests: [request({ status: "failed" })],
      collectionChildStatus: "failed",
    });
    expect(failed.stage).toBe("collection_recovery");
    expect(failed.command).toBe("retry_collection");
    expect(failed.commandLabel).toBe("重试搜集");
    expect(failed.recovery?.reason).toBe("资料搜集启动失败，请重试。");

    const cont = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      selection: selection(),
      meetings: [meeting({ status: "closed" })],
      collectionRequests: [request({ status: "needs_continue" })],
      collectionChildStatus: "needs_continue",
    });
    expect(cont.command).toBe("continue_collection");
    expect(cont.commandLabel).toBe("继续搜集");
  });

  it("retries handoff after the child run completed but the request is not handed off", () => {
    const next = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      selection: selection(),
      meetings: [meeting({ status: "closed" })],
      collectionRequests: [request({ status: "completed" })],
      collectionChildStatus: "completed",
    });
    expect(next.stage).toBe("handoff_pending");
    expect(next.targetNodeId).toBe("hf_collection_req-1");
    expect(next.command).toBe("retry_handoff");
    expect(next.commandLabel).toBe("重试自动交接");
    expect(next.navigationLabel).not.toBe(next.commandLabel);
  });

  it("carries the real collectionRunId through recovery and handoff states", () => {
    const failed = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      selection: selection(),
      meetings: [meeting({ status: "closed" })],
      collectionRequests: [request({ status: "failed", collectionRunId: "run-collect-99" })],
      collectionChildStatus: "failed",
    });
    expect(failed.stage).toBe("collection_recovery");
    expect(failed.collectionRunId).toBe("run-collect-99");
    expect(failed.collectionRunId).not.toBe(failed.collectionRequestId);
    expect(failed.collectionRunId).not.toBe("unknown");

    const handoff = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      selection: selection(),
      meetings: [meeting({ status: "closed" })],
      collectionRequests: [request({ status: "completed", collectionRunId: "run-collect-99" })],
      collectionChildStatus: "completed",
    });
    expect(handoff.stage).toBe("handoff_pending");
    expect(handoff.collectionRunId).toBe("run-collect-99");
    expect(handoff.collectionRunId).not.toBe(handoff.collectionRequestId);

    const collecting = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      selection: selection(),
      chainState: chain({ selectionId: "sel-1", collectionReady: true }),
      meetings: [meeting({ status: "closed" })],
      collectionRequests: [request({ status: "running", collectionRunId: "run-collect-99" })],
      collectionChildStatus: "running",
    });
    expect(collecting.stage).toBe("collecting");
    expect(collecting.collectionRunId).toBe("run-collect-99");
  });

  it("blocks handoff with a human-readable reason when the request has no bound run", () => {
    const next = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      selection: selection(),
      meetings: [meeting({ status: "closed" })],
      collectionRequests: [request({ status: "completed", collectionRunId: "" })],
      collectionChildStatus: "completed",
    });
    expect(next.stage).toBe("blocked");
    expect(next.collectionRunId).toBeUndefined();
    expect(next.command).toBeUndefined();
    expect(next.disabledReason).toContain("缺少子运行标识");
  });

  it("navigates to the next review after handoff", () => {
    const next = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      selection: selection(),
      meetings: [
        meeting({ meetingRoundId: "mtg-1", status: "closed", roundIndex: 1 }),
        meeting({
          meetingRoundId: "mtg-2",
          status: "open",
          roundIndex: 2,
          previousMeetingRoundId: "mtg-1",
          startedAt: "2026-08-19T04:00:00Z",
        }),
      ],
      collectionRequests: [request({
        status: "handed_off",
        handedOffAt: "2026-08-19T03:30:00Z",
        handoffRef: "kp-1",
      })],
      boundChatRoundsTerminal: false,
    });
    expect(next.stage).toBe("next_review");
    expect(next.targetNodeId).toBe("hf_meeting_2");
    expect(next.navigationLabel).toBe("前往下一轮讨论");
    expect(next.command).toBeUndefined();
  });

  it("explains the consequence of confirming a review round", () => {
    const next = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      chainState: chain({ selectionId: "sel-1" }),
      selection: selection(),
      meetings: [meeting({
        status: "awaiting_approval",
        digestDraft: { contentHash: "hash-1", agendaSummary: "s", agreements: [], disagreements: [], blockers: [], actionItems: [], decisionRefs: [], sourceMessageRefs: [] },
      })],
    });
    expect(next.commandLabel).toBe("确认并结束本轮");
    expect(next.commandDetail).toContain("归档本轮评审纪要");
  });

  it("keeps an awaiting-approval review gate ahead of converged navigation", () => {
    const next = resolveHypothesisFirstNextAction({
      run: { runId: "run-1", runtimeCurrentNodeIds: ["source_finding"] },
      chainState: chain({ hypothesisConverged: true, selectionId: "sel-1" }),
      selection: selection(),
      meetings: [meeting({
        status: "awaiting_approval",
        digestDraft: { contentHash: "hash-1", agendaSummary: "s", agreements: [], disagreements: [], blockers: [], actionItems: [], decisionRefs: [], sourceMessageRefs: [] },
      })],
    });
    expect(next.stage).toBe("review_awaiting_approval");
    expect(next.command).toBe("approve_review_digest");
    expect(next.commandLabel).toBe("确认并结束本轮");
  });

  it("keeps an active r5 review ahead of no-run and converged fallbacks", () => {
    const next = resolveHypothesisFirstNextAction({
      run: null,
      workflowActive: true,
      chainState: chain({ hypothesisConverged: true, selectionId: "sel-1" }),
      selection: selection(),
      meetings: [meeting({
        meetingRoundId: "r5",
        roundIndex: 5,
        status: "open",
      })],
      boundChatRoundsTerminal: false,
    });

    expect(next.stage).toBe("review_running");
    expect(next.targetNodeId).toBe("hf_meeting_5");
    expect(next.navigationLabel).toBe("查看评审讨论");
    expect(next.command).toBeUndefined();
    expect(next.navigationLabel).not.toBe("选择题目开始研究");
  });

  it("ignores meetings from another question when resolving the active r5 review", () => {
    const next = resolveHypothesisFirstNextAction({
      run: null,
      workflowActive: true,
      chainState: chain({
        questionId: "SCI-001",
        hypothesisConverged: true,
        selectionId: "sel-1",
      }),
      selection: selection({ questionId: "SCI-001" }),
      meetings: [
        meeting({
          question: "SCI-001",
          meetingRoundId: "r5-current",
          roundIndex: 5,
          status: "open",
        }),
        meeting({
          question: "SCI-002",
          meetingRoundId: "r6-other-question",
          roundIndex: 6,
          status: "open",
        }),
      ],
      boundChatRoundsTerminal: false,
    });

    expect(next.stage).toBe("review_running");
    expect(next.targetNodeId).toBe("hf_meeting_5");
    expect(next.meetingRoundId).toBe("r5-current");
  });

  it("follows the canonical runtime node after hypothesis convergence", () => {
    const converged = resolveHypothesisFirstNextAction({
      run: { runId: "run-1", runtimeCurrentNodeIds: ["protocol_design"] },
      chainState: chain({ hypothesisConverged: true, selectionId: "sel-1" }),
      selection: selection(),
    });
    expect(converged.stage).toBe("converged");
    expect(converged.targetNodeId).toBe("protocol_design");
    expect(converged.navigationLabel).toBe("前往协议设计");
    expect(converged.command).toBeUndefined();
    expect(converged.statusMessage).toContain("闭环已完成");
  });

  it("keeps the convergence gate as fallback until a formal runtime node is projected", () => {
    const converged = resolveHypothesisFirstNextAction({
      run: { runId: "run-1", runtimeCurrentNodeIds: [] },
      chainState: chain({ hypothesisConverged: true, selectionId: "sel-1" }),
      selection: selection(),
    });
    expect(converged.targetNodeId).toBe("hf_convergence_gate");

    const exhausted = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      chainState: chain({ budgetExhausted: true, selectionId: "sel-1" }),
      selection: selection(),
    });
    expect(exhausted.stage).toBe("budget_exhausted");
    expect(exhausted.command).toBe("human_adjudication");
    expect(exhausted.commandLabel).toBe("人工裁决");
    expect(exhausted.navigationLabel).toBe("前往假说收敛");
  });

  it("returns a blocked recovery when the chain is unrecognizable", () => {
    const next = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      chainState: chain({ selectionId: "sel-1" }),
      selection: selection(),
      meetings: [],
      selectedNodeId: "hf_selection",
    });
    expect(next.stage).toBe("blocked");
    expect(next.disabledReason).toContain("评审讨论尚未开启");
  });

  it("keeps navigation copy distinct from inspector write copy", () => {
    const stages = [
      resolveHypothesisFirstNextAction({
        run: { runId: "run-1" },
        meetings: [meeting({ meetingType: "hypothesis_candidate_generation", status: "open" })],
        boundChatRoundsTerminal: true,
      }),
      resolveHypothesisFirstNextAction({
        run: { runId: "run-1" },
        chainState: chain({ candidateCount: 1 }),
        meetings: [meeting({ meetingType: "hypothesis_candidate_generation", status: "closed" })],
      }),
      resolveHypothesisFirstNextAction({
        run: { runId: "run-1" },
        selection: selection(),
        meetings: [meeting({
          status: "awaiting_approval",
          digestDraft: {
            summary: "ok",
            evidenceRequests: [{ searchEnvelope: { keywords: ["a"] } }],
          },
        })],
      }),
    ];
    for (const next of stages) {
      expect(next.commandLabel).toBeTruthy();
      expect(next.navigationLabel).not.toBe(next.commandLabel);
    }
  });
});

describe("evidence request helpers", () => {
  it("requires at least one non-empty keyword", () => {
    expect(hasValidEvidenceRequestKeywords([])).toBe(false);
    expect(hasValidEvidenceRequestKeywords([{ searchEnvelope: { keywords: ["  "] } }])).toBe(false);
    expect(hasValidEvidenceRequestKeywords([{ searchEnvelope: { keywords: ["EEG"] } }])).toBe(true);
    expect(reviewDigestConfirmBlocker({
      summary: "x",
      agreements: ["marker consensus"],
      evidenceRequests: [{ searchEnvelope: { keywords: [] } }],
    })).toContain("有效搜集关键词");
    expect(reviewDigestConfirmBlocker({
      summary: "x",
      agreements: [],
      disagreements: [],
      actionItems: [],
      knowledgeCandidates: [],
      evidenceRequests: [],
    })).toBe("纪要未捕获讨论内容");
    // Zero requests with captured discussion is the legal convergence close:
    // the button must stay clickable so the chain can converge via UI.
    expect(reviewDigestConfirmBlocker({
      summary: "x",
      agreements: ["marker consensus"],
      evidenceRequests: [],
    })).toBeUndefined();
  });
});

describe("bound chat terminal detection", () => {
  it("trusts the server flag when present, otherwise requires every bound round to be terminal", () => {
    expect(boundChatRoundsAreTerminal({
      meeting: meeting({ boundChatRoundsTerminal: true }),
    })).toBe(true);
    expect(boundChatRoundsAreTerminal({
      meeting: meeting({ chatRoomRoundIds: ["r1", "r2"] }),
      chatRounds: [
        { roundId: "r1", status: "completed" },
        { roundId: "r2", status: "running" },
      ],
    })).toBe(false);
    expect(boundChatRoundsAreTerminal({
      meeting: meeting({ chatRoomRoundIds: ["r1"] }),
      chatRounds: [{ roundId: "r1", status: "completed" }],
    })).toBe(true);
  });
});

describe("focusNodeFromNextAction", () => {
  it("never falls back to source_finding for a new generation", () => {
    const next = resolveHypothesisFirstNextAction({
      run: { runId: "run-1" },
      meetings: [meeting({ meetingType: "hypothesis_candidate_generation", status: "open" })],
    });
    expect(focusNodeFromNextAction(next)).toBe("hf_generation");
    expect(focusNodeFromNextAction(next)).not.toBe("source_finding");
  });
});
