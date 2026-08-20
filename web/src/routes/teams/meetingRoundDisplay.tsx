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

export function meetingStatusTone(status: string): VStatusTone {
  if (status === "closed") return "success";
  if (status === "awaiting_approval") return "warning";
  if (status === "open" || status === "summarizing") return "accent";
  return "neutral";
}

function markerText(value: Record<string, unknown>): string {
  const issue = value.issue;
  const action = value.action;
  if (typeof issue === "string" && issue.trim()) return issue;
  if (typeof action === "string" && action.trim()) return action;
  return JSON.stringify(value);
}

function validationErrorMessage(error: MeetingDigestValidationError): string {
  const message = error.message?.trim();
  if (message) return message;
  return "整理结果校验失败，请重新整理";
}

export function DigestDraftView({
  draft,
  compact = false,
}: {
  draft: MeetingDigestDraft;
  compact?: boolean;
}) {
  const agreements = draft.agreements ?? [];
  const disagreements = draft.disagreements ?? [];
  const actionItems = draft.actionItems ?? [];
  const knowledgeCandidates = draft.knowledgeCandidates ?? [];
  const proposed = draft.proposedCandidates ?? [];
  const evidenceRequests = draft.evidenceRequests ?? [];
  const summary = draft.summary || draft.agendaSummary || "（空）";
  return (
    <div className={css.digestGrid} data-testid="meeting-digest-draft">
      <article className={css.digestCard}>
        <span>讨论结论</span>
        <p>{summary}</p>
      </article>
      {proposed.length ? (
        <article className={css.digestCard} data-testid="meeting-proposed-candidates">
          <span>候选清单（{proposed.length}）</span>
          <ul className={css.digestList}>
            {proposed.map((item, index) => (
              <li key={item.candidateId || `proposed-${index}`}>
                {formatProposedCandidate(item)}
              </li>
            ))}
          </ul>
        </article>
      ) : null}
      {evidenceRequests.length ? (
        <EvidenceRequestList requests={evidenceRequests} />
      ) : null}
      {draft.validationErrors?.length ? (
        <article className={css.digestCard} data-testid="meeting-digest-validation-errors">
          <span>结果校验（{draft.validationErrors.length}）</span>
          <ul className={css.digestList}>
            {draft.validationErrors.map((error, index) => (
              <li key={`${error.code || "validation"}-${index}`}>{validationErrorMessage(error)}</li>
            ))}
          </ul>
        </article>
      ) : null}
      {compact ? (
        <details>
          <summary>完整讨论结果</summary>
          <DigestDraftChapters
            agreements={agreements}
            disagreements={disagreements}
            actionItems={actionItems}
            knowledgeCandidates={knowledgeCandidates}
          />
        </details>
      ) : (
        <DigestDraftChapters
          agreements={agreements}
          disagreements={disagreements}
          actionItems={actionItems}
          knowledgeCandidates={knowledgeCandidates}
        />
      )}
    </div>
  );
}

function formatProposedCandidate(item: MeetingProposedCandidate): string {
  return item.statement?.trim() || "（无陈述）";
}

