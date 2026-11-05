/** @vitest-environment happy-dom */
import React, { act, useEffect, useMemo } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import conversationViewSource from "./ConversationView.tsx?raw";
import {
  migrateSectionExpansionRecords,
  useConversationProcessExpansion,
  type UseConversationProcessExpansionInput,
  type UseConversationProcessExpansionResult,
} from "./useConversationProcessExpansion";
import type { RetiredOverlayAlias } from "./useAgentMessageTimelineProjection";
import { projectAgentMessageTimelineMessages } from "./useAgentMessageTimelineProjection";
import { ConversationProcessDisclosure } from "./ConversationProcessDisclosure";
import type { ConversationMessage } from "../../api/types";
import { assistantTurnIsStreaming } from "../../routes/chatTurnProtocol";
import { buildAgentMessageOperations } from "./agentMessageOperations";
import { buildAgentMessageTimelineItems } from "./agentMessageTimeline";
import { buildCodexTranscriptCells } from "./codexTranscriptCells";
import { createCodexTranscriptCellRenderers } from "./conversationCodexTranscriptCells";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function baseInput(overrides: Partial<UseConversationProcessExpansionInput> = {}): UseConversationProcessExpansionInput {
  return {
    sessionId: "session-overlay-alias",
    timelineMessages: [],
    activeTimelineMessages: [],
    agentRenderStatesByMessageId: new Map(),
    agentTimelineItemsByMessageId: new Map(),
    agentOperationGroupsByMessageId: new Map(),
    ...overrides,
  };
}

function mountExpansionHook(initial: UseConversationProcessExpansionInput) {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  let input = initial;
  let latest: UseConversationProcessExpansionResult | undefined;
  const HookHost = () => {
    latest = useConversationProcessExpansion(input);
    return null;
  };
  const render = (overrides?: Partial<UseConversationProcessExpansionInput>) => {
    input = { ...input, ...overrides };
    root.render(<HookHost />);
  };
  const unmount = async () => {
    await act(async () => root.unmount());
    host.remove();
  };
  return {
    render,
    unmount,
    get result(): UseConversationProcessExpansionResult {
      if (!latest) {
        throw new Error("expansion hook is not mounted");
      }
      return latest;
    },
  };
}

function assistantFrame(id: string, completed = false, turnId = "turn-atomic"): ConversationMessage {
  const status = completed ? "completed" : "running";
  const common = { version: 3, sessionId: "session-overlay-alias", turnId, revision: 1, status, terminal: completed } as const;
  return {
    id,
    role: "assistant",
    turnId,
    status,
    timestamp: "2026-11-03T10:00:00Z",
    metadata: { turnId, ...(completed ? {} : { kind: "session_live_overlay" }) },
    turnItems: [
      { ...common, id: "thought-1:1", itemId: "thought-1", type: "reasoning", sequence: 1, text: "Thought" },
      { ...common, id: "answer-1:1", itemId: "answer-1", type: "agent_message", phase: "final_answer", sequence: 2, text: "Answer" },
    ],
  };
}

/** Uses the actual projection and remounts a row when its message id changes. */
function mountProjectedExpansion(initial: ConversationMessage[], companionMode: boolean) {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  let messages = initial;
  let activeTurnMessage: ConversationMessage | undefined;
  let sessionId = "session-overlay-alias";
  const Host = () => {
    const projection = useMemo(() => projectAgentMessageTimelineMessages({ timelineMessages: messages, activeTurnMessage, companionMode }), [messages, activeTurnMessage]);
    const expansion = useConversationProcessExpansion(baseInput({
      sessionId,
      timelineMessages: projection.messages,
      activeTimelineMessages: projection.messages,
      timelineRowIdentities: projection.rowIdentities,
      retiredOverlayAliases: projection.retiredOverlayAliases,
    }));
    useEffect(() => expansion.resetSessionExpansion(), [sessionId]);
    const renderers = createCodexTranscriptCellRenderers({ lang: "en", t: (key) => key, ...expansion });
    return projection.messages.map((message, index) => {
      const agentMessage = projection.agentMessages[index];
      const operations = buildAgentMessageOperations(agentMessage, { thought: "Thought", mental: "Mental", status: "Status" });
      const timelineItems = buildAgentMessageTimelineItems(agentMessage, operations, { lang: "en" });
      const cells = buildCodexTranscriptCells(agentMessage, { operations, timelineItems });
      return (
        <div key={message.id} data-message-id={message.id}>
          <ConversationProcessDisclosure
            cells={[]}
            language="en"
            turnStreaming={assistantTurnIsStreaming(message)}
            expanded={expansion.getExpansionState(message.id, "process", assistantTurnIsStreaming(message))}
            onExpandedChange={(expanded) => expansion.setExpansionState(message.id, "process", expanded)}
          >
            {cells.filter((cell) => cell.kind === "reasoning_summary").map((cell) => renderers.renderCodexReasoningSummaryCell(message, cell))}
          </ConversationProcessDisclosure>
        </div>
      );
    });
  };
  return {
    host,
    render(next = messages, nextSession = sessionId, nextActiveTurnMessage?: ConversationMessage) {
      messages = next;
      sessionId = nextSession;
      activeTurnMessage = nextActiveTurnMessage;
      root.render(<Host />);
    },
    async unmount() {
      await act(async () => root.unmount());
      host.remove();
    },
  };
}

