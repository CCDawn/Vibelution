/**
 * Source-collection active-stage workspace body.
 * Wave 8M: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";
import { Link2, MessageSquare } from "lucide-react";
import { Link } from "react-router-dom";

import { VNativeButton, VTooltip } from "../components/vui";
import { researchStageAgentManagementRoute } from "./teams/researchStageAgentPresentation";
import type { SourceCollectionStageModuleId } from "./teams/source-collection/stageProjection";
import { TeamSourceCollectionActiveStagePanel } from "./TeamSourceCollectionActiveStagePanel";
import shellStyles from "./TeamsRoute.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamSourceCollectionActiveStageWorkspacePanelProps = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageModules: any[];
  selectedSourceCollectionStageId: SourceCollectionStageModuleId | string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageAgentChatState: (stageId: any) => any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  repairChallengeCupTeamAgentsMutation: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionActionDisabledTitle: (readiness: any, label: string) => string | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageActionReadinessFor: (stageId: any) => any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStagePrimaryAgentBinding: (stageId: any) => any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  stageChatLabels: Record<string, { zh: string; en: string }>;
  openSourceCollectionStageAgentChat: (stageId: any) => void;
  sourceCollectionFindingStageCompact: boolean;
  selectedTeamStartSourceCollectionStageTaskError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionConversation: () => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionCandidatePanel: () => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionScreeningPanel: () => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionGraphPanel: () => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionMemoryPanel: () => ReactNode;
};

export function TeamSourceCollectionActiveStageWorkspacePanel(props: TeamSourceCollectionActiveStageWorkspacePanelProps) {
  const {
    lang,
    sourceCollectionStageModules,
    selectedSourceCollectionStageId,
    sourceCollectionStageAgentChatState,
    repairChallengeCupTeamAgentsMutation,
    sourceCollectionActionDisabledTitle,
    sourceCollectionStageActionReadinessFor,
    sourceCollectionStagePrimaryAgentBinding,
    stageChatLabels,
    openSourceCollectionStageAgentChat,
    sourceCollectionFindingStageCompact,
    selectedTeamStartSourceCollectionStageTaskError,
    renderSourceCollectionConversation,
    renderSourceCollectionCandidatePanel,
    renderSourceCollectionScreeningPanel,
    renderSourceCollectionGraphPanel,
    renderSourceCollectionMemoryPanel,
  } = props;


    const activeModule =
      sourceCollectionStageModules.find((module: any) => module.id === selectedSourceCollectionStageId)
      ?? sourceCollectionStageModules[0];
    const primaryStageAgentChatState = sourceCollectionStageAgentChatState(activeModule.id);
    const primaryStageAgentChatRoute = primaryStageAgentChatState.route;
    const primaryStageAgentChatLoading = primaryStageAgentChatState.status === "loading";
    const primaryStageAgentChatError = primaryStageAgentChatState.status === "error";
    const primaryStageAgentRepairPending =
      primaryStageAgentChatState.status === "repair" && repairChallengeCupTeamAgentsMutation.isPending;
    const primaryStageAgentFallbackTitle = primaryStageAgentChatLoading
      ? (lang === "zh" ? "正在加载 Agent 配置，请稍候" : "Loading Agent configuration")
      : primaryStageAgentChatError
        ? (lang === "zh" ? "Agent 配置加载失败，请刷新后重试" : "Agent configuration failed to load")
        : (lang === "zh" ? "当前步骤缺少可用私聊，请先修复团队 Agent 绑定" : "No usable direct chat for this step");
    const primaryStageAgentFallbackLabel = primaryStageAgentChatLoading
      ? (lang === "zh" ? "加载 Agent..." : "Loading Agent...")
      : primaryStageAgentChatError
        ? (lang === "zh" ? "Agent 加载失败" : "Agent load failed")
        : primaryStageAgentRepairPending
          ? (lang === "zh" ? "修复中" : "Repairing")
          : (lang === "zh" ? "修复团队 Agent" : "Repair Team Agents");
    const primaryStageAgentBinding = sourceCollectionStagePrimaryAgentBinding(activeModule.id);
    const primaryStageAgentConfigRoute = primaryStageAgentBinding?.agentId
      ? researchStageAgentManagementRoute(primaryStageAgentBinding.agentId)
      : "/agents";
    const primaryStageAgentConfigLabel = primaryStageAgentBinding?.agent
      ? (lang === "zh" ? "配置 Agent" : "Configure Agent")
      : (lang === "zh" ? "绑定 Agent" : "Bind Agent");
    const sourceCollectionActiveStageCompact =
      activeModule.id === "finding" && sourceCollectionFindingStageCompact;
    return (
      <TeamSourceCollectionActiveStagePanel
        lang={lang}
        stageId={activeModule.id}
        compact={sourceCollectionActiveStageCompact}
        title={activeModule.label}
        status={activeModule.status}
        inputLabel={activeModule.inputLabel}
        outputLabel={activeModule.outputLabel}
        nextLabel={activeModule.nextLabel}
        primaryAction={{
          tone: activeModule.actionTone,
          disabled: activeModule.actionDisabled,
          onAction: activeModule.onAction,
          title: sourceCollectionActionDisabledTitle(sourceCollectionStageActionReadinessFor(activeModule.id), activeModule.actionLabel) || "",
          icon: activeModule.actionIcon,
          label: activeModule.actionLabel,
        }}
        agentChatAction={primaryStageAgentChatRoute ? (
          <Link
            to={primaryStageAgentChatRoute}
            title={stageChatLabels[activeModule.id][lang]}
          >
            <MessageSquare size={13} />
            {lang === "zh" ? "进入 Agent 私聊" : "Open Agent chat"}
          </Link>
        ) : (
          <VNativeButton
            type="button"
            title={primaryStageAgentFallbackTitle}
            onClick={() => openSourceCollectionStageAgentChat(activeModule.id)}
            disabled={primaryStageAgentChatLoading || primaryStageAgentChatError || primaryStageAgentRepairPending}
          >
            <MessageSquare size={13} />
            {primaryStageAgentFallbackLabel}
          </VNativeButton>
        )}
        agentConfigAction={(
          <VTooltip content={lang === "zh" ? "当前阶段 Agent 配置" : "Current stage Agent configuration"}>
            <Link to={primaryStageAgentConfigRoute}>
              <Link2 size={13} />
              {primaryStageAgentConfigLabel}
            </Link>
          </VTooltip>
        )}
        errors={(
          <>
            {repairChallengeCupTeamAgentsMutation.error instanceof Error ? (
              <div className={styles.messageError}>{repairChallengeCupTeamAgentsMutation.error.message}</div>
            ) : null}
            {selectedTeamStartSourceCollectionStageTaskError ? (
              <div className={styles.messageError}>{selectedTeamStartSourceCollectionStageTaskError.message}</div>
            ) : null}
          </>
        )}
        renderConversationPanel={renderSourceCollectionConversation}
        renderCandidatePanel={renderSourceCollectionCandidatePanel}
        renderScreeningPanel={renderSourceCollectionScreeningPanel}
        renderGraphPanel={renderSourceCollectionGraphPanel}
        renderMemoryPanel={renderSourceCollectionMemoryPanel}
      />
    );

}
