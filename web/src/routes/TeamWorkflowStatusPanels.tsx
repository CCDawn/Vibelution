import { RefreshCw } from "lucide-react";

import type {
  TeamWorkflowCandidateGraphPayload,
  TeamWorkflowCoordinationStatus,
  TeamWorkflowKnowledgeIngestionStatus,
} from "../api/types";
import { VNativeButton } from "../components/vui";
import { TeamWorkflowGraphView, type TeamWorkflowGraphLayout } from "./TeamWorkflowGraphView";
import styles from "./TeamWorkflowStatusPanels.styles";

type TeamWorkflowStatusLang = "zh" | "en";

type TeamWorkflowStatusLabel = (value: string) => string;

type TeamWorkflowStatusActionItem = {
  code: string;
  severity: string;
  message: string;
  candidateId?: string | null;
  workflowNode?: string | null;
  taskType?: string | null;
  queue?: string | null;
};

export type TeamWorkflowModelEvidenceStatusPanelData = {
  status: string;
  summary: {
    coveredNodeCount: number;
    requiredNodeCount: number;
    evidenceCount: number;
    qwenEvidenceCount: number;
    bailianEvidenceCount: number;
    localEvidenceCount: number;
    linkedCandidateCount: number;
  };
  coverage: Array<{
    taskType: string;
    label: string;
    status: string;
    evidenceCount: number;
  }>;
  actionItems: Array<TeamWorkflowStatusActionItem & { taskType: string }>;
  officialBoundary: {
    writesFormalKnowledge: boolean;
  };
  storage: {
    evidenceStorePath: string;
  };
};

export type TeamWorkflowSourceQualityStatusPanelData = {
  status: string;
  summary: {
    sourceCandidateCount: number;
    assessedSourceCandidateCount: number;
    approvedSourceCandidateCount: number;
    needsRevisionSourceCandidateCount: number;
    unassessedSourceCandidateCount: number;
  };
  candidates: Array<{
    candidateId: string;
    title: string;
    bucket: string;
    overallScore?: number | null;
    sourceKind?: string | null;
  }>;
  actionItems: TeamWorkflowStatusActionItem[];
};

export type TeamWorkflowPaperNoteChunkStatusPanelData = {
  status: string;
  summary: {
    planCount: number;
    chunkCount: number;
    readySourceCandidateCount: number;
    plannedSourceCandidateCount: number;
    missingPlanSourceCandidateCount: number;
    openChunkCount: number;
  };
  plans: Array<{
    planId: string;
    sourceTitle?: string | null;
    sourceCandidateId: string;
    status: string;
    draftedChunkCount: number;
    chunkCount: number;
    pageScope?: string | null;
  }>;
  actionItems: TeamWorkflowStatusActionItem[];
};

function workflowStatusTone(value: string) {
  const normalized = String(value || "").toLowerCase();
  if (normalized === "ready" || normalized === "operational") {
    return styles.workflowTagReady;
  }
  if (normalized === "blocked" || normalized === "needs_revision") {
    return styles.workflowTagDanger;
  }
  if (normalized === "needs_review" || normalized === "needs_evidence" || normalized === "needs_screening" || normalized === "pending") {
    return styles.workflowTagWarning;
  }
  return styles.workflowTagNeutral;
}

function WorkflowStatusTag({
  status,
  children,
}: {
  status: string;
  children: string;
}) {
  return (
    <span className={`${styles.workflowTag} ${workflowStatusTone(status)}`}>
      {children}
    </span>
  );
}

function WorkflowStatusErrors({ messages }: { messages: string[] }) {
  return (
    <>
      {messages.map((message) => (
        <div key={message} className={styles.messageError}>{message}</div>
      ))}
    </>
  );
}

