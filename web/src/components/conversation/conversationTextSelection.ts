/**
 * Text-selection quote support for the conversation timeline (pattern:
 * zai-org/ZCode useTextSelection + SelectionActionMenu, Apache-2.0). Pure
 * selection geometry/text logic so the ConversationView effect stays a thin
 * listener shell. The menu is centered on the selection in viewport
 * coordinates, the same anchor SelectionActionMenu uses.
 */

import { resolveSelectionToolbarPosition } from "../layout/selectionToolbarPosition";

export {
  SELECTION_TOOLBAR_WIDTH_PX as SELECTION_QUOTE_MENU_WIDTH_PX,
  SELECTION_TOOLBAR_HEIGHT_PX as SELECTION_QUOTE_MENU_HEIGHT_PX,
  SELECTION_TOOLBAR_GAP_PX as SELECTION_QUOTE_MENU_GAP_PX,
  SELECTION_TOOLBAR_VIEWPORT_MARGIN_PX as SELECTION_QUOTE_MENU_VIEWPORT_MARGIN_PX,
} from "../layout/selectionToolbarPosition";

export type ConversationSelectionRect = {
  top: number;
  left: number;
  width: number;
  height: number;
  bottom: number;
  right: number;
};

export type ConversationSelectionRangeLike = {
  startContainer: Node;
  endContainer: Node;
  getBoundingClientRect(): ConversationSelectionRect;
};

export type ConversationSelectionLike = {
  rangeCount: number;
  isCollapsed: boolean;
  toString(): string;
  getRangeAt(index: number): ConversationSelectionRangeLike;
};

export type ConversationSelectionSnapshot = {
  text: string;
  rect: ConversationSelectionRect;
  /**
   * ConversationMessage id of the timeline row containing the selection
   * anchor (row wrappers carry the attribute below), or "" when the
   * selection is not anchored inside a message row.
   */
  sourceMessageId: string;
};

/**
 * Row wrappers carry the owning message id so selection quotes can become a
 * structured `message` reference chip, not just pasted text. Kept beside the
 * walker so the render site and the lookup share one attribute name.
 */
export const CONVERSATION_SELECTION_MESSAGE_ATTRIBUTE = "data-conversation-message-id";

export type ConversationSelectionMenuPosition = {
  top: number;
  left: number;
  above: boolean;
};

/** DOMRect stores coordinates on the prototype. Object spread drops them. */
export function readSelectionRect(rect: ConversationSelectionRect): ConversationSelectionRect {
  return {
    top: rect.top,
    left: rect.left,
    bottom: rect.bottom,
    right: rect.right,
    width: rect.width,
    height: rect.height,
  };
}

function rectContained(container: HTMLElement, node: Node) {
  return container.contains(node);
}

/**
 * Owning message id for a selection: walks up from the range anchor to the
 * timeline container and returns the first row wrapper's message id, or ""
 * when the anchor never passes through a message row (loading state, error
 * banner, chrome).
 */
export function findConversationSelectionMessageId(
  startContainer: Node,
  container: HTMLElement | null,
): string {
  if (!container) {
    return "";
  }
  let node: Node | null = startContainer;
  while (node && node !== container) {
    const reader = node as { getAttribute?: (name: string) => string | null };
    const value = reader.getAttribute?.(CONVERSATION_SELECTION_MESSAGE_ATTRIBUTE);
    const messageId = typeof value === "string" ? value.trim() : "";
    if (messageId) {
      return messageId;
    }
    node = node.parentElement ?? node.parentNode;
  }
  return "";
}

/**
 * Snapshot of the current selection: non-empty plain text plus the union
 * rect, only when the whole selection lives inside the timeline container.
 * Returns null when the selection is empty, collapsed, or partially (or
 * fully) outside the timeline — e.g. a composer textarea selection.
 */
export function extractConversationSelectionSnapshot(
  selection: ConversationSelectionLike | null,
  container: HTMLElement | null,
): ConversationSelectionSnapshot | null {
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed || !container) {
    return null;
  }
  const text = selection.toString().replace(/\r\n/g, "\n").trim();
  if (!text) {
    return null;
  }
  for (let index = 0; index < selection.rangeCount; index += 1) {
    const range = selection.getRangeAt(index);
    if (!rectContained(container, range.startContainer) || !rectContained(container, range.endContainer)) {
      return null;
    }
  }
  const anchorRange = selection.getRangeAt(0);
  let union: ConversationSelectionRect | null = null;
  for (let index = 0; index < selection.rangeCount; index += 1) {
    const range = selection.getRangeAt(index);
    const rect = readSelectionRect(range.getBoundingClientRect());
    if (rect.width === 0 && rect.height === 0) {
      continue;
    }
    union = union
      ? {
        top: Math.min(union.top, rect.top),
        left: Math.min(union.left, rect.left),
        bottom: Math.max(union.bottom, rect.bottom),
        right: Math.max(union.right, rect.right),
        width: Math.max(union.right, rect.right) - Math.min(union.left, rect.left),
        height: Math.max(union.bottom, rect.bottom) - Math.min(union.top, rect.top),
      }
      : rect;
  }
  if (!union) {
    // Degenerate geometry (no painted rects): nothing to anchor a menu to.
    return null;
  }
  return {
    text,
    rect: union,
    sourceMessageId: findConversationSelectionMessageId(anchorRange.startContainer, container),
  };
}

/**
 * Viewport anchor for a fixed menu. The menu is centered on the selection
 * and flipped above it (translateY(-100%)). It drops below when the top
 * edge has no room, and stays inside the viewport.
 */
export function resolveSelectionQuoteMenuPosition(
  selectionRect: ConversationSelectionRect,
  viewport: { width: number; height: number },
  menuSize?: { width: number; height: number },
): ConversationSelectionMenuPosition {
  return resolveSelectionToolbarPosition(selectionRect, viewport, menuSize);
}

/**
 * Quote text: every selected line gets a markdown `> ` prefix (blank lines
 * become `>`), appended to the current draft after a blank line so the
 * quote lands as its own block ready for a reply below it.
 */
export function buildQuotedDraftText(existingDraft: string, selectedText: string): string {
  const trimmedSelected = String(selectedText ?? "").replace(/\r\n/g, "\n").trim();
  if (!trimmedSelected) {
    return String(existingDraft ?? "");
  }
  const quote = trimmedSelected
    .split("\n")
    .map((line) => (line ? `> ${line}` : ">"))
    .join("\n");
  if (!quote) {
    return String(existingDraft ?? "");
  }
  const existing = String(existingDraft ?? "");
  if (!existing.trim()) {
    return quote;
  }
  return `${existing.replace(/\s+$/, "")}\n\n${quote}`;
}
