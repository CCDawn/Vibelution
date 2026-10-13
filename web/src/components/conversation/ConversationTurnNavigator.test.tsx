// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
    isRunning: false,
    ...overrides,
  };
}

let root: Root | null = null;
let container: HTMLElement;

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(360);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(36);
});

function mountNavigator(
  entries: ConversationTurnNavEntry[],
  onNavigate = vi.fn(),
  extra: { currentIndex?: number; runningAssistantPreview?: string } = {},
) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root?.render(
      <VuiProvider>
        <ConversationTurnNavigator
          entries={entries}
          currentIndex={extra.currentIndex ?? 0}
          ariaLabel="会话轮次导航"
          onNavigate={onNavigate}
          runningAssistantPreview={extra.runningAssistantPreview}
        />
      </VuiProvider>,
    );
  });
}

function unmountNavigator() {
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
}

afterEach(() => {
  vi.useRealTimers();
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
  vi.restoreAllMocks();
});

function pointerOver(host: Element) {
  host.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
}

describe("ConversationTurnNavigator turn rail hover previews", () => {
  it("bounds long-session DOM and navigates on the first click", () => {
    const navigate = vi.fn();
    mountNavigator(Array.from({ length: 120 }, (_, turnIndex) => navEntry({ turnIndex, userPreviewText: `问题 ${turnIndex}` })), navigate);
    const buttons = container.querySelectorAll<HTMLButtonElement>("nav button");
    expect(buttons.length).toBeGreaterThan(0);
    expect(buttons.length).toBeLessThan(40);
    act(() => { buttons[0].focus(); });
    act(() => { buttons[0].click(); });
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate.mock.calls[0][0].turnIndex).toBe(0);
  });

  it("hides short sessions and reserves the left container-query rail", () => {
    mountNavigator([navEntry()]);
    expect(container.querySelector("nav")).toBeNull();
    expect(styles.turnNavigatorRail).toContain("left-3");
    expect(styles.turnNavigatorRail).toContain("@min-[864px]/conversation:block");
    expect(styles.turnNavigatorDotMark).toContain("h-0.5 w-3");
  });
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

describe("ConversationTurnNavigator ZCode visual calibration", () => {
  function railButtons() {
    return container.querySelectorAll<HTMLButtonElement>("nav button");
  }

  function markAt(index: number) {
    const buttons = railButtons();
    const mark = buttons[index]?.querySelector("span");
    expect(mark).toBeTruthy();
    return mark?.className ?? "";
  }

  function sixTurns(overrides: Record<number, Partial<ConversationTurnNavEntry>> = {}) {
    return Array.from({ length: 6 }, (_, turnIndex) => navEntry({
      turnIndex,
      userPreviewText: `问题 ${turnIndex}`,
      ...overrides[turnIndex],
    }));
  }

  it("applies the ZCode mountain decay around the hovered tick with a strong center", () => {
    mountNavigator(sixTurns());
    const buttons = railButtons();
    act(() => {
      pointerOver(buttons[3]);
    });
    // Center: scaleX 2.6, full opacity, strong fg-primary mark.
    expect(markAt(3)).toContain("scale-x-[2.6]");
    expect(markAt(3)).toContain("opacity-100");
    expect(markAt(3)).toContain("text-[var(--fg-primary)]");
    // Distance 1: 1.7 / 0.86; distance 2: 1.25 / 0.72.
    expect(markAt(2)).toContain("scale-x-[1.7]");
    expect(markAt(2)).toContain("opacity-[0.86]");
    expect(markAt(4)).toContain("scale-x-[1.7]");
    expect(markAt(4)).toContain("opacity-[0.86]");
    expect(markAt(1)).toContain("scale-x-[1.25]");
    expect(markAt(1)).toContain("opacity-[0.72]");
    expect(markAt(5)).toContain("scale-x-[1.25]");
    expect(markAt(5)).toContain("opacity-[0.72]");
    // Beyond the mountain: plain 0.58, even for the active tick (index 0).
    expect(markAt(0)).toContain("opacity-[0.58]");
    expect(markAt(0)).not.toContain("scale-x-");
    expect(markAt(0)).not.toContain("opacity-[0.9]");
  });

  it("keeps the idle scroll-active tone at 0.9 and mutes the rest at 0.58", () => {
    mountNavigator(sixTurns());
    expect(railButtons()[0].className).toContain("turnNavigatorDotActive");
    expect(markAt(0)).toContain("opacity-[0.9]");
    expect(markAt(0)).not.toContain("scale-x-");
    for (const index of [1, 2, 3, 4, 5]) {
      expect(markAt(index)).toContain("opacity-[0.58]");
      expect(markAt(index)).not.toContain("scale-x-");
    }
  });

  it("anchors directory a11y: aria-current=location plus posinset/setsize", () => {
    mountNavigator(sixTurns());
    const buttons = railButtons();
    expect(buttons[0].getAttribute("aria-current")).toBe("location");
    for (const index of [1, 2, 3, 4, 5]) {
      expect(buttons[index].getAttribute("aria-current")).toBeNull();
    }
    buttons.forEach((button, index) => {
      expect(button.getAttribute("aria-posinset")).toBe(String(index + 1));
      expect(button.getAttribute("aria-setsize")).toBe("6");
    });
  });

  it("emphasizes running ticks with the 0.72 opacity floor and data-running", () => {
    mountNavigator(sixTurns({ 5: { isRunning: true } }));
    const buttons = railButtons();
    // Idle: running keeps 0.72 instead of the plain 0.58 idle dim.
    expect(markAt(5)).toContain("opacity-[0.72]");
    expect(markAt(4)).toContain("opacity-[0.58]");
    expect(buttons[5].getAttribute("data-running")).toBe("true");
    expect(buttons[0].getAttribute("data-running")).toBe("false");
    // Far from the hovered center, the floor still beats the 0.58 decay.
    act(() => {
      pointerOver(buttons[0]);
    });
    expect(markAt(5)).toContain("opacity-[0.72]");
  });

  it("runs the localized running fallback in hover previews only without final text", () => {
    vi.useFakeTimers();
    mountNavigator(sixTurns({
      4: { isRunning: true, assistantPreviewText: "流式中的部分正文" },
      5: { isRunning: true },
    }), undefined, { runningAssistantPreview: "助手正在回复中…" });
    const buttons = railButtons();

    // Running without assistant text: user query + localized running copy.
    act(() => {
      pointerOver(buttons[5]);
    });
    act(() => {
      vi.advanceTimersByTime(120);
    });
    let content = document.querySelector("[data-vui='hover-card-content']");
    expect(content?.textContent).toContain("问题 5");
    expect(content?.textContent).toContain("助手正在回复中…");
    expect(content?.querySelectorAll("p").length).toBe(2);

    // Streaming text already present: the assistant excerpt wins, no running copy.
    act(() => {
      pointerOver(buttons[4]);
    });
    act(() => {
      vi.advanceTimersByTime(120);
    });
    // Turn 5's card stays mounted from the previous hover; pick by content.
    const contents = [...document.querySelectorAll("[data-vui='hover-card-content']")];
    const turnFourCard = contents.find((node) => node.textContent?.includes("问题 4"));
    expect(turnFourCard?.textContent).toContain("流式中的部分正文");
    expect(turnFourCard?.textContent).not.toContain("助手正在回复中…");
    expect(turnFourCard?.querySelectorAll("p").length).toBe(2);
  });

  it("omits the running paragraph when no localized copy is provided", () => {
    vi.useFakeTimers();
    mountNavigator(sixTurns({ 5: { isRunning: true, userPreviewText: "第五轮问题" } }));
    const buttons = railButtons();
    act(() => {
      pointerOver(buttons[5]);
    });
    act(() => {
      vi.advanceTimersByTime(120);
    });
    const content = document.querySelector("[data-vui='hover-card-content']");
    expect(content?.textContent).toContain("第五轮问题");
    expect(content?.querySelectorAll("p").length).toBe(1);
  });

  it("keeps preview-less running dots unwrapped unless running copy exists", () => {
    mountNavigator(sixTurns({ 5: { isRunning: true, userPreviewText: "" } }));
    const buttons = railButtons();
    expect(buttons[5].getAttribute("data-slot")).toBeNull();
    unmountNavigator();
    mountNavigator(sixTurns({ 5: { isRunning: true, userPreviewText: "" } }), undefined, {
      runningAssistantPreview: "助手正在回复中…",
    });
    expect(railButtons()[5].getAttribute("data-slot")).toBe("hover-card-trigger");
  });
});
