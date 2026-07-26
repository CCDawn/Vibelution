/**
 * Knowledge-collection one-click completion flow graph.
 * Wave 8K: extracted from TeamsRoute.tsx for domain componentization.
 */
import { Link2, MessageSquare, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";

import { VNativeButton } from "../components/vui";
import { agentDisplayInfo } from "./agentDisplay";
import {
  sourceCollectionAgentRoleLabel,
  workflowIngestionStatusLabel,
} from "./teams/source-collection/presentationModel";
import {
  sourceCollectionCompletionFlowNodeState,
  type SourceCollectionStageModuleId,
} from "./teams/source-collection/stageProjection";
import researchStyles from "./TeamsRoute.research.styles";
import shellStyles from "./TeamsRoute.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...researchStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamKnowledgeCollectionCompletionFlowPanelProps = {
  lang: Lang;
  researchWorkflowTeamSelected: boolean;
  researchCanvasReadOnly: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamKnowledgeCollectionWorkRun: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCompletionFlow: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCompletionFlowNodes: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageModules: Array<{ id: SourceCollectionStageModuleId; label: string }>;
  workflowIngestionTone: (value: string) => string;
  parseSourceCollectionStageModuleId: (value: string | null) => SourceCollectionStageModuleId | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStagePrimaryAgentBinding: (stageId: SourceCollectionStageModuleId) => any;
  sourceCollectionStageReturnRoute: (stageId: SourceCollectionStageModuleId) => string;
  openSourceCollectionStageAgentChat: (stageId: SourceCollectionStageModuleId) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStepClassName: (state: any) => string;
  runKnowledgeCollectionCompletionAction: () => void;
  sourceCollectionCompletionActionDisabled: boolean;
  selectedTeamKnowledgeCollectionIngestPending: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionActionDisabledTitle: (readiness: any, label: string) => string | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCompletionActionReadiness: any;
};

export function TeamKnowledgeCollectionCompletionFlowPanel(props: TeamKnowledgeCollectionCompletionFlowPanelProps) {
  const {
    lang,
    researchWorkflowTeamSelected,
    researchCanvasReadOnly,
    selectedTeamKnowledgeCollectionWorkRun,
    sourceCollectionCompletionFlow,
    sourceCollectionCompletionFlowNodes,
    sourceCollectionStageModules,
    workflowIngestionTone,
    parseSourceCollectionStageModuleId,
    sourceCollectionStagePrimaryAgentBinding,
    sourceCollectionStageReturnRoute,
    openSourceCollectionStageAgentChat,
    sourceCollectionStepClassName,
    runKnowledgeCollectionCompletionAction,
    sourceCollectionCompletionActionDisabled,
    selectedTeamKnowledgeCollectionIngestPending,
    sourceCollectionActionDisabledTitle,
    sourceCollectionCompletionActionReadiness,
  } = props;


    if (!researchWorkflowTeamSelected || !researchCanvasReadOnly) {
      return null;
    }
    const workRun = selectedTeamKnowledgeCollectionWorkRun;
    const flow = sourceCollectionCompletionFlow;
    const flowStatus = String(flow?.status || workRun?.status || "queued");
    const flowError = String(flow?.error || workRun?.error || "");
    const currentStageId = String(flow?.currentStageId || "");
    return (
      <section className={styles.knowledgeCompletionFlowPanel} aria-label={lang === "zh" ? "一键流程图" : "One-click flow graph"}>
        <div className={styles.knowledgeCompletionFlowHeader}>
          <div>
            <strong>{lang === "zh" ? "一键流程图" : "One-click flow graph"}</strong>
            <span>
              {workRun
                ? (workRun.summary || workRun.currentTask || workRun.runId)
                : (lang === "zh" ? "闭环执行后，这里展示阶段 Agent 的运行状态。" : "After loop execution starts, stage Agent progress appears here.")}
            </span>
          </div>
          <span className={`${styles.workflowTag} ${workflowIngestionTone(flowStatus)}`}>
            {workflowIngestionStatusLabel(flowStatus, lang)}
          </span>
        </div>
        {flowError ? (
          <div className={styles.workflowError}>
            {flow?.errorType || workRun?.errorType ? `${flow?.errorType || workRun?.errorType}: ` : ""}
            {flowError}
          </div>
        ) : null}
        <div className={styles.knowledgeCompletionFlowNodes}>
          {sourceCollectionCompletionFlowNodes.map((rawNode, index) => {
            const stageId = parseSourceCollectionStageModuleId(String(rawNode.stageId || "")) ?? "finding";
            const node = { ...rawNode, stageId };
            const nodeState = sourceCollectionCompletionFlowNodeState(node.status);
            const binding = sourceCollectionStagePrimaryAgentBinding(stageId);
            const bindingDisplay = binding?.agent ? agentDisplayInfo(binding.agent, lang) : null;
            const agentLabel =
              bindingDisplay?.name
              || binding?.agentId
              || sourceCollectionAgentRoleLabel(node.agentRole, lang);
            const isCurrent = currentStageId === node.stageId || nodeState === "active";
            return (
              <article
                key={`${node.stageId}-${index}`}
                className={[
                  styles.knowledgeCompletionFlowNode,
                  sourceCollectionStepClassName(nodeState),
                  isCurrent ? styles.knowledgeCompletionFlowNodeCurrent : "",
                ].filter(Boolean).join(" ")}
              >
                <div className={styles.knowledgeCompletionFlowNodeHeader}>
                  <strong>{String(index + 1).padStart(2, "0")}</strong>
                  <span>{workflowIngestionStatusLabel(String(node.status || ""), lang)}</span>
                </div>
                <div className={styles.knowledgeCompletionFlowNodeBody}>
                  <b>{node.label || sourceCollectionStageModules.find((module: any) => module.id === stageId)?.label || stageId}</b>
                  <small>{lang === "zh" ? `Agent：${agentLabel}` : `Agent: ${agentLabel}`}</small>
                  <em>
                    {lang === "zh" ? "输入" : "in"} {Number(node.inputCount || 0)}
                    {" · "}
                    {lang === "zh" ? "输出" : "out"} {Number(node.outputCount || 0)}
                  </em>
                  {node.detail ? <p>{node.detail}</p> : null}
                  {node.errorType ? <p className={styles.knowledgeCompletionFlowError}>{node.errorType}</p> : null}
                </div>
                <div className={styles.knowledgeCompletionFlowActions}>
                  <Link to={sourceCollectionStageReturnRoute(stageId)}>
                    <Link2 size={13} />
                    {lang === "zh" ? "阶段详情" : "Stage detail"}
                  </Link>
                  <VNativeButton type="button" onClick={() => openSourceCollectionStageAgentChat(node.stageId)}>
                    <MessageSquare size={13} />
                    {lang === "zh" ? "Agent 私聊" : "Agent chat"}
                  </VNativeButton>
                  {nodeState === "failed" ? (
                    <VNativeButton
                      type="button"
                      onClick={runKnowledgeCollectionCompletionAction}
                      disabled={sourceCollectionCompletionActionDisabled || selectedTeamKnowledgeCollectionIngestPending}
                      title={sourceCollectionActionDisabledTitle(sourceCollectionCompletionActionReadiness, lang === "zh" ? "重试失败节点" : "Retry failed node")}
                    >
                      <RefreshCw size={13} />
                      {lang === "zh" ? "重试失败节点" : "Retry failed node"}
                    </VNativeButton>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      </section>
    );

}
