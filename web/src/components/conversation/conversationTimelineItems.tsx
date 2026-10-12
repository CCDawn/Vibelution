import type { ReactNode } from "react";
import {
  BrainCircuit,
  ChevronDown,
  ChevronRight,
  LoaderCircle,
  TerminalSquare,
} from "lucide-react";

import { VButton } from "../vui";
import type { TranslationKey } from "../../i18n/dictionaryTypes";
import type { ConversationMessage } from "../../api/types";
import { assistantTurnIsStreaming } from "../../routes/chatTurnProtocol";
import type {
  AgentMessageOperation,
} from "./agentMessageOperations";
import {
  activeAgentMessageTimelineItemId,
} from "./agentMessageTimelineActiveItem";
import type { AgentMessageTimelineItem } from "./agentMessageTimeline";
import {
  agentMessageTimelineItemRowKey,
  type AgentMessageTimelineRowIdentity,
} from "./agentMessageTimelineRows";
import { isRetryOperation } from "./conversationOperationState";
import {
  buildCodexToolActivityPills,
  completedToolPresentationSummary,
  conversationToolPresentationLabel,
} from "./conversationToolPresentation";
import {
  ConversationToolActivityPills,
  toolActivityAriaTitle,
} from "./ConversationToolActivityPills";
import {
  buildOperationDetailRows,
  DeferredOperationDetails,
  operationDetailsKind,
  readableOperationResult,
  type OperationDetailLabels,
} from "./ConversationOperationDetails";
import {
  ThoughtDurationLabel,
  ThoughtScrollBody,
  ThoughtStreamingSummary,
} from "./conversationThoughtUnits";
import type { ResponseSegment } from "./messageResponseSegments";
import type { createCodexTranscriptCellRenderers } from "./conversationCodexTranscriptCells";
import type { createConversationCodexToolDetails } from "./conversationCodexToolDetails";
import type { createConversationOperationGroups } from "./conversationOperationGroups";
import type { createConversationOperationRows } from "./conversationOperationRows";
import type { createConversationResponseBlocks } from "./conversationResponseBlocks";
import styles from "./ConversationView.styles";

type OperationRowPresentation = Pick<
  ReturnType<typeof createConversationOperationRows>,
  | "formatDuration"
  | "operationStatusToneClassName"
  | "operationStatusIcon"
  | "operationStatusText"
  | "operationLabel"
  | "buildLegacyToolActivityPills"
  | "hasOperationDetails"
>;

export type ConversationTimelineItemsDeps = OperationRowPresentation & {
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  getExpansionState: (messageId: string, section: string, defaultExpanded: boolean) => boolean;
  toggleSection: (messageId: string, section: string, defaultExpanded: boolean) => void;
  operationDetailLabels: OperationDetailLabels;
  renderComputerUseResult: (operation: AgentMessageOperation) => ReactNode;
  imageArtifactUrlsBeforeMessage: Map<string, Set<string>>;
  getCachedResponseSegments: (content: string) => ResponseSegment[];
  renderRolloutTraceEvents: ReturnType<typeof createConversationCodexToolDetails>["renderRolloutTraceEvents"];
  isCompactInternalStatusOperation: ReturnType<typeof createConversationOperationGroups>["isCompactInternalStatusOperation"];
  renderResponseSegment: ReturnType<typeof createConversationResponseBlocks>["renderResponseSegment"];
  renderAssistantFileReferenceChips: ReturnType<typeof createConversationResponseBlocks>["renderAssistantFileReferenceChips"];
};

/**
 * Agent-message timeline item renderers (thought / assistant text / command
 * group / single operation) and the timeline host. Extracted from
 * ConversationView with identical output.
 */
