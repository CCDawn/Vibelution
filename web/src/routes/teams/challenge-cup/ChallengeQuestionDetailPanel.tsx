import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Download, MoreHorizontal, RotateCcw } from "lucide-react";

import { queryKeys } from "../../../api/queryKeys";
import { fetchChallengeCupTokenUsage } from "../../../api/teamExperiment";
import { fetchHypothesisRounds } from "../../../api/hypothesisFirst";

import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import {
  VButton,
  VEmptyState,
  VErrorSummary,
  VMetricStrip,
  VDropdownMenu,
  VStateSurface,
  VStatusChip,
  VStringSelect,
  VSurface,
} from "../../../components/vui";
import { TeamHypothesisRoundTimeline } from "../TeamHypothesisRoundTimeline";
import { TeamMeetingRoundPanel } from "../TeamMeetingRoundPanel";
import { useShellI18n } from "../../../i18n/useShellI18n";
import { QuestionLineagePanel } from "../research-workflow/QuestionLineagePanel";
import { ChallengeQuestionAnalysisSection } from "./ChallengeQuestionAnalysisSection";
import { ChallengeQuestionEvidenceSection } from "./ChallengeQuestionEvidenceSection";
import { ChallengeQuestionPlanSection } from "./ChallengeQuestionPlanSection";
import { ChallengeQuestionRegisterDialog } from "./ChallengeQuestionRegisterDialog";
import { ChallengeQuestionRunResetDialog } from "./ChallengeQuestionRunResetDialog";
import { ChallengeQuestionStageZoneHeading } from "./ChallengeQuestionStageZoneHeading";
import {
  deriveChallengeQuestionStageProjection,
  stageTwoStatusCopy,
  stageZoneTitle,
} from "./challengeQuestionStageModel";
import { HypothesisSelectionPanel } from "./HypothesisSelectionPanel";
import { ChallengeQuestionTokenUsage } from "./ChallengeTokenUsageStrip";
import { isTokenUsageOverview, questionTokenUsage } from "./challengeTokenUsageModel";
import {
  exportQuestionArchivePage,
} from "./questionArchiveExport";
import {
  challengeRecordStatusLabel,
  ChallengeQuestionSectionHeading,
} from "./ChallengeQuestionDetailPrimitives";
import css from "./ChallengeQuestionDetailPanel.styles";

export type ChallengeQuestionDetailPanelProps = {
  requestedQuestionId: string;
  teamId?: string;
  detail?: ChallengeQuestionRunDetailPayload;
  isLoading: boolean;
  errorMessage?: string;
  onClose: () => void;
  /** Selected historical run id (empty = latest); revisions become reviewable. */
  selectedRunId?: string;
  onSelectRunId?: (runId: string) => void;
  onNavigateToNode?: (nodeId: string) => void;
  /** Workflow archive mode: summary-first, read-only, and safe to mount in the wide center pane. */
  readOnlyArchive?: boolean;
  archiveSummary?: {
    selectedHypotheses?: number;
    effectiveReviews: number;
    retryAttempts: number;
    collectionRequests: number;
    reviewHistory?: Array<{
      id: string;
      round: number;
      status: string;
      digestAvailable: boolean;
      retryAttempts: number;
    }>;
  };
};

/**
 * Two-stage anchor directory (descriptive names, never ordinals). Zone one
 * holds the hypothesis-generation and knowledge-chain artifacts; zone two
 * holds the research-plan/experiment artifacts, which stay visible but carry
 * the stage-two inactive semantics.
 */
const DETAIL_ANCHOR_GROUPS_ZH = [
  {
    zone: "hypothesis" as const,
    anchors: [
      ["question-agent", "题目与接单"],
      ["sources", "来源与证据"],
      ["lineage", "全链谱系"],
      ["hypotheses", "候选假设"],
      ["reviews", "七维评价"],
      ["selection", "选择"],
      ["hypothesis-first-selection", "假说选择"],
      ["hypothesis-first-meeting", "评审讨论"],
      ["hypothesis-first-rounds", "评审轮次"],
    ],
  },
  {
    zone: "plan" as const,
    anchors: [
      ["plan", "研究计划"],
      ["feedback", "人工审核"],
      ["artifact", "最终工件"],
    ],
  },
] as const;

