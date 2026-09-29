import React, { useEffect, useRef, useState, type ComponentPropsWithoutRef } from "react";
import { Check, Copy, WrapText } from "lucide-react";
import ReactMarkdown, { type Options as ReactMarkdownOptions } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
// Local bundling only: fonts resolve from node_modules alongside the CSS —
// no CDN or external font fetch is allowed.
import "katex/dist/katex.min.css";

import { VNativeButton } from "../vui";
import {
  ConversationMarkdownBlockBoundary,
  markdownBlockBoundaryKey,
  markdownBlockSourceText,
} from "./conversationMarkdownBlockBoundary";
import { formattedCodeBlockContent } from "./conversationFormattedCodeBlock";
import { classifyConversationMarkdownLinkTarget } from "./conversationMarkdownLinkTargets";
import { guardConversationMarkdownMath } from "./conversationMarkdownMathGuard";
import { ConversationMarkdownMermaidBlock } from "./conversationMarkdownMermaidBlock";
import { safeConversationMarkdownUrl } from "./conversationMarkdownUrl";
import { ConversationMarkdownWorkspaceFileLink } from "./conversationMarkdownWorkspaceFileLink";
import type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";
import {
  CODE_BLOCK_MAX_VISIBLE_LINES,
  TABLE_MAX_VISIBLE_ROWS,
  exceedsLineBudget,
  headLines,
  headRows,
} from "./conversationRenderBudget";
import {
  conversationMarkdownCodeBlockStyles,
  conversationMarkdownOverflowStyles,
  conversationMarkdownRendererStyles,
} from "./ConversationMarkdownRenderer.styles";

export type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";

export type ConversationMarkdownRendererProps = {
  content: string;
  classNames?: ConversationMarkdownClassNames;
  duplicateImageUrls?: Set<string>;
  renderImage?: (alt: string, url: string, duplicateImageUrls?: Set<string>) => React.ReactNode;
  /**
   * Session workspace root provided by the caller; enables workspace-file
   * markdown links (open / reveal / copy via the desktop bridge). Absent keeps
   * the legacy anchor behavior for every href.
   */
  workspaceRoot?: string;
  /** Bilingual chrome text for workspace-file menus and mermaid blocks. */
  language?: "zh" | "en";
};

