import { describe, expect, it } from "vitest";

import { conversationOperationIconKind } from "./conversationOperationIconModel";

describe("conversationOperationIconModel", () => {
  it("classifies operation icon kinds from kind and label", () => {
    expect(conversationOperationIconKind("thought", "anything")).toBe("thought");
    expect(conversationOperationIconKind("mental", "x")).toBe("mental");
    expect(conversationOperationIconKind("tool", "web_search")).toBe("search");
    expect(conversationOperationIconKind("tool", "open https")).toBe("link");
    expect(conversationOperationIconKind("tool", "run npm test")).toBe("terminal");
    expect(conversationOperationIconKind("tool", "write_file")).toBe("tool");
  });
});
