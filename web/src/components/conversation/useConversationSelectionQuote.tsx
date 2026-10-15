import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";

import type { SessionReferenceAttachment } from "../../api/types";
import type { Language } from "../../i18n/dictionaryTypes";
import { buildMessageReferencePayload } from "../../routes/chat/chatComposerSubmitModel";
import { ConversationSelectionQuoteMenu } from "./ConversationSelectionQuoteMenu";
import {
  buildQuotedDraftText,
  extractConversationSelectionSnapshot,
  type ConversationSelectionRect,
} from "./conversationTextSelection";

export type UseConversationSelectionQuoteInput = {
  sessionId: string;
  lang: Language;
  composerValue: string;
  timelineRef: RefObject<HTMLDivElement | null>;
  composerInputRef: RefObject<HTMLTextAreaElement | null>;
  onComposerChange: (value: string) => void;
  onOpenSideChat?: (draft: string, send: boolean) => void;
  onAddComposerReference?: (reference: SessionReferenceAttachment) => void;
  copyText: (text: string) => Promise<void>;
};

export type UseConversationSelectionQuoteResult = {
  timelineAreaRef: RefObject<HTMLDivElement | null>;
  menu: ReactNode;
};

/**
 * Timeline text-selection quote menu, extracted from ConversationView with
 * the same lifecycle: document selectionchange/mouseup/keyup, rAF-coalesced,
 * open only for a non-empty selection fully inside the timeline.
 */
