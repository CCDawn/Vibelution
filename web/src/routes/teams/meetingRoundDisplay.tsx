import type { ReactNode } from "react";
import type {
  MeetingDigestDraft,
  MeetingDigestValidationError,
  MeetingEvidenceRequestDraft,
  MeetingProposedCandidate,
  MeetingRoundRecord,
  MeetingSourceMessage,
} from "../../api/types/hypothesisFirst";
import { VStatusChip, type VStatusTone } from "../../components/vui";
import { evidenceRequestKeywords } from "./research-workflow/hypothesisFirstNextAction";
import {
  displayMeetingMessageText,
  meetingDiscussionProgress,
  meetingMessageNeedsFullText,
  meetingSpeakerLabel,
} from "./meetingRoundDisplayModel";
import css from "./meetingRoundDisplay.styles";

export const MEETING_STATUS_LABELS: Record<string, string> = {
  open: "讨论中",
  summarizing: "正在整理",
  awaiting_approval: "待人工确认",
  closed: "已结束",
};

const MEETING_STATUS_LABELS_EN: Record<string, string> = {
  open: "In discussion",
  summarizing: "Summarizing",
  awaiting_approval: "Waiting for review",
  closed: "Closed",
};

type Language = "zh" | "en";

export function meetingStatusTone(status: string): VStatusTone {
  if (status === "closed") return "success";
  if (status === "awaiting_approval") return "warning";
  if (status === "open" || status === "summarizing") return "accent";
  return "neutral";
}

function markerText(value: Record<string, unknown>): string {
  const issue = value.issue;
  const action = value.action;
  const text = value.text;
  if (typeof issue === "string" && issue.trim()) return issue;
  if (typeof action === "string" && action.trim()) return action;
  if (typeof text === "string" && text.trim()) return text;
  return JSON.stringify(value);
}

function agreementText(value: string | Record<string, unknown>, lang: Language): string {
  if (typeof value === "string") return value;
  const text = markerText(value);
  if (value.derivedFrom === "unstructured") {
    return lang === "zh" ? `发言摘要：${text}` : `Statement summary: ${text}`;
  }
  return text;
}

function validationErrorMessage(error: MeetingDigestValidationError, lang: Language): string {
  const message = error.message?.trim();
  if (message) return message;
  return lang === "zh" ? "整理结果校验失败，请重新整理" : "Digest validation failed; try organizing it again.";
}

export function DigestDraftView({
  draft,
  compact = false,
  lang = "zh",
}: {
  draft: MeetingDigestDraft;
  compact?: boolean;
  lang?: Language;
}) {
  const isZh = lang === "zh";
  const agreements = draft.agreements ?? [];
  const disagreements = draft.disagreements ?? [];
  const actionItems = draft.actionItems ?? [];
  const knowledgeCandidates = draft.knowledgeCandidates ?? [];
  const proposed = draft.proposedCandidates ?? [];
  const evidenceRequests = draft.evidenceRequests ?? [];
  const summary = draft.summary || draft.agendaSummary || (isZh ? "（空）" : "(Empty)");
  return (
    <div className={css.digestGrid} data-testid="meeting-digest-draft">
      <article className={css.digestCard}>
        <span>{isZh ? "讨论结论" : "Discussion conclusion"}</span>
        <p>{summary}</p>
      </article>
      {proposed.length ? (
        <article className={css.digestCard} data-testid="meeting-proposed-candidates">
          <span>{isZh ? `候选清单（${proposed.length}）` : `Candidate list (${proposed.length})`}</span>
          <ul className={compact ? css.proposedCandidateList : css.digestList}>
            {proposed.map((item, index) => (
              <li
                key={item.candidateId || `proposed-${index}`}
                className={compact ? css.proposedCandidate : undefined}
              >
                {formatProposedCandidate(item, lang)}
              </li>
            ))}
          </ul>
        </article>
      ) : null}
      {evidenceRequests.length ? (
        <EvidenceRequestList requests={evidenceRequests} lang={lang} />
      ) : null}
      {(draft.risks?.length ?? 0) + (draft.blockers?.length ?? 0) > 0 ? (
        <article className={css.digestCard} data-testid="meeting-digest-risks">
          <span>{isZh ? "风险与阻塞" : "Risks and blockers"}</span>
          <ul className={css.digestList}>
            {(draft.risks ?? []).map((item, index) => (
              <li key={`risk-${index}`}>{isZh ? `风险：${item}` : `Risk: ${item}`}</li>
            ))}
            {(draft.blockers ?? []).map((item, index) => (
              <li key={`blocker-${index}`}>{isZh ? `阻塞：${item}` : `Blocker: ${item}`}</li>
            ))}
          </ul>
        </article>
      ) : null}
      {draft.validationErrors?.length ? (
        <article className={css.digestCard} data-testid="meeting-digest-validation-errors">
          <span>{isZh ? `结果校验（${draft.validationErrors.length}）` : `Validation (${draft.validationErrors.length})`}</span>
          <ul className={css.digestList}>
            {draft.validationErrors.map((error, index) => (
              <li key={`${error.code || "validation"}-${index}`}>{validationErrorMessage(error, lang)}</li>
            ))}
          </ul>
        </article>
      ) : null}
      {compact ? (
        <details>
          <summary>{isZh ? "完整讨论结果" : "Full discussion result"}</summary>
          <DigestDraftChapters
            agreements={agreements}
            disagreements={disagreements}
            actionItems={actionItems}
            knowledgeCandidates={knowledgeCandidates}
            lang={lang}
          />
        </details>
      ) : (
        <DigestDraftChapters
          agreements={agreements}
          disagreements={disagreements}
          actionItems={actionItems}
          knowledgeCandidates={knowledgeCandidates}
          lang={lang}
        />
      )}
    </div>
  );
}

