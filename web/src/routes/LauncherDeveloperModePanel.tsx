import { Database, HardDrive, LoaderCircle, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";

import type {
  LauncherDeveloperCleanupAction,
  LauncherDeveloperCleanupPlan,
  LauncherDeveloperModeSetting,
  LauncherDeveloperNoiseOverview,
} from "../api/types";
import { VButton, VNativeSelect } from "../components/vui";
import { launcherRouteStyles as styles } from "./LauncherRoute.styles";

type LauncherDeveloperModeCopy = {
  cleanupApply: string;
  cleanupDbCompact: string;
  cleanupDbCompactDetail: string;
  cleanupDisabledOff: string;
  cleanupEstimated: string;
  cleanupPlanEmpty: string;
  cleanupPlanReady: string;
  cleanupPreview: string;
  cleanupQuickClean: string;
  cleanupQuickCleanDetail: string;
  cleanupSkipped: string;
  cleanupTargets: string;
  cleanupWorktreeCleanup: string;
  cleanupWorktreeCleanupDetail: string;
  developerModeAction: string;
  developerModeControlled: string;
  developerModeCurrentState: string;
  developerModeDisable: string;
  developerModeEnable: string;
  developerModeHint: string;
  developerModeLastUpdated: string;
  developerModeNoiseLoading: string;
  developerModeNoiseOverview: string;
  developerModeOff: string;
  developerModeOn: string;
  developerModeRefreshNoise: string;
  developerModeResetSandbox: string;
  developerModeSandbox: string;
  developerModeSettingsReadonly: string;
  developerModeTitle: string;
};

type DeveloperCleanupActionOption = {
  action: LauncherDeveloperCleanupAction;
  label: string;
  detail: string;
};

type LauncherDeveloperModePanelProps = {
  copy: LauncherDeveloperModeCopy;
  setting?: LauncherDeveloperModeSetting;
  noiseOverview?: LauncherDeveloperNoiseOverview;
  selectedAction: LauncherDeveloperCleanupAction;
  plan: LauncherDeveloperCleanupPlan | null;
  pending: boolean;
  noiseLoading: boolean;
  previewPending: boolean;
  applyPending: boolean;
  resetPending: boolean;
  onToggle: (enabled: boolean, baseHash: string) => void;
  onReset: () => void;
  onRefreshNoise: () => void;
  onSelectAction: (action: LauncherDeveloperCleanupAction) => void;
  onPreview: () => void;
  onApply: () => void;
};

function compactDate(value: string, locale: string) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatBytes(size: number) {
  const value = Number.isFinite(size) ? Math.max(0, size) : 0;
  if (value < 1024) {
    return `${value} B`;
  }
  const units = ["KB", "MB", "GB", "TB"];
  let scaled = value / 1024;
  let unitIndex = 0;
  while (scaled >= 1024 && unitIndex < units.length - 1) {
    scaled /= 1024;
    unitIndex += 1;
  }
  return `${scaled >= 10 ? scaled.toFixed(1) : scaled.toFixed(2)} ${units[unitIndex]}`;
}

export function LauncherDeveloperModePanel({
  copy,
  setting,
  noiseOverview,
  selectedAction,
  plan,
  pending,
  noiseLoading,
  previewPending,
  applyPending,
  resetPending,
  onToggle,
  onReset,
  onRefreshNoise,
  onSelectAction,
  onPreview,
  onApply,
}: LauncherDeveloperModePanelProps) {
  const enabled = Boolean(setting?.enabled);
  const controlsDisabled = pending || !setting;
  const actionOptions: DeveloperCleanupActionOption[] = [
    { action: "quick_clean", label: copy.cleanupQuickClean, detail: copy.cleanupQuickCleanDetail },
    { action: "db_compact", label: copy.cleanupDbCompact, detail: copy.cleanupDbCompactDetail },
    { action: "worktree_cleanup", label: copy.cleanupWorktreeCleanup, detail: copy.cleanupWorktreeCleanupDetail },
  ];
  const selectedOption = actionOptions.find((option) => option.action === selectedAction) ?? actionOptions[0];
  const matchingOverview = noiseOverview?.items.find((item) => item.action === selectedAction);
  const targetRows = plan?.targets.slice(0, 4) ?? [];
  const canPreview = enabled && !controlsDisabled && !previewPending && !applyPending;
  const canApply = enabled && Boolean(plan) && plan?.action === selectedAction && !controlsDisabled && !previewPending && !applyPending;
  const developerModeStateLabel = enabled ? copy.developerModeOn : copy.developerModeOff;
  const sandboxId = String(setting?.sandbox?.sandboxId ?? "");
  const developerModeUpdatedLabel = setting?.updatedAt
    ? enabled && sandboxId
      ? `${copy.developerModeSandbox}: ${sandboxId}`
      : `${copy.developerModeLastUpdated}: ${compactDate(setting.updatedAt, "zh-CN")}`
    : copy.developerModeSettingsReadonly;

  return (
    <section className={styles.developerPanel} data-enabled={enabled}>
      <div className={styles.developerPanelHeader}>
        <div title={copy.developerModeHint}>
          <p className={styles.panelEyebrow}>{copy.developerModeControlled}</p>
          <strong>{copy.developerModeTitle}</strong>
        </div>
        <VButton
          type="button"
          variant={enabled ? "danger" : "primary"}
          className={enabled ? `${styles.iconButton} ${styles.dangerButton}` : styles.primaryButton}
          isDisabled={controlsDisabled}
          onPress={() => onToggle(!enabled, setting?.configHash ?? "")}
          title={enabled ? copy.developerModeDisable : copy.developerModeEnable}
          icon={pending ? <LoaderCircle size={15} className={styles.spin} /> : <ShieldCheck size={15} />}
        >
          <span>{enabled ? copy.developerModeDisable : copy.developerModeEnable}</span>
        </VButton>
        <VButton
          type="button"
          variant="secondary"
          className={styles.iconButton}
          isDisabled={!enabled || controlsDisabled || resetPending}
          onPress={onReset}
          title={copy.developerModeResetSandbox}
          icon={resetPending ? <LoaderCircle size={15} className={styles.spin} /> : <RefreshCw size={15} />}
        >
          <span>{copy.developerModeResetSandbox}</span>
        </VButton>
      </div>
      <div className={styles.developerGrid}>
        <div className={styles.developerStatus} data-tone={enabled ? "warning" : "neutral"} aria-label={`${copy.developerModeCurrentState}: ${developerModeStateLabel}`}>
          <span>{copy.developerModeCurrentState}</span>
          <strong>{developerModeStateLabel}</strong>
          <small>{developerModeUpdatedLabel}</small>
        </div>
        <div className={styles.developerNoise}>
          <div className={styles.developerNoiseHeader}>
            <span>{copy.developerModeNoiseOverview}</span>
            <VButton type="button" variant="secondary" className={styles.compactButton} onPress={onRefreshNoise} isDisabled={noiseLoading} icon={noiseLoading ? <LoaderCircle size={13} className={styles.spin} /> : <RefreshCw size={13} />}>
              <span>{copy.developerModeRefreshNoise}</span>
            </VButton>
          </div>
          {noiseLoading && !noiseOverview ? <small>{copy.developerModeNoiseLoading}</small> : null}
          <div className={styles.noiseItemGrid}>
            {(noiseOverview?.items ?? []).slice(0, 4).map((item) => (
              <div key={item.id} className={styles.noiseItem} data-protected={item.protected}>
                <span>{item.label}</span>
                <strong>{formatBytes(item.sizeBytes)}</strong>
                <small>{item.targetCount} {copy.cleanupTargets}{item.skippedCount ? ` · ${item.skippedCount} ${copy.cleanupSkipped}` : ""}</small>
              </div>
            ))}
          </div>
        </div>
        <div className={styles.cleanupConsole}>
          <label className={styles.settingField} title={selectedOption.detail}>
            <span>{copy.developerModeAction}</span>
            <VNativeSelect value={selectedAction} disabled={previewPending || applyPending} onChange={(event) => onSelectAction(event.target.value as LauncherDeveloperCleanupAction)}>
              {actionOptions.map((option) => (
                <option key={option.action} value={option.action}>{option.label}</option>
              ))}
            </VNativeSelect>
          </label>
          <div className={styles.cleanupMetrics}>
            <span>{copy.cleanupEstimated}: <strong>{formatBytes(matchingOverview?.sizeBytes ?? plan?.estimatedBytes ?? 0)}</strong></span>
            <span>{copy.cleanupTargets}: <strong>{matchingOverview?.targetCount ?? plan?.targetCount ?? 0}</strong></span>
          </div>
          <div className={styles.cleanupActions}>
            <VButton type="button" variant="secondary" className={styles.iconButton} isDisabled={!canPreview} onPress={onPreview} title={!enabled ? copy.cleanupDisabledOff : copy.cleanupPreview} icon={previewPending ? <LoaderCircle size={14} className={styles.spin} /> : <Trash2 size={14} />}>
              <span>{copy.cleanupPreview}</span>
            </VButton>
            <VButton type="button" variant="primary" className={styles.primaryButton} isDisabled={!canApply} onPress={onApply} title={!enabled ? copy.cleanupDisabledOff : copy.cleanupApply} icon={applyPending ? <LoaderCircle size={14} className={styles.spin} /> : selectedAction === "db_compact" ? <Database size={14} /> : <HardDrive size={14} />}>
              <span>{copy.cleanupApply}</span>
            </VButton>
          </div>
          {plan ? (
            <div className={styles.cleanupPlan}>
              <strong>{copy.cleanupPlanReady}</strong>
              <small>{plan.planId} · {copy.cleanupEstimated}: {formatBytes(plan.estimatedBytes)}</small>
              {targetRows.length ? (
                <ul>
                  {targetRows.map((target) => (
                    <li key={target.path}>{target.relativePath || target.path}</li>
                  ))}
                </ul>
              ) : (
                <small>{copy.cleanupPlanEmpty}</small>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