function WorkflowStatusActions({
  items,
  statusLabel,
  limit,
  keyForItem,
}: {
  items: TeamWorkflowStatusActionItem[];
  statusLabel: TeamWorkflowStatusLabel;
  limit: number;
  keyForItem: (item: TeamWorkflowStatusActionItem) => string;
}) {
  if (!items.length) {
    return null;
  }

  return (
    <div className={styles.workflowIngestionActions}>
      {items.slice(0, limit).map((item) => (
        <span key={keyForItem(item)} className={workflowStatusTone(item.severity)}>
          {statusLabel(item.severity)} · {item.message}
        </span>
      ))}
    </div>
  );
}

export function TeamWorkflowModelEvidenceStatusPanel({
  lang,
  status,
  loading,
  errorMessages,
  statusLabel,
}: {
  lang: TeamWorkflowStatusLang;
  status: TeamWorkflowModelEvidenceStatusPanelData | null;
  loading: boolean;
  errorMessages: string[];
  statusLabel: TeamWorkflowStatusLabel;
}) {
  return (
    <div className={styles.workflowModelEvidencePanel}>
      <div className={styles.workflowIngestionHeader}>
        <div>
          <strong>{lang === "zh" ? "模型调用证据链" : "Model evidence chain"}</strong>
          <span>
            {status
              ? `${status.summary.coveredNodeCount}/${status.summary.requiredNodeCount} nodes · ${status.summary.evidenceCount} evidence`
              : loading
              ? (lang === "zh" ? "读取中" : "loading")
              : (lang === "zh" ? "等待模型证据" : "waiting for model evidence")}
          </span>
        </div>
        <WorkflowStatusTag status={status?.status || ""}>
          {status ? statusLabel(status.status) : (lang === "zh" ? "未读取" : "not loaded")}
        </WorkflowStatusTag>
      </div>
      {status ? (
        <>
          <div className={styles.workflowModelEvidenceStats}>
            <span>Qwen <strong>{status.summary.qwenEvidenceCount}</strong></span>
            <span>{lang === "zh" ? "百炼" : "Bailian"} <strong>{status.summary.bailianEvidenceCount}</strong></span>
            <span>{lang === "zh" ? "本地" : "local"} <strong>{status.summary.localEvidenceCount}</strong></span>
            <span>{lang === "zh" ? "候选关联" : "linked"} <strong>{status.summary.linkedCandidateCount}</strong></span>
          </div>
          <div className={styles.workflowModelEvidenceCoverage}>
            {status.coverage.map((item) => (
              <span key={item.taskType} className={`${styles.workflowIngestionStage} ${workflowStatusTone(item.status === "covered" ? "ready" : "needs_evidence")}`}>
                <strong>{item.label}</strong>
                <small>{item.evidenceCount} · {item.status}</small>
              </span>
            ))}
          </div>
          <WorkflowStatusActions
            items={status.actionItems}
            statusLabel={statusLabel}
            limit={3}
            keyForItem={(item) => `${item.code}-${item.taskType}`}
          />
          <div className={styles.workflowIngestionBoundary}>
            <span>{lang === "zh" ? "证据登记，不是正式知识" : "Evidence only, not formal knowledge"}</span>
            <span>
              {status.officialBoundary.writesFormalKnowledge
                ? (lang === "zh" ? "会写正式知识" : "writes formal knowledge")
                : (lang === "zh" ? "正式知识写入关闭" : "formal write off")}
            </span>
            <span>{status.storage.evidenceStorePath}</span>
          </div>
        </>
      ) : (
        <div className={styles.empty}>
          {loading
            ? (lang === "zh" ? "正在读取 Qwen/百炼/本地模型调用证据覆盖..." : "Loading Qwen/Bailian/local model evidence coverage...")
            : (lang === "zh" ? "暂无模型调用证据。" : "No model evidence yet.")}
        </div>
      )}
      <WorkflowStatusErrors messages={errorMessages} />
    </div>
  );
}

