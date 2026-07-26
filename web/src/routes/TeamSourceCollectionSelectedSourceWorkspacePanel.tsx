/**
 * Source-collection selected-source detail workspace.
 * Wave 8M: extracted from TeamsRoute.tsx for domain componentization.
 */
import {
  sourceCollectionCandidateOpenLabel,
  sourceCollectionCandidateProvenance,
  sourceCollectionCandidateTrace,
  sourceCollectionEvidenceLedgerCardLabel,
  sourceCollectionEvidenceLedgerSummary,
  sourceCollectionSourceTypeLabel,
} from "./teams/source-collection/evidenceModel";
import {
  candidateSourceQualityAssessmentSummary,
  sourceCollectionEvidenceLedgerDetailItems,
  sourceCollectionStatusLabel,
  sourceCollectionStorageTargetForRef,
  sourceCollectionStorageTargetLabel,
  workflowIngestionStatusLabel,
  type SourceCollectionStorageOpenTarget,
} from "./teams/source-collection/presentationModel";
import { sourceCollectionRunLabel, translateResearchPhrase } from "./teams/source-collection/runModel";
import { workflowStateLabel } from "./teams/workflowPresentation";
import {
  TeamSourceCollectionSourceDetailPanel,
  type TeamSourceCollectionSourceDetailAction,
  type TeamSourceCollectionSourceDetailEvidence,
  type TeamSourceCollectionSourceDetailFact,
  type TeamSourceCollectionSourceDetailLink,
} from "./TeamSourceCollectionSourceDetailPanel";

type Lang = "zh" | "en";

export type TeamSourceCollectionSelectedSourceWorkspacePanelProps = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedSourceCollectionCandidate: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedSourceCollectionCandidateTrace: any;
  selectedSourceCollectionRunEffectiveId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedSourceCollectionCandidateStorageArtifacts: any;
  workflowQualityTone: (value: string) => string;
  selectedSourceCollectionStorageOpenPending: boolean;
  openSourceCollectionStorageTarget: (target: SourceCollectionStorageOpenTarget, runId?: string) => void;
};

