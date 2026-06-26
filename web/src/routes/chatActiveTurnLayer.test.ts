import { describe, expect, it } from "vitest";

import type { ConversationMessage, SessionDetail, SessionStreamEvent } from "../api/types";
import {
  activeTurnLayerToConversationMessage,
  isActiveTurnSettledByDetail,
  mergeAssistantDeltaIntoActiveTurnLayer,
} from "./chatActiveTurnLayer";

function assistantDelta(
  patch: Partial<Extract<SessionStreamEvent, { type: "assistant_delta" }>>,
): Extract<SessionStreamEvent, { type: "assistant_delta" }> {
  return {
    type: "assistant_delta",
    sessionId: "session-1",
    turnId: "turn-1",
    ledgerSeq: 1,
    stage: "responding",
    content: "",
    thought: "",
    contentDelta: "",
    thoughtDelta: "",
    replaceContent: false,
    replaceThought: false,
    feedbackEvents: [],
    updatedAt: "2026-06-26T08:30:00Z",
    done: false,
    ...patch,
  };
}

describe("chat active turn layer", () => {
  it("merges assistant deltas into a separate active layer message", () => {
    const first = mergeAssistantDeltaIntoActiveTurnLayer(undefined, assistantDelta({ contentDelta: "你" }));
    const second = mergeAssistantDeltaIntoActiveTurnLayer(first, assistantDelta({ contentDelta: "好" }));

    expect(second?.content).toBe("你好");
    expect(second?.thought ?? "").toBe("");
    expect(second?.streaming).toBe(true);

    const message = activeTurnLayerToConversationMessage(second);

    expect(message?.id).toBe("session-1-message-active-turn-1");
    expect(message?.metadata?.kind).toBe("session_active_turn_layer");
    expect(message?.metadata?.turnId).toBe("turn-1");
    expect(message?.content).toBe("你好");
  });

  it("uses replace deltas as a full active-layer recovery snapshot", () => {
    const first = mergeAssistantDeltaIntoActiveTurnLayer(undefined, assistantDelta({ contentDelta: "旧内容" }));
    const recovered = mergeAssistantDeltaIntoActiveTurnLayer(
      first,
      assistantDelta({
        contentDelta: "完整内容",
        thoughtDelta: "完整思考",
        replaceContent: true,
        replaceThought: true,
      }),
    );

    expect(recovered?.content).toBe("完整内容");
    expect(recovered?.thought).toBe("完整思考");
  });

  it("treats the active layer as settled once committed detail has the same assistant turn", () => {
    const active = mergeAssistantDeltaIntoActiveTurnLayer(undefined, assistantDelta({ contentDelta: "临时回答" }));
    const detail = {
      id: "session-1",
      messages: [
        {
          id: "assistant-final",
          role: "assistant",
          content: "正式回答",
          timestamp: "2026-06-26T08:31:00Z",
          metadata: { turnId: "turn-1" },
        } satisfies ConversationMessage,
      ],
    } as SessionDetail;

    expect(isActiveTurnSettledByDetail(active, detail)).toBe(true);
  });
});
