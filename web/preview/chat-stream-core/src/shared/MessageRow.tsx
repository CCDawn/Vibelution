import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { PreviewMessage } from "../mock/syntheticConversation";

/**
 * Shared row shell for both A/B columns. Completed-message rendering mirrors
 * the production strategy (content-memoized react-markdown + remark-gfm,
 * skipHtml) replicated here so both columns differ only in list management.
 */
const MessageMarkdown = React.memo(
  function MessageMarkdown({ content }: { content: string }) {
    return (
      <div className="md-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
          {content}
        </ReactMarkdown>
      </div>
    );
  },
  (previous, next) => previous.content === next.content,
);

export const MessageRow = React.memo(
  function MessageRow({ message }: { message: PreviewMessage }) {
    return (
      <div
        className={`msg-row role-${message.role}`}
        data-conversation-row-key={message.id}
      >
        <div className="msg-bubble">
          <div className="msg-meta">
            <span className="role">{message.roleLabel}</span>
            <span>{message.id}</span>
          </div>
          <MessageMarkdown content={message.content} />
        </div>
      </div>
    );
  },
  (previous, next) => previous.message === next.message,
);

/** Long tool output is plain text (matches production tool cells). */
export function ToolOutputRow({ message }: { message: PreviewMessage }) {
  return (
    <div className="msg-row role-tool" data-conversation-row-key={message.id}>
      <div className="msg-bubble">
        <div className="msg-meta">
          <span className="role">{message.roleLabel}</span>
          <span>{message.id}</span>
        </div>
        <pre className="md-body" style={{ margin: 0, whiteSpace: "pre-wrap" }}>
          {message.content}
        </pre>
      </div>
    </div>
  );
}

export function RowForMessage({ message }: { message: PreviewMessage }) {
  if (message.role === "tool") {
    return <ToolOutputRow message={message} />;
  }
  return <MessageRow message={message} />;
}
