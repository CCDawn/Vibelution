// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import styles from "./ConversationView.styles";
import { ConversationMarkdownRenderer } from "./ConversationMarkdownRenderer";
import { ConversationMarkdownMermaidBlock } from "./conversationMarkdownMermaidBlock";
import {
  MERMAID_SOURCE_MAX_CHARS,
  MERMAID_SOURCE_MAX_LINES,
  resolveMermaidSourceBudgetDecision,
} from "./conversationMarkdownMermaid";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const mermaidState = vi.hoisted(() => ({
  initialize: vi.fn(),
  render: vi.fn<(...args: unknown[]) => Promise<{ svg: string }>>(),
}));

vi.mock("mermaid", () => ({
  default: {
    initialize: mermaidState.initialize,
    render: mermaidState.render,
  },
}));

const SAMPLE_DIAGRAM = ["flowchart TD", "  A[开始] --> B{判断}", "  B -->|是| C[结束]"].join("\n");

function renderBlock(code: string, language: "zh" | "en" = "zh") {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => {
    root.render(<ConversationMarkdownMermaidBlock code={code} preClassName="pre-chrome" language={language} />);
  });
  return {
    host,
    unmount: () => {
      act(() => {
        root.unmount();
      });
      host.remove();
    },
  };
}

describe("resolveMermaidSourceBudgetDecision", () => {
  it("keeps sources within the budget renderable", () => {
    expect(resolveMermaidSourceBudgetDecision(SAMPLE_DIAGRAM)).toEqual({ renderable: true });
    const atLineBudget = Array.from({ length: MERMAID_SOURCE_MAX_LINES }, (_, i) => `n${i}`).join("\n");
    expect(resolveMermaidSourceBudgetDecision(atLineBudget, { maxLines: MERMAID_SOURCE_MAX_LINES })).toEqual({
      renderable: true,
    });
  });

  it("rejects sources over the char or line budget", () => {
    expect(resolveMermaidSourceBudgetDecision("x".repeat(MERMAID_SOURCE_MAX_CHARS + 1)).renderable).toBe(false);
    const reason = resolveMermaidSourceBudgetDecision("x".repeat(MERMAID_SOURCE_MAX_CHARS + 1));
    expect(reason).toEqual({ renderable: false, reason: "source-too-large" });
    expect(resolveMermaidSourceBudgetDecision("a\n".repeat(MERMAID_SOURCE_MAX_LINES + 1))).toEqual({
      renderable: false,
      reason: "line-count-too-large",
    });
  });
});

