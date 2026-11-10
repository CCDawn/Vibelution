/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import { dictionaryChat } from "../../i18n/domains/dictionaryChat";
import {
  dictionaryDomainsQueryKey,
  normalizeDictionaryDomains,
} from "../../i18n/dictionaryDomainIds";
import { AgentAssistantContentSectionView } from "./AgentAssistantContentSectionView";
import styles from "./AgentAssistantContentSectionView.styles";
import {
  ASSISTANT_MESSAGE_COLLAPSE_THRESHOLD_PX,
  shouldCollapseAssistantMessage,
} from "./conversationAssistantMessageCollapse";
import { USER_MESSAGE_COLLAPSE_THRESHOLD_PX } from "./conversationUserMessageCollapse";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type ResizeObserverCallbackStub = (entries: unknown[]) => void;

/**
 * Happy-dom has no layout. Deliver natural-height observer entries and count
 * legacy layout reads separately, including async media growth.
 */
describe("AgentAssistantContentSectionView long answer collapse", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;
  let measuredHeight = 0;
  let layoutReads = 0;
  let deliverInitialMeasurement = true;
  let observedElement: Element | null = null;
  let resizeCallback: ResizeObserverCallbackStub | null = null;

  class ResizeObserverStub {
    callback: ResizeObserverCallbackStub;
    constructor(callback: ResizeObserverCallbackStub) {
      this.callback = callback;
      resizeCallback = callback;
    }
    observe(element: Element) {
      observedElement = element;
      if (deliverInitialMeasurement) {
        queueMicrotask(() => {
          if (resizeCallback === this.callback) notifyResize();
        });
      }
    }
    unobserve() {}
    disconnect() {
      resizeCallback = null;
    }
  }

  beforeEach(() => {
    measuredHeight = 0;
    layoutReads = 0;
    deliverInitialMeasurement = true;
    observedElement = null;
    resizeCallback = null;
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
      configurable: true,
      get() {
        layoutReads += 1;
        return measuredHeight;
      },
    });
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = ResizeObserverStub;
  });

  function notifyResize() {
    resizeCallback?.([{ target: observedElement, contentRect: { height: measuredHeight } }]);
  }

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
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
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
    const measured = container?.querySelector("[data-testid='assistant-message-measured-content']");
    return measured?.parentElement ?? null;
  }

  function toggleButton() {
    return (
      container?.querySelector<HTMLButtonElement>(
        "[data-testid='assistant-message-collapse-toggle']",
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

  it("collapses an oversized answer by default with fade and ghost expand toggle", async () => {
    measuredHeight = ASSISTANT_MESSAGE_COLLAPSE_THRESHOLD_PX + 600;
    await renderView(
      <AgentAssistantContentSectionView>
        <p>一段非常长的助手回答</p>
      </AgentAssistantContentSectionView>,
    );

    const button = toggleButton();
    expect(button).not.toBeNull();
    expect(button?.getAttribute("aria-expanded")).toBe("false");
    expect(button?.textContent).toBe("展开回答");
    expect(button?.className).toContain(styles.assistantCollapseToggle);
    expect(contentWrapper()?.classList.contains("assistantMessageBodyClamped")).toBe(true);
    expect(container?.querySelector(".assistantMessageCollapseFade")).not.toBeNull();
    expect(container?.textContent).toContain("一段非常长的助手回答");
  });

  it("keeps short answers uncollapsed without any toggle affordance", async () => {
    measuredHeight = ASSISTANT_MESSAGE_COLLAPSE_THRESHOLD_PX - 40;
    await renderView(
      <AgentAssistantContentSectionView>
        <p>短回答</p>
      </AgentAssistantContentSectionView>,
    );

    expect(toggleButton()).toBeNull();
    expect(contentWrapper()?.classList.contains("assistantMessageBodyWrap")).toBe(true);
    expect(container?.querySelector(".assistantMessageCollapseFade")).toBeNull();
  });

  it("expands and re-collapses through the ghost toggle without re-measuring", async () => {
    measuredHeight = ASSISTANT_MESSAGE_COLLAPSE_THRESHOLD_PX + 600;
    await renderView(
      <AgentAssistantContentSectionView>
        <p>长回答</p>
      </AgentAssistantContentSectionView>,
    );

    const readsAfterMount = layoutReads;
    await clickToggle();
    expect(toggleButton()?.getAttribute("aria-expanded")).toBe("true");
    expect(toggleButton()?.textContent).toBe("收起回答");
    expect(contentWrapper()?.classList.contains("assistantMessageBodyWrap")).toBe(true);
    expect(container?.querySelector(".assistantMessageCollapseFade")).toBeNull();
    // Toggling is a class flip, not a layout read.
    expect(layoutReads).toBe(readsAfterMount);

    await clickToggle();
    expect(toggleButton()?.getAttribute("aria-expanded")).toBe("false");
    expect(contentWrapper()?.classList.contains("assistantMessageBodyClamped")).toBe(true);
  });

  it("follows later growth from async media without a remount", async () => {
    measuredHeight = ASSISTANT_MESSAGE_COLLAPSE_THRESHOLD_PX - 40;
    await renderView(
      <AgentAssistantContentSectionView>
        <p>先渲染的短内容</p>
      </AgentAssistantContentSectionView>,
    );
    expect(toggleButton()).toBeNull();

    await act(async () => {
      measuredHeight = ASSISTANT_MESSAGE_COLLAPSE_THRESHOLD_PX + 900;
      notifyResize();
    });
    expect(toggleButton()).not.toBeNull();
    expect(contentWrapper()?.classList.contains("assistantMessageBodyClamped")).toBe(true);
  });
});

describe("conversationAssistantMessageCollapse policy", () => {
  it("keeps answers at or below the threshold expanded", () => {
    expect(shouldCollapseAssistantMessage(0)).toBe(false);
    expect(shouldCollapseAssistantMessage(ASSISTANT_MESSAGE_COLLAPSE_THRESHOLD_PX)).toBe(false);
  });

  it("collapses strictly past the threshold", () => {
    expect(shouldCollapseAssistantMessage(ASSISTANT_MESSAGE_COLLAPSE_THRESHOLD_PX + 1)).toBe(true);
  });

  it("gives the answer a looser budget than the user bubble", () => {
    expect(ASSISTANT_MESSAGE_COLLAPSE_THRESHOLD_PX).toBeGreaterThan(
      USER_MESSAGE_COLLAPSE_THRESHOLD_PX,
    );
  });
});
