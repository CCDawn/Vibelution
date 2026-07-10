import { describe, expect, it } from "vitest";

import { deriveQueryPresentation } from "./queryPresentation";

describe("query presentation", () => {
  it.each([
    [{ hasData: false, isPending: true, isFetching: true, isError: false }, "initial-loading"],
    [{ hasData: true, isPending: false, isFetching: false, isError: false }, "loaded"],
    [{ hasData: true, isPending: false, isFetching: true, isError: false }, "refreshing"],
    [{ hasData: false, isPending: false, isFetching: false, isError: true }, "error-empty"],
    [{ hasData: true, isPending: false, isFetching: false, isError: true }, "error-with-data"],
  ] as const)("maps %o to %s", (input, expected) => {
    expect(deriveQueryPresentation(input)).toBe(expected);
  });
});
