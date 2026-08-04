import type { RefObject } from "react";
import { LoaderCircle, Play } from "lucide-react";

import {
  VButton,
  VCheckbox,
  VContextualHint,
  VInput,
  VStringSelect,
} from "../components/vui";
import type { SupervisedMentalModelMode } from "./evolution/evolutionRouteModel";
import styles from "./EvolutionRoute.styles";

export type EvolutionSupervisedLiveSetupSourceOption = {
  value: string;
  label: string;
};

export type EvolutionSupervisedLiveSetupPanelProps = {
  lang: "zh" | "en";
  sourceKind: "dataset" | "bundle";
  selectedSourceValue: string;
  sourceOptions: EvolutionSupervisedLiveSetupSourceOption[];
  onSourceValueChange: (value: string) => void;
  datasetLimitInput: string;
  datasetLimitInputRef: RefObject<HTMLInputElement | null>;
  onDatasetLimitChange: (value: string) => void;
  selectedSourceLabel?: string;
  selectedSourceStatusText?: string;
  selectedSourceEvaluationText?: string;
  selectedSourceKindLabel?: string;
  selectedSourceCaseText?: string;
  selectedSourceOfficialWarning?: string;
  showMissingBundleError: boolean;
  keepWorktree: boolean;
  onKeepWorktreeChange: (value: boolean) => void;
  approvalMode: "human" | "agent";
  onApprovalModeChange: (value: "human" | "agent") => void;
  supervisedMentalModelMode: SupervisedMentalModelMode;
  onMentalModelModeChange: (value: SupervisedMentalModelMode) => void;
  startDisabled: boolean;
  startDisabledReason?: string;
  startPendingVisual: boolean;
  startLabel: string;
  startTooltip: string;
  caseLimitLabel: string;
  caseLimitHint: string;
  mentalModeLabel: string;
  mentalModeHint: string;
  mentalModeFollowLabel: string;
  mentalModeEnabledLabel: string;
  mentalModeDisabledLabel: string;
  runningLockHint?: string;
  showRunningLock: boolean;
  controlError?: string;
  onStart: () => void;
};

/**
 * Supervised live launch setup form (source, options, start).
 * Orchestration and mutation ownership stay in EvolutionRoute.
 */
