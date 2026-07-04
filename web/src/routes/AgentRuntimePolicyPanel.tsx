import type { AgentDelegationPolicy, AgentSupervisionPolicy } from "../api/types";
import { VButton, VCheckbox, VFieldRow, VNativeInput, VNativeSelect } from "../components/vui";
import styles from "./AgentRuntimePolicyPanel.styles";

export type AgentRuntimePolicyPanelCopy = {
  allowedContextModes: string;
  allowSubagents: string;
  allowWakeMessages: string;
  communication: string;
  context: string;
  delegation: string;
  delegationPolicyTitle: string;
  evidenceLevel: string;
  maxConcurrent: string;
  maxDepth: string;
  requiresReview: string;
  resetConfig: string;
  reviewMode: string;
  saveRuntimePolicy: string;
  savingRuntimePolicy: string;
  supervisionEnabled: string;
  supervisionPolicyTitle: string;
};

export type AgentRuntimePolicyPanelNotice = {
  tone: string;
  text: string;
} | null;

export type AgentRuntimePolicyPanelProps = {
  copy: AgentRuntimePolicyPanelCopy;
  lang: "zh" | "en";
  roleLabel: string;
  dirtyLabel: string;
  cleanLabel: string;
  isDirty: boolean;
  isPending: boolean;
  canSave: boolean;
  notice: AgentRuntimePolicyPanelNotice;
  delegationPolicyDraft: AgentDelegationPolicy;
  supervisionPolicyDraft: AgentSupervisionPolicy;
  inboxPendingCount: number;
  groupContextEventCount: number;
  onUpdateDelegationPolicy: (patch: Partial<AgentDelegationPolicy>) => void;
  onToggleDelegationContextMode: (mode: "isolated" | "fork", selected: boolean) => void;
  onMaxConcurrentChange: (value: string) => void;
  onMaxDepthChange: (value: string) => void;
  onUpdateSupervisionPolicy: (patch: Partial<AgentSupervisionPolicy>) => void;
  onReset: () => void;
  onSave: () => void;
};

export function AgentRuntimePolicyPanel({
  copy,
  lang,
  roleLabel,
  dirtyLabel,
  cleanLabel,
  isDirty,
  isPending,
  canSave,
  notice,
  delegationPolicyDraft,
  supervisionPolicyDraft,
  inboxPendingCount,
  groupContextEventCount,
  onUpdateDelegationPolicy,
  onToggleDelegationContextMode,
  onMaxConcurrentChange,
  onMaxDepthChange,
  onUpdateSupervisionPolicy,
  onReset,
  onSave,
}: AgentRuntimePolicyPanelProps) {
  return (
    <section className={styles.configEditor}>
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.delegation}</p>
          <h3>{roleLabel}</h3>
        </div>
        <span className={isDirty ? styles.dirtyPill : styles.cleanPill}>
          {isDirty ? dirtyLabel : cleanLabel}
        </span>
      </div>
      <div className={styles.runtimePolicyGrid}>
        <section>
          <span>{copy.delegationPolicyTitle}</span>
          <div className={styles.toggleGrid}>
            <VCheckbox
              isSelected={delegationPolicyDraft.allowSubagents}
              onChange={(value) => onUpdateDelegationPolicy({ allowSubagents: value })}
            >
              {copy.allowSubagents}
            </VCheckbox>
            <VCheckbox
              isSelected={delegationPolicyDraft.allowWakeMessages}
              onChange={(value) => onUpdateDelegationPolicy({ allowWakeMessages: value })}
            >
              {copy.allowWakeMessages}
            </VCheckbox>
          </div>
          <div className={styles.editorGrid}>
            <VFieldRow label={copy.maxConcurrent}>
              <VNativeInput
                type="number"
                min={0}
                max={8}
                value={delegationPolicyDraft.maxConcurrent}
                onChange={(event) => onMaxConcurrentChange(event.target.value)}
              />
            </VFieldRow>
            <VFieldRow label={copy.maxDepth}>
              <VNativeInput
                type="number"
                min={0}
                max={4}
                value={delegationPolicyDraft.maxDepth}
                onChange={(event) => onMaxDepthChange(event.target.value)}
              />
            </VFieldRow>
          </div>
          <div className={styles.contextModeGrid}>
            <VCheckbox
              isSelected={delegationPolicyDraft.allowedContextModes.includes("isolated")}
              onChange={(value) => onToggleDelegationContextMode("isolated", value)}
            >
              {copy.allowedContextModes}: isolated
            </VCheckbox>
            <VCheckbox
              isSelected={delegationPolicyDraft.allowedContextModes.includes("fork")}
              onChange={(value) => onToggleDelegationContextMode("fork", value)}
            >
              {copy.allowedContextModes}: fork
            </VCheckbox>
          </div>
        </section>
        <section>
          <span>{copy.supervisionPolicyTitle}</span>
          <div className={styles.toggleGrid}>
            <VCheckbox
              isSelected={supervisionPolicyDraft.supervisionEnabled}
              onChange={(value) => onUpdateSupervisionPolicy({ supervisionEnabled: value })}
            >
              {copy.supervisionEnabled}
            </VCheckbox>
            <VCheckbox
              isSelected={supervisionPolicyDraft.requiresReview}
              isDisabled={supervisionPolicyDraft.reviewMode === "required" || supervisionPolicyDraft.reviewMode === "disabled"}
              onChange={(value) => onUpdateSupervisionPolicy({ requiresReview: value })}
            >
              {copy.requiresReview}
            </VCheckbox>
          </div>
          <div className={styles.editorGrid}>
            <VFieldRow label={copy.reviewMode}>
              <VNativeSelect value={supervisionPolicyDraft.reviewMode} onChange={(event) => onUpdateSupervisionPolicy({ reviewMode: event.target.value })}>
                <option value="advisory">{lang === "zh" ? "建议" : "Advisory"}</option>
                <option value="required">{lang === "zh" ? "强制" : "Required"}</option>
                <option value="disabled">{lang === "zh" ? "关闭" : "Disabled"}</option>
              </VNativeSelect>
            </VFieldRow>
            <VFieldRow label={copy.evidenceLevel}>
              <VNativeSelect value={supervisionPolicyDraft.evidenceLevel} onChange={(event) => onUpdateSupervisionPolicy({ evidenceLevel: event.target.value })}>
                <option value="light">{lang === "zh" ? "轻量" : "Light"}</option>
                <option value="standard">{lang === "zh" ? "标准" : "Standard"}</option>
                <option value="strict">{lang === "zh" ? "严格" : "Strict"}</option>
              </VNativeSelect>
            </VFieldRow>
          </div>
          <div className={styles.pathList}>
            <span>{copy.communication}: {inboxPendingCount} pending</span>
            <span>{copy.context}: {groupContextEventCount} group events</span>
          </div>
        </section>
      </div>
      {notice ? (
        <p className={notice.tone === "error" ? styles.errorText : styles.successText}>{notice.text}</p>
      ) : null}
      <div className={styles.editorActions}>
        <VButton
          type="button"
          variant="secondary"
          isDisabled={!isDirty || isPending}
          onPress={onReset}
        >
          {copy.resetConfig}
        </VButton>
        <VButton
          type="button"
          variant="primary"
          isDisabled={!canSave || isPending}
          onPress={onSave}
        >
          {isPending ? copy.savingRuntimePolicy : copy.saveRuntimePolicy}
        </VButton>
      </div>
    </section>
  );
}
