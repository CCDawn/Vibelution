// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ConversationMessage } from "../../api/types";
import {
  useConversationForkSession,
  type UseConversationForkSessionInput,
} from "./useConversationForkSession";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const MESSAGE: ConversationMessage = {
  id: "message-user-1",
  role: "user",
  timestamp: "2026-05-22T00:00:00Z",
  content: "First prompt",
};

function Harness({
  overrides = {},
  onResult,
}: {
  overrides?: Partial<UseConversationForkSessionInput>;
  onResult: (result: ReturnType<typeof useConversationForkSession>) => void;
}) {
  const result = useConversationForkSession({
    onForkSessionFromNode: overrides.onForkSessionFromNode,
  });
  onResult(result);
  return null;
}

describe("useConversationForkSession", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
    }
    container?.remove();
    root = null;
    container = null;
  });

  async function mount(overrides: Partial<UseConversationForkSessionInput> = {}) {
    if (root) {
      await act(async () => root?.unmount());
    }
    container?.remove();
    const resultRef: { current: ReturnType<typeof useConversationForkSession> | null } = { current: null };
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<Harness overrides={overrides} onResult={(result) => { resultRef.current = result; }} />);
    });
    return resultRef;
  }

  async function flush() {
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it("opens on the visible path and closes without changing the last scope", async () => {
    const resultRef = await mount();
    expect(resultRef.current?.forkDialogMessage).toBeNull();
    expect(resultRef.current?.forkScope).toBe("visible_path");
    expect(resultRef.current?.forkPending).toBe(false);

    await act(async () => {
      resultRef.current?.setForkScope("with_branches");
    });
    await act(async () => {
      resultRef.current?.openForkDialog(MESSAGE);
    });
    expect(resultRef.current?.forkDialogMessage).toBe(MESSAGE);
    expect(resultRef.current?.forkScope).toBe("visible_path");

    await act(async () => {
      resultRef.current?.setForkScope("with_branches");
    });
    await act(async () => {
      resultRef.current?.closeForkDialog();
    });
    expect(resultRef.current?.forkDialogMessage).toBeNull();
    expect(resultRef.current?.forkScope).toBe("with_branches");
    expect(resultRef.current?.forkPending).toBe(false);
  });

  it("submits the selected scope, then closes only after the route handler resolves", async () => {
    let resolveFork: () => void = () => undefined;
    const onForkSessionFromNode = vi.fn(() => new Promise<void>((resolve) => {
      resolveFork = resolve;
    }));
    const resultRef = await mount({ onForkSessionFromNode });

    await act(async () => {
      resultRef.current?.openForkDialog(MESSAGE);
    });
    await act(async () => {
      resultRef.current?.setForkScope("with_branches");
    });
    await act(async () => {
      resultRef.current?.confirmForkSession();
    });

    expect(onForkSessionFromNode).toHaveBeenCalledTimes(1);
    expect(onForkSessionFromNode).toHaveBeenCalledWith(MESSAGE, "with_branches");
    expect(resultRef.current?.forkPending).toBe(true);
    expect(resultRef.current?.forkDialogMessage).toBe(MESSAGE);

    await act(async () => {
      resultRef.current?.confirmForkSession();
    });
    expect(onForkSessionFromNode).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveFork();
    });
    await flush();
    expect(resultRef.current?.forkDialogMessage).toBeNull();
    expect(resultRef.current?.forkPending).toBe(false);
    expect(resultRef.current?.forkScope).toBe("with_branches");
  });

  it("keeps the dialog open when the route handler rejects", async () => {
    const onForkSessionFromNode = vi.fn(() => Promise.reject(new Error("fork failed")));
    const resultRef = await mount({ onForkSessionFromNode });

    await act(async () => {
      resultRef.current?.openForkDialog(MESSAGE);
    });
    await act(async () => {
      resultRef.current?.confirmForkSession();
    });
    await flush();

    expect(onForkSessionFromNode).toHaveBeenCalledWith(MESSAGE, "visible_path");
    expect(resultRef.current?.forkDialogMessage).toBe(MESSAGE);
    expect(resultRef.current?.forkPending).toBe(false);
  });

  it("does not submit without a target message or a route handler", async () => {
    const onForkSessionFromNode = vi.fn();
    const closed = await mount({ onForkSessionFromNode });
    await act(async () => {
      closed.current?.confirmForkSession();
    });
    expect(onForkSessionFromNode).not.toHaveBeenCalled();

    const unhandled = await mount();
    await act(async () => {
      unhandled.current?.openForkDialog(MESSAGE);
    });
    await act(async () => {
      unhandled.current?.confirmForkSession();
    });
    expect(unhandled.current?.forkDialogMessage).toBe(MESSAGE);
    expect(unhandled.current?.forkPending).toBe(false);
  });
});
