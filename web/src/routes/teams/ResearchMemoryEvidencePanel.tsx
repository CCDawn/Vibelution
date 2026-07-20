import type { ReactNode } from "react";

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

const statusTone: Record<string, string> = {
  qualified: "border-[color-mix(in_srgb,var(--state-success)_30%,transparent)] bg-[var(--vui-status-success-bg)] text-[var(--vui-status-success-fg)]",
  unsupported: "border-[color-mix(in_srgb,var(--state-warning)_30%,transparent)] bg-[var(--vui-status-warning-bg)] text-[var(--vui-status-warning-fg)]",
  rejected: "border-[color-mix(in_srgb,var(--state-error)_30%,transparent)] bg-[var(--vui-status-danger-bg)] text-[var(--vui-status-danger-fg)]",
  not_established: "border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] text-[var(--fg-secondary)]",
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
    <div className="grid min-w-0 gap-1">
      <strong className="text-[var(--fg-secondary)]">{label}</strong>
      {refs.length > 0 ? (
        <ul className="grid min-w-0 gap-1">
          {refs.map((ref) => (
            <li key={`${ref.type}:${ref.id}`} className="grid min-w-0 grid-cols-[max-content_minmax(0,1fr)] gap-2">
              <span className="text-[var(--fg-tertiary)]">{ref.type || "evidence"}</span>
              <code className="min-w-0 break-all text-[var(--fg-primary)]">{ref.id}</code>
            </li>
          ))}
        </ul>
      ) : (
        <span className="text-[var(--fg-tertiary)]">{emptyText}</span>
      )}
    </div>
  );
}

