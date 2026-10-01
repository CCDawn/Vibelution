import { describe, expect, it } from "vitest";

import type { AssistantConversationTurn, SessionTurnItem } from "../../api/types";
import {
  MIN_TURN_WORK_HEADER_DURATION_MS,
  formatConversationTurnWorkBreakdown,
  formatConversationTurnWorkDuration,
  formatConversationTurnWorkedFor,
  resolveConversationTurnWorkSummary,
} from "./conversationTurnWorkStatus";

let itemSeq = 0;

/** Backend-projected turn header fields (additive wire fields, batch A). */
type TurnHeaderOverrides = {
  turnState?: string;
  turnStartedAt?: string;
  turnEndedAt?: string;
  turnActiveMs?: number;
};

function toolItem(overrides: Partial<Extract<SessionTurnItem, { type: "tool_call" }>> = {}):
Extract<SessionTurnItem, { type: "tool_call" }> {
  itemSeq += 1;
  return {
    id: `tool-${itemSeq}-r1`,
    itemId: `tool-${itemSeq}`,
    version: 3,
    sessionId: "session-1",
    turnId: "turn-1",
    type: "tool_call",
    status: "completed",
    revision: 1,
    sequence: itemSeq,
    callId: `call-${itemSeq}`,
    toolName: "terminal",
    metadata: {},
    ...overrides,
  };
}

function answerItem(text = "完成。"): Extract<SessionTurnItem, { type: "agent_message" }> {
  itemSeq += 1;
  return {
    id: `answer-${itemSeq}-r1`,
    itemId: `answer-${itemSeq}`,
    version: 3,
    sessionId: "session-1",
    turnId: "turn-1",
    type: "agent_message",
    phase: "final_answer",
    status: "completed",
    revision: 1,
    sequence: itemSeq,
    text,
  };
}

function turn(overrides: Partial<AssistantConversationTurn> = {}): AssistantConversationTurn {
  return {
    id: "assistant-1",
    role: "assistant",
    timestamp: "2026-09-16T10:00:00.000Z",
    turnId: "turn-1",
    status: "completed",
    turnItems: [],
    ...overrides,
  };
}

