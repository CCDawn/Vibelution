import { useCallback, useEffect, useRef, useState } from "react";
import type { LauncherAssistantSubmission } from "./launcherAssistantModel";
import { launcherControlOrigin, launcherControlSubmission, launcherControlToolWatermark, type LauncherControlContext, type LauncherControlIntent } from "./launcherControlContinuation";

export type LauncherControlContinuation = {
  capture: () => LauncherControlIntent | null;
  complete: (intent: LauncherControlIntent | null, canContinue?: () => boolean) => void;
  cancel: () => void;
};

/** Explicit successful operator actions enter the existing composer ACK/readback flow once. */
export function useLauncherControlContinuation(options: {
  context: LauncherControlContext;
  readCurrent: () => LauncherControlContext;
  submit: (submission: LauncherAssistantSubmission) => Promise<boolean>;
  onReady?: (control: LauncherControlContinuation | null) => void;
}) {
  const latest = useRef(options);
  latest.current = options;
  const [pending, setPending] = useState<{ intent: LauncherControlIntent; canContinue?: () => boolean } | null>(null);
  const completed = useRef(new WeakSet<LauncherControlIntent>());
  const generation = useRef(0);
  const capturedGenerations = useRef(new WeakMap<LauncherControlIntent, number>());
  useEffect(() => () => { generation.current += 1; }, []);
  const cancel = useCallback(() => { generation.current += 1; setPending(null); }, []);
  const capture = useCallback((): LauncherControlIntent | null => {
    cancel();
    const context = latest.current.readCurrent();
    const origin = launcherControlOrigin(context);
    if (!origin) return null;
    const intent = { origin, requestId: crypto.randomUUID(), ...launcherControlToolWatermark(context) };
    capturedGenerations.current.set(intent, generation.current);
    return intent;
  }, [cancel]);
  const complete = useCallback((intent: LauncherControlIntent | null, canContinue?: () => boolean) => {
    if (!intent || completed.current.has(intent) || capturedGenerations.current.get(intent) !== generation.current) return;
    completed.current.add(intent);
    // Completion belongs to the click-time identity, even if the RPC outlives navigation.
    if (canContinue && !canContinue() || launcherControlSubmission(intent, latest.current.readCurrent()).state === "stale") return;
    setPending({ intent, canContinue });
  }, []);
  useEffect(() => {
    options.onReady?.({ capture, complete, cancel });
    return () => options.onReady?.(null);
  }, [options.onReady, capture, complete, cancel]);
  useEffect(() => {
    if (!pending) return;
    if (pending.canContinue && !pending.canContinue()) { setPending(null); return; }
    const next = launcherControlSubmission(pending.intent, latest.current.readCurrent());
    if (next.state === "waiting") return;
    setPending(null);
    if (next.state === "ready") {
      // `submit` returning true means attempted, never proof of acceptance.
      // Unknown receipts remain owned by the original composer requestId.
      void latest.current.submit(next.submission);
    }
  }, [pending, options.context]);
  useEffect(() => {
    if (!pending) return;
    const timer = setTimeout(() => setPending(previous => previous === pending ? null : previous), 60_000);
    return () => clearTimeout(timer);
  }, [pending]);
  return { capture, complete, cancel };
}
