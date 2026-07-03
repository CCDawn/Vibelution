import { CheckCircle2, Eye, Link2 } from "lucide-react";
import { NavLink } from "react-router-dom";

import type { KnowledgeStewardOverview, KnowledgeStewardRecommendation, KnowledgeStewardWorkbenchPayload } from "../api/types";
import { VButton } from "../components/vui";
import styles from "./MemoryRoute.styles";

export type MemoryKnowledgeStewardPanelCopy = {
  knowledgeSteward: string;
  protectedAgent: string;
  missing: string;
  stewardDirectChat: string;
  stewardMission: string;
  loading: string;
  noDirectApply: string;
  openGovernanceTasks: string;
  pendingProposals: string;
  ratingSuggestions: string;
  stewardBoundary: string;
  reviewerRequired: string;
  preferredTools: string;
  allowedTools: string;
  stewardRecommendations: string;
  recommendationsOnly: string;
  stewardRecommendationHint: string;
  recommendedAction: string;
  traceability: string;
  stewardWorkbench: string;
  stewardStages: string;
  executable: string;
  stewardNextActions: string;
  acceptanceChecklist: string;
};

type MemoryKnowledgeStewardPanelProps = {
  copy: MemoryKnowledgeStewardPanelCopy;
  lang: "zh" | "en";
  knowledgeSteward: KnowledgeStewardOverview | undefined;
  recommendations: KnowledgeStewardRecommendation[];
  knowledgeStewardWorkbench: KnowledgeStewardWorkbenchPayload | undefined;
  recommendationsOnly: boolean;
  formatPolicyToken: (value: string | undefined) => string;
  onTraceTarget: (targetId: string) => void;
};

function stewardStageDisplayTitle(stageId: string | undefined, title: string | undefined, lang: "zh" | "en") {
  if (lang !== "zh") return title || stageId || "-";
  const candidates = [stageId, title].map((value) => String(value || "").trim().toLowerCase().replace(/\s+/g, "_")).filter(Boolean);
  const zh: Record<string, string> = {
    source_evidence_to_proposal: "来源提案",
    source_to_proposal: "来源提案",
    proposal_review: "提案审核",
    rating_review: "评级审核",
  };
  const match = candidates.map((key) => zh[key]).find(Boolean);
  return match || title || stageId || "-";
}

function compactInlineList(items: string[] | undefined, limit: number) {
  const visible = (items ?? []).map((item) => String(item).trim()).filter(Boolean);
  return {
    visible: visible.slice(0, limit),
    overflow: Math.max(0, visible.length - limit),
    title: visible.join(", "),
  };
}

