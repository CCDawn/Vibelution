import { clonePublicConfig, type PublicConfigShape } from "../configRouteLogic";
import {
  applyModelEntryEdits,
  EDITABLE_MODEL_FIELDS,
  type EditableModelField,
  type ModelFieldEdits,
} from "./modelEditableFields";

/** Unsaved whitelist edits, keyed by the stable provider/model reference. */
export type ModelEditorDrafts = Record<string, ModelFieldEdits>;

const NUMBER_FIELDS: ReadonlySet<EditableModelField> = new Set([
  "context_window", "temperature", "max_output_tokens", "timeout",
]);
const BOOLEAN_FIELDS: ReadonlySet<EditableModelField> = new Set(["enabled", "streaming"]);
const DECIMAL_NUMBER = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
const hasOwn = (value: object, key: string) => Object.prototype.hasOwnProperty.call(value, key);

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Match the pinned-model schema without normalizing incomplete input. */
export function modelEditorFieldIsValid(field: EditableModelField, value: unknown): boolean {
  if (BOOLEAN_FIELDS.has(field)) return typeof value === "boolean";
  if (typeof value !== "string") return false;
  const text = value.trim();
  if (NUMBER_FIELDS.has(field)) {
    if (!text) return true; // An empty numeric override restores inheritance.
    if (!DECIMAL_NUMBER.test(text)) return false;
    const number = Number(text);
    if (!Number.isFinite(number)) return false;
    return field === "temperature"
      ? number >= 0 && number <= 2
      : Number.isSafeInteger(number) && number > 0;
  }
  // applyModelEntryEdits deliberately ignores blank identities. Do not let a
  // save appear successful while dropping such an edit.
  return field === "default_reasoning_effort" || text.length > 0;
}

export function modelEditorDraftIsValid(edits: ModelFieldEdits): boolean {
  return EDITABLE_MODEL_FIELDS.every((field) => !hasOwn(edits, field) || modelEditorFieldIsValid(field, edits[field]));
}

function hasEdits(edits: ModelFieldEdits): boolean {
  return EDITABLE_MODEL_FIELDS.some((field) => hasOwn(edits, field));
}

/** Number of models with pending whitelist edits, rather than number of fields. */
export function modelEditorDraftCount(drafts: ModelEditorDrafts): number {
  return Object.values(drafts).filter(hasEdits).length;
}

export function modelEditorDraftsAreValid(drafts: ModelEditorDrafts): boolean {
  return Object.values(drafts).every(modelEditorDraftIsValid);
}

/**
 * Fold page drafts into a private copy of the config. The first slash separates
 * provider from model key; a model key may itself contain slashes. The existing
 * whitelist helper remains the only writer of model-entry fields.
 */
export function foldModelEditorDrafts(config: PublicConfigShape, drafts: ModelEditorDrafts): PublicConfigShape {
  const next = clonePublicConfig(config);
  const llm = isRecord(next.llm) ? next.llm : undefined;
  const providers = llm && isRecord(llm.providers) ? llm.providers : undefined;

  for (const [modelRef, edits] of Object.entries(drafts)) {
    if (!hasEdits(edits)) continue;
    const separator = modelRef.indexOf("/");
    if (separator <= 0 || separator === modelRef.length - 1) {
      throw new Error(`Invalid model reference: ${modelRef}`);
    }
    const providerId = modelRef.slice(0, separator);
    const modelKey = modelRef.slice(separator + 1);
    const provider = providers && hasOwn(providers, providerId) ? providers[providerId] : undefined;
    if (!isRecord(provider)) throw new Error(`Missing provider for model draft: ${modelRef}`);
    const models = isRecord(provider.models) ? provider.models : undefined;
    const entry = models && hasOwn(models, modelKey) ? models[modelKey] : undefined;
    if (!models || !isRecord(entry)) throw new Error(`Missing model for draft: ${modelRef}`);
    if (!modelEditorDraftIsValid(edits)) throw new Error(`Invalid model draft: ${modelRef}`);
    models[modelKey] = applyModelEntryEdits(entry, edits);
  }
  return next;
}
