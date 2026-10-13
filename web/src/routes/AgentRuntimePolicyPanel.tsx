import type { AgentDelegationPolicy, AgentSupervisionPolicy } from "../api/types";
import { VButton, VCheckbox, VFieldRow, VNativeInput, VSettingsFormPage, VStringSelect, VTooltip } from "../components/vui";
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
  agentConfigSelectClass,
} from "./agentConfigForm.styles";
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
  const footer = (
    <div className={agentConfigActionsClass}>
      <span className={isDirty ? styles.pendingStatus : styles.savedStatus} aria-live="polite">
        {isDirty ? dirtyLabel : cleanLabel}
      </span>
      <div>
        <VButton
          type="button"
          className={agentConfigQuietButtonClass}
          variant="secondary"
          aria-label={lang === "zh" ? "重置运行策略" : "Reset runtime policy"}
          isDisabled={!isDirty || isPending}
          onPress={onReset}
        >
          {copy.resetConfig}
        </VButton>
        <VButton
          type="button"
          className={agentConfigPrimaryButtonClass}
          variant="primary"
          aria-label={isPending ? copy.savingRuntimePolicy : copy.saveRuntimePolicy}
          isDisabled={!canSave || isPending}
          onPress={onSave}
        >
          {isPending ? (lang === "zh" ? "保存中…" : "Saving…") : (lang === "zh" ? "保存" : "Save")}
        </VButton>
      </div>
    </div>
  );

  return (
    <VSettingsFormPage
      className={agentConfigFormPageClass}
      ariaLabel={`${copy.delegation} · ${roleLabel}`}
      title=""
      headerClassName="hidden"
      bodyClassName={agentConfigEditorClass}
      footerClassName={agentConfigFooterClass}
      footer={footer}
    >
      <div className={agentConfigContentClass}>
        <section className={styles.fieldSection}>
          <h3 aria-label={copy.delegationPolicyTitle}>{lang === "zh" ? "委派" : "Delegation"}</h3>
          <VFieldRow label={copy.allowSubagents} className={agentConfigRowClass}>
            <VCheckbox
              aria-label={copy.allowSubagents}
              isSelected={delegationPolicyDraft.allowSubagents}
              onChange={(value) => onUpdateDelegationPolicy({ allowSubagents: value })}
            />
          </VFieldRow>
          <VFieldRow label={copy.allowWakeMessages} className={agentConfigRowClass}>
            <VCheckbox
              aria-label={copy.allowWakeMessages}
              isSelected={delegationPolicyDraft.allowWakeMessages}
              onChange={(value) => onUpdateDelegationPolicy({ allowWakeMessages: value })}
            />
          </VFieldRow>
          <VFieldRow label={copy.maxConcurrent} className={agentConfigRowClass}>
            <VNativeInput
              className={agentConfigControlClass}
              type="number"
              min={0}
              max={8}
              value={delegationPolicyDraft.maxConcurrent}
              onChange={(event) => onMaxConcurrentChange(event.target.value)}
            />
          </VFieldRow>
          <VFieldRow label={copy.maxDepth} className={agentConfigRowClass}>
            <VNativeInput
              className={agentConfigControlClass}
              type="number"
              min={0}
              max={4}
              value={delegationPolicyDraft.maxDepth}
              onChange={(event) => onMaxDepthChange(event.target.value)}
            />
          </VFieldRow>
          <VFieldRow label={copy.allowedContextModes} htmlFor="agent-runtime-context-isolated" className={agentConfigRowClass}>
            <div className={styles.contextModes}>
              <VCheckbox
                id="agent-runtime-context-isolated"
                aria-label={`${copy.allowedContextModes}: ${lang === "zh" ? "独立" : "Isolated"}`}
                isSelected={delegationPolicyDraft.allowedContextModes.includes("isolated")}
                onChange={(value) => onToggleDelegationContextMode("isolated", value)}
              >
                {lang === "zh" ? "独立" : "Isolated"}
              </VCheckbox>
              <VCheckbox
                id="agent-runtime-context-fork"
                aria-label={`${copy.allowedContextModes}: ${lang === "zh" ? "继承" : "Fork"}`}
                isSelected={delegationPolicyDraft.allowedContextModes.includes("fork")}
                onChange={(value) => onToggleDelegationContextMode("fork", value)}
              >
                {lang === "zh" ? "继承" : "Fork"}
              </VCheckbox>
            </div>
          </VFieldRow>
        </section>
        <section className={styles.fieldSection}>
          <h3>
            <VTooltip
              width="wide"
              content={(
                <span className={styles.policyMeta}>
                  <span>{copy.communication}: {inboxPendingCount} pending</span>
                  <span>{copy.context}: {groupContextEventCount} group events</span>
                </span>
              )}
            >
              <span
                className={styles.policyMetaTrigger}
                tabIndex={0}
                aria-label={`${copy.supervisionPolicyTitle}：${copy.communication} ${inboxPendingCount} pending；${copy.context} ${groupContextEventCount} group events`}
              >
                {lang === "zh" ? "监督" : "Supervision"}
              </span>
            </VTooltip>
          </h3>
          <VFieldRow label={copy.supervisionEnabled} className={agentConfigRowClass}>
            <VCheckbox
              aria-label={copy.supervisionEnabled}
              isSelected={supervisionPolicyDraft.supervisionEnabled}
              onChange={(value) => onUpdateSupervisionPolicy({ supervisionEnabled: value })}
            />
          </VFieldRow>
          <VFieldRow label={copy.requiresReview} className={agentConfigRowClass}>
            <VCheckbox
              aria-label={copy.requiresReview}
              isSelected={supervisionPolicyDraft.requiresReview}
              isDisabled={supervisionPolicyDraft.reviewMode === "required" || supervisionPolicyDraft.reviewMode === "disabled"}
              onChange={(value) => onUpdateSupervisionPolicy({ requiresReview: value })}
            />
          </VFieldRow>
          <VFieldRow label={copy.reviewMode} className={agentConfigRowClass}>
            <VStringSelect
              ariaLabel={copy.reviewMode}
              className={agentConfigSelectClass}
              value={supervisionPolicyDraft.reviewMode}
              onValueChange={(reviewMode) => onUpdateSupervisionPolicy({ reviewMode })}
              options={[
                { value: "advisory", label: lang === "zh" ? "建议" : "Advisory" },
                { value: "required", label: lang === "zh" ? "强制" : "Required" },
                { value: "disabled", label: lang === "zh" ? "关闭" : "Disabled" },
              ]}
            />
          </VFieldRow>
          <VFieldRow label={copy.evidenceLevel} className={agentConfigRowClass}>
            <VStringSelect
              ariaLabel={copy.evidenceLevel}
              className={agentConfigSelectClass}
              value={supervisionPolicyDraft.evidenceLevel}
              onValueChange={(evidenceLevel) => onUpdateSupervisionPolicy({ evidenceLevel })}
              options={[
                { value: "light", label: lang === "zh" ? "轻量" : "Light" },
                { value: "standard", label: lang === "zh" ? "标准" : "Standard" },
                { value: "strict", label: lang === "zh" ? "严格" : "Strict" },
              ]}
            />
          </VFieldRow>
        </section>
        {notice ? (
          <p aria-live="polite" className={notice.tone === "error" ? styles.errorText : styles.successText}>
            {notice.text}
          </p>
        ) : null}
      </div>
    </VSettingsFormPage>
  );
}