describe("migrateSectionExpansionRecords", () => {
  it("moves the retired id's record onto the target and drops the source", () => {
    const migrated = migrateSectionExpansionRecords(
      { "s1-message-live-t1": { "reasoning:thought-1": true } },
      [{ fromMessageId: "s1-message-live-t1", toMessageId: "s1-message-42" }],
    );
    expect(migrated).toEqual({ "s1-message-42": { "reasoning:thought-1": true } });
  });

  it("keeps the target's explicit entries over the migrated record", () => {
    const migrated = migrateSectionExpansionRecords(
      {
        "s1-message-live-t1": { "reasoning:a": false, "reasoning:b": true },
        "s1-message-42": { "reasoning:a": true, "reasoning:b": false },
      },
      [{ fromMessageId: "s1-message-live-t1", toMessageId: "s1-message-42" }],
    );
    expect(migrated).toEqual({
      "s1-message-42": { "reasoning:a": true, "reasoning:b": false },
    });
  });

  it("follows alias chains in order and ignores empty or self aliases", () => {
    const migrated = migrateSectionExpansionRecords(
      {
        "s1-message-live-t1": { "reasoning:a": true },
        "s1-message-active-t1": { "reasoning:b": true },
      },
      [
        { fromMessageId: "", toMessageId: "s1-message-42" },
        { fromMessageId: "s1-message-live-t1", toMessageId: "s1-message-live-t1" },
        { fromMessageId: "s1-message-live-t1", toMessageId: "s1-message-active-t1" },
        { fromMessageId: "s1-message-active-t1", toMessageId: "s1-message-42" },
      ],
    );
    expect(migrated).toEqual({ "s1-message-42": { "reasoning:b": true, "reasoning:a": true } });
  });

  it("returns the same reference when no alias hits a record", () => {
    const expansion = { "s1-message-42": { "reasoning:a": true } };
    expect(migrateSectionExpansionRecords(expansion, [])).toBe(expansion);
    expect(migrateSectionExpansionRecords(expansion, [
      { fromMessageId: "ghost-live", toMessageId: "s1-message-42" },
    ])).toBe(expansion);
  });
});

