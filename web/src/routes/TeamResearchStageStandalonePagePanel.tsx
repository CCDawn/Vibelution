/**
 * Research stage standalone page (experiment / iteration workspaces).
 * Wave 8I: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";
import { ArrowLeft, Play, Plus, RefreshCw, Users } from "lucide-react";
import { Link } from "react-router-dom";

import type { Team } from "../api/types";
import { VButton, VNativeButton } from "../components/vui";
import {
  researchDiagnosticStatusLabel,
  researchIterationLifecycleStatusLabel,
  type ExperimentPlanRecord,
  type ExperimentPlanningStatusPayload,
} from "./teams/experimentLoopModel";
import { RESEARCH_TEAM_ID } from "./TeamsRoute.canvasData";
import {
  researchWorkspaceStageRoute,
  researchWorkspaceViewLabel,
  teamWorkspaceRoute,
  type ResearchStageWorkspaceView,
} from "./teams/researchWorkspaceModel";
import type {
  ResearchStagePhaseStatus,
  ResearchStageType,
} from "./teams/source-collection/stageProjection";
import { teamChatRoomRoute } from "./teams/researchStageAgentPresentation";
import { ResearchMemoryEvidencePanel } from "./teams/ResearchMemoryEvidencePanel";
import researchStyles from "./TeamsRoute.research.styles";
import shellStyles from "./TeamsRoute.styles";

const styles = { ...shellStyles, ...researchStyles } as Record<string, string>;

type Lang = "zh" | "en";
type StageView = Exclude<ResearchStageWorkspaceView, "knowledge_collection">;

export type TeamResearchStageStandalonePagePanelProps = {
  stageView: StageView;
  lang: Lang;
  researchStagePhases: ResearchStagePhaseStatus[];
  experimentPlanningStatus: ExperimentPlanningStatusPayload | null | undefined;
  selectedTeam: Team | null | undefined;
  selectedTeamStartResearchStagePending: boolean;
  linkedChatRoomId: string;
  syncTeamChatRoomMutation: { mutate: (teamId: string) => void };
  activeTeamMemberCount: number;
  selectedTeamSyncPending: boolean;
  researchStageRoundStatusQuery: { isFetching: boolean; refetch: () => unknown };
  renderResearchStageAgentPanel: (stageType: ResearchStageType, variant?: "compact" | "page") => ReactNode;
  launchResearchStage: (stageType: ResearchStageType, mode?: "continue_or_start" | "new_round") => void;
  selectedTeamStartResearchStageError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamStartResearchStageResult: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  researchStageStartFeedbackText: (payload: any, lang: Lang, stageLabel?: string) => string;
  renderExperimentPlanningLedgerPanel: () => ReactNode;
  renderResearchLoopPanel: (activePlan: ExperimentPlanRecord | null, variant?: "experiment" | "iteration") => ReactNode;
};

export function TeamResearchStageStandalonePagePanel(props: TeamResearchStageStandalonePagePanelProps) {
  const {
    stageView,
    lang,
    researchStagePhases,
    experimentPlanningStatus,
    selectedTeam,
    selectedTeamStartResearchStagePending,
    linkedChatRoomId,
    syncTeamChatRoomMutation,
    activeTeamMemberCount,
    selectedTeamSyncPending,
    researchStageRoundStatusQuery,
    renderResearchStageAgentPanel,
    launchResearchStage,
    selectedTeamStartResearchStageError,
    selectedTeamStartResearchStageResult,
    researchStageStartFeedbackText,
    renderExperimentPlanningLedgerPanel,
    renderResearchLoopPanel,
  } = props;


    const stageType: ResearchStageType = stageView;
    const stagePhase = researchStagePhases.find((phase) => phase.stageType === stageType);
    const latestRound = stagePhase?.latestRound;
    const stage3Lifecycle = stageView === "iteration"
      ? experimentPlanningStatus?.lifecycleProjection?.stage3
      : undefined;
    const detailHeroStatus = stage3Lifecycle
      ? researchIterationLifecycleStatusLabel(stage3Lifecycle.status, lang)
      : (stagePhase?.status || (lang === "zh" ? "未启动" : "not started"));
    const detailHeroBestValue = stage3Lifecycle
      ? (stage3Lifecycle.bestCandidateId || (lang === "zh" ? "无" : "none"))
      : String(stagePhase?.roundCount ?? 0);
    const detailHeroDiagnosticStatus = stage3Lifecycle?.latestDiagnosticStatus.status || "";
    const detailHeroDiagnosticValue = stage3Lifecycle
      ? researchDiagnosticStatusLabel(detailHeroDiagnosticStatus, lang)
      : (latestRound ? `${latestRound.status} #${latestRound.roundNumber}` : (lang === "zh" ? "无" : "none"));
    const detailHeroBestTitle = stage3Lifecycle
      ? [stage3Lifecycle.bestValidatedPlanId, stage3Lifecycle.bestValidatedResultId].filter(Boolean).join(" · ")
      : undefined;
    const detailHeroDiagnosticTitle = stage3Lifecycle
      ? [
          stage3Lifecycle.latestDiagnosticStatus.title,
          detailHeroDiagnosticStatus ? `status: ${detailHeroDiagnosticStatus}` : "",
        ].filter(Boolean).join(" · ") || undefined
      : undefined;
    const config = {
      experiment: {
        eyebrow: lang === "zh" ? "挑战杯ai科研团队 / 实验阶段" : "Challenge Cup AI research team / experiment stage",
        title: lang === "zh" ? "实验规划工作台" : "Experiment planning workspace",
        description: lang === "zh"
          ? "把已审查知识转成可验证实验，先规划 baseline、指标、数据与执行记录；是否真正进入实验由用户触发。"
          : "Turns screened knowledge into verifiable experiments. Baselines, metrics, data, and run records are planned before execution.",
        primaryAction: lang === "zh" ? "启动实验规划" : "Start experiment planning",
        secondaryAction: lang === "zh" ? "重新规划实验" : "Replan experiment",
        modules: [
          [lang === "zh" ? "实验问题" : "Experiment question", lang === "zh" ? "从知识搜集结论中抽取可验证假设。" : "Extract verifiable hypotheses from collected knowledge."],
          [lang === "zh" ? "Baseline 与指标" : "Baseline and metrics", lang === "zh" ? "记录对照模型、评价指标和成功阈值。" : "Record control models, metrics, and success criteria."],
          [lang === "zh" ? "执行记录" : "Run records", lang === "zh" ? "预留训练、日志、结果和异常回写位置。" : "Reserve writeback slots for runs, logs, results, and exceptions."],
          [lang === "zh" ? "结果对比" : "Result comparison", lang === "zh" ? "后续承接消融、对照和实验结论。" : "Later receives ablations, comparisons, and conclusions."],
        ],
      },
      iteration: {
        eyebrow: lang === "zh" ? "挑战杯ai科研团队 / 迭代阶段" : "Challenge Cup AI research team / iteration stage",
        title: lang === "zh" ? "迭代优化工作台" : "Iteration workspace",
        description: lang === "zh"
          ? "把实验结论转成下一轮改进计划，记录复盘、版本、风险和交付门禁；每轮迭代由用户重新触发。"
          : "Turns experiment conclusions into the next improvement plan with review, versions, risks, and delivery gates.",
        primaryAction: lang === "zh" ? "启动迭代" : "Start iteration",
        secondaryAction: lang === "zh" ? "开启新一轮迭代" : "Start new iteration",
        modules: [
          [lang === "zh" ? "复盘结论" : "Review outcome", lang === "zh" ? "整理实验发现、失败原因和保留假设。" : "Summarize findings, failure causes, and retained hypotheses."],
          [lang === "zh" ? "版本计划" : "Version plan", lang === "zh" ? "给算法、数据、参数和文档建立版本边界。" : "Define version boundaries for algorithm, data, parameters, and docs."],
          [lang === "zh" ? "改进任务" : "Improvement tasks", lang === "zh" ? "把下一轮要做的优化拆成可追踪任务。" : "Split next improvements into traceable tasks."],
          [lang === "zh" ? "交付门禁" : "Delivery gate", lang === "zh" ? "保留挑战杯材料、复现实验和风险清单入口。" : "Reserve entries for deliverables, reproducibility, and risk list."],
        ],
      },
    }[stageView];
    const disabled = selectedTeamStartResearchStagePending
      || !selectedTeam?.teamId
      || stagePhase?.readiness?.ready === false;

    return (
      <section className={`${styles.route} ${styles.researchStagePage}`}>
        <header className={`${styles.header} ${styles.researchStagePageHeader}`}>
          <div>
            <p>{config.eyebrow}</p>
            <h1>{config.title}</h1>
          </div>
          <div className={styles.sourceCollectionPageActions}>
            {linkedChatRoomId ? (
              <Link to={teamChatRoomRoute(linkedChatRoomId, researchWorkspaceStageRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID, stageView), lang === "zh" ? "返回阶段页" : "Back to stage")}>
                <Users size={14} />
                {lang === "zh" ? "团队讨论" : "Team discussion"}
              </Link>
            ) : (
              <VButton
                type="button"
                density="compact"
                variant="secondary"
                icon={<Users size={14} />}
                onPress={() => selectedTeam?.teamId && syncTeamChatRoomMutation.mutate(selectedTeam.teamId)}
                isDisabled={!selectedTeam || activeTeamMemberCount === 0 || selectedTeamSyncPending}
              >
                {selectedTeamSyncPending
                  ? (lang === "zh" ? "同步中" : "Syncing")
                  : (lang === "zh" ? "同步团队讨论" : "Sync team discussion")}
              </VButton>
            )}
            <Link to={teamWorkspaceRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID)}>
              <ArrowLeft size={14} />
              {lang === "zh" ? "返回团队页面" : "Back to team"}
            </Link>
            <VNativeButton type="button" onClick={() => void researchStageRoundStatusQuery.refetch()} disabled={researchStageRoundStatusQuery.isFetching}>
              <RefreshCw size={14} />
              {lang === "zh" ? "刷新" : "Refresh"}
            </VNativeButton>
          </div>
        </header>
        <main className={styles.researchStagePageBody}>
          <section className={styles.researchStageHeroPanel}>
            <div>
              <strong>{stagePhase?.label || researchWorkspaceViewLabel(stageView, lang)}</strong>
              <p>{config.description}</p>
            </div>
            <div className={styles.researchStageHeroStats}>
              <span>
                {lang === "zh" ? "状态" : "Status"}
                <strong data-research-stage-detail-status={detailHeroStatus}>{detailHeroStatus}</strong>
              </span>
              <span>
                {stage3Lifecycle
                  ? (lang === "zh" ? "当前最佳" : "Current best")
                  : (lang === "zh" ? "轮次" : "Rounds")}
                <strong
                  className="min-w-0 break-all"
                  data-research-stage-detail-best={detailHeroBestValue}
                  title={detailHeroBestTitle}
                >
                  {detailHeroBestValue}
                </strong>
              </span>
              <span>
                {stage3Lifecycle
                  ? (lang === "zh" ? "最近诊断" : "Latest diagnostic")
                  : (lang === "zh" ? "最近" : "Latest")}
                <strong
                  className="min-w-0 break-all"
                  data-research-stage-detail-diagnostic={detailHeroDiagnosticValue}
                  data-research-stage-detail-diagnostic-status={detailHeroDiagnosticStatus || undefined}
                  title={detailHeroDiagnosticTitle}
                >
                  {detailHeroDiagnosticValue}
                </strong>
              </span>
            </div>
          </section>
          {renderResearchStageAgentPanel(stageType)}
          <section className={styles.researchStageActionPanel}>
            <div>
              <strong>{lang === "zh" ? "阶段启动" : "Stage launch"}</strong>
              <span>
                {stagePhase?.readiness?.reason || (lang === "zh" ? "本阶段只创建规划轮次，不自动执行实验或迭代。" : "This stage creates planning rounds only.")}
              </span>
            </div>
            <div className={styles.researchStagePageActions}>
              <VNativeButton type="button" onClick={() => launchResearchStage(stageType)} disabled={disabled}>
                <Play size={13} />
                {stagePhase?.primaryAction || config.primaryAction}
              </VNativeButton>
              <VNativeButton type="button" onClick={() => launchResearchStage(stageType, "new_round")} disabled={disabled}>
                <Plus size={13} />
                {stagePhase?.secondaryAction || config.secondaryAction}
              </VNativeButton>
            </div>
            {selectedTeamStartResearchStageError ? <div className={styles.workflowError}>{selectedTeamStartResearchStageError.message}</div> : null}
            {selectedTeamStartResearchStageResult?.stageRound.stageType === stageType ? (
              <div className={styles.workflowSuccess}>
                {researchStageStartFeedbackText(selectedTeamStartResearchStageResult, lang, researchWorkspaceViewLabel(stageView, lang))}
              </div>
            ) : null}
          </section>
          {stageView === "experiment" ? (
            <ResearchMemoryEvidencePanel
              summary={experimentPlanningStatus?.lifecycleProjection?.stage2.memoryContextSummary}
              lang={lang}
              stage="experiment"
              variant="detail"
            />
          ) : null}
          {stageView === "iteration" ? (
            <ResearchMemoryEvidencePanel
              summary={experimentPlanningStatus?.lifecycleProjection?.stage3.memoryContextSummary}
              lang={lang}
              stage="iteration"
              variant="detail"
            />
          ) : null}
          {stageView === "experiment" ? renderExperimentPlanningLedgerPanel() : null}
          {stageView === "iteration" ? renderResearchLoopPanel(experimentPlanningStatus?.activePlan ?? null, "iteration") : null}
          <section className={styles.researchStageModuleGrid} aria-label={lang === "zh" ? "阶段模块" : "Stage modules"}>
            {config.modules.map(([title, body]) => (
              <article key={title} className={styles.researchStageModuleCard}>
                <strong>{title}</strong>
                <span>{body}</span>
              </article>
            ))}
          </section>
          <section className={styles.researchStageBoundaryPanel}>
            <strong>{lang === "zh" ? "边界" : "Boundary"}</strong>
            <span>{lang === "zh" ? "不自动进入下一阶段。" : "Does not auto-transition to the next stage."}</span>
            <span>{lang === "zh" ? "不写正式 Team Knowledge / RAG / official graph。" : "Does not write formal Team Knowledge / RAG / official graph."}</span>
            <span>{lang === "zh" ? "规划结果先留在团队 workflow runtime memory。" : "Planning output remains in team workflow runtime memory."}</span>
          </section>
        </main>
      </section>
    );
}
