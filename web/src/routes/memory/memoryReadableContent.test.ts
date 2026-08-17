import { describe, expect, it } from "vitest";

import { humanizeMemoryFieldLabel, toReadableMemoryBlocks } from "./memoryReadableContent";

describe("memoryReadableContent", () => {
  it("turns JSON objects into labeled fields instead of a raw dump", () => {
    expect(toReadableMemoryBlocks('{"title":"Keep the rail","summary":"Do not dump JSON"}')).toEqual([
      {
        kind: "fields",
        entries: [
          { label: "title", value: "Keep the rail" },
          { label: "summary", value: "Do not dump JSON" },
        ],
      },
    ]);
  });

  it("turns JSON string arrays into lists", () => {
    expect(toReadableMemoryBlocks('["one","two"]')).toEqual([
      { kind: "list", items: ["one", "two"] },
    ]);
  });

  it("unwraps fenced JSON and keeps ordinary prose", () => {
    expect(toReadableMemoryBlocks('```json\n{"note":"plain"}\n```')).toEqual([
      { kind: "fields", entries: [{ label: "note", value: "plain" }] },
    ]);
    expect(toReadableMemoryBlocks("Agent prefers short answers.")).toEqual([
      { kind: "paragraph", text: "Agent prefers short answers." },
    ]);
  });

  it("humanizes camelCase keys", () => {
    expect(humanizeMemoryFieldLabel("privateFileCount")).toBe("private File Count");
  });
});
