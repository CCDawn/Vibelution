/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { dictionaryChat } from "../../i18n/domains/dictionaryChat";
import {
  dictionaryDomainsQueryKey,
  normalizeDictionaryDomains,
} from "../../i18n/dictionaryDomainIds";
import { AgentUserContentSectionView } from "./AgentUserContentSectionView";
import styles from "./AgentUserContentSectionView.styles";
import { USER_MESSAGE_COLLAPSE_THRESHOLD_PX } from "./conversationUserMessageCollapse";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type ResizeObserverCallbackStub = (entries: unknown[]) => void;

/**
 * Measurement-driven collapse: stub scrollHeight (happy-dom has no layout)
 * and capture the ResizeObserver callback so tests can fire async content
 * growth (the image-loads-late case) through the real re-measure path.
 */
describe("AgentUserContentSectionView long message collapse", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;
  let measuredHeight = 0;
  let resizeCallback: ResizeObserverCallbackStub | null = null;

  class ResizeObserverStub {
    constructor(callback: ResizeObserverCallbackStub) {
      resizeCallback = callback;
    }
    observe() {}
    unobserve() {}
    disconnect() {
      resizeCallback = null;
    }
  }

  beforeEach(() => {
    measuredHeight = 0;
    resizeCallback = null;
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
      configurable: true,
      get() {
        return measuredHeight;
      },
    });
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = ResizeObserverStub;
  });

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
    delete (HTMLElement.prototype as { scrollHeight?: unknown }).scrollHeight;
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = undefined;
  });

  async function renderView(node: React.ReactElement) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(
      [
        "i18n",
        "dictionary-domains",
        dictionaryDomainsQueryKey(normalizeDictionaryDomains(["chat"])),
      ],
      { zh: { ...dictionaryChat.zh }, en: { ...dictionaryChat.en } },
    );
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>);
    });
  }

  function contentWrapper() {
    const measured = container?.querySelector("[data-testid='user-message-measured-content']");
    return measured?.parentElement ?? null;
  }

  function toggleButton() {
    return (
      container?.querySelector<HTMLButtonElement>(
        "[data-testid='user-message-collapse-toggle']",
      ) ?? null
    );
  }

  async function clickToggle() {
    const button = toggleButton();
    expect(button).not.toBeNull();
    await act(async () => {
      button?.click();
    });
  }

  it("collapses an oversized message by default with fade and ghost expand toggle", async () => {
    measuredHeight = USER_MESSAGE_COLLAPSE_THRESHOLD_PX + 60;
    await renderView(
      <AgentUserContentSectionView userContentSectionIds="message-1">
        <p>一段非常长的用户消息</p>
      </AgentUserContentSectionView>,
    );

    const button = toggleButton();
    expect(button).not.toBeNull();
    expect(button?.getAttribute("aria-expanded")).toBe("false");
    expect(button?.textContent).toBe("展开");
    expect(button?.className).toContain(styles.userMessageCollapseToggle);
    expect(contentWrapper()?.classList.contains("userMessageBodyClamped")).toBe(true);
    expect(container?.querySelector(".userMessageCollapseFade")).not.toBeNull();
    expect(container?.textContent).toContain("一段非常长的用户消息");
  });

  it("keeps short messages uncollapsed without any toggle affordance", async () => {
    measuredHeight = USER_MESSAGE_COLLAPSE_THRESHOLD_PX - 40;
    await renderView(
      <AgentUserContentSectionView>
        <p>短消息</p>
      </AgentUserContentSectionView>,
    );

    expect(toggleButton()).toBeNull();
    expect(container?.querySelector(".userMessageCollapseFade")).toBeNull();
    expect(contentWrapper()?.classList.contains("userMessageBodyClamped")).toBe(false);
  });

  it("expands on click, collapses back, and re-measures async content growth", async () => {
    measuredHeight = USER_MESSAGE_COLLAPSE_THRESHOLD_PX + 60;
    await renderView(
      <AgentUserContentSectionView>
        <p>长消息</p>
      </AgentUserContentSectionView>,
    );
    expect(toggleButton()?.getAttribute("aria-expanded")).toBe("false");

    await clickToggle();
    expect(toggleButton()?.getAttribute("aria-expanded")).toBe("true");
    expect(toggleButton()?.textContent).toBe("收起");
    expect(container?.querySelector(".userMessageCollapseFade")).toBeNull();
    expect(contentWrapper()?.classList.contains("userMessageBodyClamped")).toBe(false);

    await clickToggle();
    expect(toggleButton()?.getAttribute("aria-expanded")).toBe("false");
    expect(toggleButton()?.textContent).toBe("展开");
    expect(container?.querySelector(".userMessageCollapseFade")).not.toBeNull();

    // Simulate the image-finally-loaded case: content shrinks back under the
    // threshold through the ResizeObserver path and the affordance disappears.
    measuredHeight = USER_MESSAGE_COLLAPSE_THRESHOLD_PX - 40;
    await act(async () => {
      resizeCallback?.([]);
    });
    expect(toggleButton()).toBeNull();
    expect(container?.querySelector(".userMessageCollapseFade")).toBeNull();
  });

  it("starts collapsed again on every mount instead of persisting expansion", async () => {
    measuredHeight = USER_MESSAGE_COLLAPSE_THRESHOLD_PX + 60;
    await renderView(
      <AgentUserContentSectionView>
        <p>长消息</p>
      </AgentUserContentSectionView>,
    );
    await clickToggle();
    expect(toggleButton()?.getAttribute("aria-expanded")).toBe("true");

    await act(async () => {
      root?.unmount();
    });
    root = null;
    container?.remove();
    await renderView(
      <AgentUserContentSectionView>
        <p>长消息</p>
      </AgentUserContentSectionView>,
    );

    expect(toggleButton()?.getAttribute("aria-expanded")).toBe("false");
    expect(toggleButton()?.textContent).toBe("展开");
  });
});
