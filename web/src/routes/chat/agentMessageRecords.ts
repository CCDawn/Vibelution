import type { AgentInstance, KernelTaskTimelinePayload, ProjectAgentBusEvent, SessionDetail } from "../../api/types";
import type { AgentMessageActor, AgentMessageReceipt, AgentMessageRecord } from "../../components/agent-messages";
import { avatarImageUrlFrom } from "./chatRoutePresentation";

type ObjectValue = Record<string, unknown>;
export function messageObject(value: unknown): ObjectValue {
  if (typeof value === "string") {
    try { return messageObject(JSON.parse(value)); } catch { return {}; }
  }
  return value && typeof value === "object" && !Array.isArray(value) ? value as ObjectValue : {};
}
const text = (value: unknown) => typeof value === "string" ? value.trim() : "";
const nonempty = (...values: unknown[]) => values.map(text).find(Boolean) || "";
const unique = (values: string[]) => [...new Set(values.filter(Boolean))];

function actor(id: string, name: unknown, agents: Map<string, AgentInstance>): AgentMessageActor {
  const known = agents.get(id) ?? [...agents.values()].find((item) => item.agentCode === id || item.displayName === id);
  return { agentId: known?.agentId || id, name: known?.displayName || text(name) || id || "未知 Agent", avatarImageUrl: known ? avatarImageUrlFrom(known) : undefined };
}
function receipt(value: unknown, agents: Map<string, AgentInstance>): AgentMessageReceipt {
  const row = messageObject(value), wake = messageObject(row.wake ?? row.delivery);
  const state = text(row.status), wakeState = nonempty(wake.wakeStatus, row.wakeStatus);
  const failed = ["failed", "blocked", "rejected"].includes(state);
  const wakeRejected = ["failed", "skipped_invalid_session", "skipped_policy_blocked", "skipped_archived_agent", "skipped_missing_agent", "skipped_no_direct_session"].includes(wakeState)
    || nonempty(wake.historyStatus, row.historyStatus) === "rejected";
  return {
    ...actor(nonempty(row.targetAgentId, wake.targetAgentId), row.targetAgentName, agents),
    sessionId: nonempty(row.targetSessionId, wake.targetSessionId),
    delivery: row.revoked || state === "revoked" ? "revoked" : state === "delivered" ? "delivered" : failed ? "failed" : "unknown",
    // A successful wake is admission, not proof that a worker started.
    handling: wakeRejected ? "wake_failed"
      : ["skipped_busy", "skipped_in_flight", "queued", "deferred"].includes(wakeState) ? "queued" : "unknown",
    error: failed || wakeRejected ? nonempty(row.reason, wake.reason) || undefined : undefined,
  };
}
function purpose(metadata: ObjectValue, notification = false): AgentMessageRecord["type"] {
  const nested = messageObject(metadata.agentToolMetadataJson);
  return replyTarget(metadata) ? "reply"
    : notification || metadata.requiresReply === false || metadata.replyExpected === false || metadata.messageType === "notification" || metadata.intent === "notification"
      || nested.requiresReply === false || nested.replyExpected === false || nested.messageType === "notification" || nested.intent === "notification" ? "notification" : "request";
}
function replyTarget(metadata: ObjectValue) { return nonempty(metadata.replyToMessageId, messageObject(metadata.agentToolMetadataJson).replyToMessageId); }
function title(summary: unknown, body: string) { return text(summary) || body.split("\n").find((line) => line.trim())?.slice(0, 120) || "跨 Agent 消息"; }
function replySourceAlias(metadata: ObjectValue, targetAgentId: string) {
  return replyTarget(metadata) && text(metadata.sourceTurnId)
    ? `reply-source:${text(metadata.sourceAgentId)}:${text(metadata.sourceSessionId)}:${text(metadata.sourceTurnId)}:${targetAgentId}` : "";
}

export function kernelMessageRecord(timeline: KernelTaskTimelinePayload, agents: Map<string, AgentInstance>): AgentMessageRecord | null {
  const event = timeline.event;
  if (!event || event.semanticPayload?.semanticType !== "agent.message") return null;
  const payload = messageObject(event.semanticPayload.payload), metadata = { ...messageObject(payload.metadata), ...messageObject(event.metadata) };
  const body = text(payload.content), sender = messageObject(event.sender);
  const deliveries = timeline.deliveries ?? timeline.outcome?.deliveries ?? [];
  const recipients = deliveries.map((row) => receipt(row, agents));
  for (const id of event.recipients ?? []) if (!recipients.some((row) => row.agentId === id)) recipients.push(receipt({ targetAgentId: id }, agents));
  return {
    id: event.eventId, aliases: unique([event.eventId, ...deliveries.map((row) => row.inboxMessageId), ...recipients.map((row) => replySourceAlias(metadata, row.agentId))]),
    sourceSessionId: text(metadata.sourceSessionId) || undefined, sourceEventId: event.eventId, sourceTaskId: timeline.taskId,
    sender: actor(nonempty(event.senderAgentId, sender.agentId, sender.id), sender.displayName ?? sender.name, agents),
    type: purpose(metadata, sender.type === "user"), createdAt: event.createdAt,
    title: title(payload.summary, body), body, recipients, replyToId: replyTarget(metadata) || undefined,
  };
}

