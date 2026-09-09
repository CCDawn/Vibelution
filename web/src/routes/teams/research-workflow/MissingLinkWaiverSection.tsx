/**
 * Shared missing-link waiver surface (缺陷⑪ write path, 缺陷⑰ shared mount).
 *
 * One renderer for BOTH waiver consumers: the source-collection graph
 * workspace panel and the workflow-canvas knowledge sideflow 证据关系 tab
 * (KnowledgeChildReadPanel). All data-testids are shared so both surfaces
 * stay covered by the same interaction contract.
 *
 * Run-id authority: the waive endpoint resolves the candidate-graph authority
 * from the passed run's frozen input snapshot (``sourceCollectionRunId``), so
 * callers MUST pass the run whose snapshot carries the SC run id that scopes
 * the ``candidate_graph`` record — on the canvas that is the knowledge
 * sideflow CHILD workflow run id; the formal URL run id has no such snapshot
 * and deterministically 404s ``graph_not_found``.
 *
 * A05: the enumerated gaps must come from the SAME run-scoped authority the
 * waive endpoint mutates (run snapshot → sourceCollectionRunId) — callers
 * pass the ``missingLinks`` of that scoped graph, never a team-latest record.
 */
import { useState } from "react";

import { waiveEvidenceGraphMissingLink } from "../../../api/researchWorkflow";
import type {
  TeamWorkflowCandidateGraphEdge,
} from "../../../api/types";
import { VNativeButton, VNativeInput } from "../../../components/vui";
import styles from "./MissingLinkWaiverSection.styles";

type Lang = "zh" | "en";

const WAIVER_JUSTIFICATION_MIN_CHARS = 8;

const missingLinkEdgeKey = (edge: TeamWorkflowCandidateGraphEdge) =>
  `${edge.sourceCandidateId}->${edge.targetCandidateId}:${edge.relation}`;

/** Same waiver detection rule as the readiness read side (fetch_evidence_graph_stats). */
export const missingLinkIsWaived = (edge: TeamWorkflowCandidateGraphEdge) =>
  Boolean(edge.waived)
  || String(edge.status || "").trim().toLowerCase() === "waived"
  || String(edge.status || "").trim().toLowerCase() === "accepted"
  || Boolean(edge.waiver);

export type MissingLinkWaiverSectionProps = {
  lang: Lang;
  teamId: string;
  /** Run whose frozen input snapshot scopes the graph authority — the
   * knowledge sideflow CHILD workflow run id on the canvas surface. */
  childWorkflowRunId: string;
  /** Gaps of the run-scoped candidate-graph authority (A05); ``null``/``undefined``
   * renders a graph-unavailable hint instead of a silent no-op. */
  missingLinks?: TeamWorkflowCandidateGraphEdge[] | null;
  /** Refetch of the run-scoped missing-link query; called after a waiver. */
  refetchGraph: () => Promise<unknown>;
};

export function MissingLinkWaiverSection(props: MissingLinkWaiverSectionProps) {
  const { lang, teamId, childWorkflowRunId, missingLinks, refetchGraph } = props;
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
    if (!childWorkflowRunId || waiverPending) return;
    setWaiverPending(true);
    setWaiverError(null);
    try {
      const response = await waiveEvidenceGraphMissingLink({
        runId: childWorkflowRunId,
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
      await refetchGraph();
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
      <div key={edgeKey} className={styles.missingLinkWaiverRow} data-testid="graph-missing-link-row">
        <div className={styles.missingLinkWaiverMeta}>
          <span className={styles.missingLinkWaiverPath}>
            {edge.relation}: {edge.sourceCandidateId} → {edge.targetCandidateId}
          </span>
          {waived ? (
            <span className={styles.missingLinkWaiverWaivedBadge} data-testid="graph-missing-link-waived">
              {lang === "zh" ? "已豁免" : "waived"}
            </span>
          ) : null}
          {!waived && childWorkflowRunId ? (
            <VNativeButton
              data-testid="graph-missing-link-waive"
              className={styles.missingLinkWaiverWaiveButton}
              disabled={waiverPending}
              title={lang === "zh" ? "人工确认接受该缺口（需理由，缺口仍保留计数）" : "Accept this gap with a confirmed waiver (justification required; the gap stays counted)"}
              onClick={() => openWaiverEditor(edge)}
            >
              {lang === "zh" ? "豁免" : "Waive"}
            </VNativeButton>
          ) : null}
        </div>
        {editorOpen ? (
          <div className={styles.missingLinkWaiverEditor} data-testid="graph-missing-link-editor">
            <VNativeInput
              aria-label={lang === "zh" ? "豁免理由" : "Waiver justification"}
              placeholder={lang === "zh"
                ? `填写豁免理由（至少 ${WAIVER_JUSTIFICATION_MIN_CHARS} 字，写入审计）`
                : `Justification (min ${WAIVER_JUSTIFICATION_MIN_CHARS} chars, audited)`}
              value={waiverJustification}
              disabled={waiverPending}
              onChange={(event) => setWaiverJustification(event.target.value)}
            />
            <div className={styles.missingLinkWaiverMeta}>
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
              <div role="alert" data-testid="graph-missing-link-error" className={styles.missingLinkWaiverError}>
                {waiverError}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    );
  };

  const gaps = missingLinks ?? [];
  if (!gaps.length) {
    if (missingLinks == null) {
      // Candidate graph missing: say so instead of a silent no-op surface (the
      // source-collection panel only mounts this section with a loaded graph).
      return (
        <section
          data-testid="graph-missing-links"
          aria-label={lang === "zh" ? "缺口清单与豁免" : "Missing links and waivers"}
          className={styles.missingLinkWaiverSection}
        >
          <div className={styles.missingLinkWaiverMeta}>
            <span className={styles.missingLinkWaiverHint} data-testid="graph-missing-link-graph-unavailable">
              {lang === "zh"
                ? "候选关系图尚未读取，暂无缺口清单。"
                : "Candidate graph not loaded; no missing-link list yet."}
            </span>
          </div>
        </section>
      );
    }
    // Loaded graph without gaps: nothing to waive, stay quiet.
    return null;
  }
  return (
    <section
      data-testid="graph-missing-links"
      aria-label={lang === "zh" ? "缺口清单与豁免" : "Missing links and waivers"}
      className={styles.missingLinkWaiverSection}
    >
      <div className={styles.missingLinkWaiverMeta}>
        <strong>{lang === "zh" ? "缺口" : "Missing links"}</strong>
        <span className={styles.missingLinkWaiverHint}>
          {lang === "zh"
            ? "豁免 = 人工接受该缺口（需理由审计）；缺口计数保留，不放宽门禁。"
            : "Waiver = human acceptance with an audited justification; the gap stays counted and the gate is not loosened."}
        </span>
        {!childWorkflowRunId ? (
          <span className={styles.missingLinkWaiverHint}>
            {lang === "zh" ? "缺少正式运行上下文，暂不能登记豁免。" : "No formal run context; waivers are unavailable here."}
          </span>
        ) : null}
      </div>
      {gaps.map(renderMissingLinkWaiverRow)}
      {waiverNotice ? (
        <div role="status" data-testid="graph-missing-link-notice" className={styles.missingLinkWaiverNotice}>
          {waiverNotice}
        </div>
      ) : null}
    </section>
  );
}
