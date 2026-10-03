/**
 * Model-entry editable-field whitelist (wave 3 governance, path B).
 *
 * The settings model library lets operators hand-edit pinned model entries.
 * Protocol-layer fields (wire protocol, interaction contract, reasoning
 * adapters, ...) are supplied by built-in rules and discovery; hand-editing
 * them breaks protocol combinations, so the editor exposes a small whitelist
 * of leaf fields and renders protocol-layer fields read-only with a
 * 「由协议规则供给」note. This module is the single source for both the
 * whitelist and the pure edit application, so the form and the draft write
 * action cannot drift apart.
 *
 * Field paths (schema v2 pinned entry `llm.providers.<id>.models.<key>`):
 * - entry-level: label, upstream_id, context_window, enabled
 * - `defaults.*` runtime overrides: temperature, max_output_tokens, timeout,
 *   streaming, default_reasoning_effort
 *
 * Deliberately NOT whitelisted:
 * - api_key_env / api_key / credential_ref: schema v2 credential ownership
 *   (config/llm_projection.py) rejects credentials on model entries; provider
 *   credentials are edited on the provider connection row instead.
 * - every protocol-layer field in PROTOCOL_LAYER_FIELDS: rule/discovery
 *   supplied, read-only display only.
 */

/** Editable leaf fields, in stable display order. Single source of truth. */
export const EDITABLE_MODEL_FIELDS = [
  "label",
  "model",
  "enabled",
  "context_window",
  "temperature",
  "max_output_tokens",
  "timeout",
  "streaming",
  "default_reasoning_effort",
] as const;

export type EditableModelField = (typeof EDITABLE_MODEL_FIELDS)[number];

const EDITABLE_MODEL_FIELD_SET: ReadonlySet<string> = new Set(EDITABLE_MODEL_FIELDS);

/**
 * Protocol-layer fields: supplied by built-in rules / discovery. Never
 * editable from the settings UI; shown read-only with the「由协议规则供给」
 * note when present.
 */
export const PROTOCOL_LAYER_FIELDS = [
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
] as const;

export type ProtocolLayerField = (typeof PROTOCOL_LAYER_FIELDS)[number];

const PROTOCOL_LAYER_FIELD_SET: ReadonlySet<string> = new Set(PROTOCOL_LAYER_FIELDS);

export function isEditableModelField(field: string): boolean {
  return EDITABLE_MODEL_FIELD_SET.has(field);
}

export function isProtocolLayerField(field: string): boolean {
  return PROTOCOL_LAYER_FIELD_SET.has(field);
}

/** Raw form value for one whitelist field (inputs are string-or-boolean). */
export type ModelFieldEdits = Partial<Record<EditableModelField, string | boolean>>;

/** Current form values derived from a pinned entry (empty strings = unset). */
export type ModelFieldValues = {
  label: string;
  model: string;
  context_window: string;
  temperature: string;
  max_output_tokens: string;
  timeout: string;
  default_reasoning_effort: string;
  enabled: boolean;
  streaming: boolean;
};

type FieldTarget = { container: "entry" | "defaults"; key: string };

const FIELD_TARGETS: Record<EditableModelField, FieldTarget> = {
  label: { container: "entry", key: "label" },
  model: { container: "entry", key: "upstream_id" },
  enabled: { container: "entry", key: "enabled" },
  context_window: { container: "entry", key: "context_window" },
  temperature: { container: "defaults", key: "temperature" },
  max_output_tokens: { container: "defaults", key: "max_output_tokens" },
  timeout: { container: "defaults", key: "timeout" },
  streaming: { container: "defaults", key: "streaming" },
  default_reasoning_effort: { container: "defaults", key: "default_reasoning_effort" },
};

const NUMBER_FIELDS: ReadonlySet<EditableModelField> = new Set([
  "context_window",
  "temperature",
  "max_output_tokens",
  "timeout",
]);
const BOOLEAN_FIELDS: ReadonlySet<EditableModelField> = new Set(["enabled", "streaming"]);

export function isEditableModelFieldValue(value: unknown): value is string | boolean {
  return typeof value === "string" || typeof value === "boolean";
}

/** Read current entry values into the form shape ("" = unset for strings/numbers). */
export function buildModelFieldValues(entry: unknown, fallbacks: {
  label?: string;
  upstreamId?: string;
} = {}): ModelFieldValues {
  const source = entry && typeof entry === "object" && !Array.isArray(entry)
    ? entry as Record<string, unknown>
    : {};
  const defaults = source.defaults && typeof source.defaults === "object" && !Array.isArray(source.defaults)
    ? source.defaults as Record<string, unknown>
    : {};
  const read = (field: EditableModelField): string | boolean => {
    const target = FIELD_TARGETS[field];
    const raw = target.container === "entry" ? source[target.key] : defaults[target.key];
    if (BOOLEAN_FIELDS.has(field)) {
      // Absent booleans fall back to runtime defaults (entries default enabled
      // and streaming on).
      return typeof raw === "boolean" ? raw : true;
    }
    const text = typeof raw === "string" || typeof raw === "number" ? String(raw).trim() : "";
    if (!text && field === "label") return fallbacks.label ?? "";
    if (!text && field === "model") return fallbacks.upstreamId ?? "";
    return text;
  };
  return {
    label: read("label") as string,
    model: read("model") as string,
    context_window: read("context_window") as string,
    temperature: read("temperature") as string,
    max_output_tokens: read("max_output_tokens") as string,
    timeout: read("timeout") as string,
    default_reasoning_effort: read("default_reasoning_effort") as string,
    enabled: read("enabled") as boolean,
    streaming: read("streaming") as boolean,
  };
}

