/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import type { EvolutionChatReviewCandidate } from "../api/types";
import { ReviewQueueVirtualList, SupervisedReviewTranscript } from "./SupervisedReviewRoute";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement | null = null;
let root: Root | null = null;
let originalGetBoundingClientRect: typeof HTMLElement.prototype.getBoundingClientRect | null = null;

const candidate = {
  candidateId: "candidate-1",
  sourceLogPath: "review/source.jsonl",
  conversationTurns: Array.from({ length: 1_000 }, (_, index) => ({
    turnNumber: index + 1,
    userMessage: `Check source ${index + 1}`,
    assistantMessage: `Read source ${index + 1}`,
    toolCalls: ["read_file"],
  })),
} as Pick<EvolutionChatReviewCandidate, "candidateId" | "conversationTurns" | "sourceLogPath">;

function TranscriptHarness({ candidate: currentCandidate }: { candidate: typeof candidate }) {
  return (
    <SupervisedReviewTranscript
      key={currentCandidate.candidateId}
      lang="en"
      candidate={currentCandidate}
      positiveDatasetPath="review/positive.jsonl"
      negativeDatasetPath="review/negative.jsonl"
    />
  );
}

function renderTranscript() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => {
    root?.render(<TranscriptHarness candidate={candidate} />);
  });
  return host;
}

function renderLargeQueue() {
  const items = Array.from({ length: 1_000 }, (_, index) => ({ id: `case-${index}` }));
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => {
    root?.render(
      <ReviewQueueVirtualList
        items={items}
        getItemKey={(item) => item.id}
        ariaLabel="Review samples"
        renderItem={(item) => <article role="button" tabIndex={0}>{item.id}</article>}
      />,
    );
  });
  return host;
}

function stubQueueViewport() {
  originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function () {
    const index = this.getAttribute("data-index");
    const height = index === null ? 540 : 104;
    return {
      width: 380,
      height,
      top: 0,
      left: 0,
      bottom: height,
      right: 380,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect;
  };
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
    configurable: true,
    get: () => 380,
  });
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get() {
      return this.getAttribute("data-index") === null ? 540 : 104;
    },
  });
}

afterEach(async () => {
  if (root) {
    await act(async () => root?.unmount());
  }
  host?.remove();
  root = null;
  host = null;
  if (originalGetBoundingClientRect) {
    HTMLElement.prototype.getBoundingClientRect = originalGetBoundingClientRect;
    originalGetBoundingClientRect = null;
  }
  delete (HTMLElement.prototype as { offsetWidth?: unknown }).offsetWidth;
  delete (HTMLElement.prototype as { offsetHeight?: unknown }).offsetHeight;
});

describe("SupervisedReviewTranscript", () => {
  it("mounts transcript turns only after the native disclosure opens", async () => {
    const container = renderTranscript();
    const details = container.querySelector("details");
    const summary = container.querySelector("summary");

    expect(details?.open).toBe(false);
    expect(container.textContent).toContain("Full transcript and provenance");
    expect(container.textContent).not.toContain("Turn 1");
    expect(Array.from(container.querySelectorAll("article")).filter((article) =>
      article.querySelector("strong")?.textContent?.startsWith("Turn "),
    )).toHaveLength(0);

    await act(async () => {
      summary?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
    });

    expect(details?.open).toBe(true);
    expect(container.textContent).toContain("Turn 1000");
    expect(Array.from(container.querySelectorAll("article")).filter((article) =>
      article.querySelector("strong")?.textContent?.startsWith("Turn "),
    )).toHaveLength(1_000);

    const nextCandidate = {
      ...candidate,
      candidateId: "candidate-2",
      conversationTurns: [
        {
          turnNumber: 1,
          userMessage: "New candidate request",
          assistantMessage: "New candidate response",
          toolCalls: [],
        },
      ],
    };
    await act(async () => {
      root?.render(<TranscriptHarness candidate={nextCandidate} />);
    });

    expect(container.querySelector("details")?.open).toBe(false);
    expect(container.textContent).not.toContain("New candidate request");
    expect(Array.from(container.querySelectorAll("article")).filter((article) =>
      article.querySelector("strong")?.textContent?.startsWith("Turn "),
    )).toHaveLength(0);

    await act(async () => {
      container.querySelector("summary")?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
    });

    expect(container.querySelector("details")?.open).toBe(true);
    expect(container.textContent).toContain("New candidate request");
    expect(container.textContent).not.toContain("Check source 1");
    expect(Array.from(container.querySelectorAll("article")).filter((article) =>
      article.querySelector("strong")?.textContent?.startsWith("Turn "),
    )).toHaveLength(1);

    await act(async () => {
      container.querySelector("summary")?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
    });

    expect(container.querySelector("details")?.open).toBe(false);
    expect(container.textContent).not.toContain("New candidate request");
    expect(Array.from(container.querySelectorAll("article")).filter((article) =>
      article.querySelector("strong")?.textContent?.startsWith("Turn "),
    )).toHaveLength(0);
  });
});

describe("SupervisedReview queue virtualization", () => {
  it("renders a measured window of a large queue and keeps keyboard navigation reachable", async () => {
    stubQueueViewport();
    const container = renderLargeQueue();
    const mountedRows = container.querySelectorAll("[data-review-row-index]");

    expect(mountedRows.length).toBeGreaterThan(0);
    expect(mountedRows.length).toBeLessThan(40);
    expect(container.textContent).not.toContain("case-999");

    const firstRow = container.querySelector<HTMLElement>('[role="button"]');
    expect(firstRow).not.toBeNull();
    await act(async () => {
      firstRow?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true }));
    });
    expect(document.activeElement?.closest("[data-review-row-index]")?.getAttribute("data-review-row-index")).toBe("1");
  });
});
