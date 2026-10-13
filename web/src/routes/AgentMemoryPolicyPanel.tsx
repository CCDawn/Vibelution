import { ExternalLink, X } from "lucide-react";

import { VButton, VCheckbox, VFieldRow, VNativeInput, VSettingsFormPage, VTooltip } from "../components/vui";
import {
  agentConfigFormPageClass,
  agentConfigActionsClass,
  agentConfigContentClass,
  agentConfigControlClass,
  agentConfigEditorClass,
  agentConfigFooterClass,
  agentConfigPrimaryButtonClass,
  agentConfigQuietButtonClass,
  agentConfigRowClass,
} from "./agentConfigForm.styles";
import styles from "./AgentMemoryPolicyPanel.styles";

export type AgentMemoryPolicyDraft = {
  enabled: boolean;
  readSharedGroups: string[];
  writeSharedGroups: string[];
  readKnowledgeBaseIds: string[];
  proposeKnowledgeBaseIds: string[];
  reviewKnowledgeBaseIds: string[];
  rateKnowledgeBaseIds: string[];
  newReadGroup: string;
  newWriteGroup: string;
  newReadKnowledgeBaseId: string;
  newProposeKnowledgeBaseId: string;
  newReviewKnowledgeBaseId: string;
  newRateKnowledgeBaseId: string;
};

export type AgentMemoryGroupField = "readSharedGroups" | "writeSharedGroups";
export type AgentKnowledgeBaseField =
  | "readKnowledgeBaseIds"
  | "proposeKnowledgeBaseIds"
  | "reviewKnowledgeBaseIds"
  | "rateKnowledgeBaseIds";

type AgentMemoryInputField =
  | "newReadGroup"
  | "newWriteGroup"
  | "newReadKnowledgeBaseId"
  | "newProposeKnowledgeBaseId"
  | "newReviewKnowledgeBaseId"
  | "newRateKnowledgeBaseId";

export type AgentMemoryPolicyPanelCopy = {
  memoryPolicyTitle: string;
  memoryEnabled: string;
  memoryEnabledHint: string;
  readSharedGroups: string;
  writeSharedGroups: string;
  readKnowledgeBaseIds: string;
  proposeKnowledgeBaseIds: string;
  reviewKnowledgeBaseIds: string;
  rateKnowledgeBaseIds: string;
  noSharedGroups: string;
  noKnowledgeBaseIds: string;
  sharedGroupPlaceholder: string;
  knowledgeBasePlaceholder: string;
  addSharedGroup: string;
  resetConfig: string;
  saveMemoryPolicy: string;
  savingMemoryPolicy: string;
};

type MemorySectionConfig<TField extends AgentMemoryGroupField | AgentKnowledgeBaseField> = {
  field: TField;
  inputField: AgentMemoryInputField;
  label: string;
  emptyLabel: string;
  placeholder: string;
  list?: string;
};

type AgentMemoryPolicyPanelProps = {
  copy: AgentMemoryPolicyPanelCopy;
  lang: "zh" | "en";
  policyId: string;
  rootPath: string;
  draft: AgentMemoryPolicyDraft;
  memoryGroupOptions: string[];
  dirty: boolean;
  pending: boolean;
  canSave: boolean;
  onDraftChange: (patch: Partial<AgentMemoryPolicyDraft>) => void;
  onAddMemoryGroup: (field: AgentMemoryGroupField, value: string) => void;
  onRemoveMemoryGroup: (field: AgentMemoryGroupField, value: string) => void;
  onAddKnowledgeBaseId: (field: AgentKnowledgeBaseField, value: string) => void;
  onRemoveKnowledgeBaseId: (field: AgentKnowledgeBaseField, value: string) => void;
  onOpenMemoryPage: () => void;
  onReset: () => void;
  onSave: () => void;
};

function updateInputField(
  onDraftChange: (patch: Partial<AgentMemoryPolicyDraft>) => void,
  field: AgentMemoryInputField,
  value: string,
) {
  onDraftChange({ [field]: value } as Partial<AgentMemoryPolicyDraft>);
}

function removeTitle(value: string, lang: "zh" | "en") {
  return lang === "zh" ? `移除 ${value}` : `Remove ${value}`;
}

