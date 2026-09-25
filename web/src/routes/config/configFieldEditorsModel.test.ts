import { describe, expect, it } from "vitest";

import type { ConfigEditorMeta } from "../../api/types";
import {
  collectPendingDraftLeaves,
  deriveNumberStep,
  fieldEditorDisplayText,
  isToolNameListPath,
  numberBounds,
  parseDraftLeafValue,
  resolveDraftSubtreeForSave,
  stepNumberValue,
  validateJsonText,
  validateListText,
  validateNumberText,
} from "./configFieldEditorsModel";

function meta(kind: ConfigEditorMeta["kind"], path: string, extra: Partial<ConfigEditorMeta> = {}): ConfigEditorMeta {
  return { path, label: path, hint: "", kind, badge: "", options: [], ...extra };
}

describe("validateJsonText", () => {
  it("parses valid json and rejects invalid with line/column position", () => {
    expect(validateJsonText('{"a": 1}')).toEqual({ ok: true, value: { a: 1 } });

    const raw = '{\n  "light": 500,\n}';
    const result = validateJsonText(raw);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.issue.code).toBe("jsonInvalid");
      // V8 reports the position of the trailing comma; it lands on line 3.
      expect(result.issue.line).toBe(3);
      expect(result.issue.column).toBeGreaterThan(0);
      expect(result.issue.message).toContain("JSON");
    }
  });

  it("keeps the error message when no position is available", () => {
    const result = validateJsonText("nope");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.issue.line).toBeNull();
      expect(result.issue.column).toBeNull();
      expect(result.issue.message).toBeTruthy();
    }
  });
});

describe("number validation", () => {
  it("rejects empty and non-numeric text", () => {
    const bounds = numberBounds(meta("number", "x.max_token_limit"));
    expect(validateNumberText("  ", bounds)).toEqual({ ok: false, issue: { code: "numberRequired" } });
    const invalid = validateNumberText("12e", bounds);
    expect(invalid).toEqual({ ok: false, issue: { code: "numberInvalid", value: "12e" } });
    expect(validateNumberText("42", bounds)).toEqual({ ok: true, value: 42 });
  });

  it("enforces schema bounds without inventing ranges", () => {
    const bounded = numberBounds(meta("number", "x.temp", { minimum: 0, maximum: 2 }));
    expect(validateNumberText("-1", bounded)).toEqual({ ok: false, issue: { code: "numberBelowMin", bound: 0, exclusive: false } });
    expect(validateNumberText("3", bounded)).toEqual({ ok: false, issue: { code: "numberAboveMax", bound: 2, exclusive: false } });
    expect(validateNumberText("1.5", bounded)).toEqual({ ok: true, value: 1.5 });

    const exclusive = numberBounds(meta("number", "x.limit", { exclusiveMinimum: 0 }));
    expect(validateNumberText("0", exclusive)).toEqual({ ok: false, issue: { code: "numberBelowMin", bound: 0, exclusive: true } });
    expect(validateNumberText("0.5", exclusive)).toEqual({ ok: true, value: 0.5 });

    const unbounded = numberBounds(meta("number", "x.free"));
    expect(validateNumberText("123456", unbounded)).toEqual({ ok: true, value: 123456 });
  });

  it("steps and clamps within bounds", () => {
    const bounded = numberBounds(meta("number", "x.limit", { minimum: 1000, maximum: 20000 }));
    expect(stepNumberValue(19500, bounded, 1, 1000)).toBe(20000);
    expect(stepNumberValue(1000, bounded, -1, 1000)).toBe(1000);
    expect(stepNumberValue(16000, bounded, 1, 1000)).toBe(17000);
  });

  it("derives integer steps for integer-shaped fields and 0.1 for float-shaped fields", () => {
    expect(deriveNumberStep(meta("number", "x.limit", { minimum: 1000 }), 16000)).toBe(1);
    expect(deriveNumberStep(meta("number", "x.temp", { minimum: 0, maximum: 2 }), 0.3)).toBe(0.1);
    expect(deriveNumberStep(meta("number", "x.free"), undefined)).toBe(1);
  });
});

describe("list validation", () => {
  it("treats tool whitelist paths as tool-name lists with format and duplicate errors", () => {
    expect(isToolNameListPath("context_compression.micro_compact_tool_whitelist")).toBe(true);
    expect(isToolNameListPath("network.proxy_hosts")).toBe(false);

    const result = validateListText(
      ["read_file_tool", "Grep_Search_Tool", "", "read_file_tool"].join("\n"),
      { toolNames: true },
    );
    expect(result.ok).toBe(false);
    expect(result.values).toEqual(["read_file_tool", "read_file_tool"]);
    const errors = result.issues.filter((issue) => issue.severity === "error");
    expect(errors.map((issue) => [issue.line, issue.code])).toEqual([
      [2, "listInvalidToolName"],
      [4, "listDuplicateItem"],
    ]);
    expect(result.lines.map((line) => line.line)).toEqual([1, 2, 4]);
  });

  it("only warns on blank lines and whitespace for generic lists", () => {
    const result = validateListText("  alpha , beta  \n\ngamma\n", { toolNames: false });
    expect(result.ok).toBe(true);
    expect(result.values).toEqual(["alpha , beta", "gamma"]);
    expect(result.errorCount).toBe(0);
    expect(result.issues.filter((issue) => issue.severity === "warning").map((issue) => issue.code)).toEqual([
      "listWhitespace",
      "listBlankLine",
      "listBlankLine",
    ]);
  });
});