export function MemoryKnowledgeStewardPanel({
  copy,
  lang,
  knowledgeSteward,
  recommendations,
  knowledgeStewardWorkbench,
  recommendationsOnly,
  formatPolicyToken,
  onTraceTarget,
}: MemoryKnowledgeStewardPanelProps) {
  return (
    <section className={styles.knowledgeStewardPanel} aria-label={copy.knowledgeSteward}>
      <div className={styles.managementHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.knowledgeSteward}</p>
          <h2>{knowledgeSteward?.steward.functionalDisplayName || copy.knowledgeSteward}</h2>
        </div>
        <div className={styles.managementActions}>
          <span className={knowledgeSteward?.steward.protected ? styles.statusPill : styles.statusPillMuted}>
            {knowledgeSteward?.steward.protected ? copy.protectedAgent : knowledgeSteward?.steward.status || copy.missing}
          </span>
          <NavLink className={styles.detailActionButton} to={knowledgeSteward?.steward.directChatPath || "/chat"}>
            <Link2 size={14} />
            <span>{copy.stewardDirectChat}</span>
          </NavLink>
        </div>
      </div>
      <div className={styles.stewardGrid}>
        <div className={styles.stewardMission}>
          <span>{copy.stewardMission}</span>
          <strong title={knowledgeSteward?.steward.taskProfile.mission || knowledgeSteward?.steward.displayName || copy.loading}>
            {lang === "zh" ? "知识治理" : knowledgeSteward?.steward.taskProfile.mission || knowledgeSteward?.steward.displayName || copy.loading}
          </strong>
          <small>{knowledgeSteward?.steward.taskProfile.avoidTasks || copy.noDirectApply}</small>
        </div>
        <div className={styles.stewardMetric}>
          <span>{copy.openGovernanceTasks}</span>
          <strong>{knowledgeSteward?.governance.summary.openTaskCount ?? 0}</strong>
          <small>
            {copy.pendingProposals}: {knowledgeSteward?.governance.summary.proposalReviewCount ?? 0} · {copy.ratingSuggestions}: {knowledgeSteward?.governance.summary.ratingReviewCount ?? 0}
          </small>
        </div>
        <div className={styles.stewardMetric}>
          <span>{copy.stewardBoundary}</span>
          <strong title={knowledgeSteward?.steward.permissionBoundary || "proposal_and_rating_suggestion_only"}>
            {formatPolicyToken(knowledgeSteward?.steward.permissionBoundary || "proposal_and_rating_suggestion_only")}
          </strong>
          <small>{knowledgeSteward?.operatingBoundary.formalKnowledgeRequiresReviewer ? copy.reviewerRequired : copy.noDirectApply}</small>
        </div>
      </div>
      <div className={styles.stewardToolRows}>
        {(() => {
          const preferred = compactInlineList(knowledgeSteward?.steward.toolPolicy.preferredTools, 3);
          const allowed = compactInlineList(knowledgeSteward?.steward.toolPolicy.allowedTools, 2);
          const preferredCount = (knowledgeSteward?.steward.toolPolicy.preferredTools ?? []).length;
          const allowedCount = (knowledgeSteward?.steward.toolPolicy.allowedTools ?? []).length;
          return (
            <>
              <span title={preferred.title}>{copy.preferredTools}</span>
              <code title={preferred.title}>{preferredCount} {lang === "zh" ? "项" : "items"}</code>
              <span title={allowed.title}>{copy.allowedTools}</span>
              <small title={allowed.title}>{allowedCount} {lang === "zh" ? "项" : "items"}</small>
            </>
          );
        })()}
      </div>
      {recommendations.length ? (
        <div className={styles.stewardRecommendations}>
          <div className={styles.stewardRecommendationHeader}>
            <span>{copy.stewardRecommendations}</span>
            <small>
              {recommendationsOnly ? copy.recommendationsOnly : copy.stewardRecommendationHint}
            </small>
          </div>
          {recommendations.map((recommendation) => (
            <section
              key={recommendation.recommendationId}
              className={styles.stewardRecommendationRow}
              title={[recommendation.reason, recommendation.recommendedAction, recommendation.knowledgeBaseName].filter(Boolean).join("\n")}
            >
              <span className={styles.statusPill}>{recommendation.priority}</span>
              <strong>{recommendation.title}</strong>
              <span>{recommendation.reason}</span>
              <small>
                {copy.recommendedAction}: {recommendation.recommendedAction} · {recommendation.knowledgeBaseName}
              </small>
              <VButton type="button" className={styles.detailActionButton} onClick={() => onTraceTarget(recommendation.targetId)}>
                <Eye size={14} />
                <span>{copy.traceability}</span>
              </VButton>
            </section>
          ))}
        </div>
      ) : null}
      <div className={styles.stewardWorkbench}>
        <div className={styles.stewardRecommendationHeader}>
          <span>{copy.stewardWorkbench}</span>
          <small>{copy.reviewerRequired}</small>
        </div>
        <div className={styles.stewardStageGrid} aria-label={copy.stewardStages}>
          {(knowledgeStewardWorkbench?.stages ?? []).slice(0, 2).map((stage) => (
            <section key={stage.stageId} className={styles.stewardStageCard} title={[stage.title, stage.description, stage.nextTool].filter(Boolean).join("\n")}>
              <div>
                <span className={stage.status === "clear" ? styles.statusPillMuted : styles.statusPill} title={stage.status}>
                  {formatPolicyToken(stage.status)}
                </span>
                <strong>{stewardStageDisplayTitle(stage.stageId, stage.title, lang)}</strong>
              </div>
              <p title={stage.description}>{stage.description}</p>
              <small>
                {copy.openGovernanceTasks}: {stage.openCount} · {copy.executable}: {stage.executableCount}
              </small>
              <code title={stage.nextTool}>{stage.nextTool}</code>
            </section>
          ))}
        </div>
        <div className={styles.stewardActionGrid} aria-label={copy.stewardNextActions}>
          {(knowledgeStewardWorkbench?.nextActions ?? []).slice(0, 4).map((action) => (
            <VButton key={action.actionId} type="button" className={styles.stewardActionRow} onClick={() => onTraceTarget(action.targetId)}>
              <span className={styles.statusPill}>{action.priority}</span>
              <strong>{action.title}</strong>
              <small>{action.nextStep}</small>
            </VButton>
          ))}
        </div>
        <div className={styles.stewardChecklist} aria-label={copy.acceptanceChecklist}>
          <span title={(knowledgeStewardWorkbench?.acceptanceChecklist ?? []).map((item) => item.label).join("\n")}>
            <CheckCircle2 size={13} />
            {(knowledgeStewardWorkbench?.acceptanceChecklist ?? []).length} {copy.acceptanceChecklist}
          </span>
        </div>
      </div>
    </section>
  );
}
