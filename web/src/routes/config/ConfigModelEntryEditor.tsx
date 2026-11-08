import { useMemo, useState } from "react";

import type { ConfigCatalogModel } from "../../api/types";
import { VActionGroup, VButton, VInput, VStringSelect, VSwitch } from "../../components/vui";
import styles from "./ConfigModelEntryEditor.styles";
import type { ConfigCopy } from "./configCopy";
import {
  buildModelFieldValues,
  EDITABLE_MODEL_FIELDS,
  type EditableModelField,
  type ModelFieldEdits,
  type ModelFieldValues,
} from "./modelEditableFields";
import { modelEditorDraftIsValid, modelEditorFieldIsValid } from "./modelEditorDrafts";

export type ConfigModelEntryEditorProps = {
  model: ConfigCatalogModel;
  disabled: boolean;
  busy: boolean;
  copy: ConfigCopy;
  edits: ModelFieldEdits;
  onEditsChange: (edits: ModelFieldEdits) => void;
  onEnabledChange?: (enabled: boolean) => void;
  /** Compatibility for old embedded consumers. The page uses its single save. */
  onSave?: (modelKey: string, edits: ModelFieldEdits) => void;
};

const GENERATION_FIELDS = ["temperature", "max_output_tokens", "timeout", "streaming", "default_reasoning_effort"] as const;
type GenerationField = (typeof GENERATION_FIELDS)[number];

