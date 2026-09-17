import { Download, FileText, Link2 } from "lucide-react";
import React, { ReactNode } from "react";

import type {
  AgentAttachmentPart,
  AgentReferencePart,
} from "../../agent-thread/types";
import { attachmentSizeLabel, isImageAttachment } from "./attachmentPresentation";
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
  const isImage = isImageAttachment(attachment);
  const filename =
    attachment.filename
    || attachment.artifactId
    || (isImage
      ? (lang === "zh" ? "图片" : "Image")
      : (lang === "zh" ? "附件" : "Attachment"));
  const attachmentLabel = lang === "zh" ? `用户上下文附件 ${filename}` : `User context attachment ${filename}`;

  if (isImage) {
    const imageUrl = attachment.imageUrl || attachment.url;
    if (!imageUrl) {
      return null;
    }
    return (
      <AgentContextImageAttachment
        key={part.id}
        part={part}
        attachment={attachment}
        imageUrl={imageUrl}
        filename={filename}
        attachmentLabel={attachmentLabel}
        lang={lang}
      />
    );
  }

  return renderAgentContextFileCard(
    part,
    attachment,
    filename,
    attachmentLabel,
    lang,
    attachment.downloadUrl || attachment.url || "",
  );
}

type AgentContextImageAttachmentProps = {
  part: AgentAttachmentPart;
  attachment: AgentAttachmentPart["attachment"];
  imageUrl: string;
  filename: string;
  attachmentLabel: string;
  lang: "zh" | "en";
};

function AgentContextImageAttachment({
  part,
  attachment,
  imageUrl,
  filename,
  attachmentLabel,
  lang,
}: AgentContextImageAttachmentProps) {
  const [loadFailed, setLoadFailed] = React.useState(false);
  if (loadFailed) {
    return renderAgentContextFileCard(
      part,
      attachment,
      filename,
      attachmentLabel,
      lang,
      attachment.downloadUrl || imageUrl,
    );
  }
  const downloadLabel = lang === "zh" ? `下载图片 ${filename}` : `Download image ${filename}`;
  return (
    <figure
      className={styles.userAttachment}
      role="listitem"
      aria-label={attachmentLabel}
      data-agent-context-part-id={part.id}
      data-agent-context-part-type={part.type}
      data-agent-context-attachment-name={filename}
    >
      <img
        className={styles.userAttachmentImage}
        src={imageUrl}
        alt={filename}
        loading="lazy"
        onError={() => setLoadFailed(true)}
      />
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

function renderAgentContextFileCard(
  part: AgentAttachmentPart,
  attachment: AgentAttachmentPart["attachment"],
  filename: string,
  attachmentLabel: string,
  lang: "zh" | "en",
  downloadHref: string,
) {
  const downloadLabel = lang === "zh" ? `下载文件 ${filename}` : `Download file ${filename}`;
  const sizeLabel = attachmentSizeLabel(attachment.sizeBytes);
  return (
    <figure
      key={part.id}
      className={styles.userAttachmentFile}
      role="listitem"
      aria-label={attachmentLabel}
      data-agent-context-part-id={part.id}
      data-agent-context-part-type={part.type}
      data-agent-context-attachment-name={filename}
    >
      <figcaption className={styles.userAttachmentFileMeta}>
        <span className={styles.userAttachmentFileIcon} aria-hidden="true">
          <FileText size={17} />
        </span>
        <span className={styles.userAttachmentFileCopy}>
          <span className={styles.userAttachmentFileName} title={filename}>{filename}</span>
          {sizeLabel ? (
            <span className={styles.userAttachmentFileSize}>{sizeLabel}</span>
          ) : null}
        </span>
      </figcaption>
      {downloadHref ? (
        <a
          className={styles.imageDownloadButton}
          href={downloadHref}
          download={attachment.artifactId || true}
          title={downloadLabel}
          aria-label={downloadLabel}
        >
          <Download size={14} />
        </a>
      ) : null}
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
