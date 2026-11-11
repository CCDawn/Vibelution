import { describe, expect, it, vi } from "vitest";

import {
  clearRegisteredComposerDraft,
  createComposerDraftStore,
  registerComposerDraftStore,
  resetRegisteredComposerDraftsForTests,
  restoreRegisteredComposerDraft,
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

describe("submitted draft ownership", () => {
  it("clears the mounted composer when the submit never reached the upstream draft", () => {
    // Typing inside the typing pause leaves `sessionDrafts` empty, so the
    // submit's upstream clear is not a state change and the sync above cannot
    // fire. The sent text must still leave the composer.
    const store = createComposerDraftStore("");
    registerComposerDraftStore("session-1", store);
    store.set("设置里有啊，qoder");
    try {
      expect(clearRegisteredComposerDraft("session-1", "设置里有啊，qoder")).toBe(true);
      expect(store.getSnapshot()).toBe("");
    } finally {
      resetRegisteredComposerDraftsForTests();
    }
  });

  it("keeps text typed after the submit", () => {
    const store = createComposerDraftStore("");
    registerComposerDraftStore("session-2", store);
    store.set("next message");
    try {
      expect(clearRegisteredComposerDraft("session-2", "already sent")).toBe(false);
      expect(store.getSnapshot()).toBe("next message");
    } finally {
      resetRegisteredComposerDraftsForTests();
    }
  });

  it("ignores stores that are not mounted for that session", () => {
    const store = createComposerDraftStore("still typing");
    const unregister = registerComposerDraftStore("session-3", store);
    unregister();
    expect(clearRegisteredComposerDraft("session-3", "still typing")).toBe(false);
    expect(store.getSnapshot()).toBe("still typing");
  });

  it("puts a failed submission back into an empty composer", () => {
    const store = createComposerDraftStore("");
    registerComposerDraftStore("session-4", store);
    try {
      expect(restoreRegisteredComposerDraft("session-4", "设置里有啊，qoder")).toBe(true);
      expect(store.getSnapshot()).toBe("设置里有啊，qoder");
    } finally {
      resetRegisteredComposerDraftsForTests();
    }
  });

  it("does not overwrite text typed while the request was in flight", () => {
    const store = createComposerDraftStore("new text");
    registerComposerDraftStore("session-5", store);
    try {
      expect(restoreRegisteredComposerDraft("session-5", "failed message")).toBe(false);
      expect(store.getSnapshot()).toBe("new text");
    } finally {
      resetRegisteredComposerDraftsForTests();
    }
  });
});
