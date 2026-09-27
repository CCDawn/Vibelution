import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, DatabaseBackup, FileWarning, ShieldCheck } from "lucide-react";

import type {
  ConfigMigrationArtifactConflict,
  ConfigMigrationArtifactResolution,
  ConfigMigrationConflict,
  ConfigMigrationPreview,
} from "../api/types";
import {
  VActionGroup,
  VButton,
  VCheckbox,
  VDenseTable,
  VInput,
  VPanelHeader,
  VSection,
  VStateSurface,
  VStatusChip,
  VStringSelect,
  VSurface,
  VTooltip,
} from "../components/vui";
import {
  buildArtifactResolutions,
  createArtifactResolutionDrafts,
  isValidSplitUpstreamId,
  updateArtifactResolutionDraft,
} from "./configMigrationResolutionLogic";
import { type ConfigCopy, formatConfigCopy } from "./config/configCopy";
import styles from "./ConfigModelMigrationPanel.styles";

export type ConfigModelMigrationPanelProps = {
  /** Bilingual copy table (wave 4). */
  copy: ConfigCopy;
  schemaVersion: 1 | 2;
  preview: ConfigMigrationPreview | null;
  aliasUsageCount: number;
  busy: boolean;
  onPreview: (artifactResolutions?: ConfigMigrationArtifactResolution[]) => void;
  onApply: (previewId: string, baseHash: string) => void;
};