export function TeamWorkflowCoordinationStatusPanel({
  lang,
  status,
  loading,
  errorMessages,
  statusLabel,
  channelLabel,
  stateLabel,
}: {
  lang: TeamWorkflowStatusLang;
  status: TeamWorkflowCoordinationStatus | null;
  loading: boolean;
  errorMessages: string[];
  statusLabel: TeamWorkflowStatusLabel;
  channelLabel: TeamWorkflowStatusLabel;
  stateLabel: TeamWorkflowStatusLabel;
}) {
  return (
    <div className={styles.workflowCoordinationPanel} id="research-workflow-coordination">
      <div className={styles.workflowIngestionHeader}>
        <div>
          <strong>{lang === "zh" ? "团队协调队列" : "Coordination queue"}</strong>
          <span>
            {status
              ? `${status.summary.pendingTransferCount} transfer / ${status.summary.reworkCandidateCount} rework / ${status.summary.blockedCandidateCount} blocked`
              : loading
              ? (lang === "zh" ? "读取中" : "loading")
              : (lang === "zh" ? "等待流程数据" : "waiting for workflow data")}
          </span>
        </div>
        <WorkflowStatusTag status={status?.status || ""}>
          {status ? statusLabel(status.status) : (lang === "zh" ? "未读取" : "not loaded")}
        </WorkflowStatusTag>
      </div>
      {status ? (
        <>
          <div className={styles.workflowCoordinationStats}>
            <span>{lang === "zh" ? "待决" : "transfer"} <strong>{status.summary.pendingTransferCount}</strong></span>
            <span>{lang === "zh" ? "返工" : "rework"} <strong>{status.summary.reworkCandidateCount}</strong></span>
            <span>{lang === "zh" ? "治理" : "steward"} <strong>{status.summary.stewardshipCandidateCount}</strong></span>
            <span>{lang === "zh" ? "阻塞" : "blocked"} <strong>{status.summary.blockedCandidateCount}</strong></span>
          </div>
          <div className={styles.workflowCoordinationQueues}>
            {[
              ["pendingTransfers", status.queues.pendingTransfers],
              ["needsRework", status.queues.needsRework],
              ["stewardship", status.queues.stewardship],
              ["blockedQueue", status.queues.blocked],
            ].map(([queueName, queueItems]) => (
              <div key={String(queueName)} className={styles.workflowCoordinationQueue}>
                <strong>{statusLabel(String(queueName))}</strong>
                {(queueItems as TeamWorkflowCoordinationStatus["queues"]["active"]).length ? (
                  (queueItems as TeamWorkflowCoordinationStatus["queues"]["active"]).slice(0, 3).map((item) => (
                    <span key={`${queueName}-${item.transferId || item.candidateId}`}>
                      <strong>
                        {item.transferId ? `${item.fromNode || "-"} -> ${item.toNode || "-"}` : stateLabel(item.currentState)}
                        {" · "}
                        {item.title || item.candidateType || item.candidateId}
                      </strong>
                      {item.communicationBrief ? (
                        <small>
                          {item.communicationBrief.targetAgentRole}
                          {" · "}
                          {channelLabel(item.communicationBrief.channel)}
                        </small>
                      ) : null}
                    </span>
                  ))
                ) : (
                  <small>{lang === "zh" ? "空" : "empty"}</small>
                )}
              </div>
            ))}
          </div>
          <WorkflowStatusActions
            items={status.actionItems}
            statusLabel={statusLabel}
            limit={4}
            keyForItem={(item) => `${item.code}-${item.queue}`}
          />
          <div className={styles.workflowCoordinationBriefSummary}>
            <span>
              {lang === "zh" ? "沟通建议" : "briefs"} <strong>{status.communication.briefCount}</strong>
            </span>
            <span>{status.communication.recommendedSender}</span>
            <span>
              {status.communication.autoSendEnabled
                ? (lang === "zh" ? "自动发送开启" : "auto-send on")
                : (lang === "zh" ? "不会自动发送" : "no auto-send")}
            </span>
          </div>
          <div className={styles.workflowIngestionBoundary}>
            <span>{status.coordinationPolicy.coordinationAgentId}</span>
            <span>
              {status.coordinationPolicy.requiresUserConfirmation
                ? (lang === "zh" ? "需要用户确认" : "user confirmation")
                : (lang === "zh" ? "无需用户确认" : "no user confirmation")}
            </span>
            <span>
              {status.coordinationPolicy.autoTransferEnabled
                ? (lang === "zh" ? "自动调转开启" : "auto transfer on")
                : (lang === "zh" ? "只读状态总览" : "read-only status")}
            </span>
          </div>
        </>
      ) : (
        <div className={styles.empty}>
          {loading
            ? (lang === "zh" ? "正在汇总候选队列、返工项和转移请求..." : "Aggregating candidates, rework items, and transfers...")
            : (lang === "zh" ? "暂无协调队列状态。" : "No coordination status yet.")}
        </div>
      )}
      <WorkflowStatusErrors messages={errorMessages} />
    </div>
  );
}