function TagList({ children }: { children: ReactNode[] }) {
  return <div className="flex min-w-0 flex-wrap gap-1">{children}</div>;
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
    <div className="grid min-w-0 gap-3">
      <div className="flex min-w-0 flex-wrap gap-x-3 gap-y-1 text-[var(--fg-secondary)]">
        <span>{isZh ? "有边界支持" : "qualified"} {summary.claimStatusCounts.qualified}</span>
        <span>{isZh ? "暂不支持" : "unsupported"} {summary.claimStatusCounts.unsupported}</span>
        <span>{isZh ? "已否定" : "rejected"} {summary.claimStatusCounts.rejected}</span>
        <span>{isZh ? "尚未建立" : "not established"} {summary.claimStatusCounts.not_established}</span>
      </div>
      {summary.allowedVariableContract.variables.length > 0 || summary.allowedVariableContract.frozenControls.length > 0 ? (
        <section className="grid min-w-0 gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-muted)] p-2">
          <strong>{isZh ? "变量变更合同" : "Variable change contract"}</strong>
          {summary.allowedVariableContract.variables.length > 0 ? (
            <TagList>
              {summary.allowedVariableContract.variables.map((variable) => (
                <code
                  key={`${variable.path}:${variable.source}:${variable.evidenceRef}`}
                  className="max-w-full break-all rounded bg-[var(--vui-control-muted)] px-1.5 py-0.5"
                  title={`${variable.source} · ${variable.evidenceRef}`}
                >
                  {variable.path} · {variable.source} · {variable.evidenceRef}
                </code>
              ))}
            </TagList>
          ) : null}
          {summary.allowedVariableContract.frozenControls.length > 0 ? (
            <div className="grid min-w-0 gap-1">
              <span className="text-[var(--fg-secondary)]">{isZh ? "冻结控制" : "Frozen controls"}</span>
              <TagList>
                {summary.allowedVariableContract.frozenControls.map((control) => (
                  <span key={control} className="max-w-full break-words rounded border border-[var(--vui-border-subtle)] px-1.5 py-0.5">
                    {control}
                  </span>
                ))}
              </TagList>
            </div>
          ) : null}
        </section>
      ) : null}
      <div className="grid min-w-0 gap-2">
        {summary.claimMap.map((claim) => (
          <details
            key={claim.claimId}
            className="group min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2"
          >
            <summary className="grid cursor-pointer min-w-0 grid-cols-[max-content_minmax(0,1fr)] items-start gap-2">
              <span className={`rounded border px-1.5 py-0.5 ${statusTone[claim.status] || statusTone.not_established}`}>
                {claimStatusLabel(claim.status, lang)}
              </span>
              <span className="min-w-0 break-words font-semibold text-[var(--fg-primary)]">{claim.claim}</span>
            </summary>
            <div className="mt-2 grid min-w-0 gap-3 border-t border-[var(--vui-border-subtle)] pt-2">
              <div className="grid min-w-0 gap-2 md:grid-cols-2">
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
                <div className="grid min-w-0 gap-1">
                  <strong className="text-[var(--fg-secondary)]">{isZh ? "适用边界" : "Applicable boundaries"}</strong>
                  <TagList>
                    {claim.applicableBoundaries.map((boundary) => (
                      <span key={boundary} className="max-w-full break-words">{boundary}</span>
                    ))}
                  </TagList>
                </div>
              ) : null}
              {claim.sourcePlanIds.length > 0 ? (
                <div className="grid min-w-0 gap-1">
                  <strong className="text-[var(--fg-secondary)]">{isZh ? "来源计划" : "Source plans"}</strong>
                  <TagList>
                    {claim.sourcePlanIds.map((planId) => (
                      <code key={planId} className="max-w-full break-all">{planId}</code>
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
        className="group min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-2 py-1.5 [font-size:var(--vui-font-xs)]"
        data-memory-context-id={summary.contextId}
        data-research-memory-evidence="compact"
      >
        <summary className="cursor-pointer select-none font-semibold text-[var(--fg-secondary)]">
          {isZh ? "查看 Claim Map 与变量边界" : "View claim map and variable bounds"}
        </summary>
        <div className="mt-2 grid min-w-0 gap-2 border-t border-[var(--vui-border-subtle)] pt-2">
          <div className="flex min-w-0 flex-wrap gap-x-3 gap-y-1 text-[var(--fg-secondary)]">
            <span>{isZh ? "有边界支持" : "qualified"} {summary.claimStatusCounts.qualified}</span>
            <span>{isZh ? "暂不支持" : "unsupported"} {summary.claimStatusCounts.unsupported}</span>
            <span>{isZh ? "已否定" : "rejected"} {summary.claimStatusCounts.rejected}</span>
            <span>{isZh ? "尚未建立" : "not established"} {summary.claimStatusCounts.not_established}</span>
          </div>
          {summary.allowedVariables.length > 0 ? (
            <TagList>
              {summary.allowedVariables.map((path) => (
                <code key={path} className="max-w-full break-all rounded bg-[var(--vui-control-muted)] px-1.5 py-0.5">
                  {path}
                </code>
              ))}
            </TagList>
          ) : null}
          {summary.claimMapPreview.length > 0 ? (
            <ul className="grid min-w-0 gap-1">
              {summary.claimMapPreview.map((claim) => (
                <li key={claim.claimId} className="grid min-w-0 grid-cols-[max-content_minmax(0,1fr)] gap-2">
                  <span className="text-[var(--fg-tertiary)]">{claimStatusLabel(claim.status, lang)}</span>
                  <span className="min-w-0 break-words text-[var(--fg-primary)]">{claim.claim}</span>
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
      className="grid min-w-0 gap-3 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-3 [font-size:var(--vui-font-sm)]"
      data-memory-context-id={summary.contextId}
      data-research-memory-evidence="detail"
    >
      <header className="grid min-w-0 gap-1">
        <strong>{title}</strong>
        <span className="text-[var(--fg-secondary)]">
          {isZh
            ? `已引用 ${summary.knowledgeItemCount} 条知识、${summary.successfulRunCount} 个成功结果、${summary.negativeExperimentCount} 条负向实验。`
            : `Uses ${summary.knowledgeItemCount} knowledge items, ${summary.successfulRunCount} successful results, and ${summary.negativeExperimentCount} negative experiments.`}
        </span>
      </header>
      {content}
    </section>
  );
}
