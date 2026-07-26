/**
 * Research loop template / evidence / decision panel.
 * Wave 8J: extracted from TeamsRoute.tsx for domain componentization.
 */
import { AlertTriangle, Plus, RefreshCw, Save, Send } from "lucide-react";

import type { Team } from "../api/types";
import { VNativeButton, VNativeInput, VNativeSelect } from "../components/vui";
import {
  RESEARCH_LOOP_DECISION_VALUES,
  RESEARCH_LOOP_EVIDENCE_STATUSES,
  type ExperimentPlanRecord,
  type ResearchLoopCreateDraft,
  type ResearchLoopDecisionDraft,
  type ResearchLoopDecisionValue,
  type ResearchLoopEvidenceDraft,
  type ResearchLoopEvidenceStatus,
  type ResearchLoopRecord,
  type ResearchLoopStatusPayload,
  type ResearchLoopTemplatesPayload,
} from "./teams/experimentLoopModel";
import researchStyles from "./TeamsRoute.research.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...researchStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamResearchLoopPanelProps = {
  activePlan: ExperimentPlanRecord | null;
  variant?: "experiment" | "iteration";
  lang: Lang;
  selectedTeam: Team | null | undefined;
  researchLoopStatus: ResearchLoopStatusPayload | null | undefined;
  researchLoopTemplatesPayload: ResearchLoopTemplatesPayload | null | undefined;
  selectedResearchLoopTemplateId: string;
  setSelectedResearchLoopTemplateId: (id: string) => void;
  researchLoopCreateDraft: ResearchLoopCreateDraft;
  setResearchLoopCreateDraft: (updater: (draft: ResearchLoopCreateDraft) => ResearchLoopCreateDraft) => void;
  researchLoopEvidenceDraft: ResearchLoopEvidenceDraft;
  setResearchLoopEvidenceDraft: (updater: (draft: ResearchLoopEvidenceDraft) => ResearchLoopEvidenceDraft) => void;
  researchLoopDecisionDraft: ResearchLoopDecisionDraft;
  setResearchLoopDecisionDraft: (updater: (draft: ResearchLoopDecisionDraft) => ResearchLoopDecisionDraft) => void;
  sourceCollectionDraft: { goal: string };
  researchLoopStatusQuery: { isFetching: boolean; refetch: () => unknown };
  selectedTeamCreateResearchLoopPending: boolean;
  selectedTeamCreateResearchLoopError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamCreateResearchLoopResult: any;
  selectedTeamRecordResearchLoopEvidencePending: boolean;
  selectedTeamRecordResearchLoopEvidenceError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamRecordResearchLoopEvidenceResult: any;
  selectedTeamRecordResearchLoopDecisionPending: boolean;
  selectedTeamRecordResearchLoopDecisionError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamRecordResearchLoopDecisionResult: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  materializeResearchLoopIterationDesignMutation: any;
  createResearchLoopFromWorkspace: (plan: ExperimentPlanRecord | null) => void;
  recordResearchLoopEvidenceFromWorkspace: (loop: ResearchLoopRecord) => void;
  recordResearchLoopDecisionFromWorkspace: (loop: ResearchLoopRecord) => void;
};