// Order matters: GFM first, then math, so tables/task lists resolve before
// `$…$` inline math; KaTeX runs on the rehype tree (rehype-katex degrades a
// failed formula to its LaTeX source instead of throwing — a ParseError falls
// back to a `.katex-error` span carrying the source text).
const markdownPlugins = [remarkGfm, remarkMath];
const markdownRehypePlugins: NonNullable<ReactMarkdownOptions["rehypePlugins"]> = [
  [
    rehypeKatex,
    {
      errorColor: "var(--fg-tertiary)",
      // Strict-mode issues (unicode/text-mode nits) must not fail the first
      // render pass; ParseErrors still degrade to the source-text span.
      strict: "ignore" as const,
    },
  ],
];

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
  workspaceRoot,
  language = "zh",
}: ConversationMarkdownRendererProps) {
  const normalized = normalizeConversationMarkdown(content);
  if (!normalized.trim()) {
    return null;
  }
  const guarded = guardConversationMarkdownMath(normalized);
  const hasTable = /^\s*\|.+\|\s*$/m.test(normalized);
  return (
    <div className={[classNames.markdownBody, hasTable ? classNames.markdownBodyWithTable : ""].filter(Boolean).join(" ")}>
      <ReactMarkdown
        remarkPlugins={markdownPlugins}
        rehypePlugins={markdownRehypePlugins}
        skipHtml
        components={markdownComponents(classNames, duplicateImageUrls, renderImage, workspaceRoot, language)}
      >
        {guarded}
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
  workspaceRoot?: string,
  language: "zh" | "en" = "zh",
) {
  return {
    a({ href, children }: ComponentPropsWithoutRef<"a">) {
      const rawHref = href ?? "";
      // Workspace-file links resolve against the caller-provided session
      // workspace root and open through the desktop bridge; without a root the
      // classifier keeps them "other" and the legacy anchor behavior applies.
      const target = classifyConversationMarkdownLinkTarget(rawHref, workspaceRoot);
      if (target.kind === "workspace-file") {
        return (
          <ConversationMarkdownWorkspaceFileLink
            path={target.absolutePath}
            className={classNames.inlineLink}
            language={language}
          >
            {children}
          </ConversationMarkdownWorkspaceFileLink>
        );
      }
      const safeHref = safeConversationMarkdownUrl(rawHref);
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
    pre({ children, node }: ComponentPropsWithoutRef<"pre"> & { node?: unknown }) {
      // Block-scope guard (ZCode-aligned granularity): a crash while rendering
      // this one fence degrades the fence to its raw text and leaves sibling
      // blocks untouched. The risky work (formatting, mermaid detection and
      // render machine, truncation) lives inside ConversationMarkdownPreBlock,
      // i.e. INSIDE the boundary — throws in the override body itself would
      // bypass it. Source text comes from the hast node (see
      // markdownBlockSourceText for the trade-off); the key derives from the
      // block's source position so reconciliation stays stable across
      // re-renders.
      return (
        <ConversationMarkdownBlockBoundary
          key={markdownBlockBoundaryKey(node)}
          source={markdownBlockSourceText(node)}
          preClassName={classNames.responseSegmentPre}
        >
          <ConversationMarkdownPreBlock
            preClassName={classNames.responseSegmentPre}
            language={language}
          >
            {children}
          </ConversationMarkdownPreBlock>
        </ConversationMarkdownBlockBoundary>
      );
    },
    strong({ children }: ComponentPropsWithoutRef<"strong">) {
      return <strong className={classNames.inlineStrong}>{children}</strong>;
    },
    table({ children, node }: ComponentPropsWithoutRef<"table"> & { node?: unknown }) {
      // Same block-scope guard as `pre`: table truncation/rendering runs
      // inside ConversationMarkdownTableBlock so a throw degrades only this
      // table to its cell text.
      return (
        <ConversationMarkdownBlockBoundary
          key={markdownBlockBoundaryKey(node)}
          source={markdownBlockSourceText(node)}
        >
          <ConversationMarkdownTableBlock classNames={classNames}>{children}</ConversationMarkdownTableBlock>
        </ConversationMarkdownBlockBoundary>
      );
    },
    ul({ children }: ComponentPropsWithoutRef<"ul">) {
      return <ul className={classNames.responseSegmentList}>{children}</ul>;
    },
  };
}

type ConversationMarkdownPreBlockProps = {
  children: React.ReactNode;
  preClassName: string;
  language: "zh" | "en";
};

/**
 * Block body of a fenced code block (plain fences and ```mermaid fences).
 * Everything that can realistically throw — code formatting, mermaid machine
 * render, truncation arithmetic — deliberately runs in THIS component's
 * render, i.e. inside the surrounding block boundary: work done in the
 * `components` override body itself would throw before the boundary exists
 * and fall through to the whole-message boundary instead.
 */
function ConversationMarkdownPreBlock({ children, preClassName, language }: ConversationMarkdownPreBlockProps) {
  const codeBlock = markdownCodeBlockChildren(children);
  const languageLabel = markdownCodeBlockLanguage(codeBlock);
  if ((languageLabel ?? "").trim().toLowerCase() === "mermaid") {
    return (
      <ConversationMarkdownMermaidBlock
        code={markdownCodeBlockText(codeBlock)}
        preClassName={preClassName}
        language={language}
      />
    );
  }
  return (
    <ConversationMarkdownCodeBlock
      language={languageLabel}
      text={markdownCodeBlockText(codeBlock)}
      preClassName={preClassName}
      code={codeBlock}
      truncation={truncateConversationMarkdownCodeBlock(codeBlock)}
    />
  );
}

type ConversationMarkdownTableBlockProps = {
  children: React.ReactNode;
  classNames: ConversationMarkdownClassNames;
};

/** Block body of a GFM table — see ConversationMarkdownPreBlock for the split. */
function ConversationMarkdownTableBlock({ children, classNames }: ConversationMarkdownTableBlockProps) {
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
}

function languageFromCodeClassName(className: string) {
  return className
    .split(/\s+/)
    .find((item) => item.startsWith("language-"))
    ?.slice("language-".length);
}

function markdownCodeBlockLanguage(node: React.ReactNode) {
  if (React.isValidElement<ComponentPropsWithoutRef<"code">>(node)) {
    return languageFromCodeClassName(node.props.className ?? "");
  }
  return undefined;
}

/** Plain text of a rendered code element — clipboard source for copy. */
function markdownCodeBlockText(node: React.ReactNode): string {
  if (typeof node === "string") {
    return node;
  }
  if (typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map(markdownCodeBlockText).join("");
  }
  if (React.isValidElement<{ children?: React.ReactNode }>(node)) {
    return markdownCodeBlockText(node.props.children);
  }
  return "";
}

// ZCode-aligned copy feedback: Copy flips to Check for the same feedback
// window as the turn hover copy action in ConversationView.
const CODE_COPY_FEEDBACK_MS = 1600;

async function copyMarkdownCodeToClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.setAttribute("readonly", "true");
  textArea.style.position = "absolute";
  textArea.style.opacity = "0";
  textArea.style.pointerEvents = "none";
  document.body.appendChild(textArea);
  textArea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textArea);
  if (!copied) {
    throw new Error("copy failed");
  }
}