export function TeamWorkflowKnowledgeIngestionStatusPanel({
  lang,
  status,
  loading,
  errorMessages,
  statusLabel,
}: {
  lang: TeamWorkflowStatusLang;
  status: TeamWorkflowKnowledgeIngestionStatus | null;
  loading: boolean;
  errorMessages: string[];
  statusLabel: TeamWorkflowStatusLabel;
}) {
  return (
    <div className={styles.workflowIngestionPanel} id="research-workflow-ingestion">
      <div className={styles.workflowIngestionHeader}>
        <div>
          <strong>{lang === "zh" ? "入库审核状态" : "Knowledge ingestion review"}</strong>
          <span>
            {status
              ? `${status.summary.pendingProposalCount} pending / ${status.summary.formalKnowledgeItemCount} formal`
              : loading
              ? (lang === "zh" ? "读取中" : "loading")
              : (lang === "zh" ? "等待候选" : "waiting for candidates")}
          </span>
        </div>
        <WorkflowStatusTag status={status?.status || ""}>
          {status ? statusLabel(status.status) : (lang === "zh" ? "未读取" : "not loaded")}
        </WorkflowStatusTag>
      </div>
      {status ? (
        <>
          <div className={styles.workflowIngestionStages}>
            {status.stages.map((stage) => (
              <span key={stage.stageId} className={`${styles.workflowIngestionStage} ${workflowStatusTone(stage.status)}`}>
                <strong>{stage.label}</strong>
                <small>{statusLabel(stage.status)} · {stage.count}</small>
              </span>
            ))}
          </div>
          <div className={styles.workflowIngestionStats}>
            <span>{lang === "zh" ? "来源" : "sources"} <strong>{status.summary.sourceReadyCount}/{status.summary.sourceCandidateCount}</strong></span>
            <span>{lang === "zh" ? "草稿" : "drafts"} <strong>{status.summary.localDraftCandidateCount}</strong></span>
            <span>{lang === "zh" ? "待审" : "pending"} <strong>{status.summary.pendingKnowledgeReviewCandidateCount}</strong></span>
            <span>{lang === "zh" ? "正式知识" : "formal"} <strong>{status.summary.formalKnowledgeItemCount}</strong></span>
          </div>
          <WorkflowStatusActions
            items={status.actionItems}
            statusLabel={statusLabel}
            limit={4}
            keyForItem={(item) => `${item.code}-${item.candidateId || item.workflowNode}`}
          />
          <div className={styles.workflowIngestionBoundary}>
            <span>
              {status.officialBoundary.writesOfficialKnowledge
                ? (lang === "zh" ? "正式知识已写入" : "official knowledge written")
                : (lang === "zh" ? "正式知识未写入" : "official knowledge not written")}
            </span>
            <span>
              {status.officialBoundary.writesOfficialGraph
                ? (lang === "zh" ? "正式图谱已同步" : "official graph synced")
                : (lang === "zh" ? "入库关系预览" : "ingestion map preview")}
            </span>
            <span>
              {status.officialBoundary.writesOfficialRag
                ? (lang === "zh" ? "RAG 已写入" : "RAG written")
                : (lang === "zh" ? "RAG 不由本流程写入" : "RAG write off")}
            </span>
          </div>
        </>
      ) : (
        <div className={styles.empty}>
          {loading
            ? (lang === "zh" ? "正在汇总 CandidateStore、Team Knowledge 和正式同步边界..." : "Aggregating CandidateStore, Team Knowledge, and sync boundary...")
            : (lang === "zh" ? "暂无入库审核状态。" : "No knowledge ingestion review status yet.")}
        </div>
      )}
      <WorkflowStatusErrors messages={errorMessages} />
    </div>
  );
}

