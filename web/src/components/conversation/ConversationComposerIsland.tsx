/**
 * Composer island: owns the draft subscription and the composer render tree.
 *
 * Why this exists
 * ---------------
 * The draft used to travel as a `composerValue` prop into `ConversationView`.
 * One keystroke therefore re-rendered a 1873-line component and re-ran every
 * one of its thirty-odd `useMemo`s (row projections, virtualizer inputs,
 * markdown maps) before the character appeared.
 *
 * The island inverts that: the parent no longer receives the draft at all, so
 * typing cannot invalidate it. The island subscribes to `composerDraftStore`
 * itself, and only this subtree re-renders per keystroke.
 *
 * The two outputs the timeline still needs — the submit callback and the
 * guidance label — are reported upward through `onOutputsChange`. They change
 * rarely, so the parent stays quiet while the user types.
 */

import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
} from "react";

import type { ComposerDraftStore } from "./composerDraftStore";
import { useConversationComposer } from "./useConversationComposer";

/** Everything the composer hook needs, minus the draft it now reads itself. */
export type ConversationComposerIslandProps = Omit<
  Parameters<typeof useConversationComposer>[0],
  "composerValue" | "onComposerChange"
> & {
  draftStore: ComposerDraftStore;
  /** Mirrors the draft upward for submit/queue logic that lives outside. */
  onComposerChange?: (value: string) => void;
  /** Timeline-facing outputs; called only when one of them actually changes. */
  onOutputsChange?: (outputs: ConversationComposerIslandOutputs) => void;
};

/** Element-wise compare: a rebuilt array with the same starters is not a change. */
function sameStarterList(
  previous: ConversationComposerIslandOutputs["starters"],
  next: ConversationComposerIslandOutputs["starters"],
): boolean {
  if (previous === next) {
    return true;
  }
  if (!previous || !next || previous.length !== next.length) {
    return false;
  }
  for (let index = 0; index < previous.length; index += 1) {
    if (previous[index] !== next[index]) {
      return false;
    }
  }
  return true;
}

export type ConversationComposerIslandOutputs = {
  handleSendAndFollowLatest: () => void;
  resolvedSafeGuidanceLabel: string;
  starters: ReturnType<typeof useConversationComposer>["composerStarters"];
  activateStarter: ReturnType<typeof useConversationComposer>["handleStarterCardActivate"];
};