export function ConfigModelMigrationPanel({
  copy,
  schemaVersion,
  preview,
  aliasUsageCount,
  busy,
  onPreview,
  onApply,
}: ConfigModelMigrationPanelProps) {
  const artifactWarnings = useMemo(
    () => preview?.conflicts.filter(isArtifactConflict) ?? [],
    [preview],
  );
  const [resolutionDrafts, setResolutionDrafts] = useState(() =>
    createArtifactResolutionDrafts(artifactWarnings),
  );

  useEffect(() => {
    setResolutionDrafts(createArtifactResolutionDrafts(artifactWarnings));
  }, [artifactWarnings]);

  if (schemaVersion === 2) {
    return (
      <VSurface as="section" className={styles.migration} padding="none" data-migration-status={aliasUsageCount ? "aliases_in_use" : "aliases_clear"}>
        <VPanelHeader eyebrow="Schema v2" title={copy.migrationAliasTitle} actions={<VStatusChip tone={aliasUsageCount ? "warning" : "success"}>{aliasUsageCount}{copy.migrationLiveReferenceUnit}</VStatusChip>} />
        <VStateSurface tone={aliasUsageCount ? "unavailable" : "info"} title={aliasUsageCount ? copy.migrationAliasInUseTitle : copy.migrationAliasClearTitle}>
          {aliasUsageCount
            ? copy.migrationAliasInUseBody
            : copy.migrationAliasClearBody}
        </VStateSurface>
      </VSurface>
    );
  }

  const mappings = Object.entries(preview?.modelRefMap ?? {}).map(([legacyModelId, modelRef]) => ({ legacyModelId, modelRef }));
  const credentialConflicts = preview?.conflicts.filter(
    (conflict) => "fields" in conflict && conflict.fields?.some((field) => field.includes("credential")),
  ) ?? [];
  const otherConflicts = preview?.conflicts.filter((conflict) => conflict.code !== "artifact_path_suspected") ?? [];
  const resolutions = buildArtifactResolutions(resolutionDrafts);
  const applyDisabled = busy || !preview || preview.status !== "READY";

  return (
    <VSurface as="section" className={styles.migration} padding="none" data-migration-status={preview?.status ?? "not_previewed"}>
      <VPanelHeader
        eyebrow="Schema v1 read-only inventory"
        title={copy.migrationV2Title}
        actions={<VStatusChip tone={preview?.status === "READY" ? "success" : "warning"}>{preview?.status ?? copy.migrationNotPreviewed}</VStatusChip>}
      />
      <p className={styles.critical} role="alert">
        <AlertTriangle size={14} className="inline" /> {copy.migrationCritical}
      </p>
      <VStateSurface
        tone="unavailable"
        icon={<DatabaseBackup size={15} />}
        title={copy.migrationWhyTitle}
        facts={preview ? [
          { key: "providers", label: copy.migrationFactProviders, value: preview.providers.length },
          { key: "live", label: copy.migrationFactLive, value: preview.referenceImpact.liveReferenceCount },
          { key: "history", label: copy.migrationFactHistory, value: preview.referenceImpact.historicalReferenceCount },
        ] : []}
      >
        {copy.migrationWhyBody}
      </VStateSurface>

      {preview ? (
        <>
          <div className={styles.migrationSummary}>
            {preview.providers.map((provider) => (
              <VSection
                key={provider.providerId}
                className={styles.fact}
                title={provider.label || provider.providerId}
                eyebrow={provider.providerId}
                meta={`${provider.modelRefs.length} models`}
              >
                <span className={styles.muted}>{provider.serviceClass} · {provider.driver} · {provider.credentialState}</span>
              </VSection>
            ))}
          </div>
          <div className={styles.tableScroll}>
            <VDenseTable
              ariaLabel={copy.migrationMapAria}
              className={styles.table}
              rows={mappings}
              getRowKey={(row) => row.legacyModelId}
              emptyText={copy.migrationMapEmpty}
              columns={[
                {
                  id: "old",
                  header: "v1 model ID",
                  render: (row) => (
                    <VTooltip content={row.legacyModelId}>
                      <span tabIndex={0} aria-label={`v1 model ID · ${row.legacyModelId}`}>
                        {row.legacyModelId}
                      </span>
                    </VTooltip>
                  ),
                },
                {
                  id: "new",
                  header: "Canonical modelRef",
                  render: (row) => (
                    <VTooltip content={row.modelRef}>
                      <strong tabIndex={0} aria-label={`Canonical modelRef · ${row.modelRef}`}>
                        {row.modelRef}
                      </strong>
                    </VTooltip>
                  ),
                },
              ]}
            />
          </div>

          {artifactWarnings.length ? (
            <section className={styles.resolutionSection} aria-label={copy.migrationResolutionAria}>
              <div className={styles.resolutionHeading}>
                <strong><FileWarning size={15} className="inline" /> {copy.migrationResolutionHeading}</strong>
                <span className={styles.muted}>{copy.migrationResolutionHint}</span>
              </div>
              <div className={styles.resolutionGrid}>
                {resolutionDrafts.map((draft) => {
                  const preserveAllowed = draft.allowedResolutions.includes("preserve_upstream_id");
                  const splitAllowed = draft.allowedResolutions.includes("split_deployment_artifact");
                  const splitInvalid = draft.decision === "split_deployment_artifact" && !isValidSplitUpstreamId(draft.upstreamId);
                  return (
                    <section key={draft.modelId} className={styles.resolutionCard} data-resolution-model-id={draft.modelId}>
                      <div className={styles.resolutionCardHeader}>
                        <strong>{draft.modelId}</strong>
                        <VStatusChip tone="warning">{copy.migrationOfflineChip}</VStatusChip>
                      </div>
                      <p className={styles.resolutionWarning} role="status">
                        {copy.migrationOfflineWarning}
                      </p>
                      <VStringSelect
                        ariaLabel={`${draft.modelId}${copy.migrationDecisionAriaSuffix}`}
                        value={draft.decision}
                        placeholder={copy.migrationDecisionPlaceholder}
                        options={[
                          ...(preserveAllowed ? [{ value: "preserve_upstream_id", label: copy.migrationPreserveLabel }] : []),
                          ...(splitAllowed ? [{ value: "split_deployment_artifact", label: copy.migrationSplitLabel }] : []),
                        ]}
                        onValueChange={(decision) => {
                          setResolutionDrafts((current) => updateArtifactResolutionDraft(current, draft.modelId, {
                            decision: decision as typeof draft.decision,
                            preserveConfirmed: false,
                          }));
                        }}
                      />
                      {draft.decision === "preserve_upstream_id" && preserveAllowed ? (
                        <VCheckbox
                          isSelected={draft.preserveConfirmed}
                          onChange={(preserveConfirmed) => {
                            setResolutionDrafts((current) => updateArtifactResolutionDraft(current, draft.modelId, { preserveConfirmed }));
                          }}
                        >
                          {copy.migrationPreserveConfirm}
                        </VCheckbox>
                      ) : null}
                      {draft.decision === "split_deployment_artifact" && splitAllowed ? (
                        <div className={styles.resolutionFields}>
                          <VInput
                            aria-label={`${draft.modelId}${copy.migrationNewUpstreamAriaSuffix}`}
                            value={draft.upstreamId}
                            placeholder="namespace/model-a"
                            aria-invalid={splitInvalid}
                            onChange={(event) => {
                              setResolutionDrafts((current) => updateArtifactResolutionDraft(current, draft.modelId, { upstreamId: event.target.value }));
                            }}
                          />
                          {splitInvalid ? (
                            <p className={styles.resolutionError} role="alert">{copy.migrationUpstreamInvalid}</p>
                          ) : null}
                        </div>
                      ) : null}
                    </section>
                  );
                })}
              </div>
              <VActionGroup ariaLabel={copy.migrationResolutionAria} className={styles.resolutionActions}>
                <VButton
                  isDisabled={busy || !resolutions}
                  onPress={() => {
                    if (!resolutions) return;
                    onPreview(resolutions);
                  }}
                >
                  {copy.migrationRegenerateResolutions}
                </VButton>
              </VActionGroup>
            </section>
          ) : null}
          {credentialConflicts.length ? (
            <VStateSurface tone="error" title={copy.migrationCredentialBlockedTitle}>
              {formatConfigCopy(copy.migrationCredentialBlockedTemplate, { count: credentialConflicts.length })}
            </VStateSurface>
          ) : null}
          {otherConflicts.length ? (
            <section className={styles.fact}>
              <strong>{copy.migrationUnresolvedHeading}</strong>
              <ul className={styles.conflictList}>
                {otherConflicts.map((conflict, index) => (
                  <li key={`${conflict.code}-${index}`}>{conflict.code} · {conflict.modelId || ("modelIds" in conflict ? conflict.modelIds?.join(", ") : "") || conflict.proposedProviderId || copy.migrationGlobalFallback}</li>
                ))}
              </ul>
            </section>
          ) : artifactWarnings.length ? null : (
            <VStateSurface tone="info" icon={<ShieldCheck size={15} />} title={copy.migrationNoConflictsTitle}>{copy.migrationNoConflictsBody}</VStateSurface>
          )}
        </>
      ) : (
        <VStateSurface tone="empty" title={copy.migrationPreviewFirstTitle}>{copy.migrationPreviewFirstBody}</VStateSurface>
      )}

      <VActionGroup ariaLabel={copy.migrationActionsAria} className={styles.actions}>
        <VButton isDisabled={busy} onPress={() => onPreview([])}>{copy.migrationPreviewAction}</VButton>
        <VButton
          variant="danger"
          isDisabled={applyDisabled}
          tooltip={copy.migrationApplyTooltip}
          disabledReason={!preview ? copy.migrationNeedPreviewFirst : preview.status !== "READY" ? copy.migrationConflictsRemain : busy ? copy.migrationInProgress : undefined}
          onPress={() => {
            if (!preview || preview.status !== "READY") return;
            onApply(preview.previewId, preview.baseHash);
          }}
        >
          {copy.migrationApplyAction}
        </VButton>
      </VActionGroup>
    </VSurface>
  );
}

function isArtifactConflict(conflict: ConfigMigrationConflict): conflict is ConfigMigrationArtifactConflict {
  return conflict.code === "artifact_path_suspected";
}