const DETAIL_ANCHOR_GROUPS_EN = [
  {
    zone: "hypothesis" as const,
    anchors: [
      ["question-agent", "Question & agent"],
      ["sources", "Sources & evidence"],
      ["lineage", "Question lineage"],
      ["hypotheses", "Candidate hypotheses"],
      ["reviews", "Seven-dim review"],
      ["selection", "Selection"],
      ["hypothesis-first-selection", "Hypothesis selection"],
      ["hypothesis-first-meeting", "Review discussion"],
      ["hypothesis-first-rounds", "Review rounds"],
    ],
  },
  {
    zone: "plan" as const,
    anchors: [
      ["plan", "Research plan"],
      ["feedback", "Human review"],
      ["artifact", "Final artifact"],
    ],
  },
] as const;

export function ChallengeQuestionDetailPanel({
  requestedQuestionId,
  teamId = "",
  detail,
  isLoading,
  errorMessage = "",
  onClose,
  selectedRunId = "",
  onSelectRunId,
  onNavigateToNode,
  readOnlyArchive = false,
  archiveSummary,
}: ChallengeQuestionDetailPanelProps) {
  const [reviseDialogOpen, setReviseDialogOpen] = useState(false);
  const [resetDialogOpen, setResetDialogOpen] = useState(false);
  const [archiveExportState, setArchiveExportState] = useState<"idle" | "pending" | "error">("idle");
  const [archiveExportError, setArchiveExportError] = useState("");
  const { lang } = useShellI18n();
  const isZh = lang === "zh";
  const detailAnchorGroups = isZh ? DETAIL_ANCHOR_GROUPS_ZH : DETAIL_ANCHOR_GROUPS_EN;
  const stageProjection = deriveChallengeQuestionStageProjection(detail);
  const tokenUsageQuery = useQuery({
    queryKey: queryKeys.challengeCupTokenUsage(teamId),
    queryFn: () => fetchChallengeCupTokenUsage(teamId),
    enabled: !readOnlyArchive && Boolean(teamId.trim()),
    staleTime: 15_000,
    retry: false,
  });
  const tokenUsageOverview = isTokenUsageOverview(tokenUsageQuery.data);
  const questionUsage = tokenUsageOverview
    ? questionTokenUsage(tokenUsageQuery.data, requestedQuestionId)
    : null;
  const tokenUsageState = tokenUsageQuery.isPending
    ? "pending"
    : tokenUsageQuery.isError || !tokenUsageOverview
      ? "error"
      : "success";
  const resetTargetTeamId = detail?.teamId || teamId;
  const canResetQuestionRun = Boolean(resetTargetTeamId.trim() && requestedQuestionId.trim());
  const archiveExportPending = archiveExportState === "pending";
  /**
   * Single-file HTML artifact page export (judge/demo handoff). Runs from the
   * in-memory detail payload; the review-round ledger is fetched lazily and a
   * failure only degrades that section instead of blocking the export.
   */
  const handleExportArchivePage = () => {
    if (!detail || archiveExportState === "pending") return;
    setArchiveExportState("pending");
    setArchiveExportError("");
    const exportTeamId = detail.teamId || teamId;
    void exportQuestionArchivePage({
      detail,
      teamId: exportTeamId,
      lang: isZh ? "zh" : "en",
      fetchRounds: fetchHypothesisRounds,
    })
      .then(() => {
        setArchiveExportState("idle");
      })
      .catch((error: unknown) => {
        setArchiveExportState("error");
        setArchiveExportError(error instanceof Error ? error.message : String(error));
      });
  };
  const questionResetMenu = (canResetQuestionRun || detail) ? (
    <VDropdownMenu
      aria-label={isZh ? "本题更多操作" : "More actions for this question"}
      trigger={
        <VButton
          density="compact"
          variant="secondary"
          icon={<MoreHorizontal size={15} aria-hidden="true" />}
          aria-label={isZh ? "本题更多操作" : "More actions for this question"}
        >
          {isZh ? "更多操作" : "More actions"}
        </VButton>
      }
      items={[
        ...(detail ? [{
          id: "export-question-archive",
          label: archiveExportPending
            ? (isZh ? "正在导出产物页…" : "Exporting artifact page…")
            : (isZh ? "导出产物页" : "Export artifact page"),
          icon: <Download size={15} aria-hidden="true" />,
          disabled: archiveExportPending,
          onSelect: handleExportArchivePage,
        }] : []),
        ...(canResetQuestionRun ? [{
          id: "reset-question-run",
          label: isZh ? "重置本题运行" : "Reset this question run",
          icon: <RotateCcw size={15} aria-hidden="true" />,
          danger: true,
          onSelect: () => setResetDialogOpen(true),
        }] : []),
      ]}
    />
  ) : null;
  const resetDialog = canResetQuestionRun ? (
    <ChallengeQuestionRunResetDialog
      open={resetDialogOpen}
      onOpenChange={setResetDialogOpen}
      teamId={resetTargetTeamId}
      questionId={requestedQuestionId}
      onCompleted={(targetNodeId) => onNavigateToNode?.(targetNodeId)}
    />
  ) : null;

  if (isLoading) {
    return (
      <VSurface className={css.state} tone="workspace">
        <VStateSurface
          title={isZh
            ? `正在读取 ${requestedQuestionId} 的${readOnlyArchive ? "题目档案" : "审核工件"}`
            : `Loading ${readOnlyArchive ? "question archive" : "review artifacts"} for ${requestedQuestionId}`}
          tone="loading"
        />
      </VSurface>
    );
  }
  if (errorMessage || !detail) {
    if (readOnlyArchive) {
      return (
        <VSurface className={css.archiveError} tone="workspace" data-testid="question-archive-error">
          <VErrorSummary
            tone="warning"
            label={requestedQuestionId ? `${requestedQuestionId} · ${isZh ? "题目档案 · 只读" : "Question archive · read only"}` : (isZh ? "题目档案 · 只读" : "Question archive · read only")}
            summary={isZh
              ? "题目档案暂不可用，但不会覆盖或阻断当前任务。返回当前任务后可继续处理流程。"
              : "The question archive is temporarily unavailable, but the current task remains intact."}
          />
          <VButton variant="primary" onPress={onClose}>
            {isZh ? "返回当前任务" : "Back to current task"}
          </VButton>
        </VSurface>
      );
    }
    const operableTeamId = detail?.teamId || teamId;
    const canContinueReview = Boolean(operableTeamId && requestedQuestionId);
    return (
      <VSurface className={css.state} tone="workspace">
        {canContinueReview ? (
          <VErrorSummary
            data-testid="question-detail-fail-soft-warning"
            tone="warning"
            label={
              requestedQuestionId
                ? `${requestedQuestionId} · ${isZh ? "验收档案" : "Acceptance artifacts"}`
                : (isZh ? "验收档案" : "Acceptance artifacts")
            }
            summary={
              isZh
                ? "验收档案暂不可用，假说评审仍可继续；如需从头验收，请在下方“更多操作”中重置本题运行。"
                : "Acceptance artifacts are temporarily unavailable; hypothesis review can continue. To restart from the beginning, use More actions below to reset this question run."
            }
            details={errorMessage ? <code>{errorMessage}</code> : undefined}
            openLabel={isZh ? "技术细节" : "Technical details"}
            closeLabel={isZh ? "收起" : "Hide details"}
          />
        ) : (
          <>
            <VEmptyState
              title={isZh
                ? `${requestedQuestionId || "该题"} 的验收档案暂不可用`
                : `Acceptance artifacts unavailable for ${requestedQuestionId || "this question"}`}
            />
            {errorMessage ? (
              <details className={css.techDetails}>
                <summary>{isZh ? "技术细节" : "Technical details"}</summary>
                <code>{errorMessage}</code>
              </details>
            ) : null}
          </>
        )}
        {canContinueReview ? (
          <>
            <div className={css.headerActions}>{questionResetMenu}</div>
            <div className={css.section} data-testid="question-detail-fail-soft-ops">
              <HypothesisSelectionPanel
                teamId={operableTeamId}
                questionId={requestedQuestionId}
                lang={lang}
                onOpenReviewMeeting={onNavigateToNode}
              />
              <TeamMeetingRoundPanel teamId={operableTeamId} questionId={requestedQuestionId} />
            </div>
          </>
        ) : null}
        <VButton density="compact" onPress={onClose} variant="secondary">
          {isZh ? "返回题目列表" : "Back to question list"}
        </VButton>
        {resetDialog}
      </VSurface>
    );
  }

  const { output, record } = detail;

  return (
    <main
      className={`${css.workspace} ${readOnlyArchive ? css.archiveWorkspace : ""}`}
      aria-label={isZh ? `${detail.questionId} ${readOnlyArchive ? "题目档案" : "单题验收"}` : `${detail.questionId} ${readOnlyArchive ? "question archive" : "acceptance"}`}
      data-testid={readOnlyArchive ? "question-archive" : undefined}
    >
      <header className={css.header}>
        <div>
          <span className={css.eyebrow}>{isZh ? (readOnlyArchive ? "题目档案 · 只读" : "单题验收") : (readOnlyArchive ? "Question archive · read only" : "Question acceptance")}</span>
          <h2>{detail.questionId}: {output.question_en}</h2>
          {output.question_zh ? <p className={css.questionZh}>{output.question_zh}</p> : null}
        </div>
        <div className={css.headerActions}>
          <VStatusChip tone={record.status === "approved" ? "accent" : "warning"}>
            {challengeRecordStatusLabel(record.status, isZh ? "zh" : "en")}
          </VStatusChip>
          {onSelectRunId && detail.runs.length > 1 ? (
            <label className={css.runSwitcher} data-testid="question-run-switcher">
              <span>{isZh ? "查看 run" : "Run"}</span>
              <VStringSelect
                value={selectedRunId || detail.selectedRunId}
                onValueChange={(value) => onSelectRunId(value)}
                ariaLabel={isZh ? "选择要查看的 run" : "Select run to view"}
                options={detail.runs.map((run) => ({
                  value: run.runId,
                  label: `${run.runId}${run.runId === detail.selectedRunId ? (isZh ? "（最新）" : " (latest)") : ""}`,
                }))}
              />
            </label>
          ) : null}
          {!readOnlyArchive && record.status === "needs_revision" ? (
            <VButton density="compact" variant="primary" onPress={() => setReviseDialogOpen(true)}>
              {isZh ? "登记修订产出" : "Register revision output"}
            </VButton>
          ) : null}
          {readOnlyArchive ? (
            <VButton
              density="compact"
              variant="secondary"
              data-testid="question-archive-export"
              icon={<Download size={15} aria-hidden="true" />}
              isPending={archiveExportPending}
              onPress={handleExportArchivePage}
            >
              {archiveExportPending
                ? (isZh ? "导出中…" : "Exporting…")
                : (isZh ? "导出产物页" : "Export artifact page")}
            </VButton>
          ) : null}
          {readOnlyArchive ? null : questionResetMenu}
          <VButton density="compact" icon={<ArrowLeft size={15} aria-hidden="true" />} onPress={onClose} variant="secondary">
            {isZh ? (readOnlyArchive ? "返回当前任务" : "返回题目列表") : (readOnlyArchive ? "Back to current task" : "Back to question list")}
          </VButton>
        </div>
      </header>

      {archiveExportState === "error" ? (
        <div className={css.headerActions} data-testid="question-archive-export-error">
          <VErrorSummary
            tone="warning"
            label={isZh ? "导出产物页失败" : "Artifact page export failed"}
            summary={isZh
              ? "产物页未导出，当前任务不受影响；可通过“导出产物页”重试。"
              : "The artifact page was not exported; the current task is unaffected. Retry via Export artifact page."}
            details={archiveExportError ? <code>{archiveExportError}</code> : undefined}
            openLabel={isZh ? "技术细节" : "Technical details"}
            closeLabel={isZh ? "收起" : "Hide details"}
          />
        </div>
      ) : null}

      <nav className={css.anchorNav} aria-label={isZh ? (readOnlyArchive ? "题目档案章节" : "单题验收章节") : (readOnlyArchive ? "Question archive sections" : "Acceptance sections")}>
        {readOnlyArchive
          ? ([
              ["hypotheses", isZh ? "假说摘要" : "Hypothesis summary"],
              ["lineage", isZh ? "全链谱系" : "Question lineage"],
              ["hypothesis-first-rounds", isZh ? "评审历程" : "Review history"],
            ] as const).map(([id, label]) => (
              <a href={`#${id}`} key={id}>{label}</a>
            ))
          : detailAnchorGroups.map((group) => (
            <div className={css.anchorGroup} key={group.zone} data-stage-zone={group.zone}>
              <span className={css.anchorGroupTitle}>
                {group.zone === "plan"
                  ? `${stageZoneTitle(group.zone, lang)} · ${stageTwoStatusCopy(lang)}`
                  : stageZoneTitle(group.zone, lang)}
              </span>
              <span className={css.anchorGroupLinks}>
                {group.anchors.map(([id, label]) => (
                  <a href={`#${id}`} key={id}>{label}</a>
                ))}
              </span>
            </div>
          ))}
      </nav>

      {readOnlyArchive ? (
        <>
          <VMetricStrip
            ariaLabel={isZh ? "题目档案摘要" : "Question archive summary"}
            className={css.archiveMetrics}
            metrics={[
              { id: "selected", label: isZh ? "采用假说" : "Selected", value: archiveSummary?.selectedHypotheses ?? Number(Boolean(output.selection.selected_hypothesis_id)) },
              { id: "reviews", label: isZh ? "有效评审" : "Reviews", value: archiveSummary?.effectiveReviews ?? "—" },
              { id: "retries", label: isZh ? "失败重试" : "Retries", value: archiveSummary?.retryAttempts ?? "—" },
              { id: "collections", label: isZh ? "资料请求" : "Collections", value: archiveSummary?.collectionRequests ?? "—" },
            ]}
          />
          <div className={css.archiveGrid}>
            <ChallengeQuestionAnalysisSection output={output} lang={lang} summaryOnly />
            <QuestionArchiveReviewTimeline
              history={archiveSummary?.reviewHistory ?? []}
              lang={lang}
            />
          </div>
          <section className={css.section} id="lineage" data-testid="question-lineage-section">
            <ChallengeQuestionSectionHeading
              index="03"
              title={isZh ? "全链谱系 · 只读" : "Question lineage · read only"}
            />
            <QuestionLineagePanel teamId={resetTargetTeamId} questionId={requestedQuestionId} />
          </section>
        </>
      ) : (
        <>
          {teamId ? <ChallengeQuestionTokenUsage lang={lang} usage={questionUsage} state={tokenUsageState} /> : null}
          <ChallengeQuestionStageZoneHeading
            zone="hypothesis"
            stageOneStatus={stageProjection.stageOne}
            lang={lang}
          />
          <ChallengeQuestionEvidenceSection detail={detail} lang={lang} />
          <section className={css.section} id="lineage" data-testid="question-lineage-section">
            <ChallengeQuestionSectionHeading
              index="02"
              title={isZh ? "全链谱系 · 只读" : "Question lineage · read only"}
            />
            <QuestionLineagePanel teamId={detail.teamId || teamId} questionId={detail.questionId || requestedQuestionId} />
          </section>
          <ChallengeQuestionAnalysisSection output={output} lang={lang} />
          <HypothesisSelectionPanel
            teamId={detail.teamId}
            questionId={detail.questionId}
            lang={lang}
            onOpenReviewMeeting={onNavigateToNode}
          />
          <TeamMeetingRoundPanel teamId={detail.teamId} questionId={detail.questionId} />
          <TeamHypothesisRoundTimeline teamId={detail.teamId} questionId={detail.questionId} />
          <ChallengeQuestionStageZoneHeading
            zone="plan"
            lang={lang}
          />
          <ChallengeQuestionPlanSection detail={detail} lang={lang} />
        </>
      )}

      {!readOnlyArchive && reviseDialogOpen ? (
        <ChallengeQuestionRegisterDialog
          teamId={detail.teamId}
          initialMode="register"
          parentRunId={record.runId}
          questionIdHint={detail.questionId}
          onClose={() => setReviseDialogOpen(false)}
          lang={lang}
        />
      ) : null}
      {readOnlyArchive ? null : resetDialog}
    </main>
  );
}