export function TeamWorkflowCandidateGraphStatusPanel({
  lang,
  graph,
  layout,
  loading,
  errorMessages,
  actionLabel,
  actionDisabled,
  actionTitle,
  stateLabel,
  onAction,
}: {
  lang: TeamWorkflowStatusLang;
  graph: TeamWorkflowCandidateGraphPayload | null;
  layout: TeamWorkflowGraphLayout | null;
  loading: boolean;
  errorMessages: string[];
  actionLabel: string;
  actionDisabled: boolean;
  actionTitle: string;
  stateLabel: TeamWorkflowStatusLabel;
  onAction: () => void;
}) {
  return (
    <div className={styles.workflowGraphPanel} id="research-workflow-graph">
      <div className={styles.workflowGraphHeader}>
        <div>
          <strong>{lang === "zh" ? "入库关系图" : "Ingestion map"}</strong>
          <span>
            {graph
              ? `${graph.summary.nodeCount} nodes / ${graph.summary.edgeCount} edges`
              : loading
              ? (lang === "zh" ? "读取中" : "loading")
              : (lang === "zh" ? "未生成" : "not built")}
          </span>
        </div>
        <VNativeButton
          type="button"
          onClick={onAction}
          disabled={actionDisabled}
          title={actionTitle}
        >
          <RefreshCw size={13} />
          {actionLabel}
        </VNativeButton>
      </div>
      {graph && layout ? (
        <>
          <div className={styles.workflowGraphStats}>
            <span>{graph.graphKind}</span>
            <span>{graph.summary.missingLinkCount} missing</span>
            <span>{graph.summary.unreviewedNodeCount} review</span>
            {typeof graph.summary.archivedCandidateCount === "number" ? (
              <span>{graph.summary.archivedCandidateCount} archived</span>
            ) : null}
            <span>
              {graph.officialBoundary.writesOfficialGraph
                ? (lang === "zh" ? "会写正式图谱" : "writes official graph")
                : (lang === "zh" ? "候选边界" : "candidate boundary")}
            </span>
          </div>
          <TeamWorkflowGraphView
            layout={layout}
            markerId="team-candidate-workflow-graph-arrow"
            stateLabel={stateLabel}
          />
          {graph.missingLinks.length || graph.unreviewedNodes.length ? (
            <div className={styles.workflowGraphIssues}>
              {graph.missingLinks.slice(0, 3).map((edge) => (
                <span key={`${edge.sourceCandidateId}-${edge.targetCandidateId}-${edge.relation}`}>
                  {edge.relation}: {edge.targetCandidateId}
                </span>
              ))}
              {graph.unreviewedNodes.slice(0, 3).map((node) => (
                <span key={`${node.candidateId}-${node.reason}`}>{stateLabel(node.currentState)}</span>
              ))}
            </div>
          ) : null}
          <div className={styles.workflowGraphBoundary}>
            {lang === "zh"
              ? "CandidateStore 快照 · 正式知识/RAG/图谱写入关闭"
              : "CandidateStore snapshot · official Knowledge/RAG/Graph writes off"}
          </div>
        </>
      ) : (
        <div className={styles.empty}>
          {loading
            ? (lang === "zh" ? "正在读取入库关系图..." : "Loading ingestion map...")
            : (lang === "zh" ? "还没有入库关系图，可先点击生成关系。" : "No ingestion map yet. Build the map first.")}
        </div>
      )}
      <WorkflowStatusErrors messages={errorMessages} />
    </div>
  );
}