function DigestDraftChapters(props: {
  agreements: string[];
  disagreements: Array<Record<string, unknown>>;
  actionItems: Array<Record<string, unknown>>;
  knowledgeCandidates: string[];
}) {
  return (
    <>
      <article className={css.digestCard}>
        <span>共识（{props.agreements.length}）</span>
        <ul className={css.digestList}>
          {props.agreements.map((item, index) => (
            <li key={`agreement-${index}`}>{item}</li>
          ))}
        </ul>
      </article>
      <article className={css.digestCard}>
        <span>分歧（{props.disagreements.length}）</span>
        <ul className={css.digestList}>
          {props.disagreements.map((item, index) => (
            <li key={`disagreement-${index}`}>{markerText(item)}</li>
          ))}
        </ul>
      </article>
      <article className={css.digestCard}>
        <span>行动项（{props.actionItems.length}）</span>
        <ul className={css.digestList}>
          {props.actionItems.map((item, index) => (
            <li key={`action-${index}`}>{markerText(item)}</li>
          ))}
        </ul>
      </article>
      <article className={css.digestCard}>
        <span>知识候选（{props.knowledgeCandidates.length}）</span>
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
}: {
  requests: readonly MeetingEvidenceRequestDraft[];
}) {
  return (
    <article className={css.digestCard} data-testid="meeting-evidence-requests">
      <span>搜集范围（{requests.length}）</span>
      <ul className={css.digestList}>
        {requests.map((request, index) => {
          const keywords = evidenceRequestKeywords(request);
          const sources = (request.searchEnvelope?.sourceTypes ?? []).filter(Boolean);
          const levels = (request.searchEnvelope?.evidenceLevels ?? []).filter(Boolean);
          const owners = (request.candidateRefs ?? []).filter(Boolean);
          return (
            <li key={`evidence-${index}`}>
              关键词：{keywords.length ? keywords.join("、") : "无"}
              {sources.length ? ` · 来源：${sources.join("、")}` : ""}
              {levels.length ? ` · 证据等级：${levels.join("、")}` : ""}
              {owners.length ? ` · 候选：${owners.join("、")}` : ""}
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
}: {
  messages: MeetingSourceMessage[];
  compact?: boolean;
}) {
  if (!messages.length) {
    return <p className={css.hint}>房间内尚无讨论消息。</p>;
  }
  const list = (
    <div className={css.messageList}>
      {messages.map((message, index) => (
        <MeetingMessageCard
          key={message.messageId || `message-${index}`}
          message={message}
          compact={compact}
        />
      ))}
    </div>
  );
  if (!compact) {
    return <div data-testid="meeting-source-messages">{list}</div>;
  }
  return (
    <details data-testid="meeting-source-messages">
      <summary>{messages.length} 条发言</summary>
      {list}
    </details>
  );
}

function failedMessageReason(content: string): string {
  const text = content.trim().toLowerCase();
  if (text.startsWith("network_error") || text.includes("connection error")) {
    return "Agent 发言失败 · 模型连接错误，可重新发起讨论后重试";
  }
  if (text.startsWith("protocol_error")) {
    return "Agent 发言失败 · 回复格式异常，可重新发起讨论后重试";
  }
  if (text.startsWith("timeout") || text.includes("timed out")) {
    return "Agent 发言失败 · 响应超时，可重新发起讨论后重试";
  }
  return "Agent 发言失败 · 未产生有效发言，可重新发起讨论后重试";
}

function MeetingMessageCard({
  message,
  compact = false,
}: {
  message: MeetingSourceMessage;
  compact?: boolean;
}) {
  const status = String(message.status ?? "").trim().toLowerCase();
  const failed = status === "failed" || status === "error";
  const content = String(message.content ?? "");
  const preview = failed
    ? failedMessageReason(content)
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
              <summary>技术详情</summary>
              <p className={css.hint}>{content}</p>
            </details>
          ) : null}
        </>
      ) : compact ? (
        <>
          <p className={css.messagePreview}>{preview}</p>
          {showFull ? (
            <details>
              <summary>全文</summary>
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
}: {
  round: MeetingRoundRecord;
  messages: MeetingSourceMessage[];
  compact?: boolean;
  actions?: ReactNode;
}) {
  const status = round.status;
  const digestDraft = round.digestDraft;
  const organizationFailed = status === "summarizing"
    && (Boolean(round.summaryError?.trim()) || Boolean(digestDraft?.validationErrors?.length));
  const agenda = (round.agendaQuestions ?? []).length ? (
    <article className={css.digestCard}>
      <span>议程序列</span>
      <ul className={css.digestList}>
        {(round.agendaQuestions ?? []).map((question, index) => (
          <li key={`agenda-${index}`}>{question}</li>
        ))}
      </ul>
    </article>
  ) : null;
  const digest = digestDraft ? <DigestDraftView draft={digestDraft} compact={compact} /> : null;
  const decisions = (round.decisionRefs ?? []).length ? (
    <article className={css.digestCard}>
      <span>决策记录（{(round.decisionRefs ?? []).length}）</span>
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
      已于 {round.closedAt || "—"} 由 {round.closedBy || "unknown"} 确认结束。
    </p>
  ) : null;
  const messageList = <MeetingMessageList messages={messages} compact={compact} />;
  return (
    <div data-testid="meeting-round-display">
      <div className={css.heading}>
        <div>
          <h3>{round.meetingType === "hypothesis_candidate_generation" ? "候选生成讨论" : "评审讨论"}</h3>
          <p>
            {compact
              ? `参与者 ${round.participants.length} 人`
              : `${round.meetingRoundId} · 参与者 ${round.participants.length} 人 · 房间 ${round.linkedChatRoomId || "—"}`}
          </p>
        </div>
        <div className={css.headingActions}>
          <VStatusChip tone={organizationFailed ? "danger" : meetingStatusTone(status)} data-testid="meeting-round-status">
            {organizationFailed ? "整理失败" : (MEETING_STATUS_LABELS[status] ?? status)}
          </VStatusChip>
        </div>
      </div>
      {compact ? (
        <details>
          <summary>运行详情</summary>
          <p className={css.hint}>
            讨论轮次 {round.meetingRoundId} · 房间 {round.linkedChatRoomId || "—"}
          </p>
        </details>
      ) : null}
      {agenda}
      {compact ? (
        <>
          {digest}
          {decisions}
          {closedHint}
          {actions}
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
