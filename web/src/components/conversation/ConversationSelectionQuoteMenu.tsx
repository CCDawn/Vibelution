import type { MouseEvent } from "react";

import { VButton } from "../vui";
import type { ConversationSelectionMenuPosition } from "./conversationTextSelection";
import styles from "./ConversationSelectionQuoteMenu.styles";

export type ConversationSelectionQuoteMenuProps = {
  position: ConversationSelectionMenuPosition;
  quoteLabel: string;
  copyLabel: string;
  onQuote: () => void;
  onCopy: () => void;
  /**
   * Structured message-reference action: offered only when the selection is
   * anchored inside a message row, so callers simply omit it otherwise.
   */
  referenceLabel?: string;
  onReference?: () => void;
};

/**
 * Floating action menu over a timeline text selection: quote-to-composer,
 * structured reference chip, and copy. Absolutely positioned inside the
 * timeline area; preventDefault on mousedown keeps the selection alive until
 * the action click lands.
 */
export function ConversationSelectionQuoteMenu({
  position,
  quoteLabel,
  copyLabel,
  onQuote,
  onCopy,
  referenceLabel,
  onReference,
}: ConversationSelectionQuoteMenuProps) {
  const handleMouseDown = (event: MouseEvent<HTMLDivElement>) => {
    event.preventDefault();
  };
  return (
    <div
      className={styles.selectionQuoteMenu}
      style={{
        top: position.top,
        left: position.left,
        transform: position.above ? "translateY(-100%)" : undefined,
      }}
      role="toolbar"
      aria-label={quoteLabel}
      data-conversation-selection-menu="1"
      onMouseDown={handleMouseDown}
    >
      <VButton
        type="button"
        contentLayout="plain"
        className={styles.selectionQuoteMenuItem}
        onClick={onQuote}
      >
        {quoteLabel}
      </VButton>
      {onReference ? (
        <VButton
          type="button"
          contentLayout="plain"
          className={styles.selectionQuoteMenuItem}
          onClick={onReference}
        >
          {referenceLabel}
        </VButton>
      ) : null}
      <VButton
        type="button"
        contentLayout="plain"
        className={styles.selectionQuoteMenuItem}
        onClick={onCopy}
      >
        {copyLabel}
      </VButton>
    </div>
  );
}