export function useConversationSelectionQuote({
  sessionId,
  lang,
  composerValue,
  timelineRef,
  composerInputRef,
  onComposerChange,
  onOpenSideChat,
  onAddComposerReference,
  copyText,
}: UseConversationSelectionQuoteInput): UseConversationSelectionQuoteResult {
  // Text-selection quote menu (zai-org/ZCode useTextSelection pattern,
  // Apache-2.0): snapshot of the selected text. The menu centers itself on
  // that viewport rect.
  const timelineAreaRef = useRef<HTMLDivElement | null>(null);
  const selectionQuoteDismissedTextRef = useRef<string | null>(null);
  const selectionQuoteTextRef = useRef("");
  const [selectionQuoteMenu, setSelectionQuoteMenu] = useState<{
    text: string;
    rect: ConversationSelectionRect;
    sourceMessageId: string;
  } | null>(null);
  // Selection quote lifecycle: document-level selectionchange + mouseup/keyup,
  // rAF-coalesced. The menu opens only for a non-empty selection fully inside
  // the timeline (never the composer), and closes on collapse, timeline
  // scroll, outside mousedown, or Escape (Escape also arms a dismiss guard so
  // keyup cannot immediately re-open the same selection).
  useEffect(() => {
    let frame: number | null = null;
    const evaluateSelection = () => {
      frame = null;
      const timelineArea = timelineAreaRef.current;
      const snapshot = extractConversationSelectionSnapshot(window.getSelection(), timelineRef.current);
      if (!snapshot || !timelineArea) {
        selectionQuoteDismissedTextRef.current = null;
        selectionQuoteTextRef.current = "";
        setSelectionQuoteMenu(null);
        return;
      }
      selectionQuoteTextRef.current = snapshot.text;
      if (selectionQuoteDismissedTextRef.current !== null) {
        // Escape dismissed this selection; a genuinely different selection
        // (new text) re-arms the menu, the same one stays dismissed.
        if (snapshot.text === selectionQuoteDismissedTextRef.current) {
          return;
        }
        selectionQuoteDismissedTextRef.current = null;
      }
      setSelectionQuoteMenu({
        text: snapshot.text,
        sourceMessageId: snapshot.sourceMessageId,
        rect: snapshot.rect,
      });
    };
    const scheduleEvaluation = () => {
      if (frame !== null) {
        return;
      }
      frame = requestAnimationFrame(evaluateSelection);
    };
    const handleDocumentMouseDown = (event: MouseEvent) => {
      // Mousedown inside the menu belongs to an action click, not a dismissal.
      if (event.target instanceof Element && event.target.closest("[data-conversation-selection-menu]")) {
        return;
      }
      selectionQuoteDismissedTextRef.current = null;
      setSelectionQuoteMenu(null);
    };
    const handleDocumentKeydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        selectionQuoteDismissedTextRef.current = selectionQuoteTextRef.current;
        setSelectionQuoteMenu(null);
      }
    };
    const handleTimelineScroll = () => {
      setSelectionQuoteMenu(null);
    };
    const timeline = timelineRef.current;
    document.addEventListener("selectionchange", scheduleEvaluation);
    document.addEventListener("mouseup", scheduleEvaluation);
    document.addEventListener("keyup", scheduleEvaluation);
    document.addEventListener("keydown", handleDocumentKeydown);
    document.addEventListener("mousedown", handleDocumentMouseDown);
    timeline?.addEventListener("scroll", handleTimelineScroll);
    return () => {
      if (frame !== null) {
        cancelAnimationFrame(frame);
      }
      document.removeEventListener("selectionchange", scheduleEvaluation);
      document.removeEventListener("mouseup", scheduleEvaluation);
      document.removeEventListener("keyup", scheduleEvaluation);
      document.removeEventListener("keydown", handleDocumentKeydown);
      document.removeEventListener("mousedown", handleDocumentMouseDown);
      timeline?.removeEventListener("scroll", handleTimelineScroll);
    };
    // The ref object is stable for the view lifetime, so this still binds once.
  }, [timelineRef]);
  const handleSelectionSideChat = useCallback(() => {
    if (!selectionQuoteMenu || !onOpenSideChat) {
      return;
    }
    onOpenSideChat(buildQuotedDraftText("", selectionQuoteMenu.text), false);
    setSelectionQuoteMenu(null);
    selectionQuoteDismissedTextRef.current = null;
    window.getSelection()?.removeAllRanges();
  }, [onOpenSideChat, selectionQuoteMenu]);
  const handleSelectionQuoteToComposer = useCallback(() => {
    if (!selectionQuoteMenu) {
      return;
    }
    onComposerChange(buildQuotedDraftText(composerValue, selectionQuoteMenu.text));
    setSelectionQuoteMenu(null);
    selectionQuoteDismissedTextRef.current = null;
    // Park focus and the caret at the end of the appended quote.
    requestAnimationFrame(() => {
      const input = composerInputRef.current;
      if (!input) {
        return;
      }
      input.focus();
      const end = input.value.length;
      input.setSelectionRange(end, end);
    });
  }, [composerInputRef, composerValue, onComposerChange, selectionQuoteMenu]);
  const handleSelectionCopy = useCallback(() => {
    if (!selectionQuoteMenu) {
      return;
    }
    void copyText(selectionQuoteMenu.text);
    setSelectionQuoteMenu(null);
  }, [copyText, selectionQuoteMenu]);
  /**
   * Structured quote: attaches the selection as a `message` reference chip
   * (contract: referenceId `message:{sourceMessageId}` + source session/
   * message ids + quote + single-line title). Only offered when the selection
   * anchor lives inside a message row.
   */
  const handleSelectionReferenceToComposer = useCallback(() => {
    if (!selectionQuoteMenu?.sourceMessageId || !onAddComposerReference) {
      return;
    }
    onAddComposerReference(buildMessageReferencePayload({
      sourceSessionId: sessionId,
      sourceMessageId: selectionQuoteMenu.sourceMessageId,
      quote: selectionQuoteMenu.text,
    }));
    setSelectionQuoteMenu(null);
    selectionQuoteDismissedTextRef.current = null;
  }, [onAddComposerReference, selectionQuoteMenu, sessionId]);

  const menu = selectionQuoteMenu ? (
    <ConversationSelectionQuoteMenu
      selectionRect={selectionQuoteMenu.rect}
      quoteLabel={lang === "zh" ? "引用到输入框" : "Quote to composer"}
      referenceLabel={lang === "zh" ? "作为引用" : "As reference"}
      copyLabel={lang === "zh" ? "复制" : "Copy"}
      sideLabel={lang === "zh" ? "辅助对话" : "Side chat"}
      onSideChat={onOpenSideChat ? handleSelectionSideChat : undefined}
      onQuote={handleSelectionQuoteToComposer}
      onReference={selectionQuoteMenu.sourceMessageId && onAddComposerReference
        ? handleSelectionReferenceToComposer
        : undefined}
      onCopy={handleSelectionCopy}
    />
  ) : null;

  return { timelineAreaRef, menu };
}
