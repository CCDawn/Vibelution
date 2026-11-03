/** @vitest-environment happy-dom */
import React, { act } from "react";
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
