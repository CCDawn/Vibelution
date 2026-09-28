// @vitest-environment happy-dom
/**
 * Behavior contract for the composer bridge as the single per-frame subscriber
 * of the active-turn layer store (stream render isolation):
 *  - inside the provider, the streaming active-turn message is projected from
 *    the store with the same settle rule the route used (settled layers hide
 *    the message),
 *  - outside the provider the activeTurnMessage prop passes through unchanged,
 *  - a committed frame for the subscribed session re-renders the memoized
 *    bridge (external-store updates bypass memo),
 *  - a committed frame for any other session does not re-render it,
 *  - an unrelated parent re-render with identical props is short-circuited by
 *    the memo gate.
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ConversationMessage } from "../../api/types";
import type { ActiveTurnLayerState } from "../chatActiveTurnLayer";
import { createActiveTurnLayersStore, ActiveTurnLayersStoreProvider } from "./activeTurnLayersStore";
import { ChatConversationComposerBridge } from "./ChatConversationComposerBridge";

const { lazyViewProps } = vi.hoisted(() => ({
  lazyViewProps: [] as Array<Record<string, unknown>>,
}));

vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: (props: Record<string, unknown>) => {
    lazyViewProps.push(props);
    return <div data-bridge-probe="lazy-conversation" data-active-turn-id={String((props.activeTurnMessage as ConversationMessage | undefined)?.id ?? "")} />;
  },
  prefetchConversationView: () => undefined,
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function makeLayer(ledgerSeq: number, turnId = "turn-1"): ActiveTurnLayerState {
  return {
    id: "s1-message-active-turn-1",
    sessionId: "s1",
    turnId,
    updatedAt: "2026-01-01T00:00:00.000Z",
    status: "running",
    turnItems: [],
    ledgerSeq,
  };
}

function settledAssistantMessage(turnId = "turn-1"): ConversationMessage {
  return {
    id: "assistant-committed",
    role: "assistant",
    timestamp: "2026-01-01T00:00:05.000Z",
    turnId,
    status: "completed",
    turnItems: [{
      version: 3,
      id: "item-final",
      itemId: "item-final",
      sessionId: "s1",
      turnId,
      type: "agent_message",
      phase: "final_answer",
      status: "completed",
      terminal: true,
      revision: 1,
      sequence: 1,
      text: "done",
    }],
  } as unknown as ConversationMessage;
}

type BridgeProps = React.ComponentProps<typeof ChatConversationComposerBridge>;

function baseProps(overrides: Partial<BridgeProps> = {}): BridgeProps {
  return {
    sessionId: "s1",
    title: "session",
    phase: "ready",
    messages: [],
    defaultFileContext: "workspace",
    onSubmit: () => undefined,
    onComposerChange: () => undefined,
    fallback: <div data-bridge-probe="fallback" />,
    composer: {
      actionDisabled: false,
      actionMode: "send",
      attachmentInputDisabled: false,
      attachments: [],
      disabled: false,
      editUserMessageDisabled: false,
      error: "",
      followupQueue: [],
      guidance: "",
      interruptGuidancePending: false,
      modeNotice: "",
      modeTargetPreview: "",
      pending: false,
      placeholder: "",
      references: [],
      safeGuidancePending: false,
      submitLabel: "",
      value: "",
    },
    ...overrides,
  };
}

let root: Root | null = null;
let container: HTMLElement;

function renderTree(element: React.ReactElement) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root!.render(element);
  });
}

beforeEach(() => {
  lazyViewProps.length = 0;
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
});

describe("ChatConversationComposerBridge active-turn store isolation", () => {
  it("passes the activeTurnMessage prop through outside the provider", () => {
    const propMessage = { id: "prop-message", role: "assistant" } as unknown as ConversationMessage;
    renderTree(<ChatConversationComposerBridge {...baseProps({ activeTurnMessage: propMessage })} />);
    expect(lazyViewProps).toHaveLength(1);
    expect(lazyViewProps[0].activeTurnMessage).toBe(propMessage);
  });

  it("projects the streaming layer from the store inside the provider", () => {
    const store = createActiveTurnLayersStore();
    renderTree(
      <ActiveTurnLayersStoreProvider store={store}>
        <ChatConversationComposerBridge {...baseProps()} />
      </ActiveTurnLayersStoreProvider>,
    );
    const initial = lazyViewProps[0].activeTurnMessage;
    expect(initial).toBeUndefined();

    const layer = makeLayer(1);
    act(() => {
      store.setActiveTurnLayersBySession((current) => ({ ...current, s1: layer }));
    });
    const projected = lazyViewProps[lazyViewProps.length - 1].activeTurnMessage as ConversationMessage;
    expect(projected?.id).toBe("s1-message-active-turn-1");
    expect((projected?.metadata as { ledgerSeq?: number } | undefined)?.ledgerSeq).toBe(1);
  });

  it("hides the streaming message once the canonical transcript settles the turn", () => {
    const store = createActiveTurnLayersStore();
    const messages = [settledAssistantMessage()];
    renderTree(
      <ActiveTurnLayersStoreProvider store={store}>
        <ChatConversationComposerBridge {...baseProps({ messages })} />
      </ActiveTurnLayersStoreProvider>,
    );
    act(() => {
      store.setActiveTurnLayersBySession((current) => ({ ...current, s1: makeLayer(1) }));
    });
    expect(lazyViewProps[lazyViewProps.length - 1].activeTurnMessage).toBeUndefined();
  });

  it("re-renders for own-session frames through the memo but not for other sessions", () => {
    const store = createActiveTurnLayersStore();
    // Stable prop references: the memo gate must see identical fields to bail.
    const bridgeProps = baseProps();
    renderTree(
      <ActiveTurnLayersStoreProvider store={store}>
        <ChatConversationComposerBridge {...bridgeProps} />
      </ActiveTurnLayersStoreProvider>,
    );
    expect(lazyViewProps).toHaveLength(1);

    // Own-session frame: external-store update must bypass the memo gate.
    act(() => {
      store.setActiveTurnLayersBySession((current) => ({ ...current, s1: makeLayer(1) }));
    });
    expect(lazyViewProps).toHaveLength(2);

    // Frame for a different session: subscriber key does not match, memo holds.
    act(() => {
      store.setActiveTurnLayersBySession((current) => ({ ...current, s2: { ...makeLayer(1), sessionId: "s2", id: "s2-message-active-turn-1" } }));
    });
    expect(lazyViewProps).toHaveLength(2);

    // Parent re-render with identical prop references: memo short-circuits.
    // Re-render the SAME root: a fresh createRoot would be a remount, which no
    // memo gate can short-circuit.
    act(() => {
      root!.render(
        <ActiveTurnLayersStoreProvider store={store}>
          <ChatConversationComposerBridge {...bridgeProps} />
        </ActiveTurnLayersStoreProvider>,
      );
    });
    expect(lazyViewProps).toHaveLength(2);
  });
});
