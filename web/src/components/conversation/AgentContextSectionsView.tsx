import { Download, Link2 } from "lucide-react";
import React, { ReactNode } from "react";

import type {
  AgentAttachmentPart,
  AgentReferencePart,
} from "../../agent-thread/types";
import type { AgentMessageContextSection } from "./agentMessageSections";
import styles from "./AgentContextSectionsView.styles";

type AgentContextSectionsViewProps = {
  sections: AgentMessageContextSection[];
  lang: "zh" | "en";
};

export function AgentContextSectionsView({ sections, lang }: AgentContextSectionsViewProps) {
  if (!sections.length) {
    return null;
  }
  const attachmentGroupLabel = lang === "zh" ? "用户上下文附件" : "User context attachments";
  const referenceGroupLabel = lang === "zh" ? "用户上下文引用" : "User context references";
  const renderedSections = sections
    .map((section) => {
      const attachmentNodes = section.parts
        .filter((part): part is AgentAttachmentPart => part.type === "attachment")
        .map((part) => renderAgentContextAttachmentPart(part, lang))
        .filter(isNonNullNode);
      const referenceNodes = section.parts
        .filter((part): part is AgentReferencePart => part.type === "reference")
        .map((part) => renderAgentContextReferencePart(part, lang))
        .filter(isNonNullNode);
      const renderedPartCount = attachmentNodes.length + referenceNodes.length;
      if (renderedPartCount <= 0) {
        return null;
      }
      return (
        <div
          key={section.id}
          className={styles.userContextSection}
          data-agent-context-section-id={section.id}
          data-agent-context-part-count={renderedPartCount}
        >
          {attachmentNodes.length ? (
            <div
              className={styles.userAttachmentGrid}
              role="list"
              aria-label={attachmentGroupLabel}
              data-agent-context-group="attachments"
              data-agent-context-group-count={attachmentNodes.length}
            >
              {attachmentNodes}
            </div>
          ) : null}
          {referenceNodes.length ? (
            <div
              className={styles.userContextReferences}
              role="list"
              aria-label={referenceGroupLabel}
              data-agent-context-group="references"
              data-agent-context-group-count={referenceNodes.length}
            >
              {referenceNodes}
            </div>
          ) : null}
        </div>
      );
    })
    .filter(isNonNullNode);
  return renderedSections.length ? <>{renderedSections}</> : null;
}

function renderAgentContextAttachmentPart(part: AgentAttachmentPart, lang: "zh" | "en") {
  const attachment = part.attachment;
  const imageUrl = attachment.imageUrl || attachment.url;
  if (!imageUrl) {
    return null;
  }
  const filename = attachment.filename || attachment.artifactId || (lang === "zh" ? "图片" : "Image");
  const attachmentLabel = lang === "zh" ? `用户上下文附件 ${filename}` : `User context attachment ${filename}`;
  const downloadLabel = lang === "zh" ? `下载图片 ${filename}` : `Download image ${filename}`;
  return (
    <figure
      key={part.id}
      className={styles.userAttachment}
      role="listitem"
      aria-label={attachmentLabel}
      data-agent-context-part-id={part.id}
      data-agent-context-part-type={part.type}
      data-agent-context-attachment-name={filename}
    >
      <img className={styles.userAttachmentImage} src={imageUrl} alt={filename} loading="lazy" />
      <figcaption className={styles.userAttachmentMeta}>
        <span title={filename}>{filename}</span>
        <a
          className={styles.imageDownloadButton}
          href={attachment.downloadUrl || imageUrl}
          download={attachment.artifactId || true}
          title={downloadLabel}
          aria-label={downloadLabel}
        >
          <Download size={14} />
        </a>
      </figcaption>
    </figure>
  );
}

function renderAgentContextReferencePart(part: AgentReferencePart, lang: "zh" | "en") {
  const reference = part.reference;
  const title = reference.title || reference.sessionId || (lang === "zh" ? "会话引用" : "Session reference");
  const agentLabel = reference.agentDisplayName || reference.agentCode || reference.agentId || "";
  const referenceLabel = agentLabel
    ? (lang === "zh" ? `用户上下文引用 ${title} ${agentLabel}` : `User context reference ${title} ${agentLabel}`)
    : (lang === "zh" ? `用户上下文引用 ${title}` : `User context reference ${title}`);
  return (
    <div
      key={part.id}
      className={styles.composerReferenceChip}
      role="listitem"
      aria-label={referenceLabel}
      data-agent-context-part-id={part.id}
      data-agent-context-part-type={part.type}
      data-agent-context-reference-kind={reference.kind}
      data-agent-context-reference-title={title}
      data-agent-context-reference-agent={agentLabel || undefined}
    >
      <span className={styles.composerReferenceIcon} aria-hidden="true">
        <Link2 size={13} />
      </span>
      <span className={styles.composerReferenceCopy}>
        <span className={styles.composerReferenceTitle} title={title}>
          {title}
        </span>
        {agentLabel ? (
          <span className={styles.composerReferenceMeta} title={agentLabel}>
            {agentLabel}
          </span>
        ) : null}
      </span>
    </div>
  );
}

function isNonNullNode<T extends ReactNode>(node: T | null): node is T {
  return node !== null;
}
