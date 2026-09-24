import { memo } from "react";

import { formattedCodeBlockContent } from "./conversationFormattedCodeBlock";
import { safeConversationMarkdownUrl } from "./conversationMarkdownUrl";
import type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";
import type { MarkdownBlock } from "./streamingMarkdown";

export type StreamingLiveMarkdownBlocksProps = {
  blocks: MarkdownBlock[];
  classNames: ConversationMarkdownClassNames;
};

function headingLevelClass(
  classNames: ConversationMarkdownClassNames,
  level: 1 | 2 | 3 | 4,
) {
  switch (level) {
    case 1:
      return classNames.markdownHeading1;
    case 2:
      return classNames.markdownHeading2;
    case 3:
      return classNames.markdownHeading3;
    case 4:
    default:
      return classNames.markdownHeading4;
  }
}

function LiveBlock({
  block,
  blockIndex,
  classNames,
}: {
  block: MarkdownBlock;
  blockIndex: number;
  classNames: ConversationMarkdownClassNames;
}) {
  switch (block.type) {
    case "heading": {
      const Tag = (block.level <= 2 ? "h3" : "h4") as "h3" | "h4";
      return (
        <Tag className={`${classNames.markdownHeading} ${headingLevelClass(classNames, block.level)}`}>
          {block.content}
        </Tag>
      );
    }
    case "paragraph":
      return <p className={classNames.messageBody}>{block.content}</p>;
    case "code":
      return (
        <pre className={classNames.responseSegmentPre}>
          <code>{formattedCodeBlockContent(block.content, block.language)}</code>
        </pre>
      );
    case "table":
      return (
        <div className={classNames.markdownTableWrap}>
          <table className={classNames.markdownTable}>
            <thead>
              <tr>
                {block.headers.map((cell, cellIndex) => (
                  <th key={`h-${blockIndex}-${cellIndex}`}>{cell}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={`r-${blockIndex}-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`c-${blockIndex}-${rowIndex}-${cellIndex}`}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "unorderedList":
      return (
        <ul className={classNames.responseSegmentList}>
          {block.items.map((item, itemIndex) => (
            <li key={`u-${blockIndex}-${itemIndex}`}>{item}</li>
          ))}
        </ul>
      );
    case "orderedList":
      return (
        <ol className={classNames.responseSegmentList}>
          {block.items.map((item, itemIndex) => (
            <li key={`o-${blockIndex}-${itemIndex}`}>{item}</li>
          ))}
        </ol>
      );
    case "blockquote":
      return <blockquote className={classNames.markdownBlockquote}>{block.content}</blockquote>;
    case "divider":
      return <hr className={classNames.markdownDivider} />;
    case "image": {
      // Live tail: image URLs are frequently still streaming, so render a safe
      // link placeholder; the static renderer paints the real image once the
      // message completes.
      const safeUrl = safeConversationMarkdownUrl(block.url);
      if (!safeUrl) {
        return null;
      }
      return (
        <a className={classNames.inlineLink} href={safeUrl}>
          {block.alt || safeUrl}
        </a>
      );
    }
    default:
      return null;
  }
}

/**
 * Streaming live-tail light renderer (dual-mode markdown, pattern:
 * vercel/streamdown + zai-org/ZCode, Apache-2.0). Line-level incremental
 * blocks only: no react-markdown AST pass, no syntax highlighting, no
 * mermaid. The stable zone and completed messages keep the full
 * react-markdown pipeline; only this small (bounded live-tail) subtree
 * re-parses per streaming frame.
 */
export const StreamingLiveMarkdownBlocks = memo(function StreamingLiveMarkdownBlocks({
  blocks,
  classNames,
}: StreamingLiveMarkdownBlocksProps) {
  if (!blocks.length) {
    return null;
  }
  return (
    <div data-streaming-live-blocks="1">
      {blocks.map((block, blockIndex) => (
        <LiveBlock
          key={`${blockIndex}-${block.type}`}
          block={block}
          blockIndex={blockIndex}
          classNames={classNames}
        />
      ))}
    </div>
  );
});
