import React, { useMemo, useState, type RefObject } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronUp,
  Database,
  PackageOpen,
  Play,
  Search,
} from "lucide-react";

import {
  VButton,
  VContextualHint,
  VInput,
  VStringSelect,
} from "../components/vui";
import type { SupervisedMentalModelMode } from "./evolution/evolutionRouteModel";
import styles from "./EvolutionSupervisedLiveSetupPanel.styles";

export type EvolutionSupervisedLiveSetupSourceOption = {
  value: string;
  label: string;
  kind?: "dataset" | "bundle";
  caseCount?: number | null;
  detail?: string;
  status?: string;
  selectable?: boolean;
  disabledReason?: string;
};

export type EvolutionSupervisedLiveSetupPanelProps = {
  lang: "zh" | "en";
  sourceKind: "dataset" | "bundle";
  selectedSourceValue: string;
  sourceOptions: EvolutionSupervisedLiveSetupSourceOption[];
  onSourceValueChange: (value: string) => void;
  onCancel?: () => void;
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

function sourceKind(option: EvolutionSupervisedLiveSetupSourceOption): "dataset" | "bundle" {
  if (option.kind === "dataset" || option.kind === "bundle") {
    return option.kind;
  }
  return option.value.startsWith("bundle:") ? "bundle" : "dataset";
}

function sourceKindLabel(kind: "dataset" | "bundle", lang: "zh" | "en") {
  if (kind === "dataset") {
    return lang === "zh" ? "数据集" : "Dataset";
  }
  return lang === "zh" ? "评测包" : "Evaluation bundle";
}

function sourceCaseCount(option: EvolutionSupervisedLiveSetupSourceOption, lang: "zh" | "en") {
  if (typeof option.caseCount !== "number" || !Number.isFinite(option.caseCount)) {
    return lang === "zh" ? "数量未提供" : "Case count unavailable";
  }
  return lang === "zh" ? `${option.caseCount} 个用例` : `${option.caseCount} cases`;
}

function sourceKindIcon(kind: "dataset" | "bundle") {
  return kind === "dataset" ? <Database size={14} aria-hidden="true" /> : <PackageOpen size={14} aria-hidden="true" />;
}

/**
 * Supervised live setup: choose a real workbench source, review its metadata,
 * then launch. Data ownership and run orchestration stay in EvolutionRoute.
 */
export function EvolutionSupervisedLiveSetupPanel({
  lang,
  sourceKind: activeSourceKind,
  selectedSourceValue,
  sourceOptions,
  onSourceValueChange,
  onCancel,
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
  const [searchText, setSearchText] = useState("");
  const [advancedSettingsOpen, setAdvancedSettingsOpen] = useState(false);
  const selectedSource = sourceOptions.find((option) => option.value === selectedSourceValue) ?? null;
  const normalizedSearch = searchText.trim().toLocaleLowerCase();
  const filteredSourceOptions = useMemo(
    () => sourceOptions.filter((option) => {
      if (!normalizedSearch) {
        return true;
      }
      const searchFields = [option.label, option.detail, option.status, option.value];
      return searchFields.some((field) => String(field || "").toLocaleLowerCase().includes(normalizedSearch));
    }),
    [normalizedSearch, sourceOptions],
  );
  const datasetOptions = filteredSourceOptions.filter((option) => sourceKind(option) === "dataset");
  const bundleOptions = filteredSourceOptions.filter((option) => sourceKind(option) === "bundle");
  const selectableCount = sourceOptions.filter((option) => option.selectable !== false).length;
  const selectedKind = selectedSource ? sourceKind(selectedSource) : activeSourceKind;
  const selectedCount = selectedSource
    ? sourceCaseCount(selectedSource, lang)
    : selectedSourceCaseText || (lang === "zh" ? "数量未提供" : "Case count unavailable");
  const selectedDetail = selectedSource?.detail?.trim() || selectedSourceStatusText?.trim() || "";
  const noSourceMatches = filteredSourceOptions.length === 0;
  const limitText = datasetLimitInput.trim();
  const limit = Number(limitText);
  const knownCount = selectedSource?.caseCount;
  const sampleLimitError = activeSourceKind === "dataset" && limitText
    ? !Number.isSafeInteger(limit) || limit <= 0
      ? (lang === "zh" ? "样本数须为正整数，留空表示全部。" : "Enter a positive whole number, or leave blank for all cases.")
      : typeof knownCount === "number" && limit > knownCount
        ? (lang === "zh" ? `样本数不能超过 ${knownCount}。` : `The sample limit cannot exceed ${knownCount}.`)
        : ""
    : "";
  const submissionDisabled = startDisabled || startPendingVisual || showRunningLock
    || !selectedSource || selectedSource.selectable === false || showMissingBundleError
    || knownCount === 0 || Boolean(sampleLimitError);

  const renderSourceGroup = (
    kind: "dataset" | "bundle",
    options: EvolutionSupervisedLiveSetupSourceOption[],
  ) => {
    if (options.length === 0) {
      return null;
    }
    return (
      <section className={styles.sourceGroup} aria-label={sourceKindLabel(kind, lang)} key={kind}>
        <h3 className={styles.sourceGroupHeading}>
          {sourceKindIcon(kind)}
          <span>{sourceKindLabel(kind, lang)}</span>
          <span className={styles.sourceGroupCount}>{options.length}</span>
        </h3>
        <ul className={styles.sourceList}>
          {options.map((option) => {
            const kindForOption = sourceKind(option);
            const selected = option.value === selectedSourceValue;
            const disabled = option.selectable === false;
            return (
              <li key={option.value}>
                <VButton
                  type="button"
                  contentLayout="plain"
                  variant="secondary"
                  aria-pressed={selected}
                  aria-label={`${option.label}，${sourceKindLabel(kindForOption, lang)}，${sourceCaseCount(option, lang)}${disabled && option.disabledReason ? `，${option.disabledReason}` : ""}`}
                  className={`${styles.sourceOption} ${selected ? styles.sourceOptionSelected : ""}`}
                  data-source-value={option.value}
                  isDisabled={disabled}
                  onClick={() => onSourceValueChange(option.value)}
                >
                  <span className={styles.sourceOptionTopline}>
                    <strong className={styles.sourceOptionName}>{option.label}</strong>
                    {selected ? <Check size={15} aria-hidden="true" className={styles.sourceSelectedIcon} /> : null}
                  </span>
                  <span className={styles.sourceOptionMeta}>
                    <span className={styles.sourceKindBadge}>{sourceKindLabel(kindForOption, lang)}</span>
                    <span>{sourceCaseCount(option, lang)}</span>
                    {option.status ? <span className={styles.sourceOptionStatus}>{option.status}</span> : null}
                  </span>
                  {option.detail ? <span className={styles.sourceOptionDetail}>{option.detail}</span> : null}
                  {disabled && option.disabledReason ? (
                    <span className={styles.sourceOptionDisabledReason}>{option.disabledReason}</span>
                  ) : null}
                </VButton>
              </li>
            );
          })}
        </ul>
      </section>
    );
  };

  return (
    <div className={styles.root} data-vui-region="evolution-supervised-live-setup">
      <header className={styles.header}>
        <div className={styles.headingCopy}>
          <span className={styles.eyebrow}>{lang === "zh" ? "监督进化" : "SUPERVISED EVOLUTION"}</span>
          <h2 className={styles.title}>{lang === "zh" ? "新建监督运行" : "New supervised run"}</h2>
          <p className={styles.subtitle}>
            {lang === "zh" ? "选择评测集或评测包，然后确认运行参数。" : "Choose an evaluation dataset or bundle, then confirm run settings."}
          </p>
        </div>
        <span className={styles.sourceCount}>
          {lang === "zh" ? `${selectableCount} 个可用来源` : `${selectableCount} available sources`}
        </span>
      </header>

      <div className={styles.content}>
        <section className={styles.sourcePicker} aria-labelledby="supervised-source-heading">
          <div className={styles.sectionHeader}>
            <div>
              <h2 id="supervised-source-heading" className={styles.sectionTitle}>
                {lang === "zh" ? "选择评测来源" : "Choose evaluation source"}
              </h2>
              <p className={styles.sectionHint}>
                {lang === "zh" ? "数据集会使用绑定的评测包；评测包可直接运行。" : "Datasets use their bound bundle; bundles can run directly."}
              </p>
            </div>
          </div>

          <label className={styles.searchField}>
            <Search size={15} aria-hidden="true" />
            <VInput
              id="supervised-source-search"
              className={styles.searchInput}
              type="search"
              aria-label={lang === "zh" ? "搜索评测集和评测包" : "Search datasets and bundles"}
              placeholder={lang === "zh" ? "搜索评测集或评测包" : "Search datasets or bundles"}
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
            />
          </label>

          {noSourceMatches ? (
            <p className={styles.emptySources} role="status">
              {sourceOptions.length === 0
                ? (lang === "zh" ? "当前没有可运行的评测集或评测包。" : "No runnable datasets or bundles are available.")
                : (lang === "zh" ? "没有符合条件的评测来源。" : "No evaluation sources match this search.")}
            </p>
          ) : (
            <div className={styles.sourceGroups} aria-label={lang === "zh" ? "评测来源列表" : "Evaluation source list"}>
              {renderSourceGroup("dataset", datasetOptions)}
              {renderSourceGroup("bundle", bundleOptions)}
            </div>
          )}
        </section>

        <aside className={styles.detailsPane} aria-labelledby="supervised-source-details-heading">
          <section className={styles.selectedSourceCard}>
            <div className={styles.detailsHeader}>
              <span className={styles.detailsEyebrow}>{lang === "zh" ? "当前选择" : "SELECTED SOURCE"}</span>
              <span className={styles.selectedKindBadge}>
                {sourceKindIcon(selectedKind)}
                {selectedSourceKindLabel || sourceKindLabel(selectedKind, lang)}
              </span>
            </div>
            <h2 id="supervised-source-details-heading" className={styles.selectedSourceName}>
              {selectedSourceLabel || selectedSource?.label || (lang === "zh" ? "尚未选择评测集" : "No source selected")}
            </h2>
            {selectedSource ? (
              <dl className={styles.sourceFacts}>
                <div>
                  <dt>{lang === "zh" ? "用例数量" : "Cases"}</dt>
                  <dd>{selectedCount}</dd>
                </div>
                {selectedSource.status ? (
                  <div>
                    <dt>{lang === "zh" ? "可用状态" : "Availability"}</dt>
                    <dd>{selectedSource.status}</dd>
                  </div>
                ) : null}
              </dl>
            ) : null}
            {selectedDetail ? <p className={styles.selectedSourceDetail}>{selectedDetail}</p> : null}
            {selectedSourceEvaluationText ? (
              <div className={styles.evaluationMode}>
                <strong>{lang === "zh" ? "评分方式" : "Scoring mode"}</strong>
                <span>{selectedSourceEvaluationText}</span>
              </div>
            ) : null}
            {selectedSourceOfficialWarning ? (
              <p className={styles.officialWarning}>
                <AlertTriangle size={15} aria-hidden="true" />
                <span>{selectedSourceOfficialWarning}</span>
              </p>
            ) : null}
            {!selectedSource ? (
              <p className={styles.selectPrompt}>
                {lang === "zh" ? "从左侧列表选择一个真实可用的评测来源。" : "Select a runnable source from the list."}
              </p>
            ) : null}
          </section>

          {activeSourceKind === "dataset" ? (
            <section className={styles.caseLimitCard} aria-label={caseLimitLabel}>
              <div className={styles.formLabelWithHint}>
                <label htmlFor="supervised-limit">{caseLimitLabel}</label>
                <VContextualHint content={caseLimitHint} label={`${caseLimitLabel}说明`} />
              </div>
              <VInput
                ref={datasetLimitInputRef}
                id="supervised-limit"
                className={styles.limitInput}
                type="number"
                min={1}
                step={1}
                max={typeof knownCount === "number" ? knownCount : undefined}
                aria-invalid={Boolean(sampleLimitError)}
                aria-describedby={sampleLimitError ? "supervised-sample-limit-error" : undefined}
                placeholder={lang === "zh" ? "全部" : "All cases"}
                value={datasetLimitInput}
                onChange={(event) => onDatasetLimitChange(event.target.value)}
              />
              {sampleLimitError ? <p id="supervised-sample-limit-error" role="alert" className={styles.inlineError}>{sampleLimitError}</p> : null}
            </section>
          ) : null}

          {showMissingBundleError ? (
            <p className={styles.inlineError} role="alert">
              {lang === "zh" ? "请选择一个存在的监督评测包。" : "Choose an existing supervised bundle."}
            </p>
          ) : null}

          <section className={styles.advancedSection}>
            <VButton
              type="button"
              variant="ghost"
              className={styles.advancedToggle}
              aria-expanded={advancedSettingsOpen}
              aria-controls="supervised-run-advanced-settings"
              onClick={() => setAdvancedSettingsOpen((open) => !open)}
              trailingIcon={advancedSettingsOpen ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
            >
              {lang === "zh" ? "高级运行设置" : "Advanced run settings"}
            </VButton>
            {advancedSettingsOpen ? (
              <div id="supervised-run-advanced-settings" className={styles.advancedFields}>
                <div className={styles.formField}>
                  <div className={styles.formLabelWithHint}>
                    <label htmlFor="supervised-approval-mode">{lang === "zh" ? "最终审批方式" : "Final approval mode"}</label>
                    <VContextualHint
                      content={lang === "zh"
                        ? "人工审批由用户作最终决定；Agent 审批会在复评完成后自动作出最终决定，批准时自动创建 Git 提交并请求 Launcher 激活。两者都会审阅评分、评估状态、风险与证据。"
                        : "Human approval is decided by the user. Agent approval decides automatically after rerun evaluation and, when approved, creates a Git commit and requests Launcher activation. Both review scores, evaluation state, risk, and evidence."}
                      label={lang === "zh" ? "最终审批方式说明" : "Final approval mode help"}
                    />
                  </div>
                  <VStringSelect
                    id="supervised-approval-mode"
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
                    <label htmlFor="supervised-mental-mode">{mentalModeLabel}</label>
                    <VContextualHint content={mentalModeHint} label={`${mentalModeLabel}说明`} />
                  </div>
                  <VStringSelect
                    id="supervised-mental-mode"
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
            ) : null}
          </section>
        </aside>
      </div>

      <footer className={styles.footer}>
        <div className={styles.footerMessage} aria-live="polite">
          {controlError ? <p className={styles.inlineError} role="alert">{controlError}</p>
            : showRunningLock && runningLockHint ? <p className={styles.lockHint} role="status">{runningLockHint}</p>
              : startDisabledReason ? <p className={styles.lockHint} role="status">{startDisabledReason}</p>
                : null}
        </div>
        <div className={styles.footerActions} data-single={!onCancel}>
          {onCancel ? (
            <VButton type="button" variant="secondary" className={styles.footerButton} onClick={onCancel}>
              {lang === "zh" ? "取消" : "Cancel"}
            </VButton>
          ) : null}
          <VButton
            type="button"
            variant="primary"
            className={styles.startButton}
            isDisabled={submissionDisabled}
            isPending={startPendingVisual}
            onClick={() => { if (!submissionDisabled) onStart(); }}
            tooltip={startTooltip}
            disabledReason={sampleLimitError || startDisabledReason}
            icon={<Play size={15} aria-hidden="true" />}
          >
            {startLabel}
          </VButton>
        </div>
      </footer>
    </div>
  );
}