describe("draft leaf handling", () => {
  it("formats editor display text from raw drafts or committed values", () => {
    expect(fieldEditorDisplayText("json", undefined, { a: 1 })).toBe('{\n  "a": 1\n}');
    expect(fieldEditorDisplayText("json", '{"a":', { a: 1 })).toBe('{"a":');
    expect(fieldEditorDisplayText("number", "16000", 16000)).toBe("16000");
    expect(fieldEditorDisplayText("number", undefined, 16000)).toBe("16000");
    expect(fieldEditorDisplayText("string_list", undefined, ["a", "b"])).toBe("a\nb");
    expect(fieldEditorDisplayText("text", undefined, "hello")).toBe("hello");
  });

  it("parses raw draft leaves and reports the first list error", () => {
    expect(parseDraftLeafValue(meta("number", "x.n"), "16000")).toEqual({ ok: true, value: 16000 });
    const parsed = parseDraftLeafValue(meta("string_list", "x.tool_whitelist"), "bad name!\n");
    expect(parsed.ok).toBe(false);

    const identity = parseDraftLeafValue(meta("text", "x.name"), "raw text");
    expect(identity).toEqual({ ok: true, value: "raw text" });
  });
});

describe("collectPendingDraftLeaves", () => {
  const metaMap: Record<string, ConfigEditorMeta> = {
    "s.enabled": meta("boolean", "s.enabled"),
    "s.threshold": meta("number", "s.threshold"),
    "s.summary": meta("json", "s.summary"),
    "s.whitelist": meta("string_list", "s.micro_tool_whitelist"),
    "s.name": meta("text", "s.name"),
    s: meta("object", "s"),
  };
  const metaAt = (path: string) => metaMap[path];
  const committed = { enabled: true, threshold: 16000, summary: { light: 500 }, whitelist: ["read_file_tool"], name: "agent" };

  it("collects changed leaves with normalized comparison and skips immediate kinds", () => {
    const pending = collectPendingDraftLeaves({
      draft: { enabled: false, threshold: "24000", summary: { light: 500 }, whitelist: ["read_file_tool"], name: "agent" },
      committed,
      path: "s",
      metaAt,
    });
    expect(pending.map((item) => item.path)).toEqual(["s.threshold"]);
    expect(pending[0]?.valid).toBe(true);
  });

  it("flags invalid raw drafts as pending with valid=false", () => {
    const pending = collectPendingDraftLeaves({
      draft: { enabled: true, threshold: "abc", summary: "{", whitelist: "ok_tool", name: "agent" },
      committed,
      path: "s",
      metaAt,
    });
    expect(pending.map((item) => [item.path, item.valid])).toEqual([
      ["s.threshold", false],
      ["s.summary", false],
      ["s.whitelist", true],
    ]);
  });

  it("returns nothing when the draft equals the committed tree", () => {
    const pending = collectPendingDraftLeaves({ draft: committed, committed, path: "s", metaAt });
    expect(pending).toEqual([]);
  });
});

describe("resolveDraftSubtreeForSave", () => {
  const metaMap: Record<string, ConfigEditorMeta> = {
    "s.threshold": meta("number", "s.threshold", { minimum: 1000 }),
    "s.summary": meta("json", "s.summary"),
    "s.whitelist": meta("string_list", "s.micro_tool_whitelist"),
    s: meta("object", "s"),
  };
  const metaAt = (path: string) => metaMap[path];

  it("parses raw leaves into runtime values on save", () => {
    const result = resolveDraftSubtreeForSave({
      draft: { threshold: "16000", summary: '{"light":500}', whitelist: "read_file_tool\ncli_tool" },
      path: "s",
      metaAt,
    });
    expect(result).toEqual({
      ok: true,
      value: { threshold: 16000, summary: { light: 500 }, whitelist: ["read_file_tool", "cli_tool"] },
    });
  });

  it("blocks save with the offending path when any leaf is invalid", () => {
    const result = resolveDraftSubtreeForSave({
      draft: { threshold: "12", summary: "{", whitelist: "ok_tool" },
      path: "s",
      metaAt,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.invalid.map((item) => item.path).sort()).toEqual(["s.summary", "s.threshold"]);
    }
  });
});
