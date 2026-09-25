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
};

/**
 * Floating action menu over a timeline text selection: quote-to-composer and
 * copy. Absolutely positioned inside the timeline area; preventDefault on
 * mousedown keeps the selection alive until the action click lands.
 */
export function ConversationSelectionQuoteMenu({
  position,
  quoteLabel,
  copyLabel,
  onQuote,
  onCopy,
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