export function createConversationTimelineItems({
  lang,
  t,
  getExpansionState,
  toggleSection,
  operationDetailLabels,
  renderComputerUseResult,
  imageArtifactUrlsBeforeMessage,
  getCachedResponseSegments,
  renderRolloutTraceEvents,
  isCompactInternalStatusOperation,
  renderResponseSegment,
  renderAssistantFileReferenceChips,
  formatDuration,
  operationStatusToneClassName,
  operationStatusIcon,
  operationStatusText,
  operationLabel,
  buildLegacyToolActivityPills,
  hasOperationDetails,
}: ConversationTimelineItemsDeps) {
  function renderThoughtTimelineItem(
    message: ConversationMessage,
    item: Extract<AgentMessageTimelineItem, { kind: "thought" }>,
    rowIdentity: AgentMessageTimelineRowIdentity,
    isActiveTimelineItem: boolean,
  ) {
    // ZCode parity: streaming and settled thoughts both stay collapsed until
    // the user expands; the collapsed header shows the running/settled title plus a
    // single-line rolling summary of the latest thought sentence.
    const isLive = item.status === "running" || item.status === "pending";
    const defaultExpanded = false;
    const sectionId = `thought:${item.id}`;
    const expanded = getExpansionState(message.id, sectionId, defaultExpanded);
    const toggleLabel = expanded ? t("thoughtProcessVisible") : t("thoughtProcessHidden");
    const thoughtTitle = isLive
      ? (lang === "zh" ? "思考中" : "Thinking…")
      : (lang === "zh" ? "已思考" : "Thought");
    return (
      <section
        key={agentMessageTimelineItemRowKey(rowIdentity, item)}
        className={styles.timelineThoughtCell}
        data-conversation-part-key={agentMessageTimelineItemRowKey(rowIdentity, item)}
        data-thought-section={sectionId}
        data-thought-expanded={expanded ? "true" : "false"}
      >
        <VButton
          type="button"
        contentLayout="plain"
          className={styles.timelineThoughtHeader}
          aria-expanded={expanded}
          aria-label={toggleLabel}
          onClick={(event) => {
            event.stopPropagation();
            toggleSection(message.id, sectionId, defaultExpanded);
          }}
        >
          {isActiveTimelineItem && isLive ? <LoaderCircle className={styles.statusSpinner} size={14} /> : <BrainCircuit size={14} />}
          <span className={styles.timelineCellBody}>
            <span className={`${styles.timelineCellTitleRow} ${styles.timelineCellCompactTitleRow}`}>
              <span className={styles.codexTranscriptReasoningTitle}>{thoughtTitle}</span>
              <ThoughtDurationLabel
                live={isLive}
                expanded={expanded}
                settledDurationSeconds={item.settledDurationSeconds}
                settledSecondsTemplate={t("thoughtDurationSettledSeconds")}
                settledMomentsLabel={t("thoughtDurationSettledMoments")}
              />
              {!expanded ? <ThoughtStreamingSummary text={item.text} /> : null}
            </span>
          </span>
          {expanded ? <ChevronDown size={15} aria-hidden="true" /> : <ChevronRight size={15} aria-hidden="true" />}
        </VButton>
        {expanded ? (
          <div className={styles.codexTranscriptReasoningTextButton}>
            <ThoughtScrollBody
              text={item.text}
              streaming={isLive}
            />
          </div>
        ) : null}
      </section>
    );
  }

  function renderAssistantTextTimelineItem(
    message: ConversationMessage,
    item: Extract<AgentMessageTimelineItem, { kind: "assistant_text" }>,
    rowIdentity: AgentMessageTimelineRowIdentity,
  ) {
    const segments = getCachedResponseSegments(item.text);
    return (
      <section
        key={agentMessageTimelineItemRowKey(rowIdentity, item)}
        className={styles.timelineAssistantTextCell}
        data-conversation-part-key={agentMessageTimelineItemRowKey(rowIdentity, item)}
      >
        {segments.map((segment) => renderResponseSegment(segment, imageArtifactUrlsBeforeMessage.get(message.id)))}
        {renderAssistantFileReferenceChips(message, item.text)}
      </section>
    );
  }

  function timelineStatusText(item: AgentMessageTimelineItem) {
    const status = item.status;
    if (status === "failed") {
      return lang === "zh" ? "执行失败" : "Failed";
    }
    if (status === "degraded") {
      const rawStatus = item.kind === "operation"
        ? String(item.operation.status || item.operation.rawStatus || "").trim().toLowerCase()
        : "";
      if (rawStatus === "fallback") {
        return lang === "zh" ? "备用路径" : "Fallback";
      }
      if (rawStatus === "partial") {
        return lang === "zh" ? "部分结果" : "Partial";
      }
      if (rawStatus === "unavailable") {
        return lang === "zh" ? "不可用" : "Unavailable";
      }
      if (rawStatus === "recovered") {
        return lang === "zh" ? "已恢复" : "Recovered";
      }
      return lang === "zh" ? "降级" : "Degraded";
    }
    if (status === "running") {
      return lang === "zh" ? "运行中" : "Running";
    }
    if (status === "pending") {
      return lang === "zh" ? "等待中" : "Pending";
    }
    return "";
  }

  function renderCommandGroupTimelineItem(
    message: ConversationMessage,
    item: Extract<AgentMessageTimelineItem, { kind: "command_group" }>,
    rowIdentity: AgentMessageTimelineRowIdentity,
    isActiveTimelineItem: boolean,
  ) {
    const expanded = getExpansionState(message.id, item.id, false);
    const duration = formatDuration(
      item.operations
        .map((operation) => operation.durationSeconds)
        .filter((value): value is number => typeof value === "number" && Number.isFinite(value) && value > 0)
        .reduce((total, value) => total + value, 0),
    );
    const groupPills = buildCodexToolActivityPills({
      toolName: "exec_command",
      status: item.status,
      language: lang === "en" ? "en" : "zh",
      durationLabel: duration,
      cellSummary: item.summary,
    });
    // Package title stays prominent; summary is the muted subject under the pill pair.
    if (item.title?.trim()) {
      groupPills.actionLabel = item.title.trim();
    }
    if (item.summary?.trim()) {
      groupPills.subject = item.summary.trim();
    }
    const statusTone = item.status === "completed" ? "success" : item.status === "degraded" ? "warning" : item.status;
    const timelineToneClassName = styles[`timelineOperationCell_${statusTone}` as keyof typeof styles] ?? "";
    const toneTextClassName = styles[`operationText_${statusTone}` as keyof typeof styles] ?? "";
    const toneIconClassName = styles[`operationIcon_${statusTone}` as keyof typeof styles] ?? "";
    const className = [
      styles.timelineOperationCell,
      timelineToneClassName,
    ].filter(Boolean).join(" ");
    return (
      <section
        key={agentMessageTimelineItemRowKey(rowIdentity, item)}
        className={className}
        data-conversation-part-key={agentMessageTimelineItemRowKey(rowIdentity, item)}
      >
        <VButton
          type="button"
        contentLayout="plain"
          className={`${styles.timelineCellHeader} ${toneTextClassName}`}
          aria-expanded={expanded}
          aria-label={toolActivityAriaTitle(groupPills)}
          onClick={() => toggleSection(message.id, item.id, false)}
          title={expanded ? t("executionDetailsVisible") : t("executionDetailsHidden")}
        >
          <ConversationToolActivityPills
            pills={groupPills}
            leadingIcon={(
              <span className={`${styles.operationIcon} ${toneIconClassName}`}>
                {isActiveTimelineItem && item.status === "running"
                  ? <LoaderCircle className={styles.statusSpinner} size={14} />
                  : <TerminalSquare size={14} />}
              </span>
            )}
          />
        </VButton>
        {expanded ? (
          <div className={styles.timelineCommandList}>
            {item.operations.map((operation) => {
              const operationIconClassName = styles[`operationIcon_${operationStatusToneClassName(operation)}` as keyof typeof styles] ?? "";
              const pills = buildLegacyToolActivityPills(operation);
              return (
                <div key={operation.id} className={styles.timelineCommandRow}>
                  <ConversationToolActivityPills
                    pills={pills}
                    leadingIcon={(
                      <span className={`${styles.operationIcon} ${operationIconClassName}`}>
                        {operationStatusIcon(operation, isActiveTimelineItem)}
                      </span>
                    )}
                  />
                  {renderRolloutTraceEvents(operation)}
                  {operation.error ? <span className={styles.timelineCommandError}>{operation.error}</span> : null}
                </div>
              );
            })}
          </div>
        ) : null}
      </section>
    );
  }

  function isLowValueToolLoopStatusOperation(operation: AgentMessageOperation) {
    if (operation.kind !== "status") {
      return false;
    }
    const haystack = [
      operation.label,
      operation.rawLabel,
      operation.summary,
      operation.resultPreview,
      operation.error,
    ].map((value) => String(value || "").toLowerCase()).join(" ");
    return (
      haystack.includes("long_loop")
      || haystack.includes("工具循环")
      || haystack.includes("tool loop")
      || haystack.includes("尚未形成最终回答")
      || haystack.includes("本轮尚未形成最终回答")
      || haystack.includes("尚未形成最终回答")
    );
  }

  function renderOperationTimelineItem(
    item: Extract<AgentMessageTimelineItem, { kind: "operation" }>,
    rowIdentity: AgentMessageTimelineRowIdentity,
    isActiveTimelineItem: boolean,
  ) {
    const operation = item.operation;
    // Codex does not surface internal "tool loop / no final answer yet" progress as a tool row.
    if (isLowValueToolLoopStatusOperation(operation)) {
      return null;
    }
    const rawTimelineTitle = String(item.title ?? "").trim();
    const itemSummary = String(item.summary ?? "").trim();
    const rawOperationLabel = String(operation.rawLabel ?? "").trim();
    const rawToolName = rawOperationLabel || rawTimelineTitle || String(operation.label ?? "").trim();
    const semanticToolTitle = conversationToolPresentationLabel(rawToolName, lang);
    const visibleTitle = isRetryOperation(operation)
      ? lang === "zh" ? "请求重试" : "Retrying"
      : operation.kind === "tool"
      ? rawTimelineTitle && rawTimelineTitle !== rawOperationLabel
        ? rawTimelineTitle
        : semanticToolTitle
      : rawTimelineTitle && rawTimelineTitle !== rawOperationLabel
        ? rawTimelineTitle
        : operationLabel(operation);
    const detailsId = `timeline-operation-detail-${operation.id}`;
    const detailsExpanded = getExpansionState(operation.id, "details", false);
    const canExpandDetails = hasOperationDetails(operation);
    const duration = formatDuration(operation.durationSeconds);
    const computerUseResult = renderComputerUseResult(operation);
    const readableResult = operation.kind === "tool" || isCompactInternalStatusOperation(operation)
      ? ""
      : readableOperationResult(operation, operationDetailLabels.structuredResultFallback);
    const showReadableResult = Boolean(operation.kind !== "tool" && readableResult && readableResult !== itemSummary);
    const visibleStatus = timelineStatusText(item);
    const statusTone = operationStatusToneClassName(operation);
    const timelineToneClassName = styles[`timelineOperationCell_${statusTone}` as keyof typeof styles] ?? "";
    const toneTextClassName = styles[`operationText_${statusTone}` as keyof typeof styles] ?? "";
    const toneStatusClassName = styles[`operationStatus_${statusTone}` as keyof typeof styles] ?? "";
    const toneIconClassName = styles[`operationIcon_${statusTone}` as keyof typeof styles] ?? "";
    const metaText = [visibleStatus, duration].filter(Boolean).join(" · ");
    const visibleSummary = operation.kind === "tool"
      ? completedToolPresentationSummary({
          toolSummary: operation.error,
          cellSummary: String(operation.summary ?? ""),
          resultPreview: operation.resultPreview,
          cellText: itemSummary,
          toolName: rawToolName,
          status: item.status,
          language: lang,
        })
      : statusTone === "failed" && operation.error?.trim()
        ? [itemSummary, operation.error.trim()].filter(Boolean).join(" · ")
        : itemSummary;
    const toolPills = operation.kind === "tool"
      ? buildLegacyToolActivityPills(operation, {
          status: item.status,
          title: rawToolName,
          summary: itemSummary || visibleSummary,
          durationLabel: duration,
        })
      : null;
    const className = [
      styles.timelineOperationCell,
      timelineToneClassName,
    ].filter(Boolean).join(" ");
    const leadingIcon = (
      <span className={`${styles.operationIcon} ${toneIconClassName}`}>
        {operationStatusIcon(operation, isActiveTimelineItem)}
      </span>
    );
    // Tool rows: Codex quiet chrome — leading status icon only. A trailing
    // ChevronRight was wrapping onto a second grid line as a lone "›" under the icon.
    const headerContent = toolPills ? (
      <ConversationToolActivityPills pills={toolPills} leadingIcon={leadingIcon} />
    ) : (
      <>
        {leadingIcon}
        <span className={styles.timelineCellBody}>
          <span className={`${styles.timelineCellTitleRow} ${styles.timelineCellCompactTitleRow}`}>
            <span className={`${styles.timelineCellTitle} ${toneTextClassName}`}>{visibleTitle}</span>
            {metaText ? <span className={`${styles.timelineCellMeta} ${toneStatusClassName}`}>{metaText}</span> : null}
            {canExpandDetails ? (
              <span className={styles.timelineCellInlineChevron} aria-hidden="true">
                {detailsExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </span>
            ) : null}
            {visibleSummary ? <span className={styles.timelineCellSeparator} aria-hidden="true">·</span> : null}
            {visibleSummary ? <span className={styles.timelineCellInlineSummary}>{visibleSummary}</span> : null}
          </span>
        </span>
      </>
    );
    const headerAriaLabel = toolPills ? toolActivityAriaTitle(toolPills) : visibleTitle;
    return (
      <section
        key={agentMessageTimelineItemRowKey(rowIdentity, item)}
        className={className}
        data-conversation-part-key={agentMessageTimelineItemRowKey(rowIdentity, item)}
        data-codex-tool-unified-row={toolPills ? "true" : undefined}
      >
        {canExpandDetails ? (
          <VButton
            type="button"
            className={`${styles.timelineCellHeader} ${toneTextClassName}`}
            aria-expanded={detailsExpanded}
            aria-controls={detailsId}
            aria-label={headerAriaLabel}
            onClick={() => toggleSection(operation.id, "details", false)}
            title={detailsExpanded ? t("toolCallDetailsVisible") : t("toolCallDetailsHidden")}
          >
            {headerContent}
          </VButton>
        ) : (
          <div className={`${styles.timelineCellHeader} ${toneTextClassName}`}>
            {headerContent}
          </div>
        )}
        {canExpandDetails ? (
          <>
            <DeferredOperationDetails
              operation={operation}
              expanded={detailsExpanded}
              detailsId={detailsId}
              kind={operationDetailsKind(operation)}
              buildDetailRows={(detailOperation) => buildOperationDetailRows(detailOperation, operationDetailLabels)}
            />
            {detailsExpanded ? renderRolloutTraceEvents(operation) : null}
          </>
        ) : null}
        {showReadableResult ? <pre className={styles.timelineOperationResult}>{readableResult}</pre> : null}
        {computerUseResult}
      </section>
    );
  }

  function renderAgentMessageTimelineItem(
    message: ConversationMessage,
    item: AgentMessageTimelineItem,
    rowIdentity: AgentMessageTimelineRowIdentity,
    isActiveTimelineItem: boolean,
  ) {
    if (item.kind === "thought") {
      return renderThoughtTimelineItem(message, item, rowIdentity, isActiveTimelineItem);
    }
    if (item.kind === "assistant_text") {
      return renderAssistantTextTimelineItem(message, item, rowIdentity);
    }
    if (item.kind === "command_group") {
      return renderCommandGroupTimelineItem(message, item, rowIdentity, isActiveTimelineItem);
    }
    return renderOperationTimelineItem(item, rowIdentity, isActiveTimelineItem);
  }

  function renderAgentMessageTimeline(
    message: ConversationMessage,
    items: AgentMessageTimelineItem[],
    rowIdentity: AgentMessageTimelineRowIdentity,
    processSectionIds?: string,
  ) {
    if (items.length === 0) {
      return null;
    }
    const activeItemId = activeAgentMessageTimelineItemId({ streaming: assistantTurnIsStreaming(message) }, items);
    return (
      <div
        className={styles.conversationCellTimeline}
        data-conversation-part-key={rowIdentity.processKey}
        data-agent-process-section-ids={processSectionIds}
        data-agent-process-kind={processSectionIds ? "timeline" : undefined}
      >
        {items.map((item) => renderAgentMessageTimelineItem(message, item, rowIdentity, item.id === activeItemId))}
      </div>
    );
  }

  return { renderAgentMessageTimeline };
}