function formatProposedCandidate(item: MeetingProposedCandidate, lang: Language): string {
  return item.statement?.trim() || (lang === "zh" ? "（无陈述）" : "(No statement)");
}

function DigestDraftChapters(props: {
  agreements: Array<string | Record<string, unknown>>;
  disagreements: Array<Record<string, unknown>>;
  actionItems: Array<Record<string, unknown>>;
  knowledgeCandidates: string[];
  lang: Language;
}) {
  return (
    <>
      <article className={css.digestCard}>
        <span>{props.lang === "zh" ? `共识（${props.agreements.length}）` : `Agreements (${props.agreements.length})`}</span>
        <ul className={css.digestList}>
          {props.agreements.map((item, index) => (
          <li key={`agreement-${index}`}>{agreementText(item, props.lang)}</li>
          ))}
        </ul>
      </article>
      <article className={css.digestCard}>
        <span>{props.lang === "zh" ? `分歧（${props.disagreements.length}）` : `Disagreements (${props.disagreements.length})`}</span>
        <ul className={css.digestList}>
          {props.disagreements.map((item, index) => (
            <li key={`disagreement-${index}`}>{markerText(item)}</li>
          ))}
        </ul>
      </article>
      <article className={css.digestCard}>
        <span>{props.lang === "zh" ? `行动项（${props.actionItems.length}）` : `Action items (${props.actionItems.length})`}</span>
        <ul className={css.digestList}>
          {props.actionItems.map((item, index) => (
            <li key={`action-${index}`}>{markerText(item)}</li>
          ))}
        </ul>
      </article>
      <article className={css.digestCard}>
        <span>{props.lang === "zh" ? `知识候选（${props.knowledgeCandidates.length}）` : `Knowledge candidates (${props.knowledgeCandidates.length})`}</span>
        <ul className={css.digestList}>
          {props.knowledgeCandidates.map((item, index) => (
            <li key={`knowledge-${index}`}>{item}</li>
          ))}
        </ul>
      </article>
    </>
  );
}

export function EvidenceRequestList({
  requests,
  lang = "zh",
}: {
  requests: readonly MeetingEvidenceRequestDraft[];
  lang?: Language;
}) {
  const isZh = lang === "zh";
  return (
    <article className={css.digestCard} data-testid="meeting-evidence-requests">
      <span>{isZh ? `搜集范围（${requests.length}）` : `Collection scope (${requests.length})`}</span>
      <ul className={css.digestList}>
        {requests.map((request, index) => {
          const keywords = evidenceRequestKeywords(request);
          const sources = (request.searchEnvelope?.sourceTypes ?? []).filter(Boolean);
          const levels = (request.searchEnvelope?.evidenceLevels ?? []).filter(Boolean);
          const owners = (request.candidateRefs ?? []).filter(Boolean);
          return (
            <li key={`evidence-${index}`}>
              {isZh ? "关键词：" : "Keywords: "}{keywords.length ? keywords.join(isZh ? "、" : ", ") : (isZh ? "无" : "None")}
              {sources.length ? ` · ${isZh ? "来源：" : "Sources: "}${sources.join(isZh ? "、" : ", ")}` : ""}
              {levels.length ? ` · ${isZh ? "证据等级：" : "Evidence levels: "}${levels.join(isZh ? "、" : ", ")}` : ""}
              {owners.length ? ` · ${isZh ? "候选：" : "Candidates: "}${owners.join(isZh ? "、" : ", ")}` : ""}
            </li>
          );
        })}
      </ul>
    </article>
  );
}