export function AgentMemoryPolicyPanel({
  copy,
  lang,
  policyId,
  rootPath,
  draft,
  memoryGroupOptions,
  dirty,
  pending,
  canSave,
  onDraftChange,
  onAddMemoryGroup,
  onRemoveMemoryGroup,
  onAddKnowledgeBaseId,
  onRemoveKnowledgeBaseId,
  onOpenMemoryPage,
  onReset,
  onSave,
}: AgentMemoryPolicyPanelProps) {
  const sharedGroupSections: MemorySectionConfig<AgentMemoryGroupField>[] = [
    {
      field: "readSharedGroups",
      inputField: "newReadGroup",
      label: copy.readSharedGroups,
      emptyLabel: copy.noSharedGroups,
      placeholder: copy.sharedGroupPlaceholder,
      list: "agent-memory-groups",
    },
    {
      field: "writeSharedGroups",
      inputField: "newWriteGroup",
      label: copy.writeSharedGroups,
      emptyLabel: copy.noSharedGroups,
      placeholder: copy.sharedGroupPlaceholder,
      list: "agent-memory-groups",
    },
  ];
  const knowledgeBaseSections: MemorySectionConfig<AgentKnowledgeBaseField>[] = [
    {
      field: "readKnowledgeBaseIds",
      inputField: "newReadKnowledgeBaseId",
      label: copy.readKnowledgeBaseIds,
      emptyLabel: copy.noKnowledgeBaseIds,
      placeholder: copy.knowledgeBasePlaceholder,
    },
    {
      field: "proposeKnowledgeBaseIds",
      inputField: "newProposeKnowledgeBaseId",
      label: copy.proposeKnowledgeBaseIds,
      emptyLabel: copy.noKnowledgeBaseIds,
      placeholder: copy.knowledgeBasePlaceholder,
    },
    {
      field: "reviewKnowledgeBaseIds",
      inputField: "newReviewKnowledgeBaseId",
      label: copy.reviewKnowledgeBaseIds,
      emptyLabel: copy.noKnowledgeBaseIds,
      placeholder: copy.knowledgeBasePlaceholder,
    },
    {
      field: "rateKnowledgeBaseIds",
      inputField: "newRateKnowledgeBaseId",
      label: copy.rateKnowledgeBaseIds,
      emptyLabel: copy.noKnowledgeBaseIds,
      placeholder: copy.knowledgeBasePlaceholder,
    },
  ];

  const renderMemoryField = (section: MemorySectionConfig<AgentMemoryGroupField>) => {
    const values = draft[section.field];
    return (
      <VFieldRow key={section.field} label={section.label} className={agentConfigRowClass}>
        <div className={styles.memoryControl}>
          <div
            className={styles.selectedValues}
            aria-label={values.length ? undefined : `${section.label}：${section.emptyLabel}`}
          >
            {values.map((value) => (
              <VButton
                key={`${section.field}:${value}`}
                type="button"
                className={agentConfigQuietButtonClass}
                variant="ghost"
                trailingIcon={<X size={12} />}
                aria-label={removeTitle(value, lang)}
                title={removeTitle(value, lang)}
                onPress={() => onRemoveMemoryGroup(section.field, value)}
              >
                {value}
              </VButton>
            ))}
          </div>
          <div className={styles.inlineAdd}>
            <VNativeInput
              className={agentConfigControlClass}
              list={section.list}
              aria-label={section.label}
              value={draft[section.inputField]}
              placeholder={section.placeholder}
              onChange={(event) => updateInputField(onDraftChange, section.inputField, event.target.value)}
            />
            <VButton
              type="button"
              className={agentConfigQuietButtonClass}
              variant="secondary"
              onPress={() => onAddMemoryGroup(section.field, draft[section.inputField])}
            >
              {copy.addSharedGroup}
            </VButton>
          </div>
        </div>
      </VFieldRow>
    );
  };

  const renderKnowledgeBaseField = (section: MemorySectionConfig<AgentKnowledgeBaseField>) => {
    const values = draft[section.field];
    return (
      <VFieldRow key={section.field} label={section.label} className={agentConfigRowClass}>
        <div className={styles.memoryControl}>
          <div
            className={styles.selectedValues}
            aria-label={values.length ? undefined : `${section.label}：${section.emptyLabel}`}
          >
            {values.map((value) => (
              <VButton
                key={`${section.field}:${value}`}
                type="button"
                className={agentConfigQuietButtonClass}
                variant="ghost"
                trailingIcon={<X size={12} />}
                aria-label={removeTitle(value, lang)}
                title={removeTitle(value, lang)}
                onPress={() => onRemoveKnowledgeBaseId(section.field, value)}
              >
                {value}
              </VButton>
            ))}
          </div>
          <div className={styles.inlineAdd}>
            <VNativeInput
              className={agentConfigControlClass}
              aria-label={section.label}
              value={draft[section.inputField]}
              placeholder={section.placeholder}
              onChange={(event) => updateInputField(onDraftChange, section.inputField, event.target.value)}
            />
            <VButton
              type="button"
              className={agentConfigQuietButtonClass}
              variant="secondary"
              onPress={() => onAddKnowledgeBaseId(section.field, draft[section.inputField])}
            >
              {copy.addSharedGroup}
            </VButton>
          </div>
        </div>
      </VFieldRow>
    );
  };

  const footer = (
    <div className={agentConfigActionsClass}>
      <span className={dirty ? styles.pendingStatus : styles.savedStatus} aria-live="polite">
        {dirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已保存" : "Saved")}
      </span>
      <div>
        <VButton
          type="button"
          className={agentConfigQuietButtonClass}
          variant="ghost"
          icon={<ExternalLink size={14} />}
          onPress={onOpenMemoryPage}
        >
          {lang === "zh" ? "记忆页" : "Memory"}
        </VButton>
        <VButton
          type="button"
          className={agentConfigQuietButtonClass}
          variant="secondary"
          aria-label={lang === "zh" ? "重置记忆配置" : "Reset memory settings"}
          isDisabled={!dirty || pending}
          onPress={onReset}
        >
          {copy.resetConfig}
        </VButton>
        <VButton
          type="button"
          className={agentConfigPrimaryButtonClass}
          variant="primary"
          aria-label={pending ? copy.savingMemoryPolicy : copy.saveMemoryPolicy}
          isDisabled={!canSave || pending}
          onPress={onSave}
        >
          {pending ? (lang === "zh" ? "保存中…" : "Saving…") : (lang === "zh" ? "保存" : "Save")}
        </VButton>
      </div>
    </div>
  );

  return (
    <VSettingsFormPage
      className={agentConfigFormPageClass}
      ariaLabel={copy.memoryPolicyTitle}
      title=""
      headerClassName="hidden"
      bodyClassName={agentConfigEditorClass}
      footerClassName={agentConfigFooterClass}
      footer={footer}
    >
      <div className={agentConfigContentClass}>
        <section className={styles.fieldSection}>
          <h3>{lang === "zh" ? "记忆策略" : "Memory policy"}</h3>
          <VFieldRow label={lang === "zh" ? "策略标识" : "Policy ID"} htmlFor="agent-memory-policy-id" className={agentConfigRowClass}>
            <VTooltip width="wide" content={<code className={styles.rootPathTooltip}>{rootPath || "-"}</code>}>
              <output
                id="agent-memory-policy-id"
                tabIndex={0}
                className={styles.policyIdValue}
                aria-label={`${lang === "zh" ? "策略标识" : "Policy ID"}：${policyId || "-"}；${rootPath || "-"}`}
              >
                {policyId || "-"}
              </output>
            </VTooltip>
          </VFieldRow>
          <VFieldRow label={copy.memoryEnabled} className={agentConfigRowClass}>
            <VCheckbox
              aria-label={copy.memoryEnabled}
              isSelected={draft.enabled}
              onChange={(value) => onDraftChange({ enabled: value })}
            />
          </VFieldRow>
          {sharedGroupSections.map(renderMemoryField)}
        </section>
        <section className={styles.fieldSection}>
          <h3>{lang === "zh" ? "知识库权限" : "Knowledge base access"}</h3>
          {knowledgeBaseSections.map(renderKnowledgeBaseField)}
        </section>
        <datalist id="agent-memory-groups">
          {memoryGroupOptions.map((group) => <option key={group} value={group} />)}
        </datalist>
      </div>
    </VSettingsFormPage>
  );
}
