/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import { dictionary } from "../../i18n/dictionary";
import { ConversationView } from "./ConversationView";
import type { ConversationComposerVariant } from "./conversationViewTypes";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("shared composer interrupt guidance loading state", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    await act(async () => root?.unmount());
    container?.remove();
    root = null;
    container = null;
  });

  async function renderComposer(variant: ConversationComposerVariant, pending: boolean) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity, enabled: false } },
    });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);
    queryClient.setQueryData(queryKeys.sessionMessageCuration("session-composer-loading"), { items: [] });
    const onInterruptGuidance = vi.fn();
    const onSubmit = vi.fn();

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <QueryClientProvider client={queryClient}>
          <ConversationView
            sessionId="session-composer-loading"
            title="Session"
            phase="ready"
            messages={[]}
            showHeader={false}
            showSessionOverview={false}
            showComposer
            composerVariant={variant}
            composerValue="补充要求"
            composerPlaceholder=""
            composerDisabled={false}
            composerPending={false}
            composerActionMode="stop"
            composerInterruptGuidancePending={pending}
            interruptGuidanceLabel="打断并发送"
            interruptGuidancePendingLabel="正在打断并发送…"
            onComposerChange={() => undefined}
            onSubmit={onSubmit}
            onStop={() => undefined}
            onInterruptGuidance={onInterruptGuidance}
          />
        </QueryClientProvider>,
      );
    });
    const buttons = container.querySelectorAll<HTMLButtonElement>('[data-testid="composer-primary-action"]');
    expect(buttons).toHaveLength(1);
    return { button: buttons[0], onInterruptGuidance, onSubmit };
  }

  // Both the regular compact composer and the assistant's codex composer use
  // this shared surface. Assert the rendered VButton slots, not source text.
  describe.each(["compact", "codex"] as const)("%s composer", (variant) => {
    it("keeps one centered spinner and announces the pending interrupt on the shared action", async () => {
      const { button, onInterruptGuidance } = await renderComposer(variant, true);
      const content = button.querySelector('[data-slot="vui-button-content"]');
      const icon = Array.from(content?.children ?? []).find((child) => child.getAttribute("data-slot") === "vui-button-icon");

      expect(content?.classList.contains("inline-flex")).toBe(true);
      expect(content?.classList.contains("items-center")).toBe(true);
      expect(icon).toBeDefined();
      expect(icon?.querySelectorAll("svg.lucide-loader-circle")).toHaveLength(1);
      expect(button.querySelector('[data-slot="vui-button-label"]')).toBeNull();
      expect(button.querySelectorAll("svg.lucide-loader-circle")).toHaveLength(1);
      expect(button.getAttribute("aria-label")).toBe("正在打断并发送…");
      expect(button.getAttribute("aria-busy")).toBe("true");
      expect(button.disabled).toBe(true);
      await act(async () => button.click());
      expect(onInterruptGuidance).not.toHaveBeenCalled();
    });

    it("restores the one send icon after the pending operation without a persistent interrupt pill", async () => {
      const { button, onInterruptGuidance, onSubmit } = await renderComposer(variant, false);
      expect(button.textContent).toBe("");
      expect(button.getAttribute("aria-label")).toBe(dictionary.zh.queueFollowup);
      expect(button.querySelector("svg.lucide-arrow-up")).toBeTruthy();
      expect(button.querySelector("svg.lucide-loader-circle")).toBeNull();
      expect(button.disabled).toBe(false);
      await act(async () => button.click());
      expect(onSubmit).toHaveBeenCalledTimes(1);
      expect(onInterruptGuidance).not.toHaveBeenCalled();
    });
  });
});
