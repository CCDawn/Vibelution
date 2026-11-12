import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { rekeySessionComposerEntry } from "../chatComposerState";
import {
  flushLiveDraftMirror,
  moveLiveComposerDraft,
  resetLiveComposerDraftsForTests,
  scheduleLiveDraftMirror,
  writeLiveComposerDraft,
} from "./composerLiveDraft";

const TEMP_ID = "temp-1759999999-abc";
const REAL_ID = "session-real-1";

/** Stand-in for the workbench's `sessionDrafts` mirror. */
function createMirror() {
  const entries: Record<string, string> = {};
  return {
    entries,
    apply: (sessionId: string, value: string) => {
      entries[sessionId] = value;
    },
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  resetLiveComposerDraftsForTests();
});

afterEach(() => {
  resetLiveComposerDraftsForTests();
  vi.useRealTimers();
});

describe("composer live draft rebase", () => {
  it("lands a pending mirror on the real id, never on the retired temp id", () => {
    const mirror = createMirror();
    writeLiveComposerDraft(TEMP_ID, "typed before create returned");
    scheduleLiveDraftMirror(TEMP_ID, "typed before create returned", mirror.apply);

    moveLiveComposerDraft(TEMP_ID, REAL_ID);
    vi.advanceTimersByTime(400);

    expect(mirror.entries[REAL_ID]).toBe("typed before create returned");
    expect(mirror.entries[TEMP_ID]).toBeUndefined();
  });

  it("carries flushed keystrokes through the temp-to-real rekey", () => {
    const mirror = createMirror();
    writeLiveComposerDraft(TEMP_ID, "not mirrored yet");
    scheduleLiveDraftMirror(TEMP_ID, "not mirrored yet", mirror.apply);

    flushLiveDraftMirror(TEMP_ID, mirror.apply);
    moveLiveComposerDraft(TEMP_ID, REAL_ID);
    const rekeyed = rekeySessionComposerEntry({ ...mirror.entries }, TEMP_ID, REAL_ID);

    expect(rekeyed[REAL_ID]).toBe("not mirrored yet");
  });

  it("does not let a retired timer clobber text typed after the rebase", () => {
    const mirror = createMirror();
    writeLiveComposerDraft(TEMP_ID, "old");
    scheduleLiveDraftMirror(TEMP_ID, "old", mirror.apply);
    moveLiveComposerDraft(TEMP_ID, REAL_ID);

    writeLiveComposerDraft(REAL_ID, "old plus new");
    scheduleLiveDraftMirror(REAL_ID, "old plus new", mirror.apply);
    vi.advanceTimersByTime(400);

    expect(mirror.entries[REAL_ID]).toBe("old plus new");
    expect(mirror.entries[TEMP_ID]).toBeUndefined();
  });

  it("keeps an empty draft empty when nothing was typed", () => {
    const mirror = createMirror();
    moveLiveComposerDraft(TEMP_ID, REAL_ID);
    vi.advanceTimersByTime(400);

    expect(mirror.entries[REAL_ID]).toBeUndefined();
  });
});
