/**
 * Source-collection ingestion graph workspace body.
 * Wave 8L: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";

import { TeamCandidateCard } from "../components/vui/product/team-management";
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
} from "./teams/source-collection/evidenceModel";
import { sourceCollectionResultTone } from "./teams/source-collection/presentationModel";
import type { SourceCollectionStageModuleId } from "./teams/source-collection/stageProjection";
import { workflowGraphLayout } from "./TeamWorkflowGraphLayout";
import { TeamWorkflowGraphView } from "./TeamWorkflowGraphView";
import { workflowStateLabel } from "./teams/workflowPresentation";
import { TeamSourceCollectionGraphPanel } from "./TeamSourceCollectionGraphPanel";
import shellStyles from "./TeamsRoute.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamSourceCollectionGraphWorkspacePanelProps = {
  lang: Lang;
  selectedSourceCollectionRunEffectiveId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionGraphProjection: any;
  sourceCollectionProjectedGraphNodeCount: number;
  sourceCollectionProjectedGraphEdgeCount: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamWorkflowCandidateGraph: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamWorkflowCandidatesById: Map<string, any>;
  sourceCollectionSourceFilter: string;
  sourceCollectionFocusedPanelId: string;
  selectedSourceCollectionStageId: string;
  sourceCollectionExpandedPanelId: string;
  setSourceCollectionExpandedPanelId: (id: string) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionGraphStepState: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionFilterBar: (...args: any[]) => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionPageItems: (stageId: SourceCollectionStageModuleId, items: any[]) => { items: any[]; start: number; end: number };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionPagination: (stageId: SourceCollectionStageModuleId, total: number) => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamWorkflowCandidateGraphQuery: { isPending: boolean; error?: unknown };
  selectedTeamBuildCandidateGraphError: Error | null;
  selectedSourceCollectionCandidateId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectSourceCollectionCandidate: (candidate: any) => void;
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
  } = props;


    const graphForSelectedSourceRun =
      selectedSourceCollectionRunEffectiveId && sourceCollectionGraphProjection
        ? sourceCollectionProjectedGraphNodeCount > 0 ? teamWorkflowCandidateGraph : null
        : teamWorkflowCandidateGraph;
    const graphNodeSourceCategories = (graphForSelectedSourceRun?.nodes ?? []).map((node: any) => {
      const candidate = teamWorkflowCandidatesById.get(node.candidateId);
      return candidate ? sourceCollectionCandidateSourceCategory(candidate, lang) : "missing";
    });
    const graphFilterCounts = sourceCollectionFilterCounts(graphNodeSourceCategories);
    const visibleGraphNodeIds = new Set(
      (teamWorkflowCandidateGraph?.nodes ?? [])
        .filter((node: any) => {
          const candidate = teamWorkflowCandidatesById.get(node.candidateId);
          const category = candidate ? sourceCollectionCandidateSourceCategory(candidate, lang) : "missing";
          return sourceCollectionFilterMatches(sourceCollectionSourceFilter as any, category);
        })
        .map((node: any) => node.candidateId),
    );
    const visibleGraph = graphForSelectedSourceRun
      ? {
          ...graphForSelectedSourceRun,
          nodes: graphForSelectedSourceRun.nodes.filter((node: any) => visibleGraphNodeIds.has(node.candidateId)),
          edges: graphForSelectedSourceRun.edges.filter((edge: any) =>
            visibleGraphNodeIds.has(edge.sourceCandidateId) && visibleGraphNodeIds.has(edge.targetCandidateId),
          ),
          missingLinks: graphForSelectedSourceRun.missingLinks.filter((edge: any) =>
            visibleGraphNodeIds.has(edge.sourceCandidateId) || visibleGraphNodeIds.has(edge.targetCandidateId),
          ),
          unreviewedNodes: graphForSelectedSourceRun.unreviewedNodes.filter((node: any) => visibleGraphNodeIds.has(node.candidateId)),
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
      ? visibleGraph.nodes.filter((node: any) => {
          const candidate = teamWorkflowCandidatesById.get(node.candidateId);
          return candidate ? Boolean(sourceCollectionEvidenceLedgerSummary(candidate)?.missingAnchor) : false;
        }).length
      : 0;
    const visibleGraphLayout = visibleGraph && visibleGraphSummary
      ? workflowGraphLayout({ ...visibleGraph, summary: { ...visibleGraph.summary, ...visibleGraphSummary } })
      : null;
    const pagedGraphNodes = sourceCollectionPageItems("relations", visibleGraph?.nodes ?? []);
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
        graphView={visibleGraphLayout ? (
          <TeamWorkflowGraphView
            layout={visibleGraphLayout}
            markerId="source-collection-workflow-graph-arrow"
            stateLabel={(value) => workflowStateLabel(value, lang)}
          />
        ) : null}
        nodeListAriaLabel={lang === "zh" ? "入库关系节点列表，可滚动查看" : "Ingestion map nodes, scroll to review"}
        nodeListItems={visibleGraph?.nodes.length ? pagedGraphNodes.items.map((node: any) => {
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
        }) : null}
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