type ConversationMarkdownCodeBlockProps = {
  language?: string;
  text: string;
  preClassName: string;
  code: React.ReactNode;
  truncation: ConversationMarkdownCodeTruncation | null;
};

/**
 * Completed fenced code block with a ZCode-style header: lowercase language
 * label on the left, soft-wrap toggle + copy control on the right. Header is
 * part of the block chrome (the host-provided pre style keeps its border and
 * rounding; the header attaches above it). Local-only state: wrap applies to
 * this block for its mount lifetime, copy feedback self-resets.
 */
export function ConversationMarkdownCodeBlock({
  language,
  text,
  preClassName,
  code,
  truncation,
}: ConversationMarkdownCodeBlockProps) {
  const [wrapped, setWrapped] = useState(false);
  const [copied, setCopied] = useState(false);
  const copyFeedbackRef = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (copyFeedbackRef.current !== null) {
        window.clearTimeout(copyFeedbackRef.current);
      }
    },
    [],
  );

  const preClasses = [
    preClassName,
    conversationMarkdownCodeBlockStyles.preAttached,
    wrapped ? conversationMarkdownCodeBlockStyles.preWrapped : "",
  ]
    .filter(Boolean)
    .join(" ");
  const overflowPreClasses = [
    preClassName,
    wrapped ? conversationMarkdownCodeBlockStyles.preWrapped : "",
  ]
    .filter(Boolean)
    .join(" ");
  const languageLabel = (language ?? "").trim().toLowerCase() || "text";

  const handleCopy = () => {
    if (!text.trim()) {
      return;
    }
    void copyMarkdownCodeToClipboard(text).then(() => {
      setCopied(true);
      if (copyFeedbackRef.current !== null) {
        window.clearTimeout(copyFeedbackRef.current);
      }
      copyFeedbackRef.current = window.setTimeout(() => {
        copyFeedbackRef.current = null;
        setCopied(false);
      }, CODE_COPY_FEEDBACK_MS);
    }).catch(() => undefined);
  };

  return (
    <div className={conversationMarkdownCodeBlockStyles.shell}>
      <div className={conversationMarkdownCodeBlockStyles.header} data-markdown-code-block="true">
        <span className={conversationMarkdownCodeBlockStyles.language}>{languageLabel}</span>
        <span className={conversationMarkdownCodeBlockStyles.actions}>
          <VNativeButton
            data-vui="icon-button"
            className={[
              conversationMarkdownCodeBlockStyles.headerButton,
              wrapped ? conversationMarkdownCodeBlockStyles.headerButtonActive : "",
            ]
              .filter(Boolean)
              .join(" ")}
            onClick={() => setWrapped((current) => !current)}
            aria-pressed={wrapped}
            aria-label="自动换行"
            title="自动换行"
          >
            <WrapText size={14} aria-hidden="true" />
          </VNativeButton>
          <VNativeButton
            data-vui="icon-button"
            className={conversationMarkdownCodeBlockStyles.headerButton}
            onClick={handleCopy}
            aria-label="复制代码"
            title="复制代码"
          >
            {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
          </VNativeButton>
        </span>
      </div>
      {truncation ? (
        <>
          <pre className={preClasses}>{truncation.visible}</pre>
          <details className={conversationMarkdownOverflowStyles.overflowDetails}>
            <summary className={conversationMarkdownOverflowStyles.overflowSummary}>
              {`展开其余 ${truncation.overflowCount} 行`}
            </summary>
            <pre className={overflowPreClasses}>{truncation.overflow}</pre>
          </details>
        </>
      ) : (
        <pre className={preClasses}>{code}</pre>
      )}
    </div>
  );
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
