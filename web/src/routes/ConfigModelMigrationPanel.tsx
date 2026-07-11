import { AlertTriangle, DatabaseBackup, FileWarning, ShieldCheck } from "lucide-react";

import type { ConfigMigrationPreview } from "../api/types";
import {
  VActionGroup,
  VButton,
  VDenseTable,
  VPanelHeader,
  VSection,
  VStateSurface,
  VStatusChip,
  VSurface,
} from "../components/vui";
import styles from "./ConfigModelMigrationPanel.styles";

export type ConfigModelMigrationPanelProps = {
  schemaVersion: 1 | 2;
  preview: ConfigMigrationPreview | null;
  aliasUsageCount: number;
  busy: boolean;
  onPreview: () => void;
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
  const artifactWarnings = preview?.conflicts.filter((conflict) => conflict.fields?.includes("artifact_path")) ?? [];
  const credentialConflicts = preview?.conflicts.filter((conflict) => conflict.fields?.some((field) => field.includes("credential"))) ?? [];
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
            <VStateSurface tone="unavailable" icon={<FileWarning size={15} />} title="Artifact path 需要人工确认">
              本地运行时 artifact path 不会与 upstream model ID 混用；请在应用前核对 {artifactWarnings.length} 项警告。
            </VStateSurface>
          ) : null}
          {credentialConflicts.length ? (
            <VStateSurface tone="error" title="Credential 冲突阻止应用">
              {credentialConflicts.length} 个凭据映射冲突必须先处理；界面不会显示 credential reference 目标或 secret。
            </VStateSurface>
          ) : null}
          {preview.conflicts.length ? (
            <section className={styles.fact}>
              <strong>未解决冲突</strong>
              <ul className={styles.conflictList}>
                {preview.conflicts.map((conflict, index) => (
                  <li key={`${conflict.code}-${index}`}>{conflict.code} · {conflict.modelId || conflict.proposedProviderId || "全局"}</li>
                ))}
              </ul>
            </section>
          ) : (
            <VStateSurface tone="info" icon={<ShieldCheck size={15} />} title="预览无阻塞冲突">Apply 仍需最终 destructive impact 确认，不会在预览后自动执行。</VStateSurface>
          )}
        </>
      ) : (
        <VStateSurface tone="empty" title="先生成只读迁移预览">预览会列出 Provider 分组、old-to-new modelRef、live 引用与冲突。</VStateSurface>
      )}

      <VActionGroup ariaLabel="迁移操作" className={styles.actions}>
        <VButton isDisabled={busy} onPress={onPreview}>生成迁移预览</VButton>
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
