import type { KnowledgeIngestionAdapter, KnowledgePermissionAuditPayload } from "../api/types";
import styles from "./MemoryKnowledgePermissionsPanel.styles";

type KnowledgePermissionEntry = KnowledgePermissionAuditPayload["knowledgeBases"][number]["permissions"][string] | string | null | undefined;

export type MemoryKnowledgePermissionsPanelCopy = {
  ingestionAdapters: string;
  outputContract: string;
  createsKnowledgeItem: string;
  permissionAudit: string;
  teamKnowledgeDomain: string;
  readable: string;
  proposable: string;
  reviewable: string;
  rateable: string;
  yes: string;
  no: string;
};

type MemoryKnowledgePermissionsPanelProps = {
  copy: MemoryKnowledgePermissionsPanelCopy;
  ingestionAdapters: KnowledgeIngestionAdapter[];
  permissionAudit: KnowledgePermissionAuditPayload | undefined;
};

function normalizeKnowledgePermission(permission: KnowledgePermissionEntry): { allowed: boolean; reason: string } {
  if (permission && typeof permission === "object" && "allowed" in permission) {
    return {
      allowed: Boolean(permission.allowed),
      reason: String(permission.reason || "-"),
    };
  }
  return {
    allowed: false,
    reason: typeof permission === "string" && permission.trim() ? permission : "-",
  };
}

export function MemoryKnowledgePermissionsPanel({
  copy,
  ingestionAdapters,
  permissionAudit,
}: MemoryKnowledgePermissionsPanelProps) {
  return (
    <>
      <section className={styles.managementPanel}>
        <div className={styles.managementHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.ingestionAdapters}</p>
            <h2>{copy.outputContract}</h2>
          </div>
          <span className={styles.countPill}>{ingestionAdapters.length}</span>
        </div>
        <div className={styles.permissionMatrix}>
          {ingestionAdapters.map((adapter) => (
            <section key={adapter.sourceType} className={styles.permissionRow}>
              <strong>{adapter.sourceType}</strong>
              <span>{adapter.requiredSourceRef.join(", ")}</span>
              <small>{copy.outputContract}: {adapter.outputContract.creates.join(" + ")}</small>
              <small>{copy.createsKnowledgeItem}: {adapter.outputContract.createsKnowledgeItem ? copy.yes : copy.no}</small>
            </section>
          ))}
        </div>
      </section>

      <section className={styles.managementPanel}>
        <div className={styles.managementHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.permissionAudit}</p>
            <h2>{copy.teamKnowledgeDomain}</h2>
          </div>
          <span className={styles.countPill}>{permissionAudit?.summary.knowledgeBaseCount ?? 0}</span>
        </div>
        <div className={styles.permissionMatrix}>
          {(permissionAudit?.knowledgeBases ?? []).map((row) => (
            <section key={`perm:${row.knowledgeBaseId}`} className={styles.permissionRow}>
              <strong>{row.knowledgeBaseName}</strong>
              <span>{row.teamName} · {row.teamRole || "-"}</span>
              {[
                { label: copy.readable, permission: row.permissions.read },
                { label: copy.proposable, permission: row.permissions.propose },
                { label: copy.reviewable, permission: row.permissions.review },
                { label: copy.rateable, permission: row.permissions.rate },
              ].map(({ label, permission }) => {
                const normalizedPermission = normalizeKnowledgePermission(permission);
                return (
                  <small key={label} className={normalizedPermission.allowed ? styles.statusPill : styles.statusPillMuted}>
                    {label}: {normalizedPermission.allowed ? copy.yes : normalizedPermission.reason}
                  </small>
                );
              })}
            </section>
          ))}
        </div>
      </section>
    </>
  );
}
