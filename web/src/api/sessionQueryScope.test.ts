import { describe, expect, it } from "vitest";

import {
  isSessionIndexQueryNarrowedByUser,
  isSessionIndexQueryStaleAfterTurn,
} from "./sessionQueryScope";

describe("session index refresh scope", () => {
  it("keeps the bare and default index pages fresh after a turn commits", () => {
    expect(isSessionIndexQueryStaleAfterTurn(["sessions"])).toBe(true);
    expect(isSessionIndexQueryStaleAfterTurn(["sessions", "query", "", 50, "", "recent"])).toBe(true);
  });

  it("leaves a search the user is typing into alone", () => {
    const searchKey = ["sessions", "query", "导出脚本", 50, "", "recent"];
    expect(isSessionIndexQueryStaleAfterTurn(searchKey)).toBe(false);
    expect(isSessionIndexQueryNarrowedByUser(searchKey)).toBe(true);
  });

  it("leaves deep cursor pages alone", () => {
    const cursorKey = ["sessions", "query", "", 50, "cursor-2", "recent"];
    expect(isSessionIndexQueryStaleAfterTurn(cursorKey)).toBe(false);
    expect(isSessionIndexQueryNarrowedByUser(cursorKey)).toBe(true);
  });

  it("still refreshes the archived listing and ignores other key families", () => {
    expect(isSessionIndexQueryStaleAfterTurn(["sessions", "archived", "recent"])).toBe(true);
    expect(isSessionIndexQueryStaleAfterTurn(["session", "session-1"])).toBe(false);
    expect(isSessionIndexQueryStaleAfterTurn(["runtime", "summary"])).toBe(false);
  });

  it("treats the default page as not narrowed by the user", () => {
    expect(isSessionIndexQueryNarrowedByUser(["sessions", "query", "", 50, "", "recent"])).toBe(false);
    expect(isSessionIndexQueryNarrowedByUser(["sessions"])).toBe(false);
  });
});
