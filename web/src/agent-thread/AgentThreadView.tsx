import React from "react";

import type {
  AgentAttachmentPart,
  AgentMessage,
  AgentMessagePart,
  AgentReferencePart,
  AgentRuntimeEventPart,
  AgentThread,
  AgentThoughtPart,
  AgentToolCallPart,
} from ".";
import styles from "./AgentThreadView.module.css";

export type AgentThreadViewProps = {
  thread: AgentThread;
  className?: string;
};

export function AgentThreadView({ thread, className }: AgentThreadViewProps) {
  return (
    <section
      className={classNames(styles.thread, className)}
      data-agent-thread-id={thread.id}
      data-agent-thread-source-kind={thread.source.kind}
      data-agent-thread-source-id={thread.source.id}
      data-agent-thread-status={thread.status}
    >
      {thread.messages.map((message) => (
        <AgentMessageView key={message.id} message={message} />
      ))}
    </section>
  );
}

export type AgentMessageViewProps = {
  message: AgentMessage;
};

export function AgentMessageView({ message }: AgentMessageViewProps) {
  return (
    <article
      className={styles.message}
      data-agent-message-id={message.id}
      data-agent-message-role={message.role}
      data-agent-message-streaming={message.streaming ? "true" : "false"}
      data-agent-message-turn-id={message.turnId}
    >
      <header className={styles.messageHeader}>
        <span className={styles.role}>{message.role}</span>
        <time className={styles.time} dateTime={message.createdAt}>
          {formatTimestamp(message.createdAt)}
        </time>
      </header>
      <div className={styles.parts}>
        {message.parts.map((part) => (
          <AgentMessagePartView key={part.id} part={part} />
        ))}
      </div>
    </article>
  );
}

export type AgentMessagePartViewProps = {
  part: AgentMessagePart;
};

export function AgentMessagePartView({ part }: AgentMessagePartViewProps) {
  if (part.type === "text") {
    return (
      <p className={classNames(styles.part, styles.text)} data-agent-part-id={part.id} data-agent-part-type={part.type}>
        {part.text}
      </p>
    );
  }
  if (part.type === "thought") {
    return <AgentThoughtPartView part={part} />;
  }
  if (part.type === "tool-call") {
    return <AgentToolCallPartView part={part} />;
  }
  if (part.type === "runtime-event") {
    return <AgentRuntimeEventPartView part={part} />;
  }
  if (part.type === "mental") {
    return (
      <section className={classNames(styles.part, styles.processPart)} data-agent-part-id={part.id} data-agent-part-type={part.type}>
        <PartHeader name="mental" status={part.status} />
        {part.summary ? <p className={styles.summary}>{part.summary}</p> : null}
      </section>
    );
  }
  if (part.type === "attachment") {
    return <AgentAttachmentPartView part={part} />;
  }
  return <AgentReferencePartView part={part} />;
}

export function AgentThoughtPartView({ part }: { part: AgentThoughtPart }) {
  return (
    <section className={classNames(styles.part, styles.processPart)} data-agent-part-id={part.id} data-agent-part-type={part.type}>
      <PartHeader name="thought" status={part.status} />
      <p className={styles.summary}>{part.text}</p>
    </section>
  );
}

export function AgentRuntimeEventPartView({ part }: { part: AgentRuntimeEventPart }) {
  return (
    <section className={classNames(styles.part, styles.processPart)} data-agent-part-id={part.id} data-agent-part-type={part.type}>
      <PartHeader name={part.name || part.kind} status={part.status} />
      {part.summary ? <p className={styles.summary}>{part.summary}</p> : null}
      {part.resultPreview ? <pre className={styles.preview}>{part.resultPreview}</pre> : null}
    </section>
  );
}

export function AgentToolCallPartView({ part }: { part: AgentToolCallPart }) {
  return (
    <section className={classNames(styles.part, styles.processPart)} data-agent-part-id={part.id} data-agent-part-type={part.type}>
      <PartHeader name={part.name} status={part.status} />
      {part.summary ? <p className={styles.summary}>{part.summary}</p> : null}
      {part.resultPreview ? <pre className={styles.preview}>{part.resultPreview}</pre> : null}
      {part.error ? <p className={styles.summary}>{part.error}</p> : null}
    </section>
  );
}

function AgentAttachmentPartView({ part }: { part: AgentAttachmentPart }) {
  const attachment = part.attachment;
  return (
    <span className={classNames(styles.part, styles.contextPart)} data-agent-part-id={part.id} data-agent-part-type={part.type}>
      <span className={styles.contextLabel}>{attachment.filename || attachment.artifactId}</span>
      {attachment.contentType ? <span>{attachment.contentType}</span> : null}
    </span>
  );
}

function AgentReferencePartView({ part }: { part: AgentReferencePart }) {
  const reference = part.reference;
  return (
    <span className={classNames(styles.part, styles.contextPart)} data-agent-part-id={part.id} data-agent-part-type={part.type}>
      <span className={styles.contextLabel}>{reference.title || reference.sessionId}</span>
      {reference.agentDisplayName ? <span>{reference.agentDisplayName}</span> : null}
    </span>
  );
}

function PartHeader({ name, status }: { name: string; status: string }) {
  return (
    <div className={styles.partHeader}>
      <span className={styles.partName}>{name}</span>
      <span className={styles.partStatus}>{status}</span>
    </div>
  );
}

function formatTimestamp(value: string) {
  if (!value) {
    return "";
  }
  return value.replace("T", " ").replace(/\.\d+Z$/, "Z");
}

function classNames(...values: Array<string | undefined>) {
  return values.filter(Boolean).join(" ");
}