export function MeetingMessageList({
  messages,
  compact = false,
  lang = "zh",
}: {
  messages: MeetingSourceMessage[];
  compact?: boolean;
  lang?: Language;
}) {
  if (!messages.length) {
    return <p className={css.hint}>{lang === "zh" ? "房间内尚无讨论消息。" : "No discussion messages in this room yet."}</p>;
  }
  const list = (
    <div className={css.messageList}>
      {messages.map((message, index) => (
        <MeetingMessageCard
          key={message.messageId || `message-${index}`}
          message={message}
          compact={compact}
          lang={lang}
        />
      ))}
    </div>
  );
  if (!compact) {
    return <div data-testid="meeting-source-messages">{list}</div>;
  }
  return (
    <details data-testid="meeting-source-messages">
    <summary>{lang === "zh" ? `${messages.length} 条发言` : `${messages.length} messages`}</summary>
      {list}
    </details>
  );
}

function failedMessageReason(content: string, lang: Language): string {
  const text = content.trim().toLowerCase();
  const isZh = lang === "zh";
  if (text.startsWith("network_error") || text.includes("connection error")) {
    return isZh ? "Agent 发言失败 · 模型连接错误，可重新发起讨论后重试" : "Agent message failed · model connection error; reopen the discussion and retry";
  }
  if (text.startsWith("protocol_error")) {
    return isZh ? "Agent 发言失败 · 回复格式异常，可重新发起讨论后重试" : "Agent message failed · invalid response format; reopen the discussion and retry";
  }
  if (text.startsWith("timeout") || text.includes("timed out")) {
    return isZh ? "Agent 发言失败 · 响应超时，可重新发起讨论后重试" : "Agent message failed · response timed out; reopen the discussion and retry";
  }
  return isZh ? "Agent 发言失败 · 未产生有效发言，可重新发起讨论后重试" : "Agent message failed · no valid message was produced; reopen the discussion and retry";
}

function MeetingMessageCard({
  message,
  compact = false,
  lang = "zh",
}: {
  message: MeetingSourceMessage;
  compact?: boolean;
  lang?: Language;
}) {
  const status = String(message.status ?? "").trim().toLowerCase();
  const failed = status === "failed" || status === "error";
  const content = String(message.content ?? "");
  const preview = failed
    ? failedMessageReason(content, lang)
    : displayMeetingMessageText(content, { collapseWhitespace: compact });
  const fullText = failed ? content : displayMeetingMessageText(content);
  const showFull = compact && !failed && meetingMessageNeedsFullText(content);
  return (
    <article className={css.messageCard} data-failed={failed ? "true" : "false"}>
      <div className={css.messageMeta}>
        <span>{meetingSpeakerLabel(message)}</span>
        {compact ? null : <span>{message.createdAt || "—"}</span>}
      </div>
      {failed ? (
        <>
          <p className={compact ? css.messagePreview : undefined}>{preview}</p>
          {content ? (
            <details>
              <summary>{lang === "zh" ? "技术详情" : "Technical details"}</summary>
              <p className={css.hint}>{content}</p>
            </details>
          ) : null}
        </>
      ) : compact ? (
        <>
          <p className={css.messagePreview}>{preview}</p>
          {showFull ? (
            <details>
              <summary>{lang === "zh" ? "全文" : "Full text"}</summary>
              <p className={css.messageFull}>{fullText}</p>
            </details>
          ) : null}
        </>
      ) : (
        <p className={css.messageFull}>{fullText}</p>
      )}
    </article>
  );
}

