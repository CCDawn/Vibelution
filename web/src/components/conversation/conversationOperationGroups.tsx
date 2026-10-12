import type { ReactNode } from "react";
import {
  BrainCircuit,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Search,
  Sparkles,
  TerminalSquare,
  Wrench,
} from "lucide-react";

import { VButton } from "../vui";
import type { TranslationKey } from "../../i18n/dictionaryTypes";
import type {
  AgentMessageOperation,
  AgentMessageOperationKind,
} from "./agentMessageOperations";
import {
  compactInternalProcessStateLabel,
  isRunningOperationStatus,
  operationCollectionTone,
  operationStateLabel,
  shouldShowTimelineOperation,
  type OperationStateLabels,
} from "./conversationOperationState";
import { shouldExpandReActGroupByDefault } from "./conversationReActOperationItems";
import { isInternalRuntimeStatus } from "./conversationDisplayProtocol";
import { conversationOperationIconKind } from "./conversationOperationIconModel";
import {
  buildOperationDetailRows,
  DeferredOperationDetails,
  operationDetailsKind,
  type OperationDetailLabels,
} from "./ConversationOperationDetails";
import type { createConversationOperationRows } from "./conversationOperationRows";
import type { createConversationReActRows } from "./conversationReActRows";
import styles from "./ConversationView.styles";

const INITIAL_VISIBLE_FEEDBACK_OPERATION_COUNT = 36;

type OperationRowPresentation = Pick<
  ReturnType<typeof createConversationOperationRows>,
  | "formatDuration"
  | "operationTone"
  | "operationStatusToneClassName"
  | "operationStatusIcon"
  | "operationStatusText"
  | "operationLabel"
  | "hasOperationDetails"
  | "operationGroupTitle"
  | "operationTimelineTitle"
  | "processSummaryIcon"
>;

type ReActRows = Pick<
  ReturnType<typeof createConversationReActRows>,
  "feedbackTimelineGroups" | "renderFeedbackTimelineDetails"
>;

export type ConversationOperationGroupsDeps = OperationRowPresentation & ReActRows & {
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  getExpansionState: (messageId: string, section: string, defaultExpanded: boolean) => boolean;
  toggleSection: (messageId: string, section: string, defaultExpanded: boolean) => void;
  operationStateLabels: OperationStateLabels;
  operationDetailLabels: OperationDetailLabels;
  renderComputerUseResult: (operation: AgentMessageOperation) => ReactNode;
};

/**
 * Operation timeline and the collapsible operation/feedback groups. Extracted
 * from ConversationView with identical render output; the computer-use panel
 * stays component-owned and arrives as a render prop.
 */