describe("conversationTurnWorkStatus", () => {
  it("keeps the noise threshold at 5 seconds", () => {
    expect(MIN_TURN_WORK_HEADER_DURATION_MS).toBe(5_000);
  });

  it("derives the turn span from the message timestamp to timed item facts", () => {
    const startMs = Date.parse("2026-09-16T10:00:00.000Z");
    const summary = resolveConversationTurnWorkSummary(turn({
      turnItems: [
        toolItem({
          metadata: {
            executionStartedAtEpochMs: startMs + 1_000,
            durationMs: 120_000,
          },
        }),
        // Legacy/cell-derived items may carry revision stamps; the freshest
        // stamp is the span end.
        answerItem(),
      ],
    }));
    // Canonical items carry no stamps here, so the span ends at the tool
    // completion (start + 1s + 120s) — an honest lower bound.
    expect(summary).toEqual({
      durationMs: 121_000,
      basis: "turn_span",
      toolCallCount: 1,
      toolDurationMs: 120_000,
    });
  });

  it("uses item updatedAt stamps as span end when present", () => {
    const summary = resolveConversationTurnWorkSummary(turn({
      turnItems: [
        toolItem({ metadata: {} }),
        {
          ...answerItem(),
          updatedAt: "2026-09-16T10:02:30.000Z",
        },
      ],
    }));
    expect(summary?.basis).toBe("turn_span");
    expect(summary?.durationMs).toBe(150_000);
    // No tool reported a duration: count is known, the sum is honestly null.
    expect(summary?.toolCallCount).toBe(1);
    expect(summary?.toolDurationMs).toBeNull();
  });

  it("falls back to the labeled tool-duration sum without any timestamps", () => {
    const summary = resolveConversationTurnWorkSummary(turn({
      turnItems: [
        toolItem({ metadata: { durationMs: 40_000 } }),
        toolItem({ metadata: { durationMs: 25_000 } }),
        answerItem(),
      ],
    }));
    expect(summary).toEqual({
      durationMs: 65_000,
      basis: "tool_durations",
      toolCallCount: 2,
      toolDurationMs: 65_000,
    });
  });

  it("prefers the authoritative backend turn header (turnActiveMs)", () => {
    // The backend-measured work time wins over the heuristic span even when
    // item stamps would tell a different (less complete) story.
    const message = turn({
      turnItems: [
        toolItem({
          metadata: { executionStartedAtEpochMs: Date.parse("2026-09-16T10:00:01.000Z"), durationMs: 3_000 },
        }),
        { ...answerItem(), createdAt: "2026-09-16T10:00:05.000Z", updatedAt: "2026-09-16T10:00:09.000Z" },
      ],
    }) as AssistantConversationTurn & TurnHeaderOverrides;
    message.turnState = "completed";
    message.turnStartedAt = "2026-09-16T10:00:00.000Z";
    message.turnEndedAt = "2026-09-16T10:01:30.000Z";
    message.turnActiveMs = 90_000;
    const summary = resolveConversationTurnWorkSummary(message);
    expect(summary).toEqual({
      durationMs: 90_000,
      basis: "turn_header",
      toolCallCount: 1,
      toolDurationMs: 3_000,
    });
  });

  it("derives the header span from turnStartedAt/turnEndedAt when activeMs is absent", () => {
    const message = turn({
      turnItems: [toolItem({ metadata: {} })],
    }) as AssistantConversationTurn & TurnHeaderOverrides;
    message.turnState = "completed";
    message.turnStartedAt = "2026-09-16T10:00:00.000Z";
    message.turnEndedAt = "2026-09-16T10:02:30.000Z";
    const summary = resolveConversationTurnWorkSummary(message);
    expect(summary).toEqual({
      durationMs: 150_000,
      basis: "turn_header",
      toolCallCount: 1,
      toolDurationMs: null,
    });
  });

  it("keeps the honest degradation for running turns even with a header", () => {
    // Live turns have no settled span; the header alone must not fabricate one.
    const message = turn({
      turnItems: [toolItem({ metadata: { durationMs: 40_000 } })],
    }) as AssistantConversationTurn & TurnHeaderOverrides;
    message.turnState = "running";
    message.turnStartedAt = "2026-09-16T10:00:00.000Z";
    message.turnActiveMs = 90_000;
    const summary = resolveConversationTurnWorkSummary(message);
    expect(summary).toEqual({
      durationMs: 40_000,
      basis: "tool_durations",
      toolCallCount: 1,
      toolDurationMs: 40_000,
    });
  });

  it("reads the first-class tool durationMs before the metadata fallback", () => {
    const summary = resolveConversationTurnWorkSummary(turn({
      turnItems: [
        toolItem({ metadata: { durationMs: 40_000 }, durationMs: 9_000 } as Partial<Extract<SessionTurnItem, { type: "tool_call" }>>),
      ],
    }));
    expect(summary?.basis).toBe("tool_durations");
    expect(summary?.durationMs).toBe(9_000);
    expect(summary?.toolDurationMs).toBe(9_000);
  });

  it("drops sub-threshold turns and turns without any time facts", () => {
    const startMs = Date.parse("2026-09-16T10:00:00.000Z");
    // 3s span: below the header threshold.
    expect(resolveConversationTurnWorkSummary(turn({
      turnItems: [toolItem({
        metadata: {
          executionStartedAtEpochMs: startMs,
          durationMs: 3_000,
        },
      })],
    }))).toBeNull();
    // 3s of tools with no span anchors: still below threshold.
    expect(resolveConversationTurnWorkSummary(turn({
      turnItems: [toolItem({ metadata: { durationMs: 3_000 } })],
    }))).toBeNull();
    // Untimed shell: nothing to show.
    expect(resolveConversationTurnWorkSummary(turn({
      turnItems: [answerItem()],
    }))).toBeNull();
  });

  it("formats two-unit durations for zh and en", () => {
    expect(formatConversationTurnWorkDuration(202_000, "zh")).toBe("3 分 22 秒");
    expect(formatConversationTurnWorkDuration(202_000, "en")).toBe("3m 22s");
    expect(formatConversationTurnWorkDuration(7_265_000, "zh")).toBe("2 时 1 分");
    expect(formatConversationTurnWorkDuration(900_000, "zh")).toBe("15 分");
    expect(formatConversationTurnWorkDuration(1_000, "zh")).toBe("1 秒");
  });

  it("labels the trigger by basis and keeps the breakdown factual", () => {
    const span: NonNullable<ReturnType<typeof resolveConversationTurnWorkSummary>> = {
      durationMs: 121_000,
      basis: "turn_span",
      toolCallCount: 1,
      toolDurationMs: 120_000,
    };
    expect(formatConversationTurnWorkedFor(span, "zh")).toBe("已工作 2 分 1 秒");
    expect(formatConversationTurnWorkedFor(span, "en")).toBe("Worked for 2m 1s");
    expect(formatConversationTurnWorkBreakdown(span, "zh")).toBe("工具调用 1 次 · 工具耗时 2 分");

    const toolOnly: NonNullable<ReturnType<typeof resolveConversationTurnWorkSummary>> = {
      durationMs: 65_000,
      basis: "tool_durations",
      toolCallCount: 2,
      toolDurationMs: 65_000,
    };
    expect(formatConversationTurnWorkedFor(toolOnly, "zh")).toBe("工具耗时 1 分 5 秒");
    expect(formatConversationTurnWorkBreakdown(toolOnly, "zh")).toBe("工具调用 2 次 · 工具耗时 1 分 5 秒");

    const untimed: NonNullable<ReturnType<typeof resolveConversationTurnWorkSummary>> = {
      durationMs: 150_000,
      basis: "turn_span",
      toolCallCount: 1,
      toolDurationMs: null,
    };
    expect(formatConversationTurnWorkBreakdown(untimed, "zh")).toBe("工具调用 1 次");
  });
});
