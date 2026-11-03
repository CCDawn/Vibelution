import type { MouseEvent, TransitionEvent } from "react";
import { useEffect, useRef, useState } from "react";

const PROCESS_DISCLOSURE_DURATION_MS = 200;

export type ConversationProcessUserToggle = (
  summary: HTMLElement,
  nextExpanded: boolean,
) => (() => void) | void;

export function useConversationProcessDisclosureMotion(
  running: boolean,
  onUserToggle?: ConversationProcessUserToggle,
  controlledExpanded?: boolean,
  onExpandedChange?: (expanded: boolean) => void,
) {
  const [mounted, setMounted] = useState(controlledExpanded ?? running);
  const [expanded, setExpanded] = useState(controlledExpanded ?? running);
  const frameRef = useRef<number | null>(null);
  const settleTimerRef = useRef<number | null>(null);
  const settleScrollRef = useRef<(() => void) | null>(null);
  const userExpandedRef = useRef<boolean | undefined>(undefined);

  function clearScheduledTransition() {
    if (frameRef.current !== null) {
      window.cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
    if (settleTimerRef.current !== null) {
      window.clearTimeout(settleTimerRef.current);
      settleTimerRef.current = null;
    }
  }

  function finishTransition(nextExpanded: boolean) {
    clearScheduledTransition();
    if (!nextExpanded) {
      setMounted(false);
    }
    settleScrollRef.current?.();
    settleScrollRef.current = null;
  }

  function scheduleTransitionFinish(nextExpanded: boolean) {
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    settleTimerRef.current = window.setTimeout(
      () => finishTransition(nextExpanded),
      reducedMotion ? 0 : PROCESS_DISCLOSURE_DURATION_MS + 80,
    );
  }

  function handleSummaryClick(event: MouseEvent<HTMLElement>) {
    event.preventDefault();
    const nextExpanded = !expanded;
    userExpandedRef.current = nextExpanded;
    onExpandedChange?.(nextExpanded);
    clearScheduledTransition();
    settleScrollRef.current?.();
    settleScrollRef.current = onUserToggle?.(event.currentTarget, nextExpanded) ?? null;

    if (nextExpanded) {
      setMounted(true);
      frameRef.current = window.requestAnimationFrame(() => {
        frameRef.current = null;
        setExpanded(true);
        scheduleTransitionFinish(true);
      });
      return;
    }

    setExpanded(false);
    scheduleTransitionFinish(false);
  }

  function handleContentTransitionEnd(event: TransitionEvent<HTMLDivElement>) {
    if (
      event.target === event.currentTarget
      && event.propertyName === "grid-template-rows"
    ) {
      finishTransition(expanded);
    }
  }

  useEffect(() => () => {
    clearScheduledTransition();
    settleScrollRef.current?.();
  }, []);

  useEffect(() => {
    const nextExpanded = controlledExpanded ?? userExpandedRef.current ?? running;
    if (nextExpanded === expanded) {
      return;
    }
    clearScheduledTransition();
    settleScrollRef.current?.();
    settleScrollRef.current = null;
    if (nextExpanded) {
      setMounted(true);
      frameRef.current = window.requestAnimationFrame(() => {
        frameRef.current = null;
        setExpanded(true);
        scheduleTransitionFinish(true);
      });
      return;
    }
    if (expanded) {
      setExpanded(false);
      scheduleTransitionFinish(false);
    }
  }, [controlledExpanded, running]);

  return {
    expanded,
    handleContentTransitionEnd,
    handleSummaryClick,
    mounted,
  };
}
