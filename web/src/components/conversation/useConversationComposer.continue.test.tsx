/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { dictionary } from "../../i18n/dictionary";
import { queryKeys } from "../../api/queryKeys";
import { ConversationView } from "./ConversationView";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("ConversationView continue primary action", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
  });

  async function renderContinueComposer(options: {
    onContinueTurn?: () => void;
    onSubmit: () => void;
    onStop: () => void;
  }) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity, enabled: false } },
    });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);
    queryClient.setQueryData(queryKeys.sessionMessageCuration("session-continue-primary-action"), { items: [] });

    function Harness() {
      const [value, setValue] = useState("");
      return (
        <QueryClientProvider client={queryClient}>
          <ConversationView
            sessionId="session-continue-primary-action"
            title="Session"
            phase="ready"
            messages={[]}
            showHeader={false}
            showSessionOverview={false}
            showComposer
            defaultFileContext="workspace"
            composerValue={value}
            composerPlaceholder=""
            composerDisabled={false}
            composerPending={false}
            composerActionMode="continue"
            onComposerChange={setValue}
            onSubmit={options.onSubmit}
            onStop={options.onStop}
            onContinueTurn={options.onContinueTurn}
          />
        </QueryClientProvider>
      );
    }

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<Harness />);
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    const textarea = container.querySelector<HTMLTextAreaElement>("textarea");
    if (!textarea) {
      throw new Error("composer textarea not mounted");
    }
    textarea.focus();
    return { textarea, container };
  }

  function typeIntoTextarea(textarea: HTMLTextAreaElement, value: string) {
    const nativeValueSetter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    nativeValueSetter?.call(textarea, value);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function pressEnter(textarea: HTMLTextAreaElement, options: { shiftKey?: boolean; isComposing?: boolean } = {}) {
    textarea.dispatchEvent(new KeyboardEvent("keydown", {
      key: "Enter",
      shiftKey: options.shiftKey ?? false,
      isComposing: options.isComposing ?? false,
      bubbles: true,
      cancelable: true,
    }));
  }

  it("uses Play and routes click/empty Enter only to continue without clearing the draft", async () => {
    const onContinueTurn = vi.fn();
    const onSubmit = vi.fn();
    const onStop = vi.fn();
    const { textarea } = await renderContinueComposer({ onContinueTurn, onSubmit, onStop });
    const button = container?.querySelector<HTMLButtonElement>('button[aria-label="继续任务"]');

    expect(button).toBeDefined();
    expect(button?.getAttribute("title")).toBe("继续任务");
    expect(button?.querySelector("svg.lucide-play")).not.toBeNull();

    await act(async () => button?.click());
    expect(onContinueTurn).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(onStop).not.toHaveBeenCalled();

    await act(async () => typeIntoTextarea(textarea, "保留草稿"));
    await act(async () => button?.click());
    expect(onContinueTurn).toHaveBeenCalledTimes(2);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(onStop).not.toHaveBeenCalled();
    expect(textarea.value).toBe("保留草稿");

    await act(async () => typeIntoTextarea(textarea, ""));
    await act(async () => pressEnter(textarea));
    expect(onContinueTurn).toHaveBeenCalledTimes(3);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(onStop).not.toHaveBeenCalled();
    expect(textarea.value).toBe("");

    await act(async () => pressEnter(textarea, { shiftKey: true }));
    await act(async () => pressEnter(textarea, { isComposing: true }));
    expect(onContinueTurn).toHaveBeenCalledTimes(3);
  });

  it("disables continue when its handler is absent", async () => {
    const onSubmit = vi.fn();
    const onStop = vi.fn();
    const { container: renderedContainer, textarea } = await renderContinueComposer({ onSubmit, onStop });
    const button = renderedContainer.querySelector<HTMLButtonElement>('button[aria-label="继续任务"]');

    expect(button?.disabled).toBe(true);
    await act(async () => pressEnter(textarea));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(onStop).not.toHaveBeenCalled();
  });
});
