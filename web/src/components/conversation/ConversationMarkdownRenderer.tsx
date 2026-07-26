import React, { type ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { formattedCodeBlockContent } from "./conversationFormattedCodeBlock";
import { safeConversationMarkdownUrl } from "./conversationMarkdownUrl";
import type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";
import { conversationMarkdownRendererStyles } from "./ConversationMarkdownRenderer.styles";

export type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";

export type ConversationMarkdownRendererProps = {
  content: string;
  classNames?: ConversationMarkdownClassNames;
  duplicateImageUrls?: Set<string>;
  renderImage?: (alt: string, url: string, duplicateImageUrls?: Set<string>) => React.ReactNode;
};

const markdownPlugins = [remarkGfm];

export function ConversationMarkdownRenderer({
  content,
  classNames = conversationMarkdownRendererStyles,
  duplicateImageUrls,
  renderImage,
}: ConversationMarkdownRendererProps) {
  const normalized = normalizeConversationMarkdown(content);
  if (!normalized.trim()) {
    return null;
  }
  const hasTable = /^\s*\|.+\|\s*$/m.test(normalized);
  return (
    <div className={[classNames.markdownBody, hasTable ? classNames.markdownBodyWithTable : ""].filter(Boolean).join(" ")}>
      <ReactMarkdown
        remarkPlugins={markdownPlugins}
        skipHtml
        components={markdownComponents(classNames, duplicateImageUrls, renderImage)}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  );
}

export function normalizeConversationMarkdown(content: string) {
  const lines = String(content ?? "").replace(/\r\n/g, "\n").split("\n");
  return lines.map((line) => normalizeConversationMarkdownLine(line)).join("\n");
}

function normalizeConversationMarkdownLine(line: string) {
  const trimmedStart = line.trimStart();
  const indent = line.slice(0, line.length - trimmedStart.length);
  const unordered = trimmedStart.match(/^([-*])(?=\S)(.+)$/);
  if (unordered && trimmedStart[1] !== unordered[1] && !trimmedStart.startsWith("---") && !trimmedStart.startsWith("***")) {
    return `${indent}${unordered[1]} ${unordered[2]}`;
  }

  const ordered = trimmedStart.match(/^(\d+[.)])(?=\S)(.+)$/);
  if (ordered) {
    return `${indent}${ordered[1]} ${ordered[2]}`;
  }

  const label = trimmedStart.match(/^([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9 _/-]{1,18})([：:])(?=\S)(.+)$/);
  if (label && !trimmedStart.includes("://")) {
    const separator = label[2] === "：" ? "" : " ";
    return `${indent}**${label[1].trim()}**${label[2]}${separator}${label[3].trimStart()}`;
  }

  return line;
}

function markdownComponents(
  classNames: ConversationMarkdownClassNames,
  duplicateImageUrls?: Set<string>,
  renderImage?: (alt: string, url: string, duplicateImageUrls?: Set<string>) => React.ReactNode,
) {
  return {
    a({ href, children }: ComponentPropsWithoutRef<"a">) {
      const safeHref = safeConversationMarkdownUrl(href ?? "");
      if (!safeHref) {
        return <>{children}</>;
      }
      return (
        <a className={classNames.inlineLink} href={safeHref}>
          {children}
        </a>
      );
    },
    blockquote({ children }: ComponentPropsWithoutRef<"blockquote">) {
      return <blockquote className={classNames.markdownBlockquote}>{children}</blockquote>;
    },
    code({ className, children }: ComponentPropsWithoutRef<"code">) {
      if (className) {
        return <code className={className}>{formattedCodeBlockChildren(children, languageFromCodeClassName(className))}</code>;
      }
      return <code className={classNames.inlineCode}>{children}</code>;
    },
    h1({ children }: ComponentPropsWithoutRef<"h1">) {
      return <h3 className={`${classNames.markdownHeading} ${classNames.markdownHeading1}`}>{children}</h3>;
    },
    h2({ children }: ComponentPropsWithoutRef<"h2">) {
      return <h3 className={`${classNames.markdownHeading} ${classNames.markdownHeading2}`}>{children}</h3>;
    },
    h3({ children }: ComponentPropsWithoutRef<"h3">) {
      return <h4 className={`${classNames.markdownHeading} ${classNames.markdownHeading3}`}>{children}</h4>;
    },
    h4({ children }: ComponentPropsWithoutRef<"h4">) {
      return <h4 className={`${classNames.markdownHeading} ${classNames.markdownHeading4}`}>{children}</h4>;
    },
    hr() {
      return <hr className={classNames.markdownDivider} />;
    },
    img({ alt, src }: ComponentPropsWithoutRef<"img">) {
      const safeSrc = safeConversationMarkdownUrl(src ?? "");
      if (!safeSrc) {
        return null;
      }
      return renderImage ? <>{renderImage(alt ?? "", safeSrc, duplicateImageUrls)}</> : null;
    },
    ol({ children }: ComponentPropsWithoutRef<"ol">) {
      return <ol className={classNames.responseSegmentList}>{children}</ol>;
    },
    p({ children }: ComponentPropsWithoutRef<"p">) {
      return <p className={classNames.messageBody}>{children}</p>;
    },
    pre({ children }: ComponentPropsWithoutRef<"pre">) {
      return <pre className={classNames.responseSegmentPre}>{children}</pre>;
    },
    strong({ children }: ComponentPropsWithoutRef<"strong">) {
      return <strong className={classNames.inlineStrong}>{children}</strong>;
    },
    table({ children }: ComponentPropsWithoutRef<"table">) {
      return (
        <div className={classNames.markdownTableWrap}>
          <table className={classNames.markdownTable}>{children}</table>
        </div>
      );
    },
    ul({ children }: ComponentPropsWithoutRef<"ul">) {
      return <ul className={classNames.responseSegmentList}>{children}</ul>;
    },
  };
}

function languageFromCodeClassName(className: string) {
  return className
    .split(/\s+/)
    .find((item) => item.startsWith("language-"))
    ?.slice("language-".length);
}

function formattedCodeBlockChildren(children: React.ReactNode, language?: string) {
  return formattedCodeBlockContent(React.Children.toArray(children).join(""), language);
}