export function TeamResearchLoopPanel(props: TeamResearchLoopPanelProps) {
  const {
    activePlan,
    variant = "experiment",
    lang,
    selectedTeam,
    researchLoopStatus,
    researchLoopTemplatesPayload,
    selectedResearchLoopTemplateId,
    setSelectedResearchLoopTemplateId,
    researchLoopCreateDraft,
    setResearchLoopCreateDraft,
    researchLoopEvidenceDraft,
    setResearchLoopEvidenceDraft,
    researchLoopDecisionDraft,
    setResearchLoopDecisionDraft,
    sourceCollectionDraft,
    researchLoopStatusQuery,
    selectedTeamCreateResearchLoopPending,
    selectedTeamCreateResearchLoopError,
    selectedTeamCreateResearchLoopResult,
    selectedTeamRecordResearchLoopEvidencePending,
    selectedTeamRecordResearchLoopEvidenceError,
    selectedTeamRecordResearchLoopEvidenceResult,
    selectedTeamRecordResearchLoopDecisionPending,
    selectedTeamRecordResearchLoopDecisionError,
    selectedTeamRecordResearchLoopDecisionResult,
    materializeResearchLoopIterationDesignMutation,
    createResearchLoopFromWorkspace,
    recordResearchLoopEvidenceFromWorkspace,
    recordResearchLoopDecisionFromWorkspace,
  } = props;


    const loopStatusPayload =
      selectedTeamRecordResearchLoopDecisionResult?.status
      ?? selectedTeamRecordResearchLoopEvidenceResult?.status
      ?? selectedTeamCreateResearchLoopResult?.status
      ?? researchLoopStatus;
    const templates = researchLoopTemplatesPayload?.templates?.length
      ? researchLoopTemplatesPayload.templates
      : loopStatusPayload?.templates ?? [];
    const selectedTemplate =
      templates.find((template: any) => template.templateId === selectedResearchLoopTemplateId)
      ?? templates.find((template: any) => template.templateId === loopStatusPayload?.activeLoop?.templateId)
      ?? templates[0]
      ?? null;
    const activeLoop = loopStatusPayload?.activeLoop ?? null;
    const activeTemplate =
      activeLoop?.templateSnapshot
      ?? templates.find((template: any) => template.templateId === activeLoop?.templateId)
      ?? selectedTemplate;
    const evidenceOptions = activeLoop?.readiness.requiredEvidenceTypes?.length
      ? activeLoop.readiness.requiredEvidenceTypes
      : selectedTemplate?.requiredEvidenceTypes ?? [];
    const currentEvidenceType =
      researchLoopEvidenceDraft.evidenceType
      || activeLoop?.readiness.missingEvidenceTypes?.[0]
      || evidenceOptions[0]
      || "";
    const decisionNeedsReady = researchLoopDecisionDraft.decision === "promote_to_iteration" || researchLoopDecisionDraft.decision === "accept_for_writeup";
    const canCreateLoop = Boolean(
      selectedTeam?.teamId
      && selectedTemplate
      && !selectedTeamCreateResearchLoopPending
      && (researchLoopCreateDraft.researchQuestion.trim() || activePlan?.goal || activePlan?.topic || sourceCollectionDraft.goal),
    );
    const canRecordEvidence = Boolean(
      selectedTeam?.teamId
      && activeLoop
      && currentEvidenceType
      && !selectedTeamRecordResearchLoopEvidencePending
      && (
        researchLoopEvidenceDraft.summary.trim()
        || researchLoopEvidenceDraft.metricValue.trim()
        || researchLoopEvidenceDraft.artifactRef.trim()
        || researchLoopEvidenceDraft.datasetRefs.trim()
        || researchLoopEvidenceDraft.environmentRefs.trim()
        || researchLoopEvidenceDraft.logRefs.trim()
        || researchLoopEvidenceDraft.commandPreview.trim()
      ),
    );
    const canRecordDecision = Boolean(
      selectedTeam?.teamId
      && activeLoop
      && researchLoopDecisionDraft.rationale.trim()
      && !selectedTeamRecordResearchLoopDecisionPending
      && (!decisionNeedsReady || activeLoop.readiness.readyForDecision),
    );
    const latestProposal = activeLoop?.iterationProposals?.[activeLoop.iterationProposals.length - 1] ?? null;
    const latestDecision = activeLoop?.decisions?.[activeLoop.decisions.length - 1] ?? null;
    const pendingDesignProposal = loopStatusPayload?.pendingDesignProposals?.[0] ?? null;
    const materializingPendingDesign = Boolean(
      pendingDesignProposal
      && materializeResearchLoopIterationDesignMutation.isPending
      && materializeResearchLoopIterationDesignMutation.variables?.teamId === selectedTeam?.teamId
      && materializeResearchLoopIterationDesignMutation.variables?.proposalId === pendingDesignProposal.proposalId
    );
    const panelTitle = variant === "iteration"
      ? (lang === "zh" ? "实验迭代决策" : "Experiment iteration decision")
      : (lang === "zh" ? "Research Loop 模板" : "Research Loop template");

    return (
      <section className={styles.researchLoopPanel} aria-label={panelTitle}>
        <div className={styles.researchLoopHeader}>
          <div>
            <strong>{panelTitle}</strong>
            <span>
              {loopStatusPayload?.nextActions?.[0]?.label
                || (researchLoopStatusQuery.isFetching
                  ? (lang === "zh" ? "读取实验迭代状态" : "Loading research loop")
                  : (lang === "zh" ? "选择模板后登记证据和迭代决策" : "Select a template, then record evidence and decisions"))}
            </span>
          </div>
          <VNativeButton type="button" onClick={() => void researchLoopStatusQuery.refetch()} disabled={researchLoopStatusQuery.isFetching}>
            <RefreshCw size={13} />
            {lang === "zh" ? "刷新" : "Refresh"}
          </VNativeButton>
        </div>
        <div className={styles.researchLoopStats}>
          <span>
            {lang === "zh" ? "循环" : "Loops"}
            <strong>{loopStatusPayload?.summary.totalLoopCount ?? 0}</strong>
          </span>
          <span>
            {lang === "zh" ? "可决策" : "Decision"}
            <strong>{loopStatusPayload?.summary.readyForDecisionCount ?? 0}</strong>
          </span>
          <span>
            {lang === "zh" ? "可迭代" : "Iteration"}
            <strong>{loopStatusPayload?.summary.readyForIterationCount ?? 0}</strong>
          </span>
          <span>
            {lang === "zh" ? "执行边界" : "Execution"}
            <strong>{loopStatusPayload?.boundaries?.autoExecution ? "auto" : "manual"}</strong>
          </span>
        </div>
        <div className={styles.researchLoopTemplateBar}>
          <label>
            <span>{lang === "zh" ? "验证模板" : "Template"}</span>
            <VNativeSelect value={selectedTemplate?.templateId || selectedResearchLoopTemplateId} onChange={(event) => setSelectedResearchLoopTemplateId(event.target.value)}>
              {templates.map((template: any) => (
                <option key={template.templateId} value={template.templateId}>
                  {lang === "zh" ? template.labelZh : template.label}
                </option>
              ))}
            </VNativeSelect>
          </label>
          <label>
            <span>{lang === "zh" ? "研究问题" : "Research question"}</span>
            <VNativeInput
              value={researchLoopCreateDraft.researchQuestion}
              onChange={(event) => setResearchLoopCreateDraft((draft) => ({ ...draft, researchQuestion: event.target.value }))}
              placeholder={activePlan?.goal || activePlan?.topic || sourceCollectionDraft.goal}
            />
          </label>
          <label>
            <span>{lang === "zh" ? "约束" : "Constraints"}</span>
            <VNativeInput
              value={researchLoopCreateDraft.constraints}
              onChange={(event) => setResearchLoopCreateDraft((draft) => ({ ...draft, constraints: event.target.value }))}
              placeholder={lang === "zh" ? "算力、数据、环境或复现边界" : "Compute, data, environment, or reproducibility boundary"}
            />
          </label>
          <VNativeButton type="button" onClick={() => createResearchLoopFromWorkspace(activePlan)} disabled={!canCreateLoop}>
            <Plus size={13} />
            {selectedTeamCreateResearchLoopPending ? (lang === "zh" ? "创建中" : "Creating") : (lang === "zh" ? "创建 loop" : "Create loop")}
          </VNativeButton>
        </div>
        {selectedTemplate ? (
          <div className={styles.researchLoopTemplateSummary}>
            <strong>{lang === "zh" ? selectedTemplate.labelZh : selectedTemplate.label}</strong>
            <span>{selectedTemplate.description}</span>
            <div>
              {selectedTemplate.requiredEvidenceTypes.map((item: any) => (
                <small key={item}>{item}</small>
              ))}
            </div>
          </div>
        ) : null}
        {activeLoop ? (
          <>
            <div className={styles.researchLoopActive}>
              <div>
                <span>{lang === "zh" ? "Active loop" : "Active loop"}</span>
                <strong>{activeLoop.title || activeTemplate?.labelZh || activeLoop.loopId}</strong>
                <small>{activeLoop.researchQuestion}</small>
              </div>
              <div className={styles.researchLoopStatusPills}>
                <span>{activeLoop.status}</span>
                <span>{activeTemplate?.templateKind || activeLoop.templateKind}</span>
                <span>{activeLoop.readiness.readyForDecision ? (lang === "zh" ? "证据齐备" : "evidence ready") : (lang === "zh" ? "证据缺口" : "evidence gap")}</span>
              </div>
            </div>
            <div className={styles.researchLoopEvidenceForm}>
              <label>
                <span>{lang === "zh" ? "证据类型" : "Evidence type"}</span>
                <VNativeSelect
                  value={currentEvidenceType}
                  onChange={(event) => setResearchLoopEvidenceDraft((draft) => ({ ...draft, evidenceType: event.target.value }))}
                >
                  {evidenceOptions.map((item: any) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </VNativeSelect>
              </label>
              <label>
                <span>{lang === "zh" ? "状态" : "Status"}</span>
                <VNativeSelect
                  value={researchLoopEvidenceDraft.status}
                  onChange={(event) => setResearchLoopEvidenceDraft((draft) => ({ ...draft, status: event.target.value as ResearchLoopEvidenceStatus }))}
                >
                  {RESEARCH_LOOP_EVIDENCE_STATUSES.map((status: any) => (
                    <option key={status} value={status}>{status}</option>
                  ))}
                </VNativeSelect>
              </label>
              <label>
                <span>{lang === "zh" ? "指标" : "Metric"}</span>
                <VNativeInput
                  value={researchLoopEvidenceDraft.metricValue}
                  onChange={(event) => setResearchLoopEvidenceDraft((draft) => ({ ...draft, metricValue: event.target.value }))}
                  placeholder={activePlan?.experimentPlan.metric || "0.00"}
                />
              </label>
              <label>
                <span>{lang === "zh" ? "工件" : "Artifact"}</span>
                <VNativeInput
                  value={researchLoopEvidenceDraft.artifactRef}
                  onChange={(event) => setResearchLoopEvidenceDraft((draft) => ({ ...draft, artifactRef: event.target.value }))}
                  placeholder="workspace/experiments/result.json"
                />
              </label>
              <VNativeButton type="button" onClick={() => recordResearchLoopEvidenceFromWorkspace(activeLoop)} disabled={!canRecordEvidence}>
                <Save size={13} />
                {selectedTeamRecordResearchLoopEvidencePending ? (lang === "zh" ? "登记中" : "Recording") : (lang === "zh" ? "登记证据" : "Record evidence")}
              </VNativeButton>
              <label className={styles.researchLoopWide}>
                <span>{lang === "zh" ? "摘要" : "Summary"}</span>
                <VNativeInput
                  value={researchLoopEvidenceDraft.summary}
                  onChange={(event) => setResearchLoopEvidenceDraft((draft) => ({ ...draft, summary: event.target.value }))}
                  placeholder={lang === "zh" ? "证据结论、失败原因或待复核点" : "Evidence outcome, failure reason, or review note"}
                />
              </label>
              <label className={styles.researchLoopWide}>
                <span>{lang === "zh" ? "命令预览" : "Command preview"}</span>
                <VNativeInput
                  value={researchLoopEvidenceDraft.commandPreview}
                  onChange={(event) => setResearchLoopEvidenceDraft((draft) => ({ ...draft, commandPreview: event.target.value }))}
                  placeholder="python experiments/evaluate.py --config config.yaml"
                />
              </label>
              <label>
                <span>{lang === "zh" ? "数据" : "Dataset"}</span>
                <VNativeInput
                  value={researchLoopEvidenceDraft.datasetRefs}
                  onChange={(event) => setResearchLoopEvidenceDraft((draft) => ({ ...draft, datasetRefs: event.target.value }))}
                  placeholder={activePlan?.experimentPlan.dataset || "dataset id"}
                />
              </label>
              <label>
                <span>{lang === "zh" ? "环境" : "Environment"}</span>
                <VNativeInput
                  value={researchLoopEvidenceDraft.environmentRefs}
                  onChange={(event) => setResearchLoopEvidenceDraft((draft) => ({ ...draft, environmentRefs: event.target.value }))}
                  placeholder="conda env / docker image / hardware"
                />
              </label>
              <label>
                <span>{lang === "zh" ? "日志" : "Logs"}</span>
                <VNativeInput
                  value={researchLoopEvidenceDraft.logRefs}
                  onChange={(event) => setResearchLoopEvidenceDraft((draft) => ({ ...draft, logRefs: event.target.value }))}
                  placeholder="logs/experiments/run.log"
                />
              </label>
            </div>
            <div className={styles.researchLoopDecisionForm}>
              <label>
                <span>{lang === "zh" ? "决策" : "Decision"}</span>
                <VNativeSelect
                  value={researchLoopDecisionDraft.decision}
                  onChange={(event) => setResearchLoopDecisionDraft((draft) => ({ ...draft, decision: event.target.value as ResearchLoopDecisionValue }))}
                >
                  {RESEARCH_LOOP_DECISION_VALUES.map((decision: any) => (
                    <option key={decision} value={decision}>{decision}</option>
                  ))}
                </VNativeSelect>
              </label>
              <label>
                <span>{lang === "zh" ? "下一模板" : "Next template"}</span>
                <VNativeSelect
                  value={researchLoopDecisionDraft.nextTemplateId || selectedTemplate?.templateId || activeLoop.templateId}
                  onChange={(event) => setResearchLoopDecisionDraft((draft) => ({ ...draft, nextTemplateId: event.target.value }))}
                >
                  {templates.map((template: any) => (
                    <option key={template.templateId} value={template.templateId}>
                      {lang === "zh" ? template.labelZh : template.label}
                    </option>
                  ))}
                </VNativeSelect>
              </label>
              <label className={styles.researchLoopWide}>
                <span>{lang === "zh" ? "理由" : "Rationale"}</span>
                <VNativeInput
                  value={researchLoopDecisionDraft.rationale}
                  onChange={(event) => setResearchLoopDecisionDraft((draft) => ({ ...draft, rationale: event.target.value }))}
                  placeholder={lang === "zh" ? "基于证据给出推进、修复或补证据原因" : "Reason to promote, repair, or request more evidence"}
                />
              </label>
              <VNativeButton type="button" onClick={() => recordResearchLoopDecisionFromWorkspace(activeLoop)} disabled={!canRecordDecision}>
                <Send size={13} />
                {selectedTeamRecordResearchLoopDecisionPending ? (lang === "zh" ? "提交中" : "Submitting") : (lang === "zh" ? "登记决策" : "Record decision")}
              </VNativeButton>
              <label className={styles.researchLoopWide}>
                <span>{lang === "zh" ? "下一步动作" : "Next actions"}</span>
                <VNativeInput
                  value={researchLoopDecisionDraft.nextActions}
                  onChange={(event) => setResearchLoopDecisionDraft((draft) => ({ ...draft, nextActions: event.target.value }))}
                  placeholder={activeTemplate?.defaultIterationActions?.join(" / ") || "revise hypothesis / add evidence"}
                />
              </label>
            </div>
            <div className={styles.researchLoopOutcomeGrid}>
              <section>
                <strong>{lang === "zh" ? "缺失证据" : "Missing evidence"}</strong>
                <div className={styles.experimentGapList}>
                  {(activeLoop.readiness.missingEvidenceTypes.length ? activeLoop.readiness.missingEvidenceTypes : [lang === "zh" ? "无缺口" : "no gaps"]).map((item: any) => (
                    <span key={item}>{item}</span>
                  ))}
                </div>
              </section>
              <section>
                <strong>{lang === "zh" ? "最新决策" : "Latest decision"}</strong>
                <span>{latestDecision ? `${latestDecision.decision} -> ${latestDecision.statusAfterDecision}` : (lang === "zh" ? "尚未决策" : "no decision yet")}</span>
                {latestProposal ? <small>{latestProposal.nextTemplateId}: {latestProposal.nextActions.join(" / ")}</small> : null}
                {latestProposal?.nextDesignPlanId ? (
                  <small title={latestProposal.nextDesignPlanId}>
                    {lang === "zh" ? "已生成下一版设计" : "Next design created"}
                    {` · v${latestProposal.nextDesignRevision ?? "-"} · ${latestProposal.nextDesignGateStatus || "draft"}`}
                  </small>
                ) : null}
              </section>
              {pendingDesignProposal ? (
                <section>
                  <strong>{lang === "zh" ? "待生成设计" : "Pending design"}</strong>
                  <span>{pendingDesignProposal.loopTitle || pendingDesignProposal.nextTemplateId}</span>
                  <small>{pendingDesignProposal.nextTemplateId}: {pendingDesignProposal.nextActions.join(" / ")}</small>
                  <VNativeButton
                    type="button"
                    disabled={materializingPendingDesign || !selectedTeam?.teamId}
                    onClick={() => {
                      if (!selectedTeam?.teamId) {
                        return;
                      }
                      materializeResearchLoopIterationDesignMutation.mutate({
                        teamId: selectedTeam.teamId,
                        loopId: pendingDesignProposal.loopId,
                        proposalId: pendingDesignProposal.proposalId,
                      });
                    }}
                  >
                    <Plus size={13} />
                    {materializingPendingDesign
                      ? (lang === "zh" ? "生成中" : "Creating")
                      : (lang === "zh" ? "生成设计草稿" : "Create design draft")}
                  </VNativeButton>
                  <small>{lang === "zh" ? "生成后仍需人工冻结，不会自动执行实验。" : "The draft still requires an explicit freeze and will not execute automatically."}</small>
                </section>
              ) : null}
            </div>
          </>
        ) : (
          <div className={styles.experimentLedgerEmpty}>
            <AlertTriangle size={14} />
            <span>{lang === "zh" ? "还没有 Research Loop，先从当前实验计划创建模板化循环。" : "No Research Loop yet. Create one from the active experiment plan."}</span>
          </div>
        )}
        {selectedTeamCreateResearchLoopError ? <div className={styles.workflowError}>{selectedTeamCreateResearchLoopError.message}</div> : null}
        {selectedTeamRecordResearchLoopEvidenceError ? <div className={styles.workflowError}>{selectedTeamRecordResearchLoopEvidenceError.message}</div> : null}
        {selectedTeamRecordResearchLoopDecisionError ? <div className={styles.workflowError}>{selectedTeamRecordResearchLoopDecisionError.message}</div> : null}
        {materializeResearchLoopIterationDesignMutation.error instanceof Error
          ? <div className={styles.workflowError}>{materializeResearchLoopIterationDesignMutation.error.message}</div>
          : null}
      </section>
    );

}
