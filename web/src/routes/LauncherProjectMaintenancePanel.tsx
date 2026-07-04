import { LoaderCircle, ShieldCheck, Trash2 } from "lucide-react";

import type {
  LauncherMaintenancePlan,
  LauncherMaintenanceProfileId,
  LauncherMaintenanceSummary,
} from "../api/types";
import { VButton } from "../components/vui";
import { launcherRouteStyles as styles } from "./LauncherRoute.styles";

type LauncherProjectMaintenanceCopy = {
  maintenanceActiveWorkPolicy: string;
  maintenanceApply: string;
  maintenanceCleanStart: string;
  maintenanceEstimated: string;
  maintenanceFactoryRuntime: string;
  maintenanceHint: string;
  maintenanceLoading: string;
  maintenancePlanEmpty: string;
  maintenancePlanMissingForProfile: string;
  maintenancePlanProfileMismatch: string;
  maintenancePlanReady: string;
  maintenancePreview: string;
  maintenanceProfile: string;
  maintenanceTargets: string;
  maintenanceTitle: string;
};

type LauncherProjectMaintenancePanelProps = {
  copy: LauncherProjectMaintenanceCopy;
  summary?: LauncherMaintenanceSummary;
  maintenanceProfile: LauncherMaintenanceProfileId;
  plan: LauncherMaintenancePlan | null;
  loading: boolean;
  previewPending: boolean;
  applyPending: boolean;
  onProfileChange: (profile: LauncherMaintenanceProfileId) => void;
  onPreview: () => void;
  onApply: () => void;
};

function normalizeMaintenanceProfileId(value: unknown): LauncherMaintenanceProfileId | null {
  const profileId = String(value || "").trim();
  if (profileId === "custom" || profileId === "clean_start" || profileId === "factory_runtime") {
    return profileId;
  }
  return null;
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

export function LauncherProjectMaintenancePanel({
  copy,
  summary,
  maintenanceProfile,
  plan,
  loading,
  previewPending,
  applyPending,
  onProfileChange,
  onPreview,
  onApply,
}: LauncherProjectMaintenancePanelProps) {
  const profiles = summary?.profiles ?? [];
  const selectedProfile = profiles.find((profile) => profile.id === maintenanceProfile);
  const selectedItemIds = selectedProfile?.itemIds ?? [];
  const selectedItems = (summary?.items ?? []).filter((item) => selectedItemIds.includes(item.id));
  const estimatedBytes = selectedItems.reduce((total, item) => total + Number(item.sizeBytes || 0), 0);
  const targetCount = selectedItems.reduce((total, item) => total + Number(item.candidateCount || 0), 0);
  const planProfileMatches = !plan || normalizeMaintenanceProfileId(plan.profileId) === maintenanceProfile;
  const visiblePlan = planProfileMatches ? plan : null;
  const planRows = visiblePlan?.preview.items.slice(0, 5) ?? [];
  const canPreview = Boolean(summary) && !loading && !previewPending && !applyPending;
  const canApply = Boolean(visiblePlan) && !loading && !previewPending && !applyPending;
  const applyTitle = !plan
    ? copy.maintenancePlanMissingForProfile
    : !planProfileMatches
      ? copy.maintenancePlanProfileMismatch
      : copy.maintenanceApply;

  return (
    <section
      className={styles.developerPanel}
      data-maintenance-owner="launcher"
      data-endpoint-summary="maintenance/reset/summary"
      data-endpoint-preview="maintenance/reset/preview"
      data-endpoint-apply="maintenance/reset/apply"
    >
      <div className={styles.developerPanelHeader}>
        <div title={copy.maintenanceHint}>
          <p className={styles.panelEyebrow}>Launcher 维护中心</p>
          <strong>{copy.maintenanceTitle}</strong>
        </div>
        <VButton type="button" variant="secondary" className={styles.iconButton} onPress={onPreview} isDisabled={!canPreview} title={copy.maintenancePreview} icon={previewPending ? <LoaderCircle size={15} className={styles.spin} /> : <Trash2 size={15} />}>
          <span>{copy.maintenancePreview}</span>
        </VButton>
        <VButton type="button" variant="primary" className={styles.primaryButton} onPress={onApply} isDisabled={!canApply} title={canApply ? copy.maintenanceApply : applyTitle} icon={applyPending ? <LoaderCircle size={15} className={styles.spin} /> : <ShieldCheck size={15} />}>
          <span>{copy.maintenanceApply}</span>
        </VButton>
      </div>
      <div className={styles.developerGrid}>
        <div className={styles.developerStatus} data-tone="warning">
          <span>{copy.maintenanceProfile}</span>
          <strong>{selectedProfile?.label || copy.maintenanceFactoryRuntime}</strong>
          <small>{copy.maintenanceActiveWorkPolicy}</small>
        </div>
        <div className={styles.developerNoise}>
          <div className={styles.developerNoiseHeader}>
            <span>{copy.maintenanceProfile}</span>
            <small>{loading ? copy.maintenanceLoading : summary?.executionOwner || "launcher"}</small>
          </div>
          <div className={styles.segmentedControl} role="group" aria-label={copy.maintenanceProfile}>
            {[
              ["clean_start", copy.maintenanceCleanStart],
              ["factory_runtime", copy.maintenanceFactoryRuntime],
            ].map(([profile, label]) => (
              <VButton
                key={profile}
                type="button"
                variant="secondary"
                data-active={maintenanceProfile === profile}
                isDisabled={previewPending || applyPending}
                onPress={() => {
                  onProfileChange(profile as LauncherMaintenanceProfileId);
                }}
              >
                {label}
              </VButton>
            ))}
          </div>
          <div className={styles.noiseItemGrid}>
            {selectedItems.slice(0, 4).map((item) => (
              <div key={item.id} className={styles.noiseItem} data-protected="false">
                <span>{item.name}</span>
                <strong>{item.size}</strong>
                <small>{item.candidateCount} {copy.maintenanceTargets}</small>
              </div>
            ))}
          </div>
        </div>
        <div className={styles.cleanupConsole}>
          <div className={styles.cleanupMetrics}>
            <span>{copy.maintenanceEstimated}: <strong>{formatBytes(visiblePlan?.estimatedBytes ?? estimatedBytes)}</strong></span>
            <span>{copy.maintenanceTargets}: <strong>{visiblePlan?.targetCount ?? targetCount}</strong></span>
          </div>
          {visiblePlan ? (
            <div className={styles.cleanupPlan}>
              <strong>{copy.maintenancePlanReady}</strong>
              <small>{visiblePlan.planId} · {visiblePlan.planHash.slice(0, 10)}</small>
              {planRows.length ? (
                <ul>
                  {planRows.map((item) => (
                    <li key={item.id}>{item.name}: {item.summary.deleteCount ?? 0}</li>
                  ))}
                </ul>
              ) : (
                <small>{copy.maintenancePlanEmpty}</small>
              )}
            </div>
          ) : (
            <small>{plan && !planProfileMatches ? copy.maintenancePlanProfileMismatch : copy.maintenancePlanMissingForProfile}</small>
          )}
        </div>
      </div>
    </section>
  );
}