function ConversationComposerIslandImpl({
  draftStore,
  onComposerChange,
  onOutputsChange,
  ...composerProps
}: ConversationComposerIslandProps) {
  const draft = useSyncExternalStore(
    draftStore.subscribe,
    draftStore.getSnapshot,
    draftStore.getSnapshot,
  );

  // The store is the keystroke's source of truth (it renders immediately);
  // the callback keeps the outer submit/queue state in step.
  //
  // The outer callback is read through a ref on purpose. Taking it as a
  // dependency made this callback new whenever the host re-created it, which
  // rebuilt the whole hook surface below and looped renders through
  // `onOutputsChange`. A ref pins this identity to the store alone.
  const onComposerChangeRef = useRef(onComposerChange);
  onComposerChangeRef.current = onComposerChange;
  const composerInputRef = composerProps.composerInputRef;
  // Typing must never force a synchronous layout: writing `height: auto` and
  // then reading `scrollHeight` reflows the whole document, and a long
  // transcript pays that on every keystroke (twice: here and in the effect
  // below, which re-runs because it depends on `draft`). One animation frame
  // per burst keeps it to at most one measurement, and an IME composition
  // session skips measurement entirely until the text actually commits.
  const autosizeFrameRef = useRef<number | null>(null);
  const composingRef = useRef(false);
  const lastTypedDraftRef = useRef("");
  const scheduleAutosize = useCallback(
    (element: HTMLTextAreaElement | null | undefined) => {
      if (!element || composingRef.current) {
        return;
      }
      if (autosizeFrameRef.current !== null) {
        return;
      }
      autosizeFrameRef.current = window.requestAnimationFrame(() => {
        autosizeFrameRef.current = null;
        if (composingRef.current || !element.isConnected) {
          return;
        }
        element.style.height = "auto";
        element.style.height = `${element.scrollHeight}px`;
      });
    },
    [],
  );
  const handleComposerChange = useCallback(
    (next: string) => {
      draftStore.set(next);
      onComposerChangeRef.current?.(next);
      lastTypedDraftRef.current = next;
      scheduleAutosize(composerInputRef?.current);
    },
    [composerInputRef, draftStore, scheduleAutosize],
  );

  const {
    composerSurface,
    composerStarters,
    handleStarterCardActivate,
    handleSendAndFollowLatest,
    resolvedSafeGuidanceLabel,
  } = useConversationComposer({
    ...composerProps,
    composerValue: draft,
    onComposerChange: handleComposerChange,
  });

  // Stable by construction upstream (the hook memoises starters), so this only
  // fires when a timeline-facing value really changes.
  const outputs = useMemo<ConversationComposerIslandOutputs>(
    () => ({
      handleSendAndFollowLatest,
      resolvedSafeGuidanceLabel,
      starters: composerStarters,
      activateStarter: handleStarterCardActivate,
    }),
    [
      handleSendAndFollowLatest,
      resolvedSafeGuidanceLabel,
      composerStarters,
      handleStarterCardActivate,
    ],
  );

  // Same reason as above: the host may hand a fresh reporter every render, and
  // depending on it would push a new outputs object straight back into the host.
  //
  // The field-wise guard is the second half of that: an unstable prop upstream
  // can still rebuild this object, and reporting it unconditionally set host
  // state, re-rendered the island and rebuilt the object again. Comparing the
  // fields keeps a rebuild with identical contents from reaching the host.
  const onOutputsChangeRef = useRef(onOutputsChange);
  onOutputsChangeRef.current = onOutputsChange;
  const lastReportedOutputsRef = useRef<ConversationComposerIslandOutputs | null>(null);
  useEffect(() => {
    const previous = lastReportedOutputsRef.current;
    if (
      previous
      && previous.handleSendAndFollowLatest === outputs.handleSendAndFollowLatest
      && previous.resolvedSafeGuidanceLabel === outputs.resolvedSafeGuidanceLabel
      && previous.activateStarter === outputs.activateStarter
      && sameStarterList(previous.starters, outputs.starters)
    ) {
      return;
    }
    lastReportedOutputsRef.current = outputs;
    onOutputsChangeRef.current?.(outputs);
  }, [outputs]);

  // An IME session owns the text until it commits; measuring mid-composition
  // would reflow on every pinyin keystroke and can move the candidate window.
  useEffect(() => {
    const element = composerInputRef?.current;
    if (!element) {
      return undefined;
    }
    const handleCompositionStart = () => {
      composingRef.current = true;
    };
    const handleCompositionEnd = () => {
      composingRef.current = false;
      scheduleAutosize(element);
    };
    element.addEventListener("compositionstart", handleCompositionStart);
    element.addEventListener("compositionend", handleCompositionEnd);
    return () => {
      element.removeEventListener("compositionstart", handleCompositionStart);
      element.removeEventListener("compositionend", handleCompositionEnd);
      composingRef.current = false;
      if (autosizeFrameRef.current !== null) {
        window.cancelAnimationFrame(autosizeFrameRef.current);
        autosizeFrameRef.current = null;
      }
    };
  }, [composerInputRef, scheduleAutosize]);

  // Typing autosizes through `scheduleAutosize`; this effect only covers a
  // draft arriving from outside (restored draft, queued message, cleared after
  // submit) and the composer switching variant. Skipping the value the keystroke
  // just queued keeps one character from requesting a second measurement.
  const showComposer = composerProps.showComposer;
  const composerVariant = composerProps.composerVariant;
  const composerDisabled = composerProps.composerDisabled;
  useEffect(() => {
    if (!showComposer) {
      return;
    }
    if (draft === lastTypedDraftRef.current) {
      return;
    }
    scheduleAutosize(composerInputRef?.current);
  }, [composerDisabled, composerInputRef, composerVariant, draft, scheduleAutosize, showComposer]);

  return <>{composerSurface}</>;
}

/**
 * The host re-creates a handful of props on every render (queue/attachment/
 * reference arrays, the i18n lookup, the scroll helper). Plain `memo` compared
 * those by identity, so it never matched: the island re-rendered, rebuilt its
 * outputs, pushed them back into the host, and the host rendered again — a
 * synchronous loop that froze the event loop.
 *
 * Arrays are therefore compared by content and the two callbacks are ignored;
 * everything that actually decides what the composer shows (draft store,
 * disabled/pending flags, labels, lang) still compares by identity.
 */
function areIslandPropsEqual(
  previous: ConversationComposerIslandProps,
  next: ConversationComposerIslandProps,
): boolean {
  const previousRecord = previous as Record<string, unknown>;
  const nextRecord = next as Record<string, unknown>;
  const keys = new Set([...Object.keys(previousRecord), ...Object.keys(nextRecord)]);
  for (const key of keys) {
    // `t` follows `lang`, which is compared; `scrollTimelineToBottom` is read
    // through a ref by the consumer and never decides composer paint.
    if (key === "t" || key === "scrollTimelineToBottom") {
      continue;
    }
    const left = previousRecord[key];
    const right = nextRecord[key];
    if (left === right) {
      continue;
    }
    if (Array.isArray(left) && Array.isArray(right) && sameArrayShallow(left, right)) {
      continue;
    }
    return false;
  }
  return true;
}

function sameArrayShallow(left: readonly unknown[], right: readonly unknown[]): boolean {
  if (left.length !== right.length) {
    return false;
  }
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) {
      return false;
    }
  }
  return true;
}

export const ConversationComposerIsland = memo(
  ConversationComposerIslandImpl,
  areIslandPropsEqual,
);
