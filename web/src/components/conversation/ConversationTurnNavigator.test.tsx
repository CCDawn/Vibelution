// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VuiProvider } from "../vui/VuiProvider";
import { ConversationTurnNavigator } from "./ConversationTurnNavigator";
import type { ConversationTurnNavEntry } from "./conversationTurnNavigation";
import styles from "./ConversationTurnNavigator.styles";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function navEntry(overrides: Partial<ConversationTurnNavEntry> = {}): ConversationTurnNavEntry {
  return {
    turnIndex: 0,
    anchorRowIndex: 0,
    userRowKey: "user-message:m1",
    assistantRowKey: "assistant-turn:t1",
    label: "第一轮：修复构建",
    userPreviewText: "",
    assistantPreviewText: "",
    ...overrides,
  };
}

let root: Root | null = null;
let container: HTMLElement;

function mountNavigator(entries: ConversationTurnNavEntry[]) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root?.render(
      <VuiProvider>
        <ConversationTurnNavigator
          entries={entries}
          currentIndex={0}
          ariaLabel="会话轮次导航"
          onNavigate={() => undefined}
        />
      </VuiProvider>,
    );
  });
}

afterEach(() => {
  vi.useRealTimers();
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
});

function pointerOver(host: Element) {
  host.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
}

describe("ConversationTurnNavigator turn rail hover previews", () => {
  it("passes turn previews into the hover card and replaces the native title", async () => {
    vi.useFakeTimers();
    mountNavigator([
      navEntry({
        turnIndex: 0,
        userPreviewText: "用户：帮我修一下构建",
        assistantPreviewText: "助手：已修复 tsconfig 路径别名",
      }),
      navEntry({ turnIndex: 1, label: "第二轮" }),
      navEntry({ turnIndex: 2, label: "第三轮" }),
      navEntry({ turnIndex: 3, label: "第四轮" }),
      navEntry({ turnIndex: 4, label: "第五轮" }),
      navEntry({ turnIndex: 5, label: "第六轮" }),
    ]);

    const dots = container.querySelectorAll<HTMLButtonElement>("nav button");
    expect(dots.length).toBe(6);
    // The native title tooltip is replaced by the hover card on every dot.
    for (const dot of dots) {
      expect(dot.hasAttribute("title")).toBe(false);
    }
    const wrappedDot = dots[0];
    expect(wrappedDot.getAttribute("data-slot")).toBe("hover-card-trigger");
    expect(wrappedDot.getAttribute("aria-label")).toBe("第一轮：修复构建");
    // Nothing mounts before pointer intent.
    expect(document.querySelector("[data-vui='hover-card-content']")).toBeNull();

    act(() => {
      pointerOver(wrappedDot);
    });
    act(() => {
      vi.advanceTimersByTime(120);
    });

    const content = document.querySelector("[data-vui='hover-card-content']");
    expect(content?.textContent).toContain("用户：帮我修一下构建");
    expect(content?.textContent).toContain("助手：已修复 tsconfig 路径别名");
    // User prompt clamps to two lines, assistant answer to three, stacked.
    const userLine = content?.querySelector(`.${styles.turnNavigatorHoverUser.split(" ")[1]}`);
    const assistantLine = content?.querySelector(`.${styles.turnNavigatorHoverAssistant.split(" ")[1]}`);
    expect(userLine?.textContent).toBe("用户：帮我修一下构建");
    expect(userLine?.className).toContain("line-clamp-2");
    expect(assistantLine?.className).toContain("line-clamp-3");
  });

  it("keeps dots without previews unwrapped and labelless tooltips away", () => {
    mountNavigator([
      navEntry({ turnIndex: 0 }),
      navEntry({ turnIndex: 1, label: "第二轮" }),
      navEntry({ turnIndex: 2, label: "第三轮" }),
      navEntry({ turnIndex: 3, label: "第四轮" }),
      navEntry({ turnIndex: 4, label: "第五轮" }),
      navEntry({ turnIndex: 5, label: "第六轮" }),
    ]);

    const dots = container.querySelectorAll<HTMLButtonElement>("nav button");
    expect(dots.length).toBe(6);
    for (const dot of dots) {
      expect(dot.getAttribute("data-slot")).toBeNull();
      expect(dot.hasAttribute("title")).toBe(false);
      expect(dot.getAttribute("aria-label")).toBeTruthy();
    }
  });

  it("wraps only the preview-carrying turns inside a mixed rail", async () => {
    vi.useFakeTimers();
    mountNavigator([
      navEntry({ turnIndex: 0, userPreviewText: "有提问预览" }),
      navEntry({ turnIndex: 1, label: "无预览轮" }),
      navEntry({ turnIndex: 2, label: "第三轮" }),
      navEntry({ turnIndex: 3, label: "第四轮" }),
      navEntry({ turnIndex: 4, label: "第五轮" }),
      navEntry({ turnIndex: 5, label: "第六轮" }),
    ]);

    const wrapped = container.querySelectorAll<HTMLButtonElement>(
      "nav button[data-slot='hover-card-trigger']",
    );
    expect(wrapped.length).toBe(1);
    expect(wrapped[0].getAttribute("aria-label")).toBe("第一轮：修复构建");

    // Hovering a bare dot mounts no hover card for it.
    const bareDot = container.querySelectorAll<HTMLButtonElement>("nav button")[1];
    act(() => {
      pointerOver(bareDot);
    });
    act(() => {
      vi.advanceTimersByTime(200);
    });
    const contents = document.querySelectorAll("[data-vui='hover-card-content']");
    expect(contents.length).toBe(0);
  });
});
