/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchSessionComposerExample, fetchSessionPromptSuggestion, type SessionComposerExampleResponse } from "../../api/chat";
import { useComposerPromptSuggestion, type ComposerPromptSuggestionInput, type ComposerPromptSuggestionState } from "./useComposerPromptSuggestion";

vi.mock("../../api/chat", () => ({
  fetchSessionComposerExample: vi.fn(),
  fetchSessionPromptSuggestion: vi.fn(),
  isFetchAbortError: (error: unknown) => error instanceof Error && error.name === "AbortError",
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => { resolve = resolvePromise; reject = rejectPromise; });
  return { promise, resolve, reject };
}

const zh = { command: "整理计划", starters: [{ heading: "整理", command: "整理计划" }] };
const en = { command: "Organize a plan", starters: [{ heading: "Organize", command: "Organize a plan" }] };

describe("composer starter language synchronization", () => {
  let root: Root;
  let container: HTMLDivElement;
  let state: ComposerPromptSuggestionState;
  let input: ComposerPromptSuggestionInput;
  const onAccept = vi.fn();

  function Probe() {
    state = useComposerPromptSuggestion(input, onAccept);
    return <><textarea readOnly value={input.draft} /><output>{state.starters.map(starter => `${starter.heading}: ${starter.command}`).join("|")}</output></>;
  }

  beforeEach(() => {
    vi.resetAllMocks();
    input = { sessionId: "session-1", suggestionEnabled: false, starterEnabled: true, busy: false, draft: "用户草稿", hasConversation: false };
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  async function render(next: Partial<typeof input> = {}) {
    input = { ...input, ...next };
    await act(async () => { root.render(<Probe />); await Promise.resolve(); });
  }

  it("refreshes the same mounted starter cards from zh to en to zh without accepting or writing the draft", async () => {
    vi.mocked(fetchSessionComposerExample).mockResolvedValueOnce(zh).mockResolvedValueOnce(en).mockResolvedValueOnce(zh);
    await render(); // Omitted language retains the existing Chinese default.
    expect(state.exampleCommand).toBe(zh.command);
    expect(container.querySelector("output")?.textContent).toBe("整理: 整理计划");
    await render({ language: "en" });
    expect(state.exampleCommand).toBe(en.command);
    expect(container.querySelector("output")?.textContent).toBe("Organize: Organize a plan");
    await render({ language: "zh" });
    expect(state.exampleCommand).toBe(zh.command);
    expect(fetchSessionComposerExample).toHaveBeenCalledTimes(3);
    expect(container.querySelector("textarea")?.value).toBe("用户草稿");
    expect(onAccept).not.toHaveBeenCalled();
    expect(fetchSessionPromptSuggestion).not.toHaveBeenCalled();
  });

  it("clears old cards while the new language loads and aborts the preceding request", async () => {
    const next = deferred<SessionComposerExampleResponse>();
    vi.mocked(fetchSessionComposerExample).mockResolvedValueOnce(zh).mockReturnValueOnce(next.promise);
    await render({ language: "zh" });
    const signal = vi.mocked(fetchSessionComposerExample).mock.calls[0][1]?.signal;
    await render({ language: "en" });
    expect(signal?.aborted).toBe(true);
    expect(state.exampleCommand).toBe("");
    expect(state.starters).toEqual([]);
    await act(async () => { next.resolve(en); await Promise.resolve(); });
    expect(state.exampleCommand).toBe(en.command);
    expect(onAccept).not.toHaveBeenCalled();
  });

  it.each(["success", "error"] as const)("ignores a late old-language %s after the new cards arrive", async (outcome) => {
    const old = deferred<SessionComposerExampleResponse>();
    vi.mocked(fetchSessionComposerExample).mockReturnValueOnce(old.promise).mockResolvedValueOnce(en);
    await render({ language: "zh" });
    await render({ language: "en" });
    expect(state.exampleCommand).toBe(en.command);
    await act(async () => {
      if (outcome === "success") old.resolve(zh);
      else old.reject(new Error("late request failure"));
      await Promise.resolve();
    });
    expect(state.exampleCommand).toBe(en.command);
    expect(state.starters).toEqual(en.starters);
    expect(onAccept).not.toHaveBeenCalled();
  });

  it("keeps the visible and dismissed AI ghost in the same turn across language changes", async () => {
    vi.mocked(fetchSessionPromptSuggestion).mockResolvedValue({ sessionId: "session-1", turnId: "turn-1", suggestion: "Continue", reason: "ok" });
    await render({ hasConversation: true, draft: "", suggestionEnabled: true, language: "zh" });
    expect(state.ghost).toBe("Continue");
    await render({ language: "en" });
    expect(state.ghost).toBe("Continue");
    await act(async () => state.dismissGhost());
    await render({ language: "zh" });
    expect(state.ghost).toBe("");
    expect(fetchSessionPromptSuggestion).toHaveBeenCalledTimes(1);
    expect(fetchSessionComposerExample).not.toHaveBeenCalled();
    expect(onAccept).not.toHaveBeenCalled();
  });
});
