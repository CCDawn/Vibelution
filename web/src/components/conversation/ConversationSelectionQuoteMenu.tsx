import { VButton } from "../vui";
import { VSelectionToolbar } from "../vui/primitives/VSelectionToolbar";
import type { ConversationSelectionRect } from "./conversationTextSelection";
import styles from "./ConversationSelectionQuoteMenu.styles";

export type ConversationSelectionQuoteMenuProps = {
  selectionRect: ConversationSelectionRect;
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
  /** Opens the selected text in the ordinary right-column side chat. */
  sideLabel?: string;
  onSideChat?: () => void;
};

/**
 * Floating action menu over a timeline text selection: quote-to-composer,
 * structured reference chip, and copy. Fixed to the viewport and centered
 * on the selection. preventDefault on mousedown keeps the selection alive
 * until the action click lands.
 */
export function ConversationSelectionQuoteMenu({
  selectionRect,
  quoteLabel,
  copyLabel,
  onQuote,
  onCopy,
  referenceLabel,
  onReference,
  sideLabel,
  onSideChat,
}: ConversationSelectionQuoteMenuProps) {
  return (
    <VSelectionToolbar
      anchorRect={selectionRect}
      ariaLabel={quoteLabel}
      className={styles.selectionQuoteMenu}
    >
      {onSideChat ? (
        <VButton
          type="button"
          contentLayout="plain"
          className={styles.selectionQuoteMenuItem}
          onClick={onSideChat}
        >
          {sideLabel}
        </VButton>
      ) : null}
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
    </VSelectionToolbar>
  );
}
