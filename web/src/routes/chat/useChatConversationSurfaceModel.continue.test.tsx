// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import {
  useChatConversationSurfaceModel,
  type ChatConversationSurfaceModelInput,
} from "./useChatConversationSurfaceModel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("ordinary workbench continuation wiring", () => {
  it.each([
    [false, false, true],
    [true, false, false],
    [false, true, false],
  ])("routes the handler through composerChrome (finance=%s, companion=%s)", async (financeSurface, verifiedCompanionMode, enabled) => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const continueTurn = vi.fn();
    let handler: (() => void) | undefined;
    function Harness() {
      const model = useChatConversationSurfaceModel({
        activeSessionId: "session-a",
        detail: { id: "session-a", title: "stopped", currentPhase: "ready", messages: [] },
        t: (key: string) => key,
        loadEarlierSessionMessagesMutation: { isPending: false },
        regenerateMutation: { isPending: false },
        switchHeadMutation: { isPending: false },
        composerFocusRequest: { sessionId: "session-a", signal: "" },
        companionConversationComposer: { attachmentInputDisabled: false },
        handleContinueTurn: continueTurn,
        financeSurface,
        verifiedCompanionMode,
      } as unknown as ChatConversationSurfaceModelInput);
      handler = model?.composerChrome.onContinueTurn;
      return <button disabled={!handler} onClick={handler}>Continue</button>;
    }
    try {
      await act(() => root.render(<Harness />));
      expect(handler).toBe(enabled ? continueTurn : undefined);
      await act(() => host.querySelector("button")!.click());
      expect(continueTurn).toHaveBeenCalledTimes(enabled ? 1 : 0);
    } finally {
      await act(() => root.unmount());
      host.remove();
    }
  });
});
