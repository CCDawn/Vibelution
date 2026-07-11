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
} from "../components/vui";
import {
  buildArtifactResolutions,
  createArtifactResolutionDrafts,
  isValidSplitUpstreamId,
  updateArtifactResolutionDraft,
} from "./configMigrationResolutionLogic";
import styles from "./ConfigModelMigrationPanel.styles";

export type ConfigModelMigrationPanelProps = {
  schemaVersion: 1 | 2;
  preview: ConfigMigrationPreview | null;
  aliasUsageCount: number;
  busy: boolean;
  onPreview: (artifactResolutions?: ConfigMigrationArtifactResolution[]) => void;
  onApply: (previewId: string, baseHash: string) => void;
};

export function ConfigModelMigrationPanel({
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
        <VPanelHeader eyebrow="Schema v2" title="兼容别名退出条件" actions={<VStatusChip tone={aliasUsageCount ? "warning" : "success"}>{aliasUsageCount} 个 live 引用</VStatusChip>} />
        <VStateSurface tone={aliasUsageCount ? "unavailable" : "info"} title={aliasUsageCount ? "别名仍被使用" : "别名已满足退出条件"}>
          {aliasUsageCount
            ? "只有 live 引用归零后才可进入别名清理；本工作台不会提前提供删除动作。"
            : "live 引用已经归零。别名删除仍属于后续受控清理，不在本次迁移中自动执行。"}
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
        title="迁移到 Provider-first schema v2"
        actions={<VStatusChip tone={preview?.status === "READY" ? "success" : "warning"}>{preview?.status ?? "尚未预览"}</VStatusChip>}
      />
      <p className={styles.critical} role="alert">
        <AlertTriangle size={14} className="inline" /> 迁移会修改外部 operator config。Schema v1 库存保持只读，不能在此新增、更新或删除。
      </p>
      <VStateSurface
        tone="unavailable"
        icon={<DatabaseBackup size={15} />}
        title="为什么需要迁移"
        facts={preview ? [
          { key: "providers", label: "Provider 分组", value: preview.providers.length },
          { key: "live", label: "Live 引用", value: preview.referenceImpact.liveReferenceCount },
          { key: "history", label: "历史引用", value: preview.referenceImpact.historicalReferenceCount },
        ] : []}
      >
        v1 把连接、凭据与模型混在单条记录中；v2 使用 canonical providerId/modelRef。应用前会创建备份，失败时可按 migration ID 回滚。
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
              ariaLabel="v1 到 v2 modelRef 映射"
              className={styles.table}
              rows={mappings}
              getRowKey={(row) => row.legacyModelId}
              emptyText="预览未返回模型映射。"
              columns={[
                { id: "old", header: "v1 model ID", render: (row) => <span title={row.legacyModelId}>{row.legacyModelId}</span> },
                { id: "new", header: "Canonical modelRef", render: (row) => <strong title={row.modelRef}>{row.modelRef}</strong> },
              ]}
            />
          </div>

          {artifactWarnings.length ? (
            <section className={styles.resolutionSection} aria-label="模型部署标识冲突裁决">
              <div className={styles.resolutionHeading}>
                <strong><FileWarning size={15} className="inline" /> 模型部署标识需要显式裁决</strong>
                <span className={styles.muted}>裁决只重新生成服务端预览，不会应用迁移。</span>
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
                        <VStatusChip tone="warning">离线未核验</VStatusChip>
                      </div>
                      <p className={styles.resolutionWarning} role="status">
                        verificationState: unverified_offline。请仅从服务端允许的裁决中选择。
                      </p>
                      <VStringSelect
                        ariaLabel={`${draft.modelId} 裁决方式`}
                        value={draft.decision}
                        placeholder="选择裁决方式"
                        options={[
                          ...(preserveAllowed ? [{ value: "preserve_upstream_id", label: "保留现有 upstream ID" }] : []),
                          ...(splitAllowed ? [{ value: "split_deployment_artifact", label: "拆分部署记录并指定 upstream ID" }] : []),
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
                          我确认保留此模型的现有 upstream ID
                        </VCheckbox>
                      ) : null}
                      {draft.decision === "split_deployment_artifact" && splitAllowed ? (
                        <div className={styles.resolutionFields}>
                          <VInput
                            aria-label={`${draft.modelId} 新 upstream ID`}
                            value={draft.upstreamId}
                            placeholder="namespace/model-a"
                            aria-invalid={splitInvalid}
                            onChange={(event) => {
                              setResolutionDrafts((current) => updateArtifactResolutionDraft(current, draft.modelId, { upstreamId: event.target.value }));
                            }}
                          />
                          {splitInvalid ? (
                            <p className={styles.resolutionError} role="alert">请输入非空且非路径型的 upstream ID。</p>
                          ) : null}
                        </div>
                      ) : null}
                    </section>
                  );
                })}
              </div>
              <VActionGroup ariaLabel="冲突裁决预览" className={styles.resolutionActions}>
                <VButton
                  isDisabled={busy || !resolutions}
                  onPress={() => {
                    if (!resolutions) return;
                    onPreview(resolutions);
                  }}
                >
                  重新生成裁决预览
                </VButton>
              </VActionGroup>
            </section>
          ) : null}
          {credentialConflicts.length ? (
            <VStateSurface tone="error" title="Credential 冲突阻止应用">
              {credentialConflicts.length} 个凭据映射冲突必须先处理；界面不会显示 credential reference 目标或 secret。
            </VStateSurface>
          ) : null}
          {otherConflicts.length ? (
            <section className={styles.fact}>
              <strong>未解决冲突</strong>
              <ul className={styles.conflictList}>
                {otherConflicts.map((conflict, index) => (
                  <li key={`${conflict.code}-${index}`}>{conflict.code} · {conflict.modelId || conflict.proposedProviderId || "全局"}</li>
                ))}
              </ul>
            </section>
          ) : artifactWarnings.length ? null : (
            <VStateSurface tone="info" icon={<ShieldCheck size={15} />} title="预览无阻塞冲突">Apply 仍需最终 destructive impact 确认，不会在预览后自动执行。</VStateSurface>
          )}
        </>
      ) : (
        <VStateSurface tone="empty" title="先生成只读迁移预览">预览会列出 Provider 分组、old-to-new modelRef、live 引用与冲突。</VStateSurface>
      )}

      <VActionGroup ariaLabel="迁移操作" className={styles.actions}>
        <VButton isDisabled={busy} onPress={() => onPreview([])}>生成迁移预览</VButton>
        <VButton
          variant="danger"
          isDisabled={applyDisabled}
          title={!preview ? "先生成预览" : preview.status !== "READY" ? "仍有未解决冲突" : "修改外部 operator config"}
          onPress={() => {
            if (!preview || preview.status !== "READY") return;
            onApply(preview.previewId, preview.baseHash);
          }}
        >
          应用迁移
        </VButton>
      </VActionGroup>
    </VSurface>
  );
}

function isArtifactConflict(conflict: ConfigMigrationConflict): conflict is ConfigMigrationArtifactConflict {
  return conflict.code === "artifact_path_suspected";
}
