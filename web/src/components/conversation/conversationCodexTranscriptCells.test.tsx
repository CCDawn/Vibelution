// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import type { TranslationKey } from "../../i18n/dictionaryTypes";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { createCodexTranscriptCellRenderers } from "./conversationCodexTranscriptCells";
import { VuiProvider } from "../vui";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function renderers() {
  return createCodexTranscriptCellRenderers({
    lang: "zh",
    t: (key: TranslationKey) => key,
    getExpansionState: () => false,
    toggleSection: () => undefined,
  });
}

function progressCell(text: string): CodexTranscriptCell {
  return {
    id: "cell-progress-1",
    kind: "assistant_markdown",
    status: "running",
    tone: "default",
    phase: "commentary",
    text,
  } as unknown as CodexTranscriptCell;
}

describe("codex transcript narration lanes", () => {
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

  it("strips ANSI artifacts from the live progress lane", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const node = renderers().renderCodexProgressCell(
      "message-1",
      progressCell("生成计划[1m加粗[0m正文"),
      "生成计划[1m加粗[0m正文",
    );
    await act(async () => {
      root?.render(<VuiProvider>{node}</VuiProvider>);
    });
    expect(container.textContent).toContain("生成计划加粗正文");
    expect(container.textContent).not.toContain("[1m");
    expect(container.textContent).not.toContain("[0m");
  });

  it("strips ANSI artifacts from the expanded thought lane", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const withExpansion = createCodexTranscriptCellRenderers({
      lang: "zh",
      t: (key: TranslationKey) => key,
      getExpansionState: () => true,
      toggleSection: () => undefined,
    });
    const node = withExpansion.renderCodexThoughtScrollCell("message-1", {
      cellId: "cell-thought-1",
      sectionId: "reasoning:cell-thought-1",
      text: "思考[1m片段[0m结尾",
      status: "running",
      tone: "default",
    });
    await act(async () => {
      root?.render(<VuiProvider>{node}</VuiProvider>);
    });
    expect(container.textContent).toContain("思考片段结尾");
    expect(container.textContent).not.toContain("[1m");
    expect(container.textContent).not.toContain("[0m");
  });

  it("shows a short settled thought inline and keeps a long one folded", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    // Honour the caller default so the length rule under test decides, not the mock.
    const honoringDefaults = createCodexTranscriptCellRenderers({
      lang: "zh",
      t: (key: TranslationKey) => key,
      getExpansionState: (_messageId, _section, defaultExpanded) => defaultExpanded,
      toggleSection: () => undefined,
    });
    const shortText = "先确认锁等待占比，再决定要不要动结构。";
    const longText = "先确认锁等待占比。".repeat(40);
    const renderThought = async (text: string) => {
      const node = honoringDefaults.renderCodexThoughtScrollCell("message-1", {
        cellId: "cell-thought-1",
        sectionId: "reasoning:cell-thought-1",
        text,
        status: "completed",
        tone: "default",
      });
      await act(async () => {
        root?.render(<VuiProvider>{node}</VuiProvider>);
      });
      return container?.textContent ?? "";
    };
    expect(await renderThought(shortText)).toContain(shortText);
    expect(await renderThought(longText)).not.toContain(longText.slice(0, 24));
  });
  it("renders inline code inside an expanded thought as a chip", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const withExpansion = createCodexTranscriptCellRenderers({
      lang: "zh",
      t: (key: TranslationKey) => key,
      getExpansionState: () => true,
      toggleSection: () => undefined,
    });
    const node = withExpansion.renderCodexThoughtScrollCell("message-1", {
      cellId: "cell-thought-code",
      sectionId: "reasoning:cell-thought-code",
      text: "先看 `resolve_data_home()` 的返回值",
      status: "completed",
      tone: "default",
    });
    await act(async () => {
      root?.render(<VuiProvider>{node}</VuiProvider>);
    });
    const chip = container.querySelector("code");
    expect(chip?.textContent).toBe("resolve_data_home()");
    expect(container.textContent).toContain("先看");
  });

});