export function busMessageRecord(event: ProjectAgentBusEvent, agents: Map<string, AgentInstance>): AgentMessageRecord | null {
  if (event.messageType === "project_observation") return null;
  const metadata = messageObject(event.metadata), body = event.content || event.summary || "";
  const recipients = (event.deliveries ?? []).map((row) => receipt(row, agents));
  for (const [index, id] of (event.targetAgentIds ?? []).entries()) {
    if (!recipients.some((row) => row.agentId === id)) recipients.push(receipt({ targetAgentId: id, targetAgentName: event.targetAgentNames?.[index] }, agents));
  }
  if (event.status === "revoked") recipients.forEach((row) => { row.delivery = "revoked"; row.error = event.revokeReason || undefined; });
  return {
    id: event.eventId, aliases: unique([event.eventId, event.kernel?.eventId || "", ...(event.deliveries ?? []).map((row) => row.inboxMessageId)]),
    sourceSessionId: text(metadata.sourceSessionId) || undefined, sourceEventId: event.eventId, sourceTaskId: event.kernel?.taskId,
    sender: actor(nonempty(metadata.sourceAgentId, metadata.senderAgentId, event.createdBy), event.createdBy === "user" ? "你" : event.createdBy, agents),
    type: purpose(metadata, event.messageType !== "agent_private"), createdAt: event.createdAt,
    title: title(event.summary, body), body: event.status === "revoked" ? "这条消息已撤回。" : body, recipients,
    replyToId: replyTarget(metadata) || undefined,
  };
}

export function sessionMessageRecords(session: SessionDetail, agents: Map<string, AgentInstance>, sessions: Map<string, SessionDetail>): AgentMessageRecord[] {
  const records: AgentMessageRecord[] = [];
  for (const message of session.messages ?? []) {
    const metadata = messageObject(message.metadata);
    const automaticReply = metadata.sourceSurface === "agent_inbox_reply" && Boolean(metadata.replyToMessageId);
    if (message.role === "user" && ((["agent_inbox_message", "agent_inbox_reply"].includes(text(metadata.kind)) && text(metadata.messageId)) || automaticReply)) {
      const id = text(metadata.messageId) || `reply:${session.id}:${message.nodeId || text(metadata.sourceTurnId) || message.id}`, nested = messageObject(metadata.agentToolMetadataJson);
      const replyToId = nonempty(metadata.replyToMessageId, nested.replyToMessageId);
      records.push({
        id, aliases: unique([id, replySourceAlias(metadata, text(session.agentId))]), sourceSessionId: text(metadata.sourceSessionId) || undefined,
        sender: actor(text(metadata.sourceAgentId), metadata.sourceAgentName ?? metadata.senderName, agents),
        type: replyToId ? "reply" : purpose(metadata), createdAt: message.timestamp,
        title: title(metadata.messageSummary, message.content), body: message.content,
        recipients: [{ ...actor(text(session.agentId), metadata.targetAgentName, agents), sessionId: session.id, delivery: "delivered", handling: "received" }],
        replyToId: replyToId || undefined,
      });
    }
    if (message.role !== "assistant") continue;
    for (const item of message.turnItems ?? []) {
      if (item.type !== "tool_call" || !/(^|[._])agent_message_tool$/.test(item.toolName)) continue;
      const input = messageObject(item.input), output = messageObject(item.output), delivery = messageObject(output.delivery), kernel = messageObject(output.kernel);
      const extra = messageObject(input.metadata_json);
      const targetSessionId = nonempty(output.targetSessionId, input.target_session), targetSession = sessions.get(targetSessionId);
      const targetId = nonempty(output.targetAgentId, targetSession?.agentId, input.target_agent);
      const body = text(input.content), pending = ["pending", "running", "queued"].includes(item.status);
      const sent = output.ok === true && ["recorded", "appended", "deferred"].includes(nonempty(output.inboxStatus, output.historyStatus));
      const failed = output.ok === false || ["failed", "error"].includes(item.status);
      const target = receipt({ targetAgentId: targetId, targetSessionId, status: sent ? "delivered" : failed ? "failed" : "", wakeStatus: output.wakeStatus, reason: nonempty(output.reason, [text(output.error), text(output.message)].filter(Boolean).join(": "), failed ? item.summary : ""), wake: delivery }, agents);
      if (pending) target.delivery = "sending";
      const id = `send:${session.id}:${message.turnId}:${item.itemId}`;
      records.push({
        id, aliases: unique([id, text(output.messageId), text(kernel.kernelEventId), text(kernel.eventId)]),
        sourceSessionId: session.id, sourceEventId: nonempty(kernel.kernelEventId, kernel.eventId) || undefined,
        sourceTaskId: nonempty(kernel.kernelTaskId, kernel.taskId) || undefined,
        sender: actor(text(session.agentId), "", agents), type: purpose(extra), createdAt: item.createdAt || message.timestamp,
        title: title(input.summary, body), body, recipients: [target], replyToId: text(extra.replyToMessageId) || undefined,
      });
    }
  }
  return records;
}

