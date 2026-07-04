import { ExternalLink, X } from "lucide-react";

import { VButton, VNativeInput } from "../components/vui";
import styles from "./AgentMemoryPolicyPanel.styles";

export type AgentMemoryPolicyDraft = {
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

  return (
    <section className={styles.configEditor}>
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.memoryPolicyTitle}</p>
          <h3>{policyId || "-"}</h3>
        </div>
        <span className={dirty ? styles.dirtyPill : styles.cleanPill}>
          {dirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已同步" : "Synced")}
        </span>
      </div>
      <div className={styles.pathList}>
        <code>{rootPath || "-"}</code>
      </div>
      <div className={styles.memoryPolicyGrid}>
        {sharedGroupSections.map((section) => (
          <section key={section.field}>
            <span>{section.label}</span>
            <div className={styles.tagList}>
              {draft[section.field].length ? draft[section.field].map((group) => (
                <VButton
                  key={`${section.field}:${group}`}
                  type="button"
                  variant="ghost"
                  trailingIcon={<X size={12} />}
                  title={removeTitle(group, lang)}
                  onPress={() => onRemoveMemoryGroup(section.field, group)}
                >
                  {group}
                </VButton>
              )) : <small>{section.emptyLabel}</small>}
            </div>
            <div className={styles.inlineAdd}>
              <VNativeInput
                list={section.list}
                value={draft[section.inputField]}
                placeholder={section.placeholder}
                onChange={(event) => updateInputField(onDraftChange, section.inputField, event.target.value)}
              />
              <VButton type="button" variant="secondary" onPress={() => onAddMemoryGroup(section.field, draft[section.inputField])}>
                {copy.addSharedGroup}
              </VButton>
            </div>
          </section>
        ))}
        {knowledgeBaseSections.map((section) => (
          <section key={section.field}>
            <span>{section.label}</span>
            <div className={styles.tagList}>
              {draft[section.field].length ? draft[section.field].map((knowledgeBaseId) => (
                <VButton
                  key={`${section.field}:${knowledgeBaseId}`}
                  type="button"
                  variant="ghost"
                  trailingIcon={<X size={12} />}
                  title={removeTitle(knowledgeBaseId, lang)}
                  onPress={() => onRemoveKnowledgeBaseId(section.field, knowledgeBaseId)}
                >
                  {knowledgeBaseId}
                </VButton>
              )) : <small>{section.emptyLabel}</small>}
            </div>
            <div className={styles.inlineAdd}>
              <VNativeInput
                value={draft[section.inputField]}
                placeholder={section.placeholder}
                onChange={(event) => updateInputField(onDraftChange, section.inputField, event.target.value)}
              />
              <VButton type="button" variant="secondary" onPress={() => onAddKnowledgeBaseId(section.field, draft[section.inputField])}>
                {copy.addSharedGroup}
              </VButton>
            </div>
          </section>
        ))}
      </div>
      <datalist id="agent-memory-groups">
        {memoryGroupOptions.map((group) => <option key={group} value={group} />)}
      </datalist>
      <div className={styles.editorActions}>
        <VButton
          type="button"
          variant="secondary"
          icon={<ExternalLink size={15} />}
          onPress={onOpenMemoryPage}
        >
          {lang === "zh" ? "去记忆页配置" : "Open memory page"}
        </VButton>
        <VButton
          type="button"
          variant="secondary"
          isDisabled={!dirty || pending}
          onPress={onReset}
        >
          {copy.resetConfig}
        </VButton>
        <VButton
          type="button"
          variant="primary"
          isDisabled={!canSave || pending}
          onPress={onSave}
        >
          {pending ? copy.savingMemoryPolicy : copy.saveMemoryPolicy}
        </VButton>
      </div>
    </section>
  );
}
