import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import {
  filterServerTimelineItemsForDisplayPlan,
  resolveAssistantDisplayPlan,
} from "./assistantDisplayPlan";
import type { CodexTranscriptSurface } from "./codexNativeTranscriptSurface";

function message(patch: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: "message-1",
    role: "assistant",
    content: "",
    timestamp: "2026-08-05T12:00:00Z",
    ...patch,
  };
}

function nativeSurface(cells: CodexTranscriptSurface["cells"], patch?: Partial<CodexTranscriptSurface>): CodexTranscriptSurface {
  const hasAssistantMarkdown = cells.some((cell) => cell.kind === "assistant_markdown" && Boolean(cell.text?.trim()));
  const ownsProcess = cells.some((cell) => {
    if (cell.kind === "user") return false;
    if (cell.kind === "assistant_markdown") {
      const phase = String(cell.phase || "").toLowerCase();
      const channel = String(cell.channel || "").toLowerCase();
      return phase === "commentary" || phase === "interim" || channel === "commentary";
    }
    return true;
  });
  return {
    mode: "native",
    source: "message.codexTranscript",
    cells,
    hasAssistantMarkdown,
    suppressProjectedProcess: ownsProcess,
    suppressProjectedResponse: hasAssistantMarkdown,
    suppressProjectedTurnStatus: hasAssistantMarkdown || ownsProcess,
    suppressProjectedError: false,
    ...patch,
  };
}