export function TeamSourceCollectionSelectedSourceWorkspacePanel(props: TeamSourceCollectionSelectedSourceWorkspacePanelProps) {
  const {
    lang,
    selectedSourceCollectionCandidate,
    selectedSourceCollectionCandidateTrace,
    selectedSourceCollectionRunEffectiveId,
    selectedSourceCollectionCandidateStorageArtifacts,
    workflowQualityTone,
    selectedSourceCollectionStorageOpenPending,
    openSourceCollectionStorageTarget,
  } = props;


    if (!selectedSourceCollectionCandidate) {
      return null;
    }
    const provenance = sourceCollectionCandidateProvenance(selectedSourceCollectionCandidate, lang);
    const trace = selectedSourceCollectionCandidateTrace ?? sourceCollectionCandidateTrace(selectedSourceCollectionCandidate);
    const sourceQualitySummary = candidateSourceQualityAssessmentSummary(selectedSourceCollectionCandidate);
    const evidenceLedgerSummary = sourceCollectionEvidenceLedgerSummary(selectedSourceCollectionCandidate);
    const runId = trace.runId || selectedSourceCollectionRunEffectiveId;
    const fileStorageTarget = provenance.kind === "file" && selectedSourceCollectionCandidateStorageArtifacts
      ? sourceCollectionStorageTargetForRef(provenance.value, selectedSourceCollectionCandidateStorageArtifacts)
      : null;
    const hasReadableSource = Boolean(provenance.href || fileStorageTarget);
    const hasSearchEvidence = Boolean(trace.searchUrl || trace.query || trace.searchProvider || trace.queryId || trace.assignmentId);
    const storageTargets: SourceCollectionStorageOpenTarget[] = ["run_directory", "search_events", "records", "candidates"];
    const readableLinks: TeamSourceCollectionSourceDetailLink[] = provenance.href
      ? [{
          id: "source",
          href: provenance.href,
          title: provenance.href,
          label: sourceCollectionCandidateOpenLabel(provenance, lang),
        }]
      : [];
    const sourceActions: TeamSourceCollectionSourceDetailAction[] = fileStorageTarget
      ? [{
          id: `file-${fileStorageTarget}`,
          target: fileStorageTarget,
          runId,
          label: sourceCollectionStorageTargetLabel(fileStorageTarget, lang),
          title: provenance.value,
        }]
      : [];
    const storageActions: TeamSourceCollectionSourceDetailAction[] = runId
      ? storageTargets.map((target: any) => ({
          id: `${selectedSourceCollectionCandidate.candidateId}-${target}`,
          target,
          runId,
          label: sourceCollectionStorageTargetLabel(target, lang),
        }))
      : [];
    const noticeMessage = hasReadableSource
      ? ""
      : provenance.kind === "search_evidence"
        ? (lang === "zh" ? "仅有搜索记录，缺少可读来源" : "Only search evidence is available")
        : (lang === "zh" ? "缺少可读来源" : "Readable source missing");
    const searchEvidence: TeamSourceCollectionSourceDetailEvidence[] = [
      trace.query
        ? {
            id: "query",
            label: lang === "zh" ? "搜索问题" : "Search query",
            value: translateResearchPhrase(trace.query, lang),
            title: trace.query,
          }
        : null,
      trace.searchProvider
        ? {
            id: "provider",
            label: lang === "zh" ? "搜索源" : "Provider",
            value: trace.searchProvider,
            title: trace.searchProvider,
          }
        : null,
      trace.searchUrl
        ? {
            id: "api",
            label: lang === "zh" ? "API 证据" : "API evidence",
            value: lang === "zh" ? "打开 API 原文" : "Open raw API",
            title: trace.searchUrl,
            href: trace.searchUrl,
          }
        : null,
    ].filter((item): item is TeamSourceCollectionSourceDetailEvidence => Boolean(item));
    const facts: TeamSourceCollectionSourceDetailFact[] = [
      [lang === "zh" ? "类型" : "Type", sourceCollectionSourceTypeLabel(selectedSourceCollectionCandidate.sourceKind || selectedSourceCollectionCandidate.candidateType, lang)],
      [lang === "zh" ? "来源" : "Source", provenance.value],
      [lang === "zh" ? "查询" : "Query", trace.query ? translateResearchPhrase(trace.query, lang) : ""],
      [lang === "zh" ? "资料记录" : "Record", trace.recordId],
      [lang === "zh" ? "批次" : "Run", runId ? sourceCollectionRunLabel(runId) : ""],
      [lang === "zh" ? "分工" : "Assignment", trace.assignmentId],
      [lang === "zh" ? "搜索源" : "Provider", trace.searchProvider],
      [
        "Evidence Ledger",
        evidenceLedgerSummary
          ? sourceCollectionEvidenceLedgerCardLabel(evidenceLedgerSummary, lang)
          : "",
      ],
    ]
      .filter(([, value]) => Boolean(value))
      .map(([label, value]) => ({ label: String(label), value: String(value) }));
    const statusLabel = sourceQualitySummary
      ? `${workflowIngestionStatusLabel(sourceQualitySummary.decision, lang)} · ${sourceQualitySummary.overallScore}/100`
      : workflowStateLabel(selectedSourceCollectionCandidate.currentState, lang);
    return (
      <TeamSourceCollectionSourceDetailPanel
        lang={lang}
        title={selectedSourceCollectionCandidate.title || selectedSourceCollectionCandidate.candidateId}
        candidateId={selectedSourceCollectionCandidate.candidateId}
        statusLabel={statusLabel}
        statusToneClassName={workflowQualityTone(selectedSourceCollectionCandidate.qualityStatus)}
        readableLinks={readableLinks}
        actions={[...sourceActions, ...storageActions]}
        noticeMessage={noticeMessage}
        searchEvidence={hasSearchEvidence ? searchEvidence : []}
        evidenceLedger={evidenceLedgerSummary ? sourceCollectionEvidenceLedgerDetailItems(evidenceLedgerSummary, lang) : []}
        facts={facts}
        pending={selectedSourceCollectionStorageOpenPending}
        onOpenTarget={(target, targetRunId) => openSourceCollectionStorageTarget(target as SourceCollectionStorageOpenTarget, targetRunId)}
      />
    );

}
