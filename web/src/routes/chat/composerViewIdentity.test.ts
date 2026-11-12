import { afterEach, describe, expect, it } from "vitest";

import {
  rememberComposerViewRebase,
  resetComposerViewRebaseForTests,
  resolveComposerViewKey,
} from "./composerViewIdentity";

const TEMP_ID = "temp-session-1759999999-abc";
const REAL_ID = "session-real-1";
const OTHER_ID = "session-real-2";

afterEach(() => {
  resetComposerViewRebaseForTests();
});

describe("composer view identity", () => {
  it("keeps the temp view key for the real id that replaced it", () => {
    rememberComposerViewRebase(TEMP_ID, REAL_ID);

    expect(resolveComposerViewKey(REAL_ID)).toBe(TEMP_ID);
  });

  it("still remounts for any other conversation switch", () => {
    rememberComposerViewRebase(TEMP_ID, REAL_ID);

    expect(resolveComposerViewKey(OTHER_ID)).toBe(OTHER_ID);
    expect(resolveComposerViewKey(TEMP_ID)).toBe(TEMP_ID);
  });

  it("resolves to its own id when no rebase was recorded", () => {
    expect(resolveComposerViewKey(REAL_ID)).toBe(REAL_ID);
  });

  it("ignores empty and self-referential rebases", () => {
    rememberComposerViewRebase(TEMP_ID, TEMP_ID);
    expect(resolveComposerViewKey(TEMP_ID)).toBe(TEMP_ID);

    rememberComposerViewRebase("", REAL_ID);
    expect(resolveComposerViewKey(REAL_ID)).toBe(REAL_ID);
  });

  it("tracks only the newest rebase", () => {
    rememberComposerViewRebase(TEMP_ID, REAL_ID);
    rememberComposerViewRebase(OTHER_ID, "session-real-3");

    expect(resolveComposerViewKey(REAL_ID)).toBe(REAL_ID);
    expect(resolveComposerViewKey("session-real-3")).toBe(OTHER_ID);
  });
});
