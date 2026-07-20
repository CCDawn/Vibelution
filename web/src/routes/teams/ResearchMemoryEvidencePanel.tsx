import type { ReactNode } from "react";

import styles, { statusTone } from "./ResearchMemoryEvidencePanel.styles";

export type ResearchMemoryEvidenceRef = {
  type: string;
  id: string;
};

export type ResearchMemoryClaim = {
  claimId: string;
  claim: string;
  status: "qualified" | "unsupported" | "rejected" | "not_established" | string;
  supportEvidenceRefs: ResearchMemoryEvidenceRef[];
  counterEvidenceRefs: ResearchMemoryEvidenceRef[];
  applicableBoundaries: string[];
  sourcePlanIds: string[];
};

export type ResearchMemoryContextSummary = {
  contextId: string;
  knowledgeItemCount: number;
  reviewedSourceCount: number;
  negativeExperimentCount: number;
  successfulRunCount: number;
  forbiddenDuplicateExperimentCount: number;
  claimCount: number;
  claimStatusCounts: {
    qualified: number;
    unsupported: number;
    rejected: number;
    not_established: number;
  };
  allowedVariableCount: number;
  allowedVariables: string[];
  allowedVariableContract: {
    status: string;
    variables: Array<{
      path: string;
      source: string;
      evidenceRef: string;
    }>;
    frozenControls: string[];
  };
  claimMap: ResearchMemoryClaim[];
  claimMapPreview: Array<{
    claimId: string;
    claim: string;
    status: ResearchMemoryClaim["status"];
  }>;
  missingEvidence: string[];
};

type ResearchMemoryEvidencePanelProps = {
  summary?: ResearchMemoryContextSummary;
  lang: "zh" | "en";
  stage: "experiment" | "iteration";
  variant: "compact" | "detail";
};

function claimStatusLabel(status: string, lang: "zh" | "en") {
  if (lang === "en") {
    return status.replaceAll("_", " ");
  }
  return {
    qualified: "有边界支持",
    unsupported: "暂不支持",
    rejected: "已否定",
    not_established: "尚未建立",
  }[status] || status;
}

function EvidenceList({
  refs,
  emptyText,
  label,
}: {
  refs: ResearchMemoryEvidenceRef[];
  emptyText: string;
  label: string;
}) {
  return (
    <div className={styles.evidenceList}>
      <strong className={styles.evidenceLabel}>{label}</strong>
      {refs.length > 0 ? (
        <ul className={styles.evidenceItems}>
          {refs.map((ref) => (
            <li key={`${ref.type}:${ref.id}`} className={styles.evidenceItem}>
              <span className={styles.evidenceType}>{ref.type || "evidence"}</span>
              <code className={styles.evidenceId}>{ref.id}</code>
            </li>
          ))}
        </ul>
      ) : (
        <span className={styles.emptyText}>{emptyText}</span>
      )}
    </div>
  );
}

function TagList({ children }: { children: ReactNode[] }) {
  return <div className={styles.tagList}>{children}</div>;
}

