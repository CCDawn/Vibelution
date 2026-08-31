import { useId } from "react";

import { VButton, VSurface } from "../../components/vui";
import type {
  ChallengeMeetingEvidenceRequest,
  ChallengeMeetingMessagePayload,
  ChatRoomMessage,
} from "../../api/types";
import {
  tokenizeChatMentions,
  type ChatMentionTarget,
} from "../chatMentionTokens";
import styles from "./ChatGroupMessagePresentation.styles";
import {
  shouldCollapseGroupMessage,
  stripGroupSpeakerPrefix,
} from "./chatRoutePresentation";

export type ChatMentionedTextProps = {
  content: string;
  fallback?: string;
  lang: "zh" | "en";
  mentionTargets: ChatMentionTarget[];
  onOpenMentionTarget: (target: ChatMentionTarget) => void;
};

export function ChatMentionedText({
  content,
  fallback = "",
  lang,
  mentionTargets,
  onOpenMentionTarget,
}: ChatMentionedTextProps) {
  const text = content || fallback;
  return (
    <>
      {tokenizeChatMentions(text, mentionTargets).map((segment, index) => {
        if (segment.type === "text") {
          return <span key={`text-${index}`}>{segment.text}</span>;
        }
        const mentionLabel = segment.target.kind === "all"
          ? (lang === "zh" ? "全体成员" : "All agents")
          : [segment.target.displayName, segment.target.agentCode].filter(Boolean).join(" · ");
        return (
          <VButton
            key={`mention-${index}-${segment.text}`}
            type="button"
            className={styles.agentMention}
            onClick={() => onOpenMentionTarget(segment.target)}
            aria-label={lang === "zh" ? `打开 ${mentionLabel} 的索引` : `Open ${mentionLabel} index`}
            title={lang === "zh" ? "打开对应 Agent 索引" : "Open the matching agent index"}
          >
            {segment.text}
          </VButton>
        );
      })}
    </>
  );
}

export type ChatGroupMessageBodyProps = {
  message: ChatRoomMessage;
  identityName: string;
  lang: "zh" | "en";
  expandedMessageIds: string[];
  mentionTargets: ChatMentionTarget[];
  onOpenMentionTarget: (target: ChatMentionTarget) => void;
  onToggleExpanded: (messageId: string) => void;
};

function structuredChallengePayload(
  message: ChatRoomMessage,
): ChallengeMeetingMessagePayload | null {
  const payload = message.messagePayload;
  if (
    payload?.schemaVersion !== 1
    || payload.kind !== "challenge_meeting_message"
    || payload.audit?.parseStatus !== "structured"
  ) {
    return null;
  }
  return payload;
}

function evidenceFields(request: ChallengeMeetingEvidenceRequest, lang: "zh" | "en") {
  const values = [
    {
      label: lang === "zh" ? "关联候选" : "Candidates",
      value: request.candidateRefs?.join(" · "),
    },
    {
      label: lang === "zh" ? "检索关键词" : "Keywords",
      value: request.searchEnvelope?.keywords?.join(" · "),
    },
    {
      label: lang === "zh" ? "来源类型" : "Source types",
      value: request.searchEnvelope?.sourceTypes?.join(" · "),
    },
    {
      label: lang === "zh" ? "证据等级" : "Evidence levels",
      value: request.searchEnvelope?.evidenceLevels?.join(" · "),
    },
    {
      label: lang === "zh" ? "最低要求" : "Minimum level",
      value: request.requirements?.minEvidenceLevel,
    },
    {
      label: lang === "zh" ? "完整度" : "Completeness",
      value: request.requirements?.completeness,
    },
  ];
  return values.filter((field) => Boolean(field.value));
}

