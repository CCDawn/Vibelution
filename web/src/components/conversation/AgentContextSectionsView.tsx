import { Download, Link2 } from "lucide-react";
import React, { ReactNode } from "react";

import type {
  AgentAttachmentPart,
  AgentReferencePart,
} from "../../agent-thread/types";
import type { AgentMessageContextSection } from "./messageSections";
import styles from "./ConversationView.styles";

type AgentContextSectionsViewProps = {
  sections: AgentMessageContextSection[];
  lang: "zh" | "en";
};

export function AgentContextSectionsView({ sections, lang }: AgentContextSectionsViewProps) {
  if (!sections.length) {
    return null;
  }
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
            <div className={styles.userAttachmentGrid}>
              {attachmentNodes}
            </div>
          ) : null}
          {referenceNodes.length ? (
            <div className={styles.userContextReferences}>
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
  const downloadLabel = lang === "zh" ? "下载图片" : "Download image";
  const filename = attachment.filename || attachment.artifactId || (lang === "zh" ? "图片" : "Image");
  return (
    <figure
      key={part.id}
      className={styles.userAttachment}
      data-agent-context-part-id={part.id}
      data-agent-context-part-type={part.type}
    >
      <img className={styles.userAttachmentImage} src={imageUrl} alt={filename} loading="lazy" />
      <figcaption className={styles.userAttachmentMeta}>
        <span>{filename}</span>
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
  return (
    <div
      key={part.id}
      className={styles.composerReferenceChip}
      data-agent-context-part-id={part.id}
      data-agent-context-part-type={part.type}
    >
      <span className={styles.composerReferenceIcon} aria-hidden="true">
        <Link2 size={13} />
      </span>
      <span className={styles.composerReferenceCopy}>
        {title}
        {agentLabel ? <span> · {agentLabel}</span> : null}
      </span>
    </div>
  );
}

function isNonNullNode<T extends ReactNode>(node: T | null): node is T {
  return node !== null;
}