/** Protocol-layer facts present on the entry, for read-only display only. */
export function extractProtocolFacts(entry: unknown): Array<{
  field: ProtocolLayerField;
  value: string;
}> {
  const source = entry && typeof entry === "object" && !Array.isArray(entry)
    ? entry as Record<string, unknown>
    : {};
  const defaults = source.defaults && typeof source.defaults === "object" && !Array.isArray(source.defaults)
    ? source.defaults as Record<string, unknown>
    : {};
  const facts: Array<{ field: ProtocolLayerField; value: string }> = [];
  for (const field of PROTOCOL_LAYER_FIELDS) {
    const raw = field in source ? source[field] : defaults[field];
    let text = "";
    if (typeof raw === "string" || typeof raw === "number" || typeof raw === "boolean") {
      text = String(raw);
    } else if (Array.isArray(raw)) {
      text = raw.map((item) => (typeof item === "string" ? item : JSON.stringify(item))).join(" / ");
    } else if (raw && typeof raw === "object") {
      text = JSON.stringify(raw);
    }
    if (text.trim()) {
      facts.push({ field, value: text.trim() });
    }
  }
  return facts;
}

function parseNumberEdit(value: string): number | null | undefined {
  const text = value.trim();
  if (!text) return null; // explicit clear
  const parsed = Number(text);
  if (!Number.isFinite(parsed)) return undefined; // invalid → keep existing
  return parsed;
}

/**
 * Apply whitelist edits to a pinned entry. Only whitelist paths are touched;
 * protocol-layer fields, capabilities, and unknown keys are preserved
 * verbatim. Invalid numeric edits keep the existing value; empty numeric
 * edits clear the key (fall back to rule/discovery-supplied values).
 */
export function applyModelEntryEdits(
  entry: unknown,
  edits: ModelFieldEdits,
): Record<string, unknown> {
  const next: Record<string, unknown> = entry && typeof entry === "object" && !Array.isArray(entry)
    ? { ...(entry as Record<string, unknown>) }
    : {};
  const defaultsSource = next.defaults && typeof next.defaults === "object" && !Array.isArray(next.defaults)
    ? next.defaults as Record<string, unknown>
    : {};
  const defaults: Record<string, unknown> = { ...defaultsSource };
  const defaultsChanged = new Set<string>();

  for (const field of EDITABLE_MODEL_FIELDS) {
    if (!isEditableModelFieldValue(edits[field])) continue;
    const edit = edits[field];
    const target = FIELD_TARGETS[field];
    const current = target.container === "entry" ? next[target.key] : defaults[target.key];

    if (BOOLEAN_FIELDS.has(field)) {
      if (typeof edit !== "boolean" || edit === current) continue;
      if (target.container === "entry") next[target.key] = edit;
      else {
        defaults[target.key] = edit;
        defaultsChanged.add(target.key);
      }
      continue;
    }

    if (typeof edit !== "string") continue;
    if (NUMBER_FIELDS.has(field)) {
      const parsed = parseNumberEdit(edit);
      if (parsed === undefined) continue; // invalid → keep existing
      if (parsed === null) {
        // explicit clear → drop the key so rule/discovery values apply again
        if (target.container === "entry") delete next[target.key];
        else {
          delete defaults[target.key];
          defaultsChanged.add(target.key);
        }
        continue;
      }
      if (parsed === current) continue;
      if (target.container === "entry") next[target.key] = parsed;
      else {
        defaults[target.key] = parsed;
        defaultsChanged.add(target.key);
      }
      continue;
    }

    const text = edit.trim();
    // Identity fields (label / model) must stay non-empty: blank edits keep
    // the existing value. The reasoning-effort select uses "" as an explicit
    //「跟随协议规则」clear.
    if (!text) {
      if (field !== "default_reasoning_effort") continue;
      if (target.key in defaults) {
        delete defaults[target.key];
        defaultsChanged.add(target.key);
      }
      continue;
    }
    if (text === current) continue;
    if (target.container === "entry") next[target.key] = text;
    else {
      defaults[target.key] = text;
      defaultsChanged.add(target.key);
    }
  }

  if (defaultsChanged.size) {
    next.defaults = defaults;
  }
  return next;
}