/** A controlled whitelist editor. Entry and generation values remain page drafts. */
export function ConfigModelEntryEditor({
  model, disabled, busy, copy, edits, onEditsChange, onSave, onEnabledChange,
}: ConfigModelEntryEditorProps) {
  const baseline = useMemo(
    () => buildModelFieldValues(model.draftEntry, { label: model.label, upstreamId: model.upstreamId }),
    [model.draftEntry, model.label, model.upstreamId],
  );
  const [added, setAdded] = useState<{ modelRef: string; fields: GenerationField[] }>({ modelRef: model.modelRef, fields: [] });
  const values: ModelFieldValues = { ...baseline };
  const changedEdits: ModelFieldEdits = {};
  for (const field of EDITABLE_MODEL_FIELDS) {
    if (field === "enabled" && onEnabledChange) continue;
    const value = edits[field];
    if ((typeof value === "string" || typeof value === "boolean") && value !== baseline[field]) {
      Object.assign(values, { [field]: value });
      changedEdits[field] = value;
    }
  }
  const update = (field: EditableModelField, value: string | boolean) => {
    const next = { ...changedEdits };
    if (value === baseline[field]) delete next[field];
    else next[field] = value;
    onEditsChange(next);
  };
  const locked = disabled || busy;
  const dirty = Object.keys(changedEdits).length > 0;
  const valid = modelEditorDraftIsValid(changedEdits);
  const reasoningValues = [...new Set([
    ...(model.reasoningEffortValues ?? []),
    ...(values.default_reasoning_effort ? [values.default_reasoning_effort] : []),
  ])];
  const defaults = model.draftEntry?.defaults;
  const overrides = defaults && typeof defaults === "object" && !Array.isArray(defaults)
    ? defaults as Record<string, unknown> : {};
  const visibleGeneration = GENERATION_FIELDS.filter((field) =>
    overrides[field] != null
    || Object.prototype.hasOwnProperty.call(edits, field)
    || (added.modelRef === model.modelRef && added.fields.includes(field)),
  );
  const availableGeneration = GENERATION_FIELDS.filter((field) =>
    !visibleGeneration.includes(field)
    && (field !== "default_reasoning_effort" || reasoningValues.length > 0),
  );
  const labels: Record<GenerationField, string> = {
    temperature: copy.modelEditFieldTemperature,
    max_output_tokens: copy.modelEditFieldMaxOutputTokens,
    timeout: copy.modelEditFieldTimeout,
    streaming: copy.modelEditFieldStreaming,
    default_reasoning_effort: copy.modelEditFieldReasoningEffort,
  };
  const numericInput = (field: "context_window" | "temperature" | "max_output_tokens" | "timeout", label: string) => (
    <label className={styles.modelEditField} data-model-edit-field={field} key={field}>
      <span>{label}</span>
      <VInput
        className={styles.modelEditInput}
        type="text"
        inputMode={field === "temperature" ? "decimal" : "numeric"}
        value={values[field]}
        disabled={locked}
        placeholder={copy.useModelDeclared}
        aria-invalid={!modelEditorFieldIsValid(field, values[field]) || undefined}
        onChange={(event) => update(field, event.target.value)}
      />
    </label>
  );
  return (
    <div className={styles.modelEditForm} data-model-edit-form={model.modelRef}>
      <div className={styles.modelEditGrid} aria-label={copy.modelEditFieldsAria}>
        <label className={styles.modelEditField} data-model-edit-field="label">
          <span>{copy.modelEditFieldLabel}</span>
          <VInput className={styles.modelEditInput} value={values.label} disabled={locked} aria-invalid={!values.label.trim() || undefined}
            onChange={(event) => update("label", event.target.value)} />
        </label>
        <label className={styles.modelEditField} data-model-edit-field="model">
          <span>{copy.modelEditFieldModel}</span>
          <VInput className={styles.modelEditInput} value={values.model} disabled={locked} title={copy.modelEditModelHint}
            aria-invalid={!values.model.trim() || undefined}
            onChange={(event) => update("model", event.target.value)} />
        </label>
        {numericInput("context_window", copy.modelEditFieldContextWindow)}
        <div className={styles.modelEditField} data-model-edit-field="enabled">
          <span>{copy.modelEditFieldEnabled}</span>
          <div className={styles.modelEditSwitch}>
            <VSwitch isSelected={values.enabled === true} isDisabled={locked} aria-label={copy.modelEditFieldEnabled}
              title={onEnabledChange ? copy.modelSwitchHint : undefined}
              onChange={(value) => onEnabledChange ? onEnabledChange(value) : update("enabled", value)} />
          </div>
        </div>
      </div>

      <div className={styles.modelEditParameters} role="group" aria-label={copy.modelEditGenerationTitle}>
        <div className={styles.modelEditParameterHeading}>
          <h3 className={styles.modelEditParameterTitle}>{copy.modelEditGenerationTitle}</h3>
          {availableGeneration.length > 0 ? <VStringSelect
            className={styles.modelEditAddParameter}
            ariaLabel={copy.modelEditAddParameter}
            value=""
            isDisabled={locked}
            options={[
              { value: "", label: copy.modelEditAddParameter },
              ...availableGeneration.map((field) => ({ value: field, label: labels[field] })),
            ]}
            onValueChange={(value) => {
              const field = availableGeneration.find((candidate) => candidate === value);
              if (field) setAdded((current) => ({
                modelRef: model.modelRef,
                fields: [...(current.modelRef === model.modelRef ? current.fields : []), field],
              }));
            }}
          /> : null}
        </div>
        {visibleGeneration.length > 0 ? <div className={styles.modelEditGrid}>
          {visibleGeneration.map((field) => {
            if (field === "streaming") return (
              <div className={styles.modelEditField} data-model-edit-field={field} key={field}>
                <span>{labels[field]}</span>
                <div className={styles.modelEditSwitch}>
                  <VSwitch isSelected={values.streaming === true} isDisabled={locked} aria-label={labels[field]}
                    onChange={(value) => update(field, value)} />
                </div>
              </div>
            );
            if (field === "default_reasoning_effort") return (
              <label className={styles.modelEditField} data-model-edit-field={field} key={field}>
                <span>{labels[field]}</span>
                <VStringSelect ariaLabel={labels[field]} value={values.default_reasoning_effort} isDisabled={locked}
                  options={[{ value: "", label: copy.modelEditReasoningFollowRules }, ...reasoningValues.map((value) => ({ value, label: value }))]}
                  onValueChange={(value) => update(field, value)} />
              </label>
            );
            return numericInput(field, labels[field]);
          })}
        </div> : <p className={styles.modelEditHint} data-model-edit-generation-empty>{copy.modelEditGenerationEmpty}</p>}
      </div>

      {!valid ? <p className={styles.modelEditHint} role="alert">{copy.saveBlockedInvalid}</p> : null}
      {onSave ? <VActionGroup ariaLabel={`${model.modelRef}${copy.modelActionsAriaSuffix}`}>
        <VButton variant="primary" data-model-action="save-edit" isDisabled={locked || !dirty || !valid}
          onPress={() => onSave(model.modelKey, changedEdits)}>
          {busy ? copy.actionModelUpdateBusy : copy.modelEditSaveAction}
        </VButton>
        <VButton data-model-action="cancel-edit" isDisabled={locked || !dirty} onPress={() => onEditsChange({})}>
          {copy.modelEditCancelAction}
        </VButton>
      </VActionGroup> : null}
    </div>
  );
}
