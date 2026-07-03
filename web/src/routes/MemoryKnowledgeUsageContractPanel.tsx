import { XCircle } from "lucide-react";

import type { MemoryUsageContractPayload } from "../api/types";
import styles from "./MemoryRoute.styles";

export type MemoryKnowledgeUsageContractPanelCopy = {
  usageContract: string;
  memoryDomains: string;
  reviewerRequired: string;
  promptBoundary: string;
  ownerScope: string;
  sourcePath: string;
  allowedUse: string;
  writeBoundary: string;
  forbiddenActions: string;
  currentContractState: string;
  knowledgeBases: string;
  healthFindings: string;
  operationsHealth: string;
  governancePlan: string;
  planOnly: string;
};

type MemoryKnowledgeUsageContractPanelProps = {
  copy: MemoryKnowledgeUsageContractPanelCopy;
  lang: "zh" | "en";
  contract: MemoryUsageContractPayload | undefined;
  formatDomainLabel: (label: string | undefined, domainId: string | undefined) => string;
  formatOwnerLabel: (owner: string | undefined) => string;
  formatBoundaryLabel: (boundary: string | undefined) => string;
  formatPolicyToken: (value: string | undefined) => string;
};

export function MemoryKnowledgeUsageContractPanel({
  copy,
  lang,
  contract,
  formatDomainLabel,
  formatOwnerLabel,
  formatBoundaryLabel,
  formatPolicyToken,
}: MemoryKnowledgeUsageContractPanelProps) {
  const domains = contract?.domains ?? [];
  const hiddenDomains = domains.slice(4);

  return (
    <section className={styles.usageContractPanel} aria-label={copy.usageContract}>
      <div className={styles.managementHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.usageContract}</p>
          <h2>{copy.memoryDomains}</h2>
        </div>
        <span className={styles.countPill}>{domains.length}</span>
      </div>
      <div className={styles.contractPrinciples}>
        <span title={(contract?.principles ?? []).join("\n")}>
          {(contract?.principles ?? []).length} {lang === "zh" ? "条边界规则" : "boundary rules"}
        </span>
        <span title={copy.reviewerRequired}>{copy.reviewerRequired}</span>
        <span title={copy.promptBoundary}>{copy.promptBoundary}</span>
      </div>
      <div className={styles.contractDomainGrid}>
        {domains.slice(0, 4).map((domain) => (
          <section
            key={domain.domainId}
            className={styles.contractDomainRow}
            title={[
              domain.label,
              domain.owner && `${copy.ownerScope}: ${domain.owner}`,
              domain.storage && `${copy.sourcePath}: ${domain.storage}`,
              `${copy.allowedUse}: ${domain.readsThrough.join(", ") || "-"}`,
              `${copy.writeBoundary}: ${domain.canCreateFormalKnowledge ? copy.reviewerRequired : domain.boundary}`,
              `Prompt: ${domain.promptDefault || "-"}`,
            ].filter(Boolean).join("\n")}
          >
            <div>
              <strong>{formatDomainLabel(domain.label, domain.domainId)}</strong>
              <small>{formatOwnerLabel(domain.owner)}</small>
            </div>
            <span>{domain.canCreateFormalKnowledge ? (lang === "zh" ? "需审核" : copy.reviewerRequired) : formatBoundaryLabel(domain.boundary)}</span>
            <code>{formatPolicyToken(domain.promptDefault)}</code>
          </section>
        ))}
        {hiddenDomains.length > 0 ? (
          <section className={styles.contractDomainRow} title={hiddenDomains.map((domain) => domain.label).join("\n")}>
            <div>
              <strong>+{hiddenDomains.length}</strong>
              <small>{copy.memoryDomains}</small>
            </div>
            <span>{lang === "zh" ? "悬停查看" : "Hover for details"}</span>
            <code>{copy.promptBoundary}</code>
          </section>
        ) : null}
      </div>
      <div className={styles.contractStateGrid}>
        <section>
          <span>{copy.currentContractState}</span>
          <strong>{Number(contract?.currentState.knowledge.knowledgeBaseCount ?? 0)}</strong>
          <small>{copy.knowledgeBases}</small>
        </section>
        <section>
          <span>{copy.healthFindings}</span>
          <strong>{Number(contract?.currentState.operationsHealth.findingCount ?? 0)}</strong>
          <small>{copy.operationsHealth}</small>
        </section>
        <section>
          <span>{copy.governancePlan}</span>
          <strong>{Number(contract?.currentState.governancePlan.actionCount ?? 0)}</strong>
          <small>{copy.planOnly}</small>
        </section>
      </div>
      <div className={styles.contractForbiddenList} aria-label={copy.forbiddenActions}>
        <span title={(contract?.forbiddenActions ?? []).join("\n")}>
          <XCircle size={13} />
          {(contract?.forbiddenActions ?? []).length} {copy.forbiddenActions}
        </span>
      </div>
    </section>
  );
}