export function MeetingRoundDisplay({
  round,
  messages,
  compact = false,
  actions,
  lang = "zh",
}: {
  round: MeetingRoundRecord;
  messages: MeetingSourceMessage[];
  compact?: boolean;
  actions?: ReactNode;
  lang?: Language;
}) {
  const isZh = lang === "zh";
  const status = round.status;
  const digestDraft = round.digestDraft;
  const organizationFailed = status === "summarizing"
    && (Boolean(round.summaryError?.trim()) || Boolean(digestDraft?.validationErrors?.length));
  const agenda = (round.agendaQuestions ?? []).length ? (
    <article className={css.digestCard}>
      <span>{isZh ? "议程序列" : "Agenda"}</span>
      <ul className={css.digestList}>
        {(round.agendaQuestions ?? []).map((question, index) => (
          <li key={`agenda-${index}`}>{question}</li>
        ))}
      </ul>
    </article>
  ) : null;
  const digest = digestDraft ? <DigestDraftView draft={digestDraft} compact={compact} lang={lang} /> : null;
  const decisions = (round.decisionRefs ?? []).length ? (
    <article className={css.digestCard}>
      <span>{isZh ? `决策记录（${(round.decisionRefs ?? []).length}）` : `Decision records (${(round.decisionRefs ?? []).length})`}</span>
      <div className={css.decisionList}>
        {(round.decisionRefs ?? []).map((ref) => (
          <div key={ref}>
            <code>{ref}</code>
          </div>
        ))}
      </div>
    </article>
  ) : null;
  const closedHint = status === "closed" ? (
    <p className={css.hint}>
      {isZh ? "已于" : "Closed on"} {round.closedAt || "—"} {isZh ? "由" : "by"} {round.closedBy || "unknown"} {isZh ? "确认结束。" : "."}
    </p>
  ) : null;
  const messageList = <MeetingMessageList messages={messages} compact={compact} lang={lang} />;
  const speakerOrder = (round as unknown as { speakerOrder?: unknown }).speakerOrder;
  const discussionProgress = meetingDiscussionProgress({
    participants: round.participants,
    speakerOrder: Array.isArray(speakerOrder) ? speakerOrder.map((item) => String(item)) : undefined,
    messages,
  });
  const showDiscussionProgress = status === "open" || status === "summarizing";
  return (
    <div className="grid min-w-0 gap-3" data-testid="meeting-round-display">
      <div className={css.heading}>
        <div>
          <h3>{round.meetingType === "hypothesis_candidate_generation" ? (isZh ? "候选生成讨论" : "Candidate generation discussion") : (isZh ? "评审讨论" : "Review discussion")}</h3>
          <p>
            {compact
              ? (isZh ? `参与者 ${round.participants.length} 人` : `${round.participants.length} participants`)
              : (isZh
                ? `${round.meetingRoundId} · 参与者 ${round.participants.length} 人 · 房间 ${round.linkedChatRoomId || "—"}`
                : `${round.meetingRoundId} · ${round.participants.length} participants · room ${round.linkedChatRoomId || "—"}`)}
          </p>
          {showDiscussionProgress ? (
            <p data-testid="meeting-discussion-progress">{discussionProgress.label}</p>
          ) : null}
        </div>
        <div className={css.headingActions}>
          <VStatusChip tone={organizationFailed ? "danger" : meetingStatusTone(status)} data-testid="meeting-round-status">
            {organizationFailed
              ? (isZh ? "整理失败" : "Summarization failed")
              : ((isZh ? MEETING_STATUS_LABELS : MEETING_STATUS_LABELS_EN)[status] ?? status)}
          </VStatusChip>
        </div>
      </div>
      {compact ? (
        <details>
          <summary>{isZh ? "运行详情" : "Run details"}</summary>
          <p className={css.hint}>
            {isZh ? "讨论轮次" : "Discussion round"} {round.meetingRoundId} · {isZh ? "房间" : "Room"} {round.linkedChatRoomId || "—"}
          </p>
        </details>
      ) : null}
      {agenda}
      {compact ? (
        <>
          {digest}
          {decisions}
          {closedHint}
          {actions ? <div className={css.actionFooter}>{actions}</div> : null}
          {messageList}
        </>
      ) : (
        <>
          {messageList}
          {digest}
          {decisions}
          {closedHint}
          {actions}
        </>
      )}
    </div>
  );
}