export function createConversationOperationGroups({
  lang,
  t,
  getExpansionState,
  toggleSection,
  operationStateLabels,
  operationDetailLabels,
  renderComputerUseResult,
  formatDuration,
  operationTone,
  operationStatusToneClassName,
  operationStatusIcon,
  operationStatusText,
  operationLabel,
  hasOperationDetails,
  operationGroupTitle,
  operationTimelineTitle,
  processSummaryIcon,
  feedbackTimelineGroups,
  renderFeedbackTimelineDetails,
}: ConversationOperationGroupsDeps) {
  function operationIcon(kind: AgentMessageOperationKind, label: string) {
    switch (conversationOperationIconKind(kind, label)) {
      case "thought":
        return <Sparkles size={17} />;
      case "mental":
        return <BrainCircuit size={17} />;
      case "search":
        return <Search size={17} />;
      case "link":
        return <ExternalLink size={17} />;
      case "terminal":
        return <TerminalSquare size={17} />;
      case "tool":
      default:
        return <Wrench size={17} />;
    }
  }

  function isCompactInternalStatusOperation(operation: AgentMessageOperation) {
    return Boolean(
      operation.kind === "status"
      && !operation.error?.trim()
      && isInternalRuntimeStatus({
        kind: "status",
        name: operation.rawLabel ?? operation.label,
        status: operation.status,
        summary: operation.summary,
        resultPreview: operation.resultPreview,
      }),
    );
  }

  function renderOperationTimeline(operations: AgentMessageOperation[], options: { limitInitialRows?: boolean } = {}) {
    const shouldLimitRows = options.limitInitialRows && operations.length > INITIAL_VISIBLE_FEEDBACK_OPERATION_COUNT;
    const hiddenOperationCount = shouldLimitRows ? operations.length - INITIAL_VISIBLE_FEEDBACK_OPERATION_COUNT : 0;
    const visibleOperations = shouldLimitRows
      ? operations.slice(-INITIAL_VISIBLE_FEEDBACK_OPERATION_COUNT)
      : operations;
    return (
      <div className={styles.operationTimeline}>
        {hiddenOperationCount > 0 ? (
          <div className={styles.operationTimelineTrimmed}>
            {lang === "zh"
              ? `已折叠更早 ${hiddenOperationCount} 步执行记录`
              : `${hiddenOperationCount} earlier execution steps collapsed`}
          </div>
        ) : null}
        {visibleOperations.map((operation) => {
          const duration = formatDuration(operation.durationSeconds);
          const detailsId = `operation-detail-${operation.id}`;
          const detailsExpanded = getExpansionState(operation.id, "details", false);
          const canExpandDetails = hasOperationDetails(operation);
          const computerUseResult = renderComputerUseResult(operation);
          const detailToggleTitle = operation.kind === "thought"
            ? detailsExpanded ? t("thoughtProcessVisible") : t("thoughtProcessHidden")
            : operation.kind === "status"
              ? detailsExpanded ? t("executionDetailsVisible") : t("executionDetailsHidden")
            : detailsExpanded ? t("toolCallDetailsVisible") : t("toolCallDetailsHidden");
          const statusTone = operationStatusToneClassName(operation);
          const operationClassName = [
            styles.operationItem,
            styles[`operationItem_${operationTone(operation)}`],
            styles[`operationItem_${statusTone}`],
            isRunningOperationStatus(operation.status) ? styles.operationItemActive : "",
          ].filter(Boolean).join(" ");
          return (
            <div key={operation.id} className={styles.operationItemWrap}>
              <div className={operationClassName}>
                <span
                  className={`${styles.operationIcon} ${styles[`operationIcon_${operation.kind}`]} ${styles[`operationIcon_${statusTone}`]}`}
                >
                  {operationIcon(operation.kind, operation.label)}
                </span>
                <div className={`${styles.operationText} ${styles[`operationText_${statusTone}`]}`}>
                  <span className={`${styles.operationName} ${styles[`operationText_${statusTone}`]}`}>{operationLabel(operation)}</span>
                  {operation.summary ? (
                    <span className={`${styles.operationSummaryText} ${styles[`operationText_${statusTone}`]}`}>{operation.summary}</span>
                  ) : null}
                </div>
                <span className={`${styles.operationStatus} ${styles[`operationStatus_${statusTone}`]}`}>
                  {operationStatusIcon(operation)}
                  <span>{operationStatusText(operation.status)}</span>
                </span>
                {duration ? <span className={styles.operationDuration}>{duration}</span> : null}
                {canExpandDetails ? (
                  <VButton
                    type="button"
                    className={styles.operationDetailToggle}
                    aria-expanded={detailsExpanded}
                    aria-controls={detailsId}
                    onClick={() => toggleSection(operation.id, "details", false)}
                    title={detailToggleTitle}
                    isIconOnly
                    icon={detailsExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />} />
                ) : (
                  <span className={styles.operationChevron} aria-hidden="true">
                    {hasOperationDetails(operation) ? <ChevronRight size={16} /> : null}
                  </span>
                )}
              </div>
              {canExpandDetails ? (
                <DeferredOperationDetails
                  operation={operation}
                  expanded={detailsExpanded}
                  detailsId={detailsId}
                  kind={operationDetailsKind(operation)}
                  buildDetailRows={(detailOperation) => buildOperationDetailRows(detailOperation, operationDetailLabels)}
                />
              ) : null}
              {computerUseResult}
            </div>
          );
        })}
      </div>
    );
  }

  function renderOperationGroup(
    messageId: string,
    section: "thought" | "mental" | "tools",
    operations: AgentMessageOperation[],
    defaultExpanded: boolean,
  ) {
    if (operations.length === 0) {
      return null;
    }
    const expanded = getExpansionState(messageId, section, defaultExpanded);
    const kind = operations[0]?.kind ?? "tool";
    const title = operationGroupTitle(kind, operations.length);
    const toggleTitle = expanded
      ? section === "thought"
        ? t("thoughtProcessVisible")
        : section === "mental"
          ? t("mentalProcessVisible")
          : t("toolProcessVisible")
      : section === "thought"
        ? t("thoughtProcessHidden")
        : section === "mental"
          ? t("mentalProcessHidden")
          : t("toolProcessHidden");
    return (
      <section className={styles.operationGroup}>
        <VButton
          type="button"
          className={styles.operationSummary}
          aria-expanded={expanded}
          onClick={() => toggleSection(messageId, section, defaultExpanded)}
          title={toggleTitle}
          icon={operationIcon(kind, title)}
          trailingIcon={expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        >
          <span>{title}</span>
          {!expanded && operations[0]?.summary ? (
            <span className={styles.operationSummaryPreview}>{operations[0].summary}</span>
          ) : null}
        </VButton>
        {expanded ? renderOperationTimeline(operations) : null}
      </section>
    );
  }

  function renderFeedbackTimelineGroup(
    messageId: string,
    operations: AgentMessageOperation[],
    defaultExpanded: boolean,
    processSectionIds?: string,
  ) {
    if (operations.length === 0) {
      return null;
    }
    const { visibleOperations, reActGroups } = feedbackTimelineGroups(operations);
    if (visibleOperations.length === 0) {
      return null;
    }
    if (reActGroups.length === 0) {
      return null;
    }
    const defaultTimelineExpanded = defaultExpanded || reActGroups.some((group) => shouldExpandReActGroupByDefault(group));
    const expanded = getExpansionState(messageId, "feedback", defaultTimelineExpanded);
    const title = operationTimelineTitle(visibleOperations);
    const collectionTone = operationCollectionTone(operations);
    const stateLabel = operations.length > visibleOperations.length && collectionTone === "running"
      ? compactInternalProcessStateLabel(collectionTone, operations, operationStateLabels)
      : operationStateLabel(operationCollectionTone(visibleOperations), operationStateLabels);
    return (
      <section
        className={`${styles.operationGroup} ${styles.executionTraceGroup}`}
        data-agent-process-section-ids={processSectionIds}
        data-agent-process-kind={processSectionIds ? "feedback" : undefined}
      >
        <VButton
          type="button"
          className={styles.operationSummary}
          aria-expanded={expanded}
          onClick={() => toggleSection(messageId, "feedback", defaultTimelineExpanded)}
          title={expanded ? t("executionDetailsVisible") : t("executionDetailsHidden")}
          icon={operationIcon(operations[0]?.kind ?? "tool", title)}
          trailingIcon={expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        >
          <span>{title}</span>
          <span className={styles.operationSummaryCount}>{stateLabel}</span>
        </VButton>
        {expanded ? renderFeedbackTimelineDetails(messageId, operations) : null}
      </section>
    );
  }

  return {
    isCompactInternalStatusOperation,
    renderOperationTimeline,
    renderOperationGroup,
    renderFeedbackTimelineGroup,
  };
}