export function TeamWorkflowSourceQualityStatusPanel({
  lang,
  status,
  loading,
  errorMessages,
  statusLabel,
}: {
  lang: TeamWorkflowStatusLang;
  status: TeamWorkflowSourceQualityStatusPanelData | null;
  loading: boolean;
  errorMessages: string[];
  statusLabel: TeamWorkflowStatusLabel;
}) {
  return (
    <div className={styles.workflowSourceQualityPanel}>
      <div className={styles.workflowIngestionHeader}>
        <div>
          <strong>{lang === "zh" ? "资料提炼复核" : "Source extraction review"}</strong>
          <span>
            {status
              ? `${status.summary.approvedSourceCandidateCount} approved / ${status.summary.sourceCandidateCount} sources`
              : loading
              ? (lang === "zh" ? "读取中" : "loading")
              : (lang === "zh" ? "等待 source_manifest" : "waiting for source_manifest")}
          </span>
        </div>
        <WorkflowStatusTag status={status?.status || ""}>
          {status ? statusLabel(status.status) : (lang === "zh" ? "未读取" : "not loaded")}
        </WorkflowStatusTag>
      </div>
      {status ? (
        <>
          <div className={styles.workflowSourceQualityStats}>
            <span>{lang === "zh" ? "来源" : "sources"} <strong>{status.summary.sourceCandidateCount}</strong></span>
            <span>{lang === "zh" ? "已审查" : "reviewed"} <strong>{status.summary.assessedSourceCandidateCount}</strong></span>
            <span>{lang === "zh" ? "通过" : "approved"} <strong>{status.summary.approvedSourceCandidateCount}</strong></span>
            <span>{lang === "zh" ? "待修订" : "revision"} <strong>{status.summary.needsRevisionSourceCandidateCount}</strong></span>
            <span>{lang === "zh" ? "未审查" : "pending review"} <strong>{status.summary.unassessedSourceCandidateCount}</strong></span>
          </div>
          {status.candidates.length ? (
            <div className={styles.workflowSourceQualityQueue}>
              {status.candidates.slice(0, 5).map((item) => (
                <span key={item.candidateId} className={workflowStatusTone(item.bucket === "approved" ? "ready" : item.bucket)}>
                  <strong>{item.title}</strong>
                  <small>
                    {statusLabel(item.bucket)} · {item.overallScore ? `${item.overallScore}/100` : "-"} · {item.sourceKind || "source"}
                  </small>
                </span>
              ))}
            </div>
          ) : null}
          <WorkflowStatusActions
            items={status.actionItems}
            statusLabel={statusLabel}
            limit={3}
            keyForItem={(item) => `${item.code}-${item.candidateId}`}
          />
          <div className={styles.workflowIngestionBoundary}>
            <span>{lang === "zh" ? "资料提炼 Agent" : "Source extraction Agent"}</span>
            <span>{lang === "zh" ? "只写 CandidateStore" : "CandidateStore only"}</span>
            <span>{lang === "zh" ? "不写正式知识/RAG/图谱" : "no formal Knowledge/RAG/Graph writes"}</span>
          </div>
        </>
      ) : (
        <div className={styles.empty}>
          {loading
            ? (lang === "zh" ? "正在汇总资料提炼复核状态..." : "Aggregating source extraction review status...")
            : (lang === "zh" ? "暂无资料提炼复核状态。" : "No source extraction review status yet.")}
        </div>
      )}
      <WorkflowStatusErrors messages={errorMessages} />
    </div>
  );
}

