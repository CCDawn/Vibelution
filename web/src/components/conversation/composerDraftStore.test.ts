import { describe, expect, it, vi } from "vitest";

import {
  createComposerDraftStore,
  syncComposerDraftStoreFromUpstream,
} from "./composerDraftStore";

describe("syncComposerDraftStoreFromUpstream", () => {
  it("clears the composer when a submit resets the upstream draft", () => {
    const store = createComposerDraftStore("你来还原");

    expect(syncComposerDraftStoreFromUpstream(store, "")).toBe(true);
    expect(store.getSnapshot()).toBe("");
  });

  it("leaves the typed text alone while the upstream still carries it", () => {
    const store = createComposerDraftStore("你");

    expect(syncComposerDraftStoreFromUpstream(store, "你来还原")).toBe(false);
    expect(store.getSnapshot()).toBe("你");
  });

  it("does not notify subscribers when the composer is already empty", () => {
    const store = createComposerDraftStore("");
    const listener = vi.fn();
    store.subscribe(listener);

    expect(syncComposerDraftStoreFromUpstream(store, "")).toBe(false);
    expect(listener).not.toHaveBeenCalled();
  });
});
