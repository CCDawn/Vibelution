/**
 * Source-collection ingestion graph workspace body.
 * Wave 8L: extracted from TeamsRoute.tsx for domain componentization.
 * 缺陷⑪: missing-link rows carry the confirmed human waiver surface.
 */
import { useState, type ReactNode } from "react";

import { waiveEvidenceGraphMissingLink } from "../../../../api/researchWorkflow";
import type {
  TeamWorkflowCandidate,
  TeamWorkflowCandidateGraphEdge,
  TeamWorkflowCandidateGraphPayload,
} from "../../../../api/types";
import { TeamCandidateCard } from "../../../../components/vui/product/team-management";
import { VNativeButton, VNativeInput } from "../../../../components/vui";
import {
  sourceCollectionCandidateProvenance,
  sourceCollectionCandidateSourceCategory,
  sourceCollectionEvidenceLedgerActionLabel,
  sourceCollectionEvidenceLedgerCardLabel,
  sourceCollectionEvidenceLedgerSummary,
  sourceCollectionEvidenceLedgerTone,
  sourceCollectionFilterCounts,
  sourceCollectionFilterMatches,
  sourceCollectionSourceFilterLabel,
  sourceCollectionSourceTypeLabel,
} from "../evidenceModel";
import type { SourceCollectionSourceFilter } from "../evidenceModel";
import { sourceCollectionResultTone } from "../presentationModel";
import type { SourceCollectionStageCardProjection, SourceCollectionStageModuleId } from "../stageProjection";
import { workflowGraphLayout } from "../../../TeamWorkflowGraphLayout";
import { TeamWorkflowGraphView } from "../../../TeamWorkflowGraphView";
import { workflowStateLabel } from "../../workflowPresentation";
import { TeamSourceCollectionGraphPanel } from "./TeamSourceCollectionGraphPanel";
import shellStyles from "../../../TeamsRoute.styles";
import workflowStyles from "../../../TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

const WAIVER_JUSTIFICATION_MIN_CHARS = 8;

const missingLinkRowClass = "min-w-0 grid gap-1.5 rounded-[var(--radius-control)] border border-[color:var(--border-soft)] p-1.5 [font-size:var(--vui-font-xs)] leading-[var(--vui-line-tight)] text-[var(--fg-secondary)]";
const missingLinkMetaClass = "min-w-0 flex flex-wrap items-center gap-x-2 gap-y-1";
const missingLinkPathClass = "min-w-0 truncate text-[var(--fg-primary)]";
const missingLinkWaivedBadgeClass = "shrink-0 rounded-[var(--radius-control)] border border-[color:var(--border-soft)] px-1.5 py-0.5 text-[var(--fg-tertiary)]";
const missingLinkEditorClass = "min-w-0 grid gap-1";

const missingLinkEdgeKey = (edge: TeamWorkflowCandidateGraphEdge) =>
  `${edge.sourceCandidateId}->${edge.targetCandidateId}:${edge.relation}`;

/** Same waiver detection rule as the readiness read side (fetch_evidence_graph_stats). */
const missingLinkIsWaived = (edge: TeamWorkflowCandidateGraphEdge) =>
  Boolean(edge.waived)
  || String(edge.status || "").trim().toLowerCase() === "waived"
  || String(edge.status || "").trim().toLowerCase() === "accepted"
  || Boolean(edge.waiver);

export type TeamSourceCollectionGraphWorkspacePanelProps = {
  lang: Lang;
  selectedSourceCollectionRunEffectiveId: string;
  sourceCollectionGraphProjection: SourceCollectionStageCardProjection | null | undefined;
  sourceCollectionProjectedGraphNodeCount: number;
  sourceCollectionProjectedGraphEdgeCount: number;
  teamWorkflowCandidateGraph: TeamWorkflowCandidateGraphPayload | null | undefined;
  teamWorkflowCandidatesById: Map<string, TeamWorkflowCandidate>;
  sourceCollectionSourceFilter: SourceCollectionSourceFilter;
  sourceCollectionFocusedPanelId: string;
  selectedSourceCollectionStageId: string;
  sourceCollectionExpandedPanelId: string;
  setSourceCollectionExpandedPanelId: (id: string) => void;
  sourceCollectionGraphStepState: string | null | undefined;
  renderSourceCollectionFilterBar: (counts: ReturnType<typeof sourceCollectionFilterCounts>, label: string) => ReactNode;
  sourceCollectionPageItems: <T>(stageId: SourceCollectionStageModuleId, items: T[]) => { items: T[]; start: number; end: number };
  renderSourceCollectionPagination: (stageId: SourceCollectionStageModuleId, total: number) => ReactNode;
  teamWorkflowCandidateGraphQuery: {
    isPending: boolean;
    error?: unknown;
    refetch: () => Promise<unknown>;
  };
  selectedTeamBuildCandidateGraphError: Error | null;
  selectedSourceCollectionCandidateId: string;
  selectSourceCollectionCandidate: (candidate: TeamWorkflowCandidate) => void;
  /** Formal workflow run context — required to register a waiver. */
  teamId: string;
  workflowRunId: string;
};

