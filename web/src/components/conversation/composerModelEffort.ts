import type { SessionLlmModelOption, SessionModelSelection } from "../../api/types";

/** Stable empty list so a missing choices payload does not change identity every render. */
export const EMPTY_COMPOSER_MODEL_CHOICES: SessionLlmModelOption[] = [];

/** Canonical id stored on a per-session model pin. modelRef wins over the library id. */
export function composerModelChoiceId(model: SessionLlmModelOption): string {
  return model.modelRef || model.modelId;
}

export function findComposerModelChoice(
  choices: readonly SessionLlmModelOption[],
  modelId: string,
): SessionLlmModelOption | undefined {
  const id = modelId.trim();
  if (!id) return undefined;
  return choices.find((choice) => choice.modelRef === id || choice.modelId === id);
}

export function modelMatchesComposerId(model: SessionLlmModelOption, modelId: string): boolean {
  const id = modelId.trim();
  return Boolean(id) && (model.modelRef === id || model.modelId === id);
}

/** True when the pin names a model other than the session default. */
export function composerModelLeavesSessionDefault(
  sessionDefaultModelId: string,
  selection: SessionModelSelection | null,
): boolean {
  const selected = selection?.modelId?.trim() || "";
  if (!selected || !sessionDefaultModelId.trim()) return false;
  return selected !== sessionDefaultModelId.trim();
}

/**
 * Effort that belongs to `model`. Keep the previous level when that model
 * allows it; otherwise use the model's own default, then its first level.
 * Empty when the model has no levels.
 */
export function resolveComposerEffortForModel(
  previousEffort: string,
  model: SessionLlmModelOption | null | undefined,
): string {
  const values = model?.reasoningEffortValues ?? [];
  if (!values.length) return "";
  const previous = previousEffort.trim();
  if (previous && values.includes(previous)) return previous;
  const fallback = model?.defaultReasoningEffort?.trim() || "";
  if (fallback && values.includes(fallback)) return fallback;
  return values[0] ?? "";
}

/** Level shown on the thinking control for the model the next send will use. */
export function displayedComposerEffort(input: {
  sessionDefaultModelId: string;
  sessionEffort: string;
  selection: SessionModelSelection | null;
  model: SessionLlmModelOption | null;
}): string {
  const pinned = composerModelLeavesSessionDefault(input.sessionDefaultModelId, input.selection)
    ? input.selection?.reasoningEffort || input.sessionEffort
    : input.sessionEffort;
  return resolveComposerEffortForModel(pinned, input.model);
}

export function selectionsEqual(
  left: SessionModelSelection | null,
  right: SessionModelSelection | null,
): boolean {
  if (left === right) return true;
  if (!left || !right) return !left && !right;
  return left.modelId === right.modelId
    && (left.reasoningEffort || "") === (right.reasoningEffort || "");
}

/**
 * Model menu result. Following the session default clears the pin.
 * A different model carries a level that model actually supports.
 */
export function selectionAfterModelPick(input: {
  sessionDefaultModelId: string;
  sessionEffort: string;
  previousSelection: SessionModelSelection | null;
  previousModel: SessionLlmModelOption | null;
  next: SessionModelSelection | null;
  choices: readonly SessionLlmModelOption[];
}): SessionModelSelection | null {
  const requested = input.next?.modelId?.trim() || "";
  if (!requested) return null;
  const nextModel = findComposerModelChoice(input.choices, requested);
  if (!nextModel) return { modelId: requested };
  if (modelMatchesComposerId(nextModel, input.sessionDefaultModelId)) return null;
  const previousEffort = displayedComposerEffort({
    sessionDefaultModelId: input.sessionDefaultModelId,
    sessionEffort: input.sessionEffort,
    selection: input.previousSelection,
    model: input.previousModel,
  });
  const effort = resolveComposerEffortForModel(previousEffort, nextModel);
  const modelId = composerModelChoiceId(nextModel);
  return effort ? { modelId, reasoningEffort: effort } : { modelId };
}

/**
 * Repair a stored pin so the saved level matches the selected model's contract.
 * Unknown ids are left alone until the choice list can identify them.
 */
export function normalizeStoredComposerModelSelection(input: {
  sessionDefaultModelId: string;
  sessionEffort: string;
  selection: SessionModelSelection | null;
  choices: readonly SessionLlmModelOption[];
}): SessionModelSelection | null {
  if (!input.selection?.modelId) return null;
  const model = findComposerModelChoice(input.choices, input.selection.modelId);
  if (!model) return input.selection;
  if (modelMatchesComposerId(model, input.sessionDefaultModelId)) return null;
  const modelId = composerModelChoiceId(model);
  const effort = resolveComposerEffortForModel(
    input.selection.reasoningEffort || input.sessionEffort,
    model,
  );
  return effort ? { modelId, reasoningEffort: effort } : { modelId };
}

export type ComposerModelChoiceGroup = {
  key: string;
  label: string;
  choices: SessionLlmModelOption[];
};

/** Preserve choice order and group by provider, the way the model menu is drawn. */
export function groupComposerModelChoices(
  choices: readonly SessionLlmModelOption[],
): ComposerModelChoiceGroup[] {
  const groups: ComposerModelChoiceGroup[] = [];
  for (const choice of choices) {
    const key = choice.providerId || choice.providerLabel || "provider";
    const label = choice.providerLabel || choice.providerId || key;
    const existing = groups.find((group) => group.key === key);
    if (existing) {
      existing.choices.push(choice);
    } else {
      groups.push({ key, label, choices: [choice] });
    }
  }
  return groups;
}