/** Exact source identifiers only; identical bodies/titles are independent sends. */
export function mergeAgentMessageRecords(inputs: AgentMessageRecord[]): AgentMessageRecord[] {
  const records: AgentMessageRecord[] = [];
  const aliases = new Map<string, AgentMessageRecord>();
  for (const incoming of inputs) {
    const ids = unique([incoming.id, ...(incoming.aliases ?? [])]);
    const existing = ids.map((id) => aliases.get(id)).find(Boolean);
    if (existing) {
      const mergedRecipients = [...existing.recipients];
      for (const row of incoming.recipients) {
        const index = mergedRecipients.findIndex((prior) => prior.agentId === row.agentId && (!prior.sessionId || !row.sessionId || prior.sessionId === row.sessionId));
        if (index < 0) mergedRecipients.push({ ...row });
        else {
          const prior = mergedRecipients[index];
          const revoked = prior.delivery === "revoked" || row.delivery === "revoked";
          const progress = ["received", "processing", "replied"] as const;
          const confirmed = [prior, row].filter((item) => progress.some((state) => state === item.handling))
            .sort((a, b) => progress.findIndex((state) => state === b.handling) - progress.findIndex((state) => state === a.handling))[0];
          mergedRecipients[index] = { ...prior, ...row,
            delivery: revoked ? "revoked" : prior.delivery === "delivered" || row.delivery === "delivered" ? "delivered" : row.delivery === "unknown" ? prior.delivery : row.delivery,
            handling: revoked ? "unknown" : confirmed?.handling ?? (row.handling === "unknown" ? prior.handling : row.handling),
            error: confirmed && !revoked ? confirmed.error : row.error || prior.error };
        }
      }
      const aliasList = unique([existing.id, ...(existing.aliases ?? []), ...ids]);
      const revoked = mergedRecipients.some((row) => row.delivery === "revoked");
      const canonicalEnvelope = incoming.id === incoming.sourceEventId;
      // Receiver journal entries confirm receipt, but cannot rewrite a sent
      // envelope (including a later recall) with an old prompt/body or purpose.
      Object.assign(existing, { aliases: aliasList, recipients: mergedRecipients,
        sourceSessionId: existing.sourceSessionId || incoming.sourceSessionId,
        sourceEventId: existing.sourceEventId || incoming.sourceEventId,
        sourceTaskId: existing.sourceTaskId || incoming.sourceTaskId,
        sender: existing.sender.agentId ? existing.sender : incoming.sender,
        createdAt: existing.createdAt || incoming.createdAt,
        title: existing.title || incoming.title,
        type: incoming.replyToId ? "reply" : canonicalEnvelope ? incoming.type : existing.type,
        body: revoked ? "这条消息已撤回。" : canonicalEnvelope ? incoming.body || existing.body : existing.body || incoming.body,
        replyToId: incoming.replyToId || existing.replyToId });
      aliasList.forEach((id) => aliases.set(id, existing));
    } else {
      const record = { ...incoming, recipients: incoming.recipients.map((row) => ({ ...row })), aliases: ids };
      records.push(record); ids.forEach((id) => aliases.set(id, record));
    }
  }
  for (const reply of records) {
    if (!reply.replyToId) continue;
    const origin = aliases.get(reply.replyToId);
    if (!origin) continue;
    reply.replyToId = origin.id;
    // A linked reply attempt is not a reply receipt until it reaches the sender.
    if (!origin.sender.agentId || !reply.recipients.some((row) => row.agentId === origin.sender.agentId && row.delivery === "delivered")) continue;
    for (const recipient of origin.recipients) {
      if (recipient.delivery !== "revoked" && recipient.agentId && recipient.agentId === reply.sender.agentId) recipient.handling = "replied";
    }
  }
  return records.sort((a, b) => (Date.parse(b.createdAt) || 0) - (Date.parse(a.createdAt) || 0));
}

export function currentConversationMessages(records: AgentMessageRecord[], sessionId: string) {
  if (!sessionId) return [];
  const outbound = records.filter((record) => record.sourceSessionId === sessionId);
  const ids = new Set(outbound.map((record) => record.id));
  return records.filter((record) => ids.has(record.id) || (record.replyToId && ids.has(record.replyToId)));
}