export function TeamSourceCollectionGraphWorkspacePanel(props: TeamSourceCollectionGraphWorkspacePanelProps) {
  const {
    lang,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionGraphProjection,
    sourceCollectionProjectedGraphNodeCount,
    sourceCollectionProjectedGraphEdgeCount,
    teamWorkflowCandidateGraph,
    teamWorkflowCandidatesById,
    sourceCollectionSourceFilter,
    sourceCollectionFocusedPanelId,
    selectedSourceCollectionStageId,
    sourceCollectionExpandedPanelId,
    setSourceCollectionExpandedPanelId,
    sourceCollectionGraphStepState,
    renderSourceCollectionFilterBar,
    sourceCollectionPageItems,
    renderSourceCollectionPagination,
    teamWorkflowCandidateGraphQuery,
    selectedTeamBuildCandidateGraphError,
    selectedSourceCollectionCandidateId,
    selectSourceCollectionCandidate,
    teamId,
    workflowRunId,
  } = props;

  const [unresolvedNodeNotice, setUnresolvedNodeNotice] = useState<string | null>(null);
  const [waiverEditorKey, setWaiverEditorKey] = useState<string | null>(null);
  const [waiverJustification, setWaiverJustification] = useState("");
  const [waiverPending, setWaiverPending] = useState(false);
  const [waiverError, setWaiverError] = useState<string | null>(null);
  const [waiverNotice, setWaiverNotice] = useState<string | null>(null);

  const openWaiverEditor = (edge: TeamWorkflowCandidateGraphEdge) => {
    setWaiverEditorKey(missingLinkEdgeKey(edge));
    setWaiverJustification("");
    setWaiverError(null);
    setWaiverNotice(null);
  };
  const closeWaiverEditor = () => {
    setWaiverEditorKey(null);
    setWaiverJustification("");
    setWaiverError(null);
  };
  const submitWaiver = async (edge: TeamWorkflowCandidateGraphEdge) => {
    if (!workflowRunId || waiverPending) return;
    setWaiverPending(true);
    setWaiverError(null);
    try {
      const response = await waiveEvidenceGraphMissingLink({
        runId: workflowRunId,
        teamId,
        sourceCandidateId: edge.sourceCandidateId,
        targetCandidateId: edge.targetCandidateId,
        relation: edge.relation,
        justification: waiverJustification.trim(),
        confirmed: true,
      });
      setWaiverNotice(
        response.alreadyWaived
          ? (lang === "zh"
            ? "该缺口此前已登记豁免，无需重复操作。"
            : "This gap was already waived; nothing changed.")
          : (lang === "zh"
            ? "已登记豁免：缺口保留计数，但不再阻塞知识入库就绪门。"
            : "Waiver recorded: the gap stays counted but no longer blocks the ingestion gate."),
      );
      setWaiverEditorKey(null);
      setWaiverJustification("");
      await teamWorkflowCandidateGraphQuery.refetch();
    } catch (error) {
      setWaiverError(error instanceof Error ? error.message : String(error));
    } finally {
      setWaiverPending(false);
    }
  };

  const renderMissingLinkWaiverRow = (edge: TeamWorkflowCandidateGraphEdge) => {
    const edgeKey = missingLinkEdgeKey(edge);
    const waived = missingLinkIsWaived(edge);
    const editorOpen = waiverEditorKey === edgeKey;
    const justificationReady = waiverJustification.trim().length >= WAIVER_JUSTIFICATION_MIN_CHARS;
    return (
      <div key={edgeKey} className={missingLinkRowClass} data-testid="graph-missing-link-row">
        <div className={missingLinkMetaClass}>
          <span className={missingLinkPathClass}>
            {edge.relation}: {edge.sourceCandidateId} → {edge.targetCandidateId}
          </span>
          {waived ? (
            <span className={missingLinkWaivedBadgeClass} data-testid="graph-missing-link-waived">
              {lang === "zh" ? "已豁免" : "waived"}
            </span>
          ) : null}
          {!waived && workflowRunId ? (
            <VNativeButton
              data-testid="graph-missing-link-waive"
              className="shrink-0"
              disabled={waiverPending}
              title={lang === "zh" ? "人工确认接受该缺口（需理由，缺口仍保留计数）" : "Accept this gap with a confirmed waiver (justification required; the gap stays counted)"}
              onClick={() => openWaiverEditor(edge)}
            >
              {lang === "zh" ? "豁免" : "Waive"}
            </VNativeButton>
          ) : null}
        </div>
        {editorOpen ? (
          <div className={missingLinkEditorClass} data-testid="graph-missing-link-editor">
            <VNativeInput
              aria-label={lang === "zh" ? "豁免理由" : "Waiver justification"}
              placeholder={lang === "zh"
                ? `填写豁免理由（至少 ${WAIVER_JUSTIFICATION_MIN_CHARS} 字，写入审计）`
                : `Justification (min ${WAIVER_JUSTIFICATION_MIN_CHARS} chars, audited)`}
              value={waiverJustification}
              disabled={waiverPending}
              onChange={(event) => setWaiverJustification(event.target.value)}
            />
            <div className={missingLinkMetaClass}>
              <VNativeButton
                data-testid="graph-missing-link-waive-confirm"
                disabled={waiverPending || !justificationReady}
                onClick={() => void submitWaiver(edge)}
              >
                {lang === "zh" ? "确认豁免" : "Confirm waiver"}
              </VNativeButton>
              <VNativeButton disabled={waiverPending} onClick={closeWaiverEditor}>
                {lang === "zh" ? "取消" : "Cancel"}
              </VNativeButton>
            </div>
            {waiverError ? (
              <div role="alert" data-testid="graph-missing-link-error" className="text-[var(--fg-danger)]">
                {waiverError}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    );
  };

  const graphForSelectedSourceRun =
      selectedSourceCollectionRunEffectiveId && sourceCollectionGraphProjection
        ? sourceCollectionProjectedGraphNodeCount > 0 ? teamWorkflowCandidateGraph : null
        : teamWorkflowCandidateGraph;
  const graphNodeSourceCategories = (graphForSelectedSourceRun?.nodes ?? []).map((node) => {
    const candidate = teamWorkflowCandidatesById.get(node.candidateId);
    return candidate ? sourceCollectionCandidateSourceCategory(candidate, lang) : "missing";
  });
  const graphFilterCounts = sourceCollectionFilterCounts(graphNodeSourceCategories);
  const visibleGraphNodeIds = new Set(
    (teamWorkflowCandidateGraph?.nodes ?? [])
      .filter((node) => {
        const candidate = teamWorkflowCandidatesById.get(node.candidateId);
        const category = candidate ? sourceCollectionCandidateSourceCategory(candidate, lang) : "missing";
        return sourceCollectionFilterMatches(sourceCollectionSourceFilter, category);
      })
      .map((node) => node.candidateId),
  );
  const visibleGraph = graphForSelectedSourceRun
    ? {
        ...graphForSelectedSourceRun,
        nodes: graphForSelectedSourceRun.nodes.filter((node) => visibleGraphNodeIds.has(node.candidateId)),
        edges: graphForSelectedSourceRun.edges.filter((edge) =>
          visibleGraphNodeIds.has(edge.sourceCandidateId) && visibleGraphNodeIds.has(edge.targetCandidateId),
        ),
        missingLinks: graphForSelectedSourceRun.missingLinks.filter((edge) =>
          visibleGraphNodeIds.has(edge.sourceCandidateId) || visibleGraphNodeIds.has(edge.targetCandidateId),
        ),
        unreviewedNodes: graphForSelectedSourceRun.unreviewedNodes.filter((node) => visibleGraphNodeIds.has(node.candidateId)),
      }
    : null;
  const visibleGraphSummary = visibleGraph
    ? {
        nodeCount: visibleGraph.nodes.length,
        edgeCount: visibleGraph.edges.length,
        missingLinkCount: visibleGraph.missingLinks.length,
        unreviewedNodeCount: visibleGraph.unreviewedNodes.length,
      }
    : null;
  const visibleGraphMissingEvidenceAnchorCount = visibleGraph
    ? visibleGraph.nodes.filter((node) => {
        const candidate = teamWorkflowCandidatesById.get(node.candidateId);
        return candidate ? Boolean(sourceCollectionEvidenceLedgerSummary(candidate)?.missingAnchor) : false;
      }).length
    : 0;
  const visibleGraphLayout = visibleGraph && visibleGraphSummary
    ? workflowGraphLayout({ ...visibleGraph, summary: { ...visibleGraph.summary, ...visibleGraphSummary } })
    : null;
  const pagedGraphNodes = sourceCollectionPageItems("relations", visibleGraph?.nodes ?? []);
  const missingLinksSection = (visibleGraph?.missingLinks.length ?? 0) > 0 ? (
    <section
      data-testid="graph-missing-links"
      aria-label={lang === "zh" ? "缺口清单与豁免" : "Missing links and waivers"}
      className="min-w-0 grid gap-1.5"
    >
      <div className={missingLinkMetaClass}>
        <strong>{lang === "zh" ? "缺口" : "Missing links"}</strong>
        <span className="text-[var(--fg-tertiary)]">
          {lang === "zh"
            ? "豁免 = 人工接受该缺口（需理由审计）；缺口计数保留，不放宽门禁。"
            : "Waiver = human acceptance with an audited justification; the gap stays counted and the gate is not loosened."}
        </span>
        {!workflowRunId ? (
          <span className="text-[var(--fg-tertiary)]">
            {lang === "zh" ? "缺少正式运行上下文，暂不能登记豁免。" : "No formal run context; waivers are unavailable here."}
          </span>
        ) : null}
      </div>
      {visibleGraph?.missingLinks.map(renderMissingLinkWaiverRow)}
      {waiverNotice ? (
        <div role="status" data-testid="graph-missing-link-notice" className="text-[var(--fg-secondary)]">
          {waiverNotice}
        </div>
      ) : null}
    </section>
  ) : null;
  const graphNodeCards = visibleGraph?.nodes.length ? pagedGraphNodes.items.map((node) => {
    const candidate = teamWorkflowCandidatesById.get(node.candidateId) ?? null;
    const provenance = candidate ? sourceCollectionCandidateProvenance(candidate, lang) : null;
    const evidenceLedgerSummary = candidate ? sourceCollectionEvidenceLedgerSummary(candidate) : null;
    const selected = candidate ? selectedSourceCollectionCandidateId === candidate.candidateId : false;
    return (
      <TeamCandidateCard
        key={`graph-node-${node.candidateId}`}
        tone={evidenceLedgerSummary ? sourceCollectionEvidenceLedgerTone(evidenceLedgerSummary) : sourceCollectionResultTone(node.qualityStatus || node.currentState)}
        statusLabel={workflowStateLabel(node.currentState, lang)}
        title={node.title || node.candidateId}
        summary={node.candidateId}
        meta={[
          { key: "type", label: sourceCollectionSourceTypeLabel(node.candidateType, lang) },
          { key: "node", label: node.currentWorkflowNode },
          ...(candidate
            ? [{ key: "category", label: sourceCollectionSourceFilterLabel(sourceCollectionCandidateSourceCategory(candidate, lang), lang) }]
            : []),
          ...(evidenceLedgerSummary
            ? [
                { key: "evidence-ledger", label: sourceCollectionEvidenceLedgerCardLabel(evidenceLedgerSummary, lang) },
                ...(evidenceLedgerSummary.missingAnchor
                  ? [{ key: "evidence-action", label: sourceCollectionEvidenceLedgerActionLabel(evidenceLedgerSummary, lang) }]
                  : []),
              ]
            : []),
        ]}
        source={provenance ? {
          label: provenance.label,
          value: provenance.value,
          href: provenance.href,
          title: provenance.href || provenance.value,
          missing: provenance.kind === "missing",
        } : undefined}
        selected={selected}
        onActivate={candidate ? () => selectSourceCollectionCandidate(candidate) : undefined}
      />
    );
  }) : [];
  return (
    <TeamSourceCollectionGraphPanel
      lang={lang}
      focused={sourceCollectionFocusedPanelId === "source-collection-graph-panel"}
      open={
        selectedSourceCollectionStageId === "relations"
        || sourceCollectionExpandedPanelId === "source-collection-graph-panel"
        || sourceCollectionGraphStepState === "active"
      }
      onToggle={(event) => {
        if (!event.currentTarget.open && sourceCollectionExpandedPanelId === "source-collection-graph-panel") {
          setSourceCollectionExpandedPanelId("");
        }
      }}
      rangeText={visibleGraph ? `${pagedGraphNodes.start}-${pagedGraphNodes.end}/${visibleGraph.nodes.length}` : `${sourceCollectionProjectedGraphNodeCount} / ${sourceCollectionProjectedGraphEdgeCount}`}
      filterBar={renderSourceCollectionFilterBar(graphFilterCounts, lang === "zh" ? "入库关系过滤" : "Ingestion map filters")}
      stats={[
        { key: "nodes", label: lang === "zh" ? "当前节点" : "visible nodes", value: visibleGraphSummary?.nodeCount ?? 0 },
        { key: "edges", label: lang === "zh" ? "当前关系" : "visible edges", value: visibleGraphSummary?.edgeCount ?? 0 },
        { key: "missing", label: lang === "zh" ? "缺口" : "missing", value: visibleGraphSummary?.missingLinkCount ?? 0 },
        { key: "review", label: lang === "zh" ? "待审" : "review", value: visibleGraphSummary?.unreviewedNodeCount ?? 0 },
        { key: "evidence-anchor", label: lang === "zh" ? "待补证据" : "missing evidence", value: visibleGraphMissingEvidenceAnchorCount },
      ]}
      hasGraph={Boolean(visibleGraph && visibleGraphLayout && visibleGraphSummary && visibleGraph.nodes.length)}
      graphNotice={unresolvedNodeNotice ? (
        <div role="status" data-testid="graph-node-unresolved-notice">
          {lang === "zh"
            ? `节点 ${unresolvedNodeNotice} 超出已加载的候选范围，暂无法打开详情；请收窄过滤条件后重试。`
            : `Node ${unresolvedNodeNotice} is outside the loaded candidate preview; narrow the filter and try again.`}
        </div>
      ) : undefined}
      graphView={visibleGraphLayout ? (
        <TeamWorkflowGraphView
          layout={visibleGraphLayout}
          markerId="source-collection-workflow-graph-arrow"
          stateLabel={(value: string) => workflowStateLabel(value, lang)}
          lang={lang}
          focusCandidateId={selectedSourceCollectionCandidateId}
          onFocusCandidate={(candidateId: string) => {
            const candidate = teamWorkflowCandidatesById.get(candidateId);
            if (candidate) {
              setUnresolvedNodeNotice(null);
              selectSourceCollectionCandidate(candidate);
              return;
            }
            // Beyond the loaded candidate preview — say so instead of a
            // silent no-op click.
            setUnresolvedNodeNotice(candidateId);
          }}
        />
      ) : null}
      nodeListAriaLabel={lang === "zh" ? "入库关系节点列表，可滚动查看" : "Ingestion map nodes, scroll to review"}
      nodeListItems={graphNodeCards.length || missingLinksSection ? (
        <>
          {missingLinksSection}
          {graphNodeCards}
        </>
      ) : null}
      pagination={visibleGraph ? renderSourceCollectionPagination("relations", visibleGraph.nodes.length) : null}
      emptyMessage={
        graphForSelectedSourceRun && !visibleGraph?.nodes.length
          ? (lang === "zh" ? "当前过滤条件下没有入库关系节点。" : "No ingestion map nodes match this filter.")
          : teamWorkflowCandidateGraphQuery.isPending
            ? (lang === "zh" ? "正在读取入库关系图..." : "Loading ingestion map...")
            : (lang === "zh" ? "尚未生成入库关系图。" : "No ingestion map yet.")
      }
      errors={(
        <>
          {teamWorkflowCandidateGraphQuery.error instanceof Error ? (
            <div className={styles.messageError}>{teamWorkflowCandidateGraphQuery.error.message}</div>
          ) : null}
          {selectedTeamBuildCandidateGraphError ? (
            <div className={styles.messageError}>{selectedTeamBuildCandidateGraphError.message}</div>
          ) : null}
        </>
      )}
    />
  );

}
