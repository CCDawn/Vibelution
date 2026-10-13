import type { ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { VButton } from "../vui";
import type { TranslationKey } from "../../i18n/dictionaryTypes";
import type {
  AgentMessageOperation,
  AgentMessageReActOperationGroup,
} from "./agentMessageOperations";
import { buildAgentMessageReActOperationGroups } from "./agentMessageOperations";
import {
  compactVisibleTimelineOperations,
  shouldShowTimelineOperation,
} from "./conversationOperationState";
import {
  reActActionOperations,
  reActResultItems,
  reActThoughtItems,
} from "./conversationReActOperationItems";
import {
  buildOperationDetailRows,
  DeferredOperationDetails,
  readableOperationResult,
  type OperationDetailLabels,
} from "./ConversationOperationDetails";
import { ConversationToolActivityPills } from "./ConversationToolActivityPills";
import type { createConversationOperationRows } from "./conversationOperationRows";
import styles from "./ConversationView.styles";

type OperationRowPresentation = Pick<
  ReturnType<typeof createConversationOperationRows>,
  | "formatDuration"
  | "buildLegacyToolActivityPills"
  | "operationLabel"
  | "operationStatusIcon"
  | "operationStatusText"
  | "operationStatusToneClassName"
  | "hasOperationDetails"
>;

export type ConversationReActRowsDeps = OperationRowPresentation & {
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  getExpansionState: (messageId: string, section: string, defaultExpanded: boolean) => boolean;
  toggleSection: (messageId: string, section: string, defaultExpanded: boolean) => void;
  operationDetailLabels: OperationDetailLabels;
  renderComputerUseResult: (operation: AgentMessageOperation) => ReactNode;
};

/**
 * ReAct（思考/行动/结果）process rows and the feedback timeline grouping.
 * Extracted from ConversationView with identical render output; the computer
 * -use panel stays component-owned and arrives as a render prop.
 */
export function createConversationReActRows({
  lang,
  t,
  getExpansionState,
  toggleSection,
  operationDetailLabels,
  renderComputerUseResult,
  formatDuration,
  buildLegacyToolActivityPills,
  operationLabel,
  operationStatusIcon,
  operationStatusText,
  operationStatusToneClassName,
  hasOperationDetails,
}: ConversationReActRowsDeps) {
  function renderReActActionSection(group: AgentMessageReActOperationGroup) {
    const actions = reActActionOperations(group);
    if (actions.length === 0) {
      return null;
    }
    return (
      <section className={styles.reActOperationSection}>
        <div className={styles.reActToolList}>
          {actions.map((operation) => {
            const duration = formatDuration(operation.durationSeconds);
            const detailsId = `operation-detail-${operation.id}`;
            const detailsExpanded = getExpansionState(operation.id, "details", false);
            const canExpandDetails = hasOperationDetails(operation);
            const computerUseResult = renderComputerUseResult(operation);
            const statusTone = operationStatusToneClassName(operation);
            const pills = operation.kind === "tool"
              ? buildLegacyToolActivityPills(operation)
              : null;
            return (
              <div key={operation.id} className={`${styles.reActToolItem} ${styles[`operationItem_${statusTone}`]}`}>
                <div className={`${styles.reActToolLine} ${styles[`operationItem_${statusTone}`]}`}>
                  {pills ? (
                    <ConversationToolActivityPills pills={pills} />
                  ) : (
                    <span className={`${styles.reActToolName} ${styles[`operationText_${statusTone}`]}`}>{operationLabel(operation)}</span>
                  )}
                  {!pills && operation.summary ? (
                    <span className={`${styles.reActToolSummary} ${styles[`operationText_${statusTone}`]}`}>{operation.summary}</span>
                  ) : null}
                  {!pills ? (
                    <span className={`${styles.reActToolStatus} ${styles[`operationStatus_${statusTone}`]}`}>
                      {operationStatusIcon(operation)}
                      <span>{operationStatusText(operation.status)}</span>
                      {duration ? <span>{duration}</span> : null}
                    </span>
                  ) : null}
                  {canExpandDetails ? (
                    <VButton
                      type="button"
                      className={styles.reActToolDetailToggle}
                      aria-expanded={detailsExpanded}
                      aria-controls={detailsId}
                      onClick={() => toggleSection(operation.id, "details", false)}
                      title={detailsExpanded ? t("toolCallDetailsVisible") : t("toolCallDetailsHidden")}
                      isIconOnly
                      icon={detailsExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />} />
                  ) : null}
                </div>
                {canExpandDetails ? (
                  <DeferredOperationDetails
                    operation={operation}
                    expanded={detailsExpanded}
                    detailsId={detailsId}
                    kind="tool"
                    buildDetailRows={(detailOperation) => buildOperationDetailRows(detailOperation, operationDetailLabels)}
                  />
                ) : null}
                {computerUseResult}
              </div>
            );
          })}
        </div>
      </section>
    );
  }

  function renderReActThoughtSection(group: AgentMessageReActOperationGroup) {
    const thoughts = reActThoughtItems(group);
    if (thoughts.length === 0) {
      return null;
    }
    return (
      <section className={styles.reActOperationSection}>
        <span className={styles.reActOperationSectionLabel}>{lang === "zh" ? "思考" : "Thinking"}</span>
        <div className={styles.reActThoughtStack}>
          {thoughts.map((item) => (
            <pre key={item.id} className={styles.reActThoughtText}>{item.value}</pre>
          ))}
        </div>
      </section>
    );
  }

  function renderReActResultSection(messageId: string, group: AgentMessageReActOperationGroup) {
    const results = reActResultItems(group, {
      operationLabel,
      readableOperationResult: (operation) => readableOperationResult(operation, operationDetailLabels.structuredResultFallback),
    });
    if (results.length === 0) {
      return null;
    }
    const sectionId = `feedback-react-results-${group.id}`;
    const bodyId = `${sectionId}-body`;
    const expanded = getExpansionState(messageId, sectionId, false);
    const label = lang === "zh"
      ? results.length > 1 ? `结果 ${results.length}` : "结果"
      : results.length > 1 ? `${results.length} results` : "Result";
    return (
      <section className={styles.reActOperationSection}>
        <VButton
          type="button"
          className={styles.reActResultToggle}
          aria-expanded={expanded}
          aria-controls={bodyId}
          onClick={() => toggleSection(messageId, sectionId, false)}
          title={expanded
            ? lang === "zh" ? "折叠工具结果" : "Collapse tool results"
            : lang === "zh" ? "展开工具结果" : "Expand tool results"}
          trailingIcon={expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        >
          <span className={styles.reActOperationSectionLabel}>{label}</span>
        </VButton>
        {expanded ? (
          <div id={bodyId} className={styles.reActResultList}>
            {results.map((item) => (
              <div
                key={item.id}
                className={`${styles.reActResultItem} ${item.tone === "failed" ? styles.reActResultItem_failed : ""}`}
              >
                <span className={styles.reActResultLabel}>{item.label}</span>
                <pre className={styles.reActResultValue}>{item.value}</pre>
              </div>
            ))}
          </div>
        ) : null}
      </section>
    );
  }

  function renderReActOperationContent(messageId: string, group: AgentMessageReActOperationGroup) {
    return (
      <div className={styles.reActOperationBody}>
        {renderReActThoughtSection(group)}
        {renderReActActionSection(group)}
        {renderReActResultSection(messageId, group)}
      </div>
    );
  }

  function feedbackTimelineGroups(operations: AgentMessageOperation[]) {
    const visibleOperations = compactVisibleTimelineOperations(operations.filter(shouldShowTimelineOperation));
    return {
      visibleOperations,
      reActGroups: buildAgentMessageReActOperationGroups(visibleOperations),
    };
  }

  function renderFeedbackTimelineDetails(messageId: string, operations: AgentMessageOperation[]) {
    const { reActGroups } = feedbackTimelineGroups(operations);
    if (reActGroups.length === 0) {
      return null;
    }
    return (
      <div className={styles.reActOperationList}>
        {reActGroups.map((group) => (
          <div key={group.id}>
            {renderReActOperationContent(messageId, group)}
          </div>
        ))}
      </div>
    );
  }

  return {
    renderReActOperationContent,
    feedbackTimelineGroups,
    renderFeedbackTimelineDetails,
  };
}