function QuestionArchiveReviewTimeline({
  history,
  lang,
}: {
  history: Array<{
    id: string;
    round: number;
    status: string;
    digestAvailable: boolean;
    retryAttempts: number;
  }>;
  lang: "zh" | "en";
}) {
  const isZh = lang === "zh";
  return (
    <section className={css.section} id="hypothesis-first-rounds">
      <ChallengeQuestionSectionHeading
        index="02"
        title={isZh ? "评审历程" : "Review history"}
      />
      {history.length ? (
        <ol className={css.archiveTimeline}>
          {history.map((item) => {
            const statusLabel = item.status === "closed"
              ? (isZh ? "已闭环" : "Closed")
              : item.status === "open"
                ? (isZh ? "进行中" : "Active")
                : (isZh ? "待确认" : "Awaiting review");
            return (
              <li className={css.archiveTimelineItem} key={item.id}>
                <span className={css.archiveTimelineMarker} aria-hidden="true" />
                <div>
                  <div className={css.archiveTimelineTopline}>
                    <strong>{isZh ? `第 ${item.round} 轮` : `Round ${item.round}`}</strong>
                    <VStatusChip tone={item.status === "closed" ? "success" : "accent"}>
                      {statusLabel}
                    </VStatusChip>
                  </div>
                  <p className={css.archiveTimelineDetail}>
                    {item.digestAvailable
                      ? (isZh ? "评审结论与纪要已归档。" : "Review conclusion and digest archived.")
                      : (isZh ? "评审仍在进行或等待纪要。" : "Review is active or awaiting its digest.")}
                    {item.retryAttempts > 0
                      ? (isZh ? ` 含 ${item.retryAttempts} 次失败重试。` : ` Includes ${item.retryAttempts} failed retries.`)
                      : ""}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className={css.archiveHint}>{isZh ? "尚无有效评审记录。" : "No effective review history yet."}</p>
      )}
    </section>
  );
}
