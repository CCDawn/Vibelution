import { describe, expect, it } from "vitest";

import {
  ASSISTANT_ACTION_LABELS,
  assistantActionFromToolArguments,
  assistantActionKindForTool,
  assistantActionLabel,
  assistantActionLabelForTool,
} from "./assistantActionLabels";

describe("assistant action presentation metadata", () => {
  it("keeps approval label pairs and conversation labels on the same curated actions", () => {
    for (const [action, labels] of Object.entries(ASSISTANT_ACTION_LABELS)) {
      expect(labels).toHaveLength(2);
      expect(assistantActionLabel(action, "zh")).toBe(labels[0]);
      expect(assistantActionLabel(action, "en")).toBe(labels[1]);
      expect(assistantActionKindForTool("personal_assistant_action_tool", { action })).not.toBeNull();
    }
  });

  it.each(["personal_assistant_action_tool", "personal_assistant_manage_tool"])(
    "normalizes only real action arguments for %s",
    (toolName) => {
      expect(assistantActionFromToolArguments(toolName, [{}, { action: " SOURCE-SEARCH " }]))
        .toBe("source_search");
      expect(assistantActionLabelForTool(toolName, { action: " SOURCE-SEARCH " }, "en"))
        .toBe("Search source");
      expect(assistantActionFromToolArguments(toolName, { action: "future_action" })).toBe("future_action");
      expect(assistantActionKindForTool(toolName, { action: "future_action" })).toBeNull();
      for (const args of [null, {}, { action: 42 }, { action: " " }, '{"action":"source_read"}']) {
        expect(assistantActionFromToolArguments(toolName, args)).toBeNull();
      }
    },
  );

  it("does not treat inherited object properties or actions on other tools as known actions", () => {
    for (const action of ["constructor", "__proto__", "toString"]) {
      expect(assistantActionLabel(action)).toBeNull();
      expect(assistantActionKindForTool("personal_assistant_action_tool", { action })).toBeNull();
    }
    expect(assistantActionFromToolArguments("read_file_tool", { action: "source_search" })).toBeNull();
  });
});
