import { useLayoutEffect, useRef, type MouseEvent } from "react";
import { createPortal } from "react-dom";

import { VButton } from "../vui";
import {
  resolveSelectionQuoteMenuPosition,
  SELECTION_QUOTE_MENU_HEIGHT_PX,
  SELECTION_QUOTE_MENU_WIDTH_PX,
  type ConversationSelectionRect,
} from "./conversationTextSelection";
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
}: ConversationSelectionQuoteMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const menu = menuRef.current;
    if (!menu) {
      return;
    }
    const place = () => {
      const measured = menu.getBoundingClientRect();
      const position = resolveSelectionQuoteMenuPosition(
        selectionRect,
        { width: window.innerWidth, height: window.innerHeight },
        {
          width: measured.width || SELECTION_QUOTE_MENU_WIDTH_PX,
          height: measured.height || SELECTION_QUOTE_MENU_HEIGHT_PX,
        },
      );
      menu.style.left = `${position.left}px`;
      menu.style.top = `${position.top}px`;
      menu.style.transform = position.above ? "translateY(-100%)" : "none";
    };
    place();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(place);
    observer?.observe(menu);
    window.addEventListener("resize", place);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", place);
    };
  }, [
    selectionRect.bottom,
    selectionRect.height,
    selectionRect.left,
    selectionRect.right,
    selectionRect.top,
    selectionRect.width,
  ]);
  const handleMouseDown = (event: MouseEvent<HTMLDivElement>) => {
    event.preventDefault();
  };
  const menu = (
    <div
      ref={menuRef}
      className={styles.selectionQuoteMenu}
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
  if (typeof document === "undefined") {
    return menu;
  }
  return createPortal(menu, document.body);
}
