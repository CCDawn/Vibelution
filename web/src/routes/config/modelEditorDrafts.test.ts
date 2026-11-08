import { describe, expect, it } from "vitest";

import type { PublicConfigShape } from "../configRouteLogic";
import type { ModelFieldEdits } from "./modelEditableFields";
import {
  foldModelEditorDrafts,
  modelEditorDraftCount,
  modelEditorDraftIsValid,
  modelEditorDraftsAreValid,
} from "./modelEditorDrafts";

function config(): PublicConfigShape {
  return {
    unknownRoot: { keep: [1, "unchanged"] },
    ui: { theme: "dark" },
    llm: {
      mode: "existing",
      providers: {
        local: {
          api_key_env: "EXISTING_KEY_ENV", auth: "oauth:existing", base_url: "https://existing.example",
          protocols: { preferred: "responses" },
          models: {
            "stable-id": {
              upstream_id: "old-upstream", label: "Existing", context_window: 128000,
              wire_protocol: "responses", interaction_contract: "tool_chat",
              capabilities: { image_input: { value: "supported" } }, extraEntry: { untouched: true },
              defaults: { temperature: 0.7, timeout: 60, streaming: true, extraDefault: ["kept"] },
            },
            "org/model": { upstream_id: "org/model", defaults: { max_output_tokens: 1024 } },
          },
        },
        other: { models: { second: { upstream_id: "second", enabled: true } } },
      },
    },
  };
}

function model(source: PublicConfigShape, provider = "local", key = "stable-id"): Record<string, unknown> {
  const providers = (source.llm as { providers: Record<string, { models: Record<string, Record<string, unknown>> }> }).providers;
  return providers[provider].models[key];
}

describe("page model-editor drafts", () => {
  it("folds only editable leaves while preserving stable IDs, unknown fields and all other config", () => {
    const original = config();
    const before = structuredClone(original);
    const next = foldModelEditorDrafts(original, {
      "local/stable-id": { model: "new-upstream", label: "Renamed", temperature: "0.2", context_window: "262144" },
    });
    expect(model(next)).toEqual({
      ...model(before), upstream_id: "new-upstream", label: "Renamed", context_window: 262144,
      defaults: { ...(model(before).defaults as object), temperature: 0.2 },
    });
    expect(next).toEqual({
      ...before,
      llm: { ...(before.llm as object), providers: {
        ...((before.llm as { providers: object }).providers),
        local: {
          ...(before.llm as { providers: { local: object } }).providers.local,
          models: { "stable-id": model(next), "org/model": model(before, "local", "org/model") },
        },
      } },
    });
    expect(original).toEqual(before);
    expect(next).not.toBe(original);
  });

  it("cannot edit provider credentials, protocol facts or model capability through an untrusted edit map", () => {
    const original = config();
    const edits = {
      label: "Allowed", api_key_env: "REPLACED", auth: "replacement", wire_protocol: "other",
      capabilities: "replaced", upstream_id: "bypass",
    } as unknown as ModelFieldEdits;
    const next = foldModelEditorDrafts(original, { "local/stable-id": edits });
    expect(model(next)).toEqual({ ...model(original), label: "Allowed" });
    expect((next.llm as { providers: { local: { api_key_env: string; auth: string } } }).providers.local)
      .toMatchObject({ api_key_env: "EXISTING_KEY_ENV", auth: "oauth:existing" });
  });

  it("folds several providers and splits model references only at the first slash", () => {
    const next = foldModelEditorDrafts(config(), {
      "local/stable-id": { enabled: false },
      "local/org/model": { max_output_tokens: "4096" },
      "other/second": { label: "Second label" },
    });
    expect(model(next).enabled).toBe(false);
    expect(model(next, "local", "org/model").defaults).toEqual({ max_output_tokens: 4096 });
    expect(model(next, "other", "second").label).toBe("Second label");
  });

  it("clears optional numeric and reasoning overrides without materializing unrelated defaults", () => {
    const original = config();
    (model(original).defaults as Record<string, unknown>).default_reasoning_effort = "high";
    const next = foldModelEditorDrafts(original, {
      "local/stable-id": { context_window: "", temperature: " ", default_reasoning_effort: "" },
      "other/second": { label: "Other" },
    });
    expect(model(next)).not.toHaveProperty("context_window");
    expect(model(next).defaults).toEqual({ timeout: 60, streaming: true, extraDefault: ["kept"] });
    expect(model(next, "other", "second")).not.toHaveProperty("defaults");
  });

  it.each([
    { temperature: "invalid" }, { temperature: "Infinity" }, { temperature: "1e" }, { temperature: "0x1" },
    { temperature: "-0.1" }, { temperature: "2.1" }, { timeout: "0" }, { timeout: "1.5" },
    { context_window: "-1" }, { max_output_tokens: "NaN" }, { model: " " }, { label: "" },
    { enabled: "false" },
  ] satisfies ModelFieldEdits[])("rejects invalid raw edits without mutating the config: %j", (edits) => {
    const original = config();
    const before = structuredClone(original);
    expect(modelEditorDraftIsValid(edits)).toBe(false);
    expect(() => foldModelEditorDrafts(original, { "local/stable-id": edits })).toThrow("Invalid model draft");
    expect(original).toEqual(before);
  });

  it.each(["absent/stable-id", "local/absent", "local", "/stable-id", "local/"])("rejects missing or malformed targets: %s", (ref) => {
    const original = config();
    expect(() => foldModelEditorDrafts(original, { [ref]: { label: "New" } })).toThrow();
    expect(original).toEqual(config());
  });

  it("treats empty draft maps as no changes and counts models, including explicit clears", () => {
    const original = config();
    expect(foldModelEditorDrafts(original, { "local/stable-id": {} })).toEqual(original);
    const drafts = { "local/stable-id": { label: "New", timeout: "90" }, "local/org/model": {}, "other/second": { context_window: "" } };
    expect(modelEditorDraftCount(drafts)).toBe(2);
    expect(modelEditorDraftsAreValid(drafts)).toBe(true);
    expect(modelEditorDraftsAreValid({ "local/stable-id": { timeout: "bad" } })).toBe(false);
    expect(modelEditorDraftIsValid({ temperature: "0", timeout: "1e2", enabled: false })).toBe(true);
  });
});