export function ResearchMemoryEvidencePanel({
  summary,
  lang,
  stage,
  variant,
}: ResearchMemoryEvidencePanelProps) {
  if (!summary || (summary.claimCount === 0 && summary.allowedVariableCount === 0)) {
    return null;
  }

  const isZh = lang === "zh";
  const title = stage === "experiment"
    ? (isZh ? "实验设计使用的团队记忆" : "Team memory used by experiment design")
    : (isZh ? "执行迭代使用的团队记忆" : "Team memory used by execution and iteration");
  const content = (
    <div className={styles.content}>
      <div className={styles.statusList}>
        <span>{isZh ? "有边界支持" : "qualified"} {summary.claimStatusCounts.qualified}</span>
        <span>{isZh ? "暂不支持" : "unsupported"} {summary.claimStatusCounts.unsupported}</span>
        <span>{isZh ? "已否定" : "rejected"} {summary.claimStatusCounts.rejected}</span>
        <span>{isZh ? "尚未建立" : "not established"} {summary.claimStatusCounts.not_established}</span>
      </div>
      {summary.allowedVariableContract.variables.length > 0 || summary.allowedVariableContract.frozenControls.length > 0 ? (
        <section className={styles.variableContract}>
          <strong>{isZh ? "变量变更合同" : "Variable change contract"}</strong>
          {summary.allowedVariableContract.variables.length > 0 ? (
            <TagList>
              {summary.allowedVariableContract.variables.map((variable) => (
                <code
                  key={`${variable.path}:${variable.source}:${variable.evidenceRef}`}
                  className={styles.variableTag}
                  title={`${variable.source} · ${variable.evidenceRef}`}
                >
                  {variable.path} · {variable.source} · {variable.evidenceRef}
                </code>
              ))}
            </TagList>
          ) : null}
          {summary.allowedVariableContract.frozenControls.length > 0 ? (
            <div className={styles.frozenControls}>
              <span className={styles.evidenceLabel}>{isZh ? "冻结控制" : "Frozen controls"}</span>
              <TagList>
                {summary.allowedVariableContract.frozenControls.map((control) => (
                  <span key={control} className={styles.frozenControl}>
                    {control}
                  </span>
                ))}
              </TagList>
            </div>
          ) : null}
        </section>
      ) : null}
      <div className={styles.claimList}>
        {summary.claimMap.map((claim) => (
          <details
            key={claim.claimId}
            className={styles.claimDetails}
          >
            <summary className={styles.claimSummary}>
              <span className={`${styles.statusBadge} ${statusTone[claim.status] || statusTone.not_established}`}>
                {claimStatusLabel(claim.status, lang)}
              </span>
              <span className={styles.claimTitle}>{claim.claim}</span>
            </summary>
            <div className={styles.claimBody}>
              <div className={styles.evidenceGrid}>
                <EvidenceList
                  refs={claim.supportEvidenceRefs}
                  label={isZh ? "支持证据" : "Supporting evidence"}
                  emptyText={isZh ? "无直接支持证据" : "No direct supporting evidence"}
                />
                <EvidenceList
                  refs={claim.counterEvidenceRefs}
                  label={isZh ? "反证 / 边界证据" : "Counter / boundary evidence"}
                  emptyText={isZh ? "无直接反证" : "No direct counter evidence"}
                />
              </div>
              {claim.applicableBoundaries.length > 0 ? (
                <div className={styles.frozenControls}>
                  <strong className={styles.evidenceLabel}>{isZh ? "适用边界" : "Applicable boundaries"}</strong>
                  <TagList>
                    {claim.applicableBoundaries.map((boundary) => (
                      <span key={boundary} className={styles.breakWords}>{boundary}</span>
                    ))}
                  </TagList>
                </div>
              ) : null}
              {claim.sourcePlanIds.length > 0 ? (
                <div className={styles.frozenControls}>
                  <strong className={styles.evidenceLabel}>{isZh ? "来源计划" : "Source plans"}</strong>
                  <TagList>
                    {claim.sourcePlanIds.map((planId) => (
                      <code key={planId} className={styles.breakAll}>{planId}</code>
                    ))}
                  </TagList>
                </div>
              ) : null}
            </div>
          </details>
        ))}
      </div>
    </div>
  );

  if (variant === "compact") {
    return (
      <details
        className={styles.compactDetails}
        data-memory-context-id={summary.contextId}
        data-research-memory-evidence="compact"
      >
        <summary className={styles.compactSummary}>
          {isZh ? "查看 Claim Map 与变量边界" : "View claim map and variable bounds"}
        </summary>
        <div className={styles.compactBody}>
          <div className={styles.statusList}>
            <span>{isZh ? "有边界支持" : "qualified"} {summary.claimStatusCounts.qualified}</span>
            <span>{isZh ? "暂不支持" : "unsupported"} {summary.claimStatusCounts.unsupported}</span>
            <span>{isZh ? "已否定" : "rejected"} {summary.claimStatusCounts.rejected}</span>
            <span>{isZh ? "尚未建立" : "not established"} {summary.claimStatusCounts.not_established}</span>
          </div>
          {summary.allowedVariables.length > 0 ? (
            <TagList>
              {summary.allowedVariables.map((path) => (
                <code key={path} className={styles.variableTag}>
                  {path}
                </code>
              ))}
            </TagList>
          ) : null}
          {summary.claimMapPreview.length > 0 ? (
            <ul className={styles.evidenceItems}>
              {summary.claimMapPreview.map((claim) => (
                <li key={claim.claimId} className={styles.evidenceItem}>
                  <span className={styles.evidenceType}>{claimStatusLabel(claim.status, lang)}</span>
                  <span className={styles.previewClaim}>{claim.claim}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </details>
    );
  }

  return (
    <section
      className={styles.detailSection}
      data-memory-context-id={summary.contextId}
      data-research-memory-evidence="detail"
    >
      <header className={styles.detailHeader}>
        <strong>{title}</strong>
        <span className={styles.evidenceLabel}>
          {isZh
            ? `已引用 ${summary.knowledgeItemCount} 条知识、${summary.successfulRunCount} 个成功结果、${summary.negativeExperimentCount} 条负向实验。`
            : `Uses ${summary.knowledgeItemCount} knowledge items, ${summary.successfulRunCount} successful results, and ${summary.negativeExperimentCount} negative experiments.`}
        </span>
      </header>
      {content}
    </section>
  );
}
