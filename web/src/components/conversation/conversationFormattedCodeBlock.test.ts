import { describe, expect, it } from "vitest";

import { formattedCodeBlockContent } from "./conversationFormattedCodeBlock";

describe("conversationFormattedCodeBlock", () => {
  it("pretty-prints json language blocks and leaves others untouched", () => {
    expect(formattedCodeBlockContent('{"a":1}', "json")).toBe('{\n  "a": 1\n}');
    expect(formattedCodeBlockContent("not-json", "json")).toBe("not-json");
    expect(formattedCodeBlockContent('{"a":1}', "ts")).toBe('{"a":1}');
    expect(formattedCodeBlockContent("{bad", "json")).toBe("{bad");
  });
});