export function TeamWorkflowPaperNoteChunkStatusPanel({
  lang,
  status,
  loading,
  errorMessages,
  statusLabel,
}: {
  lang: TeamWorkflowStatusLang;
  status: TeamWorkflowPaperNoteChunkStatusPanelData | null;
  loading: boolean;
  errorMessages: string[];
  statusLabel: TeamWorkflowStatusLabel;
}) {
  return (
    <div className={styles.workflowPaperNoteChunkPanel}>
      <div className={styles.workflowIngestionHeader}>
        <div>
          <strong>{lang === "zh" ? "paper_note 分块计划" : "paper_note chunk plan"}</strong>
          <span>
            {status
              ? `${status.summary.planCount} plans / ${status.summary.chunkCount} chunks`
              : loading
              ? (lang === "zh" ? "读取中" : "loading")
              : (lang === "zh" ? "等待 source extraction" : "waiting for source extraction")}
          </span>
        </div>
        <WorkflowStatusTag status={status?.status || ""}>
          {status ? statusLabel(status.status) : (lang === "zh" ? "未读取" : "not loaded")}
        </WorkflowStatusTag>
      </div>
      {status ? (
        <>
          <div className={styles.workflowPaperNoteChunkStats}>
            <span>{lang === "zh" ? "可分块来源" : "ready sources"} <strong>{status.summary.readySourceCandidateCount}</strong></span>
            <span>{lang === "zh" ? "已规划来源" : "planned sources"} <strong>{status.summary.plannedSourceCandidateCount}</strong></span>
            <span>{lang === "zh" ? "缺计划" : "missing plans"} <strong>{status.summary.missingPlanSourceCandidateCount}</strong></span>
            <span>{lang === "zh" ? "待 draft" : "open chunks"} <strong>{status.summary.openChunkCount}</strong></span>
          </div>
          {status.plans.length ? (
            <div className={styles.workflowPaperNoteChunkPlans}>
              {status.plans.slice(0, 4).map((plan) => (
                <span key={plan.planId}>
                  <strong>{plan.sourceTitle || plan.sourceCandidateId}</strong>
                  <small>{statusLabel(plan.status)} · {plan.draftedChunkCount}/{plan.chunkCount} · {plan.pageScope || "-"}</small>
                </span>
              ))}
            </div>
          ) : (
            <div className={styles.empty}>
              {lang === "zh"
                ? "还没有分块计划。对已完成内容提取的 source 生成计划后，才能按 chunk 产出 paper_note。"
                : "No chunk plan yet. Generate plans for extracted sources before drafting paper_notes by chunk."}
            </div>
          )}
          <WorkflowStatusActions
            items={status.actionItems}
            statusLabel={statusLabel}
            limit={3}
            keyForItem={(item) => `${item.code}-${item.candidateId}`}
          />
          <div className={styles.workflowIngestionBoundary}>
            <span>{lang === "zh" ? "CandidateStore 计划" : "CandidateStore plan"}</span>
            <span>{lang === "zh" ? "不写正式知识/RAG/图谱" : "no formal Knowledge/RAG/Graph writes"}</span>
            <span>{lang === "zh" ? "后续 paper_note draft 需带 chunkId" : "paper_note draft should use chunkId"}</span>
          </div>
        </>
      ) : (
        <div className={styles.empty}>
          {loading
            ? (lang === "zh" ? "正在汇总 source extraction 与 paper_note chunk 计划..." : "Aggregating source extraction and paper_note chunk plans...")
            : (lang === "zh" ? "暂无 paper_note 分块状态。" : "No paper_note chunk status yet.")}
        </div>
      )}
      <WorkflowStatusErrors messages={errorMessages} />
    </div>
  );
}