export function EvolutionSupervisedLiveSetupPanel({
  lang,
  sourceKind,
  selectedSourceValue,
  sourceOptions,
  onSourceValueChange,
  datasetLimitInput,
  datasetLimitInputRef,
  onDatasetLimitChange,
  selectedSourceLabel,
  selectedSourceStatusText,
  selectedSourceEvaluationText,
  selectedSourceKindLabel,
  selectedSourceCaseText,
  selectedSourceOfficialWarning,
  showMissingBundleError,
  keepWorktree,
  onKeepWorktreeChange,
  approvalMode,
  onApprovalModeChange,
  supervisedMentalModelMode,
  onMentalModelModeChange,
  startDisabled,
  startDisabledReason,
  startPendingVisual,
  startLabel,
  startTooltip,
  caseLimitLabel,
  caseLimitHint,
  mentalModeLabel,
  mentalModeHint,
  mentalModeFollowLabel,
  mentalModeEnabledLabel,
  mentalModeDisabledLabel,
  runningLockHint,
  showRunningLock,
  controlError,
  onStart,
}: EvolutionSupervisedLiveSetupPanelProps) {
  return (
    <div className={styles.supervisedRunSetup} data-vui-region="evolution-supervised-live-setup">
      <div className={styles.formGrid}>
        <div className={sourceKind === "dataset" ? styles.compactFieldGrid : styles.formGrid}>
          <div className={styles.formField}>
            <div className={styles.formLabelWithHint}>
              <label>{lang === "zh" ? "评测来源" : "Evaluation source"}</label>
              <VContextualHint
                content={lang === "zh" ? "数据集会先物化，评测包可直接运行。" : "A dataset is materialized first; a bundle runs directly."}
                label={lang === "zh" ? "评测来源说明" : "Evaluation source help"}
              />
            </div>
            <VStringSelect
              ariaLabel={lang === "zh" ? "评测来源" : "Evaluation source"}
              className={styles.selectInput}
              value={selectedSourceValue}
              options={sourceOptions}
              onValueChange={onSourceValueChange}
            />
          </div>
          {sourceKind === "dataset" ? (
            <div className={styles.formField}>
              <div className={styles.formLabelWithHint}>
                <label htmlFor="supervised-limit">{caseLimitLabel}</label>
                <VContextualHint content={caseLimitHint} label={`${caseLimitLabel}说明`} />
              </div>
              <VInput
                ref={datasetLimitInputRef}
                id="supervised-limit"
                className={styles.textInput}
                type="number"
                min={1}
                placeholder="all"
                value={datasetLimitInput}
                onChange={(event) => onDatasetLimitChange(event.target.value)}
              />
            </div>
          ) : null}
        </div>
        {selectedSourceLabel ? (
          <div className={styles.sourceMetaCompact}>
            <div className={styles.sourceMetaMain}>
              <strong>{selectedSourceLabel}</strong>
              <span>{selectedSourceStatusText}</span>
              {selectedSourceEvaluationText ? <span>{selectedSourceEvaluationText}</span> : null}
            </div>
            <span className={styles.sourceMetaSide}>
              {selectedSourceKindLabel} · {selectedSourceCaseText}
            </span>
          </div>
        ) : null}
        {selectedSourceOfficialWarning ? (
          <p className={styles.sourceWarningStrip}>{selectedSourceOfficialWarning}</p>
        ) : null}
        {showMissingBundleError ? (
          <p className={styles.errorTextCompact}>
            {lang === "zh" ? "请选择一个存在的监督评测包。" : "Choose an existing supervised bundle."}
          </p>
        ) : null}
      </div>

      <div className={styles.supervisedRunOptions}>
        <VCheckbox
          className={styles.checkboxRow}
          isSelected={keepWorktree}
          onChange={onKeepWorktreeChange}
        >
          <span className={styles.checkboxLabel}>{lang === "zh" ? "保留 worktree" : "Keep worktree"}</span>
        </VCheckbox>
        <div className={styles.formField}>
          <div className={styles.formLabelWithHint}>
            <label>{lang === "zh" ? "最终审批方式" : "Final approval mode"}</label>
            <VContextualHint
              content={lang === "zh"
                ? "人工审批由用户作最终决定；Agent 审批会在复评完成后自动作出最终决定，批准时自动创建 Git 提交并请求 Launcher 激活。两者都审阅评分、评估状态、风险与证据。"
                : "Human approval is decided by the user. Agent approval automatically makes the final decision after rerun evaluation and, when approved, creates a Git commit and requests Launcher activation. Both review scores, states, risk, and evidence."}
              label={lang === "zh" ? "最终审批方式说明" : "Final approval mode help"}
            />
          </div>
          <VStringSelect
            ariaLabel={lang === "zh" ? "最终审批方式" : "Final approval mode"}
            className={styles.selectInput}
            value={approvalMode}
            options={[
              { value: "human", label: lang === "zh" ? "人工审批" : "Human approval" },
              { value: "agent", label: lang === "zh" ? "Agent 审批" : "Agent approval" },
            ]}
            onValueChange={(value) => onApprovalModeChange(value === "agent" ? "agent" : "human")}
          />
        </div>
        <div className={styles.formField}>
          <div className={styles.formLabelWithHint}>
            <label>{mentalModeLabel}</label>
            <VContextualHint content={mentalModeHint} label={`${mentalModeLabel}说明`} />
          </div>
          <VStringSelect
            ariaLabel={mentalModeLabel}
            className={styles.selectInput}
            value={supervisedMentalModelMode}
            options={[
              { value: "follow", label: mentalModeFollowLabel },
              { value: "enabled", label: mentalModeEnabledLabel },
              { value: "disabled", label: mentalModeDisabledLabel },
            ]}
            onValueChange={(value) => onMentalModelModeChange(value as SupervisedMentalModelMode)}
          />
        </div>
      </div>

      <div className={styles.controlFooter}>
        <div className={styles.controlActions}>
          <VButton
            type="button"
            variant="primary"
            className={`${styles.inlineAction} ${styles.supervisedPrimaryAction}`}
            isDisabled={startDisabled}
            onClick={onStart}
            tooltip={startTooltip}
            disabledReason={startDisabledReason}
            icon={
              startPendingVisual
                ? <LoaderCircle size={15} />
                : <Play size={15} />
            }
          >
            {startLabel}
          </VButton>
        </div>
        {showRunningLock && runningLockHint ? <p className={styles.noticeText}>{runningLockHint}</p> : null}
        {controlError ? (
          <p className={styles.errorText}>{controlError}</p>
        ) : null}
      </div>
    </div>
  );
}
