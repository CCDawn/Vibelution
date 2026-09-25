import { memo } from "react";

import { renderConversationInlineMarkdown } from "./conversationInlineMarkdown";
import { formattedCodeBlockContent } from "./conversationFormattedCodeBlock";
import {
  LIVE_CODE_MAX_VISIBLE_LINES,
  LIVE_TABLE_MAX_VISIBLE_ROWS,
  headRows,
  tailLines,
} from "./conversationRenderBudget";
import { safeConversationMarkdownUrl } from "./conversationMarkdownUrl";
import type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";
import type { MarkdownBlock } from "./streamingMarkdown";
import styles from "./StreamingLiveMarkdownBlocks.styles";

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
      // Live-tail inline light rendering (code pills / links / strong) shares
      // the same classNames map as the settled pipeline, so inline code never
      // paints as bare backticks and the settle flip keeps one visual.
      return (
        <p className={classNames.messageBody}>
          {renderConversationInlineMarkdown(block.content, classNames, blockIndex)}
        </p>
      );
    case "code": {
      // Live-tail render budget: an unclosed fence holds its whole block in
      // the live tail, so only the newest lines paint per frame (static hint,
      // no interaction — settle flips to the full renderer with the
      // details-expand budget).
      const tail = tailLines(formattedCodeBlockContent(block.content, block.language), LIVE_CODE_MAX_VISIBLE_LINES);
      return (
        <>
          {tail.overflowCount > 0 ? (
            <div className={styles.liveCodeInflowHint}>{`…已流入 ${tail.overflowCount} 行`}</div>
          ) : null}
          <pre className={classNames.responseSegmentPre}>
            <code>{tail.visible}</code>
          </pre>
        </>
      );
    }
    case "table": {
      // Live-tail render budget: newest rows keep appending, so the head rows
      // stay stable across frames and the inflow is announced, not rendered.
      const rows = headRows(block.rows, LIVE_TABLE_MAX_VISIBLE_ROWS);
      return (
        <>
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
                {rows.visible.map((row, rowIndex) => (
                  <tr key={`r-${blockIndex}-${rowIndex}`}>
                    {row.map((cell, cellIndex) => (
                      <td key={`c-${blockIndex}-${rowIndex}-${cellIndex}`}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rows.overflowCount > 0 ? (
            <div className={styles.liveTableInflowHint}>{`+${rows.overflowCount} 行流入中`}</div>
          ) : null}
        </>
      );
    }
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