describe("assistantDisplayPlan", () => {
  it("lets projected content own the body when native is only an orphan fragment", () => {
    const fullAnswer = "继续审查后的结论更明确：仅打开状态栏不会降低缓存命中率。";
    const plan = resolveAssistantDisplayPlan({
      message: message({
        content: fullAnswer,
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "message-1",
          cells: [
            {
              id: "orphan",
              kind: "assistant_markdown",
              messageId: "message-1",
              status: "completed",
              tone: "neutral",
              text: "存。",
            },
          ],
        },
      }),
      surface: nativeSurface([
        {
          id: "orphan",
          kind: "assistant_markdown",
          messageId: "message-1",
          status: "completed",
          tone: "neutral",
          text: "存。",
        },
      ], { suppressProjectedResponse: false }),
    });

    expect(plan.renderMode).toBe("legacy");
    expect(plan.nativeOwnsFinalAnswer).toBe(false);
    expect(plan.answerOwner).toBe("response_section");
    expect(plan.suppressProjectedResponse).toBe(false);
    expect(plan.includeTimelineAssistantText).toBe(false);
  });

  it("uses package_cells mode when turnItems v2 package is present", () => {
    const fullAnswer = "检查完成。";
    const plan = resolveAssistantDisplayPlan({
      message: message({
        content: fullAnswer,
        turnItems: [
          {
            version: 2,
            id: "answer:0",
            itemId: "answer",
            type: "assistant_message",
            kind: "assistant_message",
            channel: "answer",
            phase: "final_answer",
            status: "completed",
            provisional: false,
            terminal: true,
            revision: 0,
            sequence: 1,
            text: fullAnswer,
          },
        ],
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "message-1",
          cells: [
            {
              id: "final",
              kind: "assistant_markdown",
              messageId: "message-1",
              status: "completed",
              tone: "neutral",
              phase: "final_answer",
              terminal: true,
              text: fullAnswer,
            },
          ],
        },
      }),
      surface: nativeSurface([
        {
          id: "final",
          kind: "assistant_markdown",
          messageId: "message-1",
          status: "completed",
          tone: "neutral",
          phase: "final_answer",
          terminal: true,
          text: fullAnswer,
        },
      ]),
      serverTimelineItems: [
        { kind: "assistant_text", text: fullAnswer },
        { kind: "command_group", text: "tools" },
      ],
    });

    expect(plan.renderMode).toBe("package_cells");
    expect(plan.hasTurnItemPackage).toBe(true);
    expect(plan.answerOwner).toBe("canonical_turn_items");
    expect(plan.includeTimelineAssistantText).toBe(false);
    expect(plan.stripTimelineAssistantText).toBe(true);
    expect(plan.suppressProjectedResponse).toBe(true);
    expect(plan.shouldRenderCodexSurface).toBe(true);

    const filtered = filterServerTimelineItemsForDisplayPlan(
      [
        { kind: "assistant_text", text: fullAnswer },
        { kind: "command_group", text: "tools" },
      ],
      plan,
    );
    expect(filtered).toEqual([{ kind: "command_group", text: "tools" }]);
  });

  it("lets explicit final_answer native cells own the body without package", () => {
    const fullAnswer = "检查完成。";
    const plan = resolveAssistantDisplayPlan({
      message: message({
        content: "legacy duplicate final",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "message-1",
          cells: [
            {
              id: "final",
              kind: "assistant_markdown",
              messageId: "message-1",
              status: "completed",
              tone: "neutral",
              phase: "final_answer",
              terminal: true,
              text: fullAnswer,
            },
          ],
        },
      }),
      surface: nativeSurface([
        {
          id: "final",
          kind: "assistant_markdown",
          messageId: "message-1",
          status: "completed",
          tone: "neutral",
          phase: "final_answer",
          terminal: true,
          text: fullAnswer,
        },
      ]),
    });

    expect(plan.renderMode).toBe("native_transcript");
    expect(plan.nativeOwnsFinalAnswer).toBe(true);
    expect(plan.answerOwner).toBe("native_transcript");
    expect(plan.suppressProjectedResponse).toBe(true);
    expect(plan.includeTimelineAssistantText).toBe(false);
  });

  it("omits assistant-only server timeline when native owns the final answer", () => {
    const plan = resolveAssistantDisplayPlan({
      message: message({
        content: "最终回答",
        timelineItems: [
          {
            id: "t1",
            kind: "assistant_text",
            status: "completed",
            text: "最终回答",
          },
        ],
      }),
      surface: nativeSurface([
        {
          id: "final",
          kind: "assistant_markdown",
          messageId: "message-1",
          status: "completed",
          tone: "neutral",
          phase: "final_answer",
          terminal: true,
          text: "最终回答",
        },
      ]),
      serverTimelineItems: [
        { kind: "assistant_text", text: "最终回答" },
      ],
    });

    expect(plan.nativeOwnsFinalAnswer).toBe(true);
    expect(plan.omitAssistantOnlyServerTimeline).toBe(true);
    expect(plan.includeTimelineAssistantText).toBe(false);
    expect(filterServerTimelineItemsForDisplayPlan(
      [{ kind: "assistant_text", text: "最终回答" }],
      plan,
    )).toBeUndefined();
  });

  it("lets timeline own the final answer only in legacy mode", () => {
    const fullAnswer = "这是完整最终回答。";
    const plan = resolveAssistantDisplayPlan({
      message: message({ content: fullAnswer }),
      surface: {
        mode: "empty",
        source: "none",
        cells: [],
        hasAssistantMarkdown: false,
        suppressProjectedProcess: false,
        suppressProjectedResponse: false,
        suppressProjectedTurnStatus: false,
        suppressProjectedError: false,
      },
      builtTimelineItems: [
        { kind: "assistant_text", text: fullAnswer },
        { kind: "operation", text: "tool" },
      ],
      hasAgentMessageTimeline: true,
    });

    expect(plan.renderMode).toBe("legacy");
    expect(plan.timelineOwnsFinalAnswer).toBe(true);
    expect(plan.answerOwner).toBe("timeline_assistant_text");
    expect(plan.suppressProjectedResponse).toBe(true);
  });

  it("renders process alongside answer only when cells do not already own process", () => {
    const fullAnswer = "最终回答。";
    const answerOnlySurface = nativeSurface([
      {
        id: "final",
        kind: "assistant_markdown",
        messageId: "message-1",
        status: "completed",
        tone: "neutral",
        phase: "final_answer",
        terminal: true,
        text: fullAnswer,
      },
    ]);
    const alongside = resolveAssistantDisplayPlan({
      message: message({ content: fullAnswer }),
      surface: answerOnlySurface,
      hasAgentMessageTimeline: true,
    });
    expect(alongside.nativeOwnsFinalAnswer).toBe(true);
    expect(alongside.suppressProjectedProcess).toBe(false);
    expect(alongside.shouldRenderNativeProcessAlongsideAnswer).toBe(true);

    const processInCells = resolveAssistantDisplayPlan({
      message: message({ content: fullAnswer }),
      surface: nativeSurface([
        {
          id: "tool",
          kind: "tool_call",
          messageId: "message-1",
          status: "completed",
          tone: "neutral",
          title: "run",
        },
        {
          id: "final",
          kind: "assistant_markdown",
          messageId: "message-1",
          status: "completed",
          tone: "neutral",
          phase: "final_answer",
          terminal: true,
          text: fullAnswer,
        },
      ]),
      hasAgentMessageTimeline: true,
    });
    expect(processInCells.suppressProjectedProcess).toBe(true);
    expect(processInCells.shouldRenderNativeProcessAlongsideAnswer).toBe(false);
  });
});