function StructuredChallengeMessage({
  message,
  payload,
  lang,
  expandedMessageIds,
  onToggleExpanded,
}: {
  message: ChatRoomMessage;
  payload: ChallengeMeetingMessagePayload;
  lang: "zh" | "en";
  expandedMessageIds: string[];
  onToggleExpanded: (messageId: string) => void;
}) {
  const instanceId = useId().replace(/:/g, "");
  const titleId = `challenge-message-title-${instanceId}`;
  const protocolId = `challenge-message-protocol-${instanceId}`;
  const protocolExpansionId = `${message.messageId}:protocol`;
  const protocolExpanded = expandedMessageIds.includes(protocolExpansionId);
  const { display, protocol, audit } = payload;

  return (
    <article className={styles.structuredMessage} aria-labelledby={titleId}>
      <h3 id={titleId} className={styles.structuredConclusion}>{display.conclusion}</h3>

      {display.sections.length ? (
        <div className={styles.structuredSections}>
          {display.sections.map((section, index) => (
            <section className={styles.structuredSection} key={`${section.title}-${index}`}>
              <h4 className={styles.structuredSectionTitle}>{section.title}</h4>
              <ul className={styles.structuredList}>
                {section.bullets.map((bullet, bulletIndex) => (
                  <li key={`${bullet}-${bulletIndex}`}>{bullet}</li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      ) : null}

      <div className={styles.protocolGrid}>
        {protocol.agreements.length ? (
          <VSurface as="section" tone="row" elevation="flat" padding="compact" className={styles.protocolCard}>
            <h4 className={styles.protocolCardTitle}>{lang === "zh" ? "已形成共识" : "Agreements"}</h4>
            <ul className={styles.protocolCardList}>
              {protocol.agreements.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
            </ul>
          </VSurface>
        ) : null}

        {protocol.disagreements.length ? (
          <VSurface as="section" tone="row" elevation="flat" padding="compact" className={styles.protocolCard}>
            <h4 className={styles.protocolCardTitle}>{lang === "zh" ? "仍有分歧" : "Disagreements"}</h4>
            <div className={styles.disagreementList}>
              {protocol.disagreements.map((item, index) => (
                <div className={styles.disagreementItem} key={`${item.issue}-${index}`}>
                  <strong className={styles.disagreementIssue}>{item.issue}</strong>
                  {item.positions.map((position, positionIndex) => (
                    <span key={`${position}-${positionIndex}`}>{position}</span>
                  ))}
                  {item.unresolvedReason ? (
                    <span>{lang === "zh" ? "未收敛原因：" : "Unresolved: "}{item.unresolvedReason}</span>
                  ) : null}
                </div>
              ))}
            </div>
          </VSurface>
        ) : null}

        {protocol.risks.length ? (
          <VSurface as="section" tone="row" elevation="flat" padding="compact" className={styles.protocolCard}>
            <h4 className={styles.protocolCardTitle}>{lang === "zh" ? "风险边界" : "Risks"}</h4>
            <ul className={styles.protocolCardList}>
              {protocol.risks.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
            </ul>
          </VSurface>
        ) : null}

        {protocol.actionItems.length ? (
          <VSurface as="section" tone="row" elevation="flat" padding="compact" className={styles.protocolCard}>
            <h4 className={styles.protocolCardTitle}>{lang === "zh" ? "下一步动作" : "Next actions"}</h4>
            <ul className={styles.protocolCardList}>
              {protocol.actionItems.map((item, index) => (
                <li key={`${item.ownerRoleId}-${item.action}-${index}`}>
                  <strong>{item.ownerRoleId}</strong>{"："}{item.action}
                  {item.dueGate ? ` · ${item.dueGate}` : ""}
                </li>
              ))}
            </ul>
          </VSurface>
        ) : null}
      </div>

      {protocol.evidenceRequests.length ? (
        <VSurface as="section" tone="inset" elevation="flat" padding="normal" className={styles.protocolCard}>
          <h4 className={styles.protocolCardTitle}>{lang === "zh" ? "需要补证据" : "Evidence needed"}</h4>
          <div className={styles.evidenceList}>
            {protocol.evidenceRequests.map((request, index) => (
              <article className={styles.evidenceItem} key={`${request.rationale}-${index}`}>
                <p className={styles.evidenceRationale}>{request.rationale}</p>
                <dl className={styles.evidenceFields}>
                  {evidenceFields(request, lang).map((field) => (
                    <div className={styles.evidenceField} key={field.label}>
                      <dt className={styles.evidenceLabel}>{field.label}</dt>
                      <dd className={styles.evidenceValue}>{field.value}</dd>
                    </div>
                  ))}
                </dl>
              </article>
            ))}
          </div>
        </VSurface>
      ) : null}

      {audit.rawModelOutput ? (
        <div className={styles.protocolDisclosure}>
          <VButton
            type="button"
            variant="ghost"
            className={styles.groupBubbleToggle}
            aria-expanded={protocolExpanded}
            aria-controls={protocolId}
            onClick={() => onToggleExpanded(protocolExpansionId)}
          >
            {protocolExpanded
              ? (lang === "zh" ? "收起原始协议" : "Hide raw protocol")
              : (lang === "zh" ? "查看原始协议" : "Show raw protocol")}
          </VButton>
          <div id={protocolId} hidden={!protocolExpanded}>
            {protocolExpanded ? (
              <pre className={styles.rawProtocol}>{audit.rawModelOutput}</pre>
            ) : null}
          </div>
        </div>
      ) : null}
    </article>
  );
}

export function ChatGroupMessageBody({
  message,
  identityName,
  lang,
  expandedMessageIds,
  mentionTargets,
  onOpenMentionTarget,
  onToggleExpanded,
}: ChatGroupMessageBodyProps) {
  const structuredPayload = structuredChallengePayload(message);
  if (structuredPayload) {
    return (
      <StructuredChallengeMessage
        message={message}
        payload={structuredPayload}
        lang={lang}
        expandedMessageIds={expandedMessageIds}
        onToggleExpanded={onToggleExpanded}
      />
    );
  }

  const content = stripGroupSpeakerPrefix(message, identityName);
  const expanded = expandedMessageIds.includes(message.messageId);
  const collapsible = shouldCollapseGroupMessage(content);
  const collapsed = collapsible && !expanded;
  const collapseLabel = lang === "zh" ? "展开全文" : "Show full";

  const messageStatus = String(message.status ?? "").toLowerCase();
  const failureReason = messageStatus !== "completed" && !content.trim()
    ? String(message.summary || message.errorType || "").trim()
    : "";
  return (
    <>
      <p className={collapsed ? `${styles.groupBubbleBody} ${styles.groupBubbleBodyCollapsed}` : styles.groupBubbleBody}>
        <ChatMentionedText
          content={content}
          fallback={failureReason
            ? (lang === "zh" ? `发言未完成：${failureReason}` : `Message incomplete: ${failureReason}`)
            : (lang === "zh" ? "暂无内容" : "No content yet")}
          lang={lang}
          mentionTargets={mentionTargets}
          onOpenMentionTarget={onOpenMentionTarget}
        />
      </p>
      {collapsible ? (
        <VButton
          type="button"
          className={styles.groupBubbleToggle}
          onClick={() => onToggleExpanded(message.messageId)}
        >
          {expanded ? (lang === "zh" ? "收起" : "Collapse") : collapseLabel}
        </VButton>
      ) : null}
    </>
  );
}
