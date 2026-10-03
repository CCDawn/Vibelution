import { describe, expect, it } from "vitest";

import {
  applyModelEntryEdits,
  buildModelFieldValues,
  EDITABLE_MODEL_FIELDS,
  extractProtocolFacts,
  isEditableModelField,
  isProtocolLayerField,
  PROTOCOL_LAYER_FIELDS,
} from "./modelEditableFields";

/** Pinned entry fixture mirroring `llm.providers.<id>.models.<key>`. */
function pinnedEntry(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    upstream_id: "gpt-5.2",
    label: "GPT 5.2",
    enabled: true,
    context_window: 400000,
    wire_protocol: "responses",
    interaction_contract: "tool_chat",
    model_protocol: "openai",
    capabilities: { image_input: { value: "supported" } },
    defaults: {
      reasoning_effort_values: ["low", "medium", "high"],
      reasoning_effort_adapter: "reasoning_object",
      default_reasoning_effort: "medium",
      temperature: 0.7,
      streaming: true,
    },
    ...overrides,
  };
}

describe("modelEditableFields whitelist", () => {
  it("keeps the editable whitelist stable and disjoint from protocol-layer fields", () => {
    // Set-stability pin: the whitelist is the wave-3 governance contract; any
    // change here is a user-visible editor surface change and must be explicit.
    expect([...EDITABLE_MODEL_FIELDS]).toEqual([
      "label",
      "model",
      "enabled",
      "context_window",
      "temperature",
      "max_output_tokens",
      "timeout",
      "streaming",
      "default_reasoning_effort",
    ]);
    expect([...PROTOCOL_LAYER_FIELDS]).toEqual([
      "model_protocol",
      "wire_protocol",
      "interaction_contract",
      "compatibility",
      "reasoning_effort_adapter",
      "reasoning_effort_values",
      "reasoning_state_field",
      "thinking_type",
      "thinking_display",
      "prompt_cache",
    ]);
    for (const field of EDITABLE_MODEL_FIELDS) {
      expect(isProtocolLayerField(field)).toBe(false);
      expect(isEditableModelField(field)).toBe(true);
    }
    for (const field of PROTOCOL_LAYER_FIELDS) {
      expect(isEditableModelField(field)).toBe(false);
      expect(isProtocolLayerField(field)).toBe(true);
    }
    // Credentials never belong on schema-v2 model entries (credential ownership
    // gate in config/llm_projection.py), so the whitelist must not admit them.
    for (const credentialField of ["api_key", "api_key_env", "credential_ref"]) {
      expect(isEditableModelField(credentialField)).toBe(false);
    }
  });

  it("builds form values from entry and defaults with fallbacks for identity", () => {
    const values = buildModelFieldValues(pinnedEntry(), { label: "fallback", upstreamId: "fb" });
    expect(values).toEqual({
      label: "GPT 5.2",
      model: "gpt-5.2",
      enabled: true,
      context_window: "400000",
      temperature: "0.7",
      max_output_tokens: "",
      timeout: "",
      streaming: true,
      default_reasoning_effort: "medium",
    });
    // Missing entry: booleans fall back to runtime defaults, identity falls back.
    const empty = buildModelFieldValues(undefined, { label: "fallback", upstreamId: "fb" });
    expect(empty.label).toBe("fallback");
    expect(empty.model).toBe("fb");
    expect(empty.enabled).toBe(true);
    expect(empty.streaming).toBe(true);
  });

  it("applies only whitelist edits and preserves protocol-layer fields verbatim", () => {
    const entry = pinnedEntry();
    const next = applyModelEntryEdits(entry, {
      label: "GPT 5.2 fast",
      model: "gpt-5.2-turbo",
      context_window: "262144",
      temperature: "0.2",
      max_output_tokens: "8192",
      timeout: "120",
      streaming: false,
      enabled: false,
      default_reasoning_effort: "high",
    });
    expect(next).toEqual({
      upstream_id: "gpt-5.2-turbo",
      label: "GPT 5.2 fast",
      enabled: false,
      context_window: 262144,
      wire_protocol: "responses",
      interaction_contract: "tool_chat",
      model_protocol: "openai",
      capabilities: { image_input: { value: "supported" } },
      defaults: {
        reasoning_effort_values: ["low", "medium", "high"],
        reasoning_effort_adapter: "reasoning_object",
        default_reasoning_effort: "high",
        temperature: 0.2,
        streaming: false,
        max_output_tokens: 8192,
        timeout: 120,
      },
    });
    // Source entry untouched.
    expect(entry.defaults).toHaveProperty("temperature", 0.7);
  });

  it("ignores non-whitelist edit keys even when a caller sends them", () => {
    const entry = pinnedEntry();
    const next = applyModelEntryEdits(entry, {
      // @ts-expect-error — protocol fields are not valid edits; the gate must drop them.
      wire_protocol: "chat_completions",
      // @ts-expect-error — credentials are never editable on model entries.
      api_key_env: "EVIL_KEY",
    } as Record<string, string>);
    expect(next.wire_protocol).toBe("responses");
    expect(next.api_key_env).toBeUndefined();
    expect(next.defaults).toEqual(entry.defaults);
  });

  it("clears numeric fields on empty edits and keeps existing values on invalid ones", () => {
    const next = applyModelEntryEdits(pinnedEntry(), {
      context_window: "",
      temperature: "not-a-number",
      max_output_tokens: "",
    });
    expect(next).not.toHaveProperty("context_window");
    expect(next.defaults).toHaveProperty("temperature", 0.7);
    expect(next.defaults).not.toHaveProperty("max_output_tokens");
  });

  it("keeps defaults when clearing a defaults field that carries protocol keys", () => {
    const next = applyModelEntryEdits(pinnedEntry(), { default_reasoning_effort: "" });
    expect(next.defaults).toEqual({
      reasoning_effort_values: ["low", "medium", "high"],
      reasoning_effort_adapter: "reasoning_object",
      temperature: 0.7,
      streaming: true,
    });
  });

  it("creates defaults only when a defaults-scoped field actually changes", () => {
    const plain = applyModelEntryEdits({ upstream_id: "m" }, { label: "M" });
    expect(plain).toEqual({ upstream_id: "m", label: "M" });
    const withDefaults = applyModelEntryEdits({ upstream_id: "m" }, { label: "M", streaming: false });
    expect(withDefaults.defaults).toEqual({ streaming: false });
  });

  it("skips edits equal to the current value (no phantom writes)", () => {
    const entry = pinnedEntry();
    const next = applyModelEntryEdits(entry, {
      label: "GPT 5.2",
      model: "gpt-5.2",
      temperature: "0.7",
      streaming: true,
      enabled: true,
    });
    expect(next).toEqual(entry);
  });

  it("extracts only present protocol-layer facts for read-only display", () => {
    const facts = extractProtocolFacts(pinnedEntry());
    expect(facts).toEqual([
      { field: "model_protocol", value: "openai" },
      { field: "wire_protocol", value: "responses" },
      { field: "interaction_contract", value: "tool_chat" },
      { field: "reasoning_effort_adapter", value: "reasoning_object" },
      { field: "reasoning_effort_values", value: "low / medium / high" },
    ]);
    expect(extractProtocolFacts({ upstream_id: "m" })).toEqual([]);
    expect(extractProtocolFacts(undefined)).toEqual([]);
  });
});
