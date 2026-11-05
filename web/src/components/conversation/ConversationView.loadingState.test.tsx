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
            onSubmit={() => undefined}
            onStop={() => undefined}
            onInterruptGuidance={onInterruptGuidance}
          />
        </QueryClientProvider>,
      );
    });
    const button = container.querySelector<HTMLButtonElement>('[data-testid="composer-interrupt-guidance"]');
    if (!button) throw new Error("interrupt guidance button not mounted");
    return { button, onInterruptGuidance };
  }

  // Both the regular compact composer and the assistant's codex composer use
  // this shared surface. Assert the rendered VButton slots, not source text.
  describe.each(["compact", "codex"] as const)("%s composer", (variant) => {
    it("keeps one pending icon beside the label in the horizontal content slot", async () => {
      const { button, onInterruptGuidance } = await renderComposer(variant, true);
      const content = button.querySelector('[data-slot="vui-button-content"]');
      const icon = Array.from(content?.children ?? []).find((child) => child.getAttribute("data-slot") === "vui-button-icon");
      const label = Array.from(content?.children ?? []).find((child) => child.getAttribute("data-slot") === "vui-button-label");

      expect(content?.classList.contains("inline-flex")).toBe(true);
      expect(content?.classList.contains("items-center")).toBe(true);
      expect(icon).toBeDefined();
      expect(icon?.querySelectorAll("svg.lucide-loader-circle")).toHaveLength(1);
      expect(label?.querySelector("svg")).toBeNull();
      expect(label?.textContent).toBe("正在打断并发送…");
      expect(button.querySelectorAll("svg.lucide-loader-circle")).toHaveLength(1);
      expect(button.getAttribute("aria-label")).toBe("正在打断并发送…");
      expect(button.title).toBe("正在打断并发送…");
      expect(button.disabled).toBe(true);
      await act(async () => button.click());
      expect(onInterruptGuidance).not.toHaveBeenCalled();
    });

    it("keeps the idle label and click handler without a spinner", async () => {
      const { button, onInterruptGuidance } = await renderComposer(variant, false);
      expect(button.textContent).toBe("打断并发送");
      expect(button.getAttribute("aria-label")).toBe("打断并发送");
      expect(button.querySelector("svg.lucide-loader-circle")).toBeNull();
      expect(button.disabled).toBe(false);
      await act(async () => button.click());
      expect(onInterruptGuidance).toHaveBeenCalledTimes(1);
    });
  });
});