describe("ConversationMarkdownMermaidBlock", () => {
  beforeEach(() => {
    mermaidState.initialize.mockClear();
    mermaidState.render.mockReset();
    mermaidState.render.mockResolvedValue({ svg: '<svg viewBox="0 0 10 10"><g>图</g></svg>' });
  });

  it("rests in idle plaintext with a render action and never imports mermaid before the click", () => {
    const { host, unmount } = renderBlock(SAMPLE_DIAGRAM);
    try {
      expect(host.querySelector('[data-mermaid-state="idle"]')).not.toBeNull();
      expect(host.querySelector('button[aria-label="渲染 Mermaid 图表"]')).not.toBeNull();
      const pre = host.querySelector("pre");
      expect(pre?.textContent).toBe(SAMPLE_DIAGRAM);
      // Lazy: no mermaid module work before the explicit render action.
      expect(mermaidState.initialize).not.toHaveBeenCalled();
      expect(mermaidState.render).not.toHaveBeenCalled();
    } finally {
      unmount();
    }
  });

  it("lazily loads mermaid on the render action and mounts the sanitized svg viewport", async () => {
    const { host, unmount } = renderBlock(SAMPLE_DIAGRAM);
    try {
      const button = host.querySelector<HTMLButtonElement>('button[aria-label="渲染 Mermaid 图表"]');
      await act(async () => {
        button!.click();
      });
      expect(mermaidState.initialize).toHaveBeenCalledTimes(1);
      expect(mermaidState.initialize).toHaveBeenCalledWith(
        expect.objectContaining({ startOnLoad: false, securityLevel: "strict" }),
      );
      expect(mermaidState.render).toHaveBeenCalledTimes(1);
      expect(mermaidState.render.mock.calls[0]?.[1]).toBe(SAMPLE_DIAGRAM);
      const ready = host.querySelector('[data-mermaid-state="ready"]');
      expect(ready).not.toBeNull();
      const canvas = host.querySelector('[role="img"]');
      expect(canvas).not.toBeNull();
      expect(canvas!.innerHTML).toContain("<svg");
      expect(host.querySelector("pre")).toBeNull();
    } finally {
      unmount();
    }
  });

  it("degrades to plaintext with an error hint when the mermaid render fails", async () => {
    mermaidState.render.mockRejectedValueOnce(new Error("Parse error on line 2"));
    const { host, unmount } = renderBlock(SAMPLE_DIAGRAM);
    try {
      const button = host.querySelector<HTMLButtonElement>('button[aria-label="渲染 Mermaid 图表"]');
      await act(async () => {
        button!.click();
      });
      expect(host.querySelector('[data-mermaid-state="failed"]')).not.toBeNull();
      const status = host.querySelector('[data-mermaid-state="failed"] .markdownMermaidStatus');
      expect(status?.textContent).toContain("Mermaid 渲染失败");
      expect(status?.textContent).toContain("Parse error on line 2");
      // The source stays readable as plaintext.
      expect(host.querySelector("pre")?.textContent).toBe(SAMPLE_DIAGRAM);
      // A retry action is offered again after the failure.
      expect(host.querySelector('button[aria-label="渲染 Mermaid 图表"]')).not.toBeNull();
    } finally {
      unmount();
    }
  });

  it("keeps over-budget sources as plaintext with a hint and no render action", () => {
    const overLines = Array.from({ length: MERMAID_SOURCE_MAX_LINES + 1 }, (_, i) => `node${i}`).join("\n");
    const { host, unmount } = renderBlock(overLines);
    try {
      expect(host.querySelector('[data-mermaid-state="over-budget"]')).not.toBeNull();
      expect(host.querySelector('button[aria-label="渲染 Mermaid 图表"]')).toBeNull();
      expect(host.textContent).toContain("图表过大（超过 600 行）");
      expect(host.querySelector("pre")?.textContent).toBe(overLines);
      expect(mermaidState.render).not.toHaveBeenCalled();
    } finally {
      unmount();
    }

    const overChars = `${"x".repeat(MERMAID_SOURCE_MAX_CHARS + 1)}\nflowchart TD`;
    const charHost = renderBlock(overChars);
    try {
      expect(charHost.host.querySelector('[data-mermaid-state="over-budget"]')).not.toBeNull();
      expect(charHost.host.querySelector('button[aria-label="渲染 Mermaid 图表"]')).toBeNull();
      expect(charHost.host.textContent).toContain("图表过大（超过 20000 字符）");
    } finally {
      charHost.unmount();
    }
  });

  it("localizes the render chrome", async () => {
    const { host, unmount } = renderBlock(SAMPLE_DIAGRAM, "en");
    try {
      expect(host.querySelector('button[aria-label="Render Mermaid diagram"]')).not.toBeNull();
      const button = host.querySelector<HTMLButtonElement>('button[aria-label="Render Mermaid diagram"]');
      await act(async () => {
        button!.click();
      });
      expect(host.querySelector('[role="img"]')?.getAttribute("aria-label")).toBe("Mermaid diagram");
    } finally {
      unmount();
    }
  });
});

describe("ConversationMarkdownRenderer mermaid fence routing", () => {
  beforeEach(() => {
    mermaidState.initialize.mockClear();
    mermaidState.render.mockReset();
    mermaidState.render.mockResolvedValue({ svg: "<svg />" });
  });

  it("routes ```mermaid fences to the mermaid block instead of the plain code block", () => {
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content={["```mermaid", SAMPLE_DIAGRAM, "```"].join("\n")}
        classNames={styles}
      />,
    );
    expect(html).toContain('data-markdown-mermaid-block="true"');
    expect(html).toContain('data-mermaid-state="idle"');
    expect(html).toContain('aria-label="渲染 Mermaid 图表"');
    // Static markup escapes the diagram arrows; the source text is intact.
    expect(html).toContain("flowchart TD");
    expect(html).toContain("A[开始] --&gt; B{判断}");
    expect(html).toContain("B --&gt;|是| C[结束]");
    // Not the regular code-block header copy/wrap controls.
    expect(html).not.toContain('aria-label="复制代码"');
    expect(html).not.toContain('aria-label="自动换行"');
    // Mermaid stays lazy: no module initialization on the settled render path.
    expect(mermaidState.initialize).not.toHaveBeenCalled();
  });

  it("keeps non-mermaid fences on the code-block path", () => {
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer content={["```mermaidish", "plain", "```"].join("\n")} classNames={styles} />,
    );
    expect(html).not.toContain("data-markdown-mermaid-block");
    expect(html).toContain('aria-label="复制代码"');
  });
});