describe("useConversationProcessExpansion overlay alias migration", () => {
  it.each([false, true])("follows running and settled defaults for an untouched controlled process (companion=%s)", async (companionMode) => {
    const mount = mountProjectedExpansion([assistantFrame("same-row")], companionMode);
    try {
      await act(async () => mount.render());
      expect(mount.host.querySelector("summary")!.getAttribute("aria-expanded")).toBe("true");
      await act(async () => mount.render([assistantFrame("same-row", true)]));
      expect(mount.host.querySelector("summary")!.getAttribute("aria-expanded")).toBe("false");
      await act(async () => mount.render([assistantFrame("same-row")]));
      await act(async () => new Promise((resolve) => setTimeout(resolve, 40)));
      expect(mount.host.querySelector("summary")!.getAttribute("aria-expanded")).toBe("true");
    } finally {
      await mount.unmount();
    }
  });

  it.each([false, true])("migrates onto the painted row after overlay dedupe and durable folding choose different ids (companion=%s)", async (companionMode) => {
    const live = assistantFrame("session-overlay-alias-message-live-A");
    const durable = assistantFrame("session-overlay-alias-message-43");
    durable.metadata = { turnId: "turn-atomic", messageIndex: 43 };
    const active = assistantFrame("session-overlay-alias-message-active-B");
    active.metadata = { turnId: "turn-atomic", kind: "session_active_turn_layer" };
    const nextProjection = projectAgentMessageTimelineMessages({
      timelineMessages: [durable, live],
      activeTurnMessage: active,
      companionMode,
    });
    expect(nextProjection.retiredOverlayAliases).toEqual([{ fromMessageId: live.id, toMessageId: active.id }]);
    expect(nextProjection.messages.map((message) => message.id)).toEqual([durable.id]);

    const mount = mountProjectedExpansion([live], companionMode);
    try {
      await act(async () => mount.render());
      await act(async () => mount.host.querySelector('[data-thought-expanded] button')!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })));
      await act(async () => mount.host.querySelector("summary")!.click());
      await act(async () => mount.render([durable, live], "session-overlay-alias", active));
      const paintedRow = mount.host.querySelector('[data-message-id]')!;
      expect(paintedRow.getAttribute("data-message-id")).toBe(durable.id);
      expect(paintedRow.querySelector("summary")!.getAttribute("aria-expanded")).toBe("false");
      expect(paintedRow.querySelector('[data-thought-expanded]')!.getAttribute("data-thought-expanded")).toBe("true");
    } finally {
      await mount.unmount();
    }
  });

  it.each([false, true])("keeps user-opened process and thought across an atomic live→durable remount (companion=%s)", async (companionMode) => {
    const live = assistantFrame("session-overlay-alias-message-live-turn-atomic");
    const durable = assistantFrame("session-overlay-alias-message-42", true);
    expect(projectAgentMessageTimelineMessages({ timelineMessages: [durable], companionMode }).retiredOverlayAliases).toEqual([]);
    const mount = mountProjectedExpansion([live], companionMode);
    try {
      await act(async () => mount.render());
      const liveRow = mount.host.querySelector('[data-message-id]')!;
      const summary = liveRow.querySelector("summary")!;
      await act(async () => summary.click());
      await act(async () => summary.click());
      await act(async () => new Promise((resolve) => setTimeout(resolve, 40)));
      await act(async () => liveRow.querySelector('[data-thought-expanded] button')!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })));
      expect(liveRow.querySelector('[data-thought-expanded]')!.getAttribute("data-thought-expanded")).toBe("true");

      await act(async () => mount.render([durable]));
      const durableRow = mount.host.querySelector('[data-message-id]')!;
      expect(durableRow).not.toBe(liveRow);
      expect(durableRow.getAttribute("data-message-id")).toBe(durable.id);
      expect(durableRow.querySelector('summary')!.getAttribute("aria-expanded")).toBe("true");
      expect(durableRow.querySelector('[data-thought-expanded]')!.getAttribute("data-thought-expanded")).toBe("true");
      await act(async () => mount.render([durable]));
      expect(mount.host.querySelector('[data-thought-expanded]')!.getAttribute("data-thought-expanded")).toBe("true");
    } finally {
      await mount.unmount();
    }
  });

  it("does not transfer a previous session's row choice into the same turn in another session", async () => {
    const mount = mountProjectedExpansion([assistantFrame("old-live")], false);
    try {
      await act(async () => mount.render());
      await act(async () => mount.host.querySelector('[data-thought-expanded] button')!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })));
      await act(async () => mount.render([assistantFrame("other-durable", true)], "other-session"));
      expect(mount.host.querySelector('summary')!.getAttribute("aria-expanded")).toBe("false");
    } finally {
      await mount.unmount();
    }
  });

  it("carries an explicit collapsed process choice through durable and running row replacements", async () => {
    const mount = mountProjectedExpansion([assistantFrame("first-live")], false);
    try {
      await act(async () => mount.render());
      await act(async () => mount.host.querySelector("summary")!.click());
      await act(async () => mount.render([assistantFrame("durable", true)]));
      expect(mount.host.querySelector("summary")!.getAttribute("aria-expanded")).toBe("false");
      await act(async () => mount.render([assistantFrame("replayed-live")]));
      expect(mount.host.querySelector("summary")!.getAttribute("aria-expanded")).toBe("false");
    } finally {
      await mount.unmount();
    }
  });

  it("expires old row identities after the bounded history fills", async () => {
    const mount = mountProjectedExpansion([assistantFrame("old-live")], false);
    try {
      await act(async () => mount.render());
      await act(async () => mount.host.querySelector("summary")!.click());
      await act(async () => mount.host.querySelector("summary")!.click());
      await act(async () => new Promise((resolve) => setTimeout(resolve, 40)));
      await act(async () => mount.render(Array.from({ length: 129 }, (_, index) => (
        assistantFrame(`message-${index}`, true, `turn-${index}`)
      ))));
      await act(async () => mount.render([assistantFrame("old-durable", true)]));
      expect(mount.host.querySelector("summary")!.getAttribute("aria-expanded")).toBe("false");
    } finally {
      await mount.unmount();
    }
  });

  it("carries an explicit live-id toggle onto the durable id after settle", async () => {
    const mount = mountExpansionHook(baseInput());
    await act(async () => mount.render());

    // The user expands a thought section while the turn paints under the
    // live overlay id.
    await act(async () => mount.result.toggleSection("s1-message-live-t1", "reasoning:thought-1", false));
    expect(mount.result.getExpansionState("s1-message-live-t1", "reasoning:thought-1", false)).toBe(true);

    // The turn settles: the projection retires the overlay and reports the
    // durable replacement. The explicit choice must follow the row.
    await act(async () => mount.render({
      retiredOverlayAliases: [{ fromMessageId: "s1-message-live-t1", toMessageId: "s1-message-42" }],
    }));
    expect(mount.result.getExpansionState("s1-message-42", "reasoning:thought-1", false)).toBe(true);
    // The retired id carries no record anymore: back to the default (collapsed).
    expect(mount.result.getExpansionState("s1-message-live-t1", "reasoning:thought-1", false)).toBe(false);

    await mount.unmount();
  });

  it("refreshes work defaults in both directions until the user chooses, then migrates that choice", async () => {
    const mount = mountExpansionHook(baseInput());
    await act(async () => mount.render());
    expect(mount.result.getExpansionState("live", "work", false)).toBe(false);
    // A late warning, resumed stream or missing final must reveal its record.
    expect(mount.result.getExpansionState("live", "work", true)).toBe(true);
    expect(mount.result.getExpansionState("live", "work", false)).toBe(false);
    await act(async () => mount.result.setExpansionState("live", "work", false));
    expect(mount.result.getExpansionState("live", "work", true)).toBe(false);
    await act(async () => mount.render({ retiredOverlayAliases: [{ fromMessageId: "live", toMessageId: "durable" }] }));
    expect(mount.result.getExpansionState("durable", "work", true)).toBe(false);
    await mount.unmount();
  });

  it("leaves state untouched when an alias misses (zero drift from current behavior)", async () => {
    const mount = mountExpansionHook(baseInput());
    await act(async () => mount.render());

    const before = mount.result.sectionExpansion;
    await act(async () => mount.render({
      retiredOverlayAliases: [{ fromMessageId: "ghost-live", toMessageId: "ghost-durable" }],
    }));
    expect(mount.result.sectionExpansion).toBe(before);

    // The plain toggle/default flow is unaffected.
    await act(async () => mount.result.toggleSection("m1", "process", false));
    expect(mount.result.getExpansionState("m1", "process", false)).toBe(true);
    expect(mount.result.getExpansionState("m2", "process", false)).toBe(false);

    await mount.unmount();
  });

  it("never overrides an explicit choice already made on the durable row", async () => {
    const mount = mountExpansionHook(baseInput());
    await act(async () => mount.render());

    // Durable row: user opened section a, closed section b.
    await act(async () => mount.result.toggleSection("s1-message-42", "reasoning:a", false));
    await act(async () => mount.result.toggleSection("s1-message-42", "reasoning:b", false));
    await act(async () => mount.result.toggleSection("s1-message-42", "reasoning:b", false));
    // Live overlay: the opposite choices were made there before the settle.
    await act(async () => mount.result.toggleSection("s1-message-live-t1", "reasoning:a", false));
    await act(async () => mount.result.toggleSection("s1-message-live-t1", "reasoning:a", false));
    await act(async () => mount.result.toggleSection("s1-message-live-t1", "reasoning:b", false));

    await act(async () => mount.render({
      retiredOverlayAliases: [{ fromMessageId: "s1-message-live-t1", toMessageId: "s1-message-42" }],
    }));
    expect(mount.result.getExpansionState("s1-message-42", "reasoning:a", false)).toBe(true);
    expect(mount.result.getExpansionState("s1-message-42", "reasoning:b", false)).toBe(false);

    await mount.unmount();
  });

  it("keeps the ConversationView wiring fed from the projection output", () => {
    expect(conversationViewSource).toContain(
      "retiredOverlayAliases: activeAgentMessageTimelineProjection.retiredOverlayAliases",
    );
  });
});
