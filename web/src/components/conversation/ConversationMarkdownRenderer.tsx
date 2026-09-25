import React, { type ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { formattedCodeBlockContent } from "./conversationFormattedCodeBlock";
import { safeConversationMarkdownUrl } from "./conversationMarkdownUrl";
import type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";
import {
  CODE_BLOCK_MAX_VISIBLE_LINES,
  TABLE_MAX_VISIBLE_ROWS,
  exceedsLineBudget,
  headLines,
  headRows,
} from "./conversationRenderBudget";
import {
  conversationMarkdownOverflowStyles,
  conversationMarkdownRendererStyles,
} from "./ConversationMarkdownRenderer.styles";

export type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";

export type ConversationMarkdownRendererProps = {
  content: string;
  classNames?: ConversationMarkdownClassNames;
  duplicateImageUrls?: Set<string>;
  renderImage?: (alt: string, url: string, duplicateImageUrls?: Set<string>) => React.ReactNode;
};

const markdownPlugins = [remarkGfm];

/**
 * Content-memoized: completed messages never re-parse; a re-render with the
 * same content/classNames/renderImage short-circuits before the normalize +
 * react-markdown AST pass. During streaming only the live message (whose
 * content actually grows) re-parses; its stable prefix is additionally split
 * out by ConversationStreamingResponseContent.
 */
export const ConversationMarkdownRenderer = React.memo(function ConversationMarkdownRenderer({
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
});

export function normalizeConversationMarkdown(content: string) {
  const lines = String(content ?? "").replace(/\r\n/g, "\n").split("\n");
  // Fence state for the HTML-tag escape below: code-fence content must pass
  // through untouched (a backslash there renders literally).
  let fenceMarker: string | null = null;
  return lines
    .map((line) => {
      const normalized = normalizeConversationMarkdownLine(line);
      const fence = normalized.match(/^\s{0,3}(`{3,}|~{3,})/);
      if (fenceMarker) {
        if (fence && fence[1].startsWith(fenceMarker)) {
          fenceMarker = null;
        }
        return normalized;
      }
      if (fence) {
        fenceMarker = fence[1].slice(0, 1).repeat(3);
        return normalized;
      }
      return escapeLineInitialEnvelopeTag(normalized);
    })
    .join("\n");
}

// Internal-format envelope tags some relays leak into the answer channel.
// At line start they would open a CommonMark HTML block, and `skipHtml`
// drops that block wholesale — silently swallowing every following plaintext
// line up to the next blank line. Backslash-escaping the leading `<` turns
// the tag into literal text so adjacent content survives. Other raw HTML
// (e.g. `<script>...`) keeps its existing inert-drop posture. The optional
// leading backslash in the pattern keeps the escape idempotent across
// repeated normalize passes while streaming.
const ENVELOPE_TAG_LINE_RE = /^\s{0,3}(\\?)<\/?(?:think|thinking|summary|analysis)\b/i;

function escapeLineInitialEnvelopeTag(line: string) {
  return line.replace(ENVELOPE_TAG_LINE_RE, (match, existingEscape: string) =>
    existingEscape ? match : match.replace("<", "\\<"),
  );
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
    code({ children }: ComponentPropsWithoutRef<"code">) {
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
      if (!renderImage) {
        // Default path (e.g. streaming stable prefix): render lazily and
        // async-decoded so offscreen images never block first paint. No
        // className — callers constrain via `[&_img]` wrappers.
        return <img alt={alt ?? ""} src={safeSrc} loading="lazy" decoding="async" />;
      }
      return <>{renderImage(alt ?? "", safeSrc, duplicateImageUrls)}</>;
    },
    ol({ children }: ComponentPropsWithoutRef<"ol">) {
      return <ol className={classNames.responseSegmentList}>{children}</ol>;
    },
    p({ children }: ComponentPropsWithoutRef<"p">) {
      return <p className={classNames.messageBody}>{children}</p>;
    },
    pre({ children }: ComponentPropsWithoutRef<"pre">) {
      const codeBlock = markdownCodeBlockChildren(children);
      const truncation = truncateConversationMarkdownCodeBlock(codeBlock);
      if (!truncation) {
        return <pre className={classNames.responseSegmentPre}>{codeBlock}</pre>;
      }
      return (
        <>
          <pre className={classNames.responseSegmentPre}>{truncation.visible}</pre>
          <details className={conversationMarkdownOverflowStyles.overflowDetails}>
            <summary className={conversationMarkdownOverflowStyles.overflowSummary}>
              {`展开其余 ${truncation.overflowCount} 行`}
            </summary>
            <pre className={classNames.responseSegmentPre}>{truncation.overflow}</pre>
          </details>
        </>
      );
    },
    strong({ children }: ComponentPropsWithoutRef<"strong">) {
      return <strong className={classNames.inlineStrong}>{children}</strong>;
    },
    table({ children }: ComponentPropsWithoutRef<"table">) {
      const truncation = truncateConversationMarkdownTable(children);
      if (!truncation) {
        return (
          <div className={classNames.markdownTableWrap}>
            <table className={classNames.markdownTable}>{children}</table>
          </div>
        );
      }
      return (
        <>
          <div className={classNames.markdownTableWrap}>
            <table className={classNames.markdownTable}>{truncation.visible}</table>
          </div>
          <details className={conversationMarkdownOverflowStyles.overflowDetails}>
            <summary className={conversationMarkdownOverflowStyles.overflowSummary}>
              {`展开其余 ${truncation.overflowCount} 行`}
            </summary>
            <div className={classNames.markdownTableWrap}>
              <table className={classNames.markdownTable}>{truncation.overflow}</table>
            </div>
          </details>
        </>
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

function markdownCodeBlockChildren(children: React.ReactNode) {
  const childNodes = React.Children.toArray(children);
  if (childNodes.length !== 1 || !React.isValidElement<ComponentPropsWithoutRef<"code">>(childNodes[0])) {
    return children;
  }

  const codeElement = childNodes[0];
  const className = codeElement.props.className ?? "";
  return (
    <code className={className || undefined}>
      {formattedCodeBlockChildren(codeElement.props.children, languageFromCodeClassName(className))}
    </code>
  );
}

type ConversationMarkdownCodeTruncation = {
  visible: React.ReactNode;
  overflow: React.ReactNode;
  overflowCount: number;
};

/**
 * Render budget for completed code blocks: over-budget blocks keep the head
 * lines in the primary `<pre>` and fold the rest behind a native `<details>`
 * (same interaction shape as ConversationPatchDiff). Full semantics stay in
 * the DOM; only first paint is bounded.
 */
function truncateConversationMarkdownCodeBlock(node: React.ReactNode): ConversationMarkdownCodeTruncation | null {
  if (!React.isValidElement<ComponentPropsWithoutRef<"code">>(node)) {
    return null;
  }
  const parts = React.Children.toArray(node.props.children);
  if (parts.length !== 1 || typeof parts[0] !== "string") {
    return null;
  }
  // remark fenced-code values carry a trailing newline; that newline is fence
  // syntax, not a rendered line, so it is stripped before budget arithmetic.
  const text = parts[0].replace(/\n$/, "");
  if (!exceedsLineBudget(text, CODE_BLOCK_MAX_VISIBLE_LINES)) {
    return null;
  }
  const slice = headLines(text, CODE_BLOCK_MAX_VISIBLE_LINES);
  const className = node.props.className || undefined;
  return {
    visible: <code className={className}>{slice.visible}</code>,
    overflow: <code className={className}>{slice.overflow}</code>,
    overflowCount: slice.overflowCount,
  };
}

type ConversationMarkdownTableTruncation = {
  visible: React.ReactNode;
  overflow: React.ReactNode;
  overflowCount: number;
};

/**
 * Render budget for completed tables: over-budget tables render the head data
 * rows and fold the rest behind a `<details>` that repeats the column headers
 * so the expansion stays readable.
 */
function truncateConversationMarkdownTable(children: React.ReactNode): ConversationMarkdownTableTruncation | null {
  const sections = React.Children.toArray(children);
  const bodySectionIndexes: number[] = [];
  const bodyRowLists: React.ReactNode[][] = [];
  let totalRows = 0;
  sections.forEach((section, index) => {
    if (!React.isValidElement<{ children?: React.ReactNode }>(section) || section.type !== "tbody") {
      return;
    }
    const rows = React.Children.toArray(section.props.children);
    bodySectionIndexes.push(index);
    bodyRowLists.push(rows);
    totalRows += rows.length;
  });
  if (totalRows <= TABLE_MAX_VISIBLE_ROWS) {
    return null;
  }

  let visibleBudget = TABLE_MAX_VISIBLE_ROWS;
  const visibleBodyRows = bodyRowLists.map((rows) => {
    const visible = rows.slice(0, Math.max(0, visibleBudget));
    visibleBudget -= visible.length;
    return visible;
  });
  const overflowBodyRows = bodyRowLists.map((rows, index) => rows.slice(visibleBodyRows[index]?.length ?? 0));
  const projectSections = (renderOverflow: boolean) =>
    sections
      .map((section, index) => {
        if (!React.isValidElement<{ children?: React.ReactNode }>(section)) {
          return null;
        }
        const bodyIndex = bodySectionIndexes.indexOf(index);
        if (bodyIndex >= 0) {
          const projectedRows = renderOverflow ? overflowBodyRows[bodyIndex] : visibleBodyRows[bodyIndex];
          return React.cloneElement(section, {}, projectedRows);
        }
        // Primary table keeps every non-body section as-is; the overflow
        // table repeats only the column headers (thead) so the expansion
        // stays readable without duplicating other sections.
        if (!renderOverflow) {
          return section;
        }
        return section.type === "thead" ? section : null;
      })
      .filter(Boolean);

  return {
    visible: projectSections(false),
    overflow: projectSections(true),
    overflowCount: totalRows - TABLE_MAX_VISIBLE_ROWS,
  };
}
