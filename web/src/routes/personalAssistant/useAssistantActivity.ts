import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchSessionDetail } from "../../api/chat";
import { fetchPetActivity } from "../../api/pet";
import { queryKeys } from "../../api/queryKeys";
import type { PersonalAssistant } from "../../api/types/personalAssistant";
import type { PetActivityTone, PetAnimationState } from "../../api/types/petActivity";
import { useShellI18n } from "../../i18n/useShellI18n";
import { petActivityRefetchInterval, petPhaseLabel, petToneLabel } from "../desktopPet/desktopPetModel";
import { personalAssistantSessionMatches } from "./personalAssistantModel";
import { assistantReplyIds, assistantReplyStore } from "./assistantReplyActivity";

/** Read-only adapter. Native Session transcript, admission and SSE are unchanged. */
export function useAssistantActivity({ enabled, assistant, reading, showCompletion = true, idleMessage = "" }: {
  enabled: boolean; assistant?: PersonalAssistant | null; reading: boolean; showCompletion?: boolean; idleMessage?: string;
}) {
  const { lang } = useShellI18n();
  const query = useQuery({ queryKey: queryKeys.petActivity(), queryFn: fetchPetActivity, enabled,
    refetchInterval: q => petActivityRefetchInterval(q.state.data), refetchIntervalInBackground: false, retry: false });
  const sessionId = assistant?.directSessionId ?? "";
  const replies = useQuery({ queryKey: queryKeys.personalAssistantReplies(assistant?.agentId ?? "", sessionId),
    queryFn: ({ signal }) => fetchSessionDetail(sessionId, { signal, transcriptScope: "window", messageLimit: 12, includeSecondary: false }),
    enabled: enabled && Boolean(assistant), refetchInterval: 3000, refetchIntervalInBackground: false, retry: false });
  const store = useMemo(() => assistantReplyStore(`${assistant?.agentId ?? ""}:${sessionId}`), [assistant?.agentId, sessionId]);
  const replyState = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  const [clock, setClock] = useState(Date.now);
  const [completionUntil, setCompletionUntil] = useState(0);
  const [reduced, setReduced] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReduced(media.matches);
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);
  useEffect(() => {
    if (assistant && replies.data && !replies.isError && personalAssistantSessionMatches(assistant, replies.data)) {
      store.observe(assistantReplyIds(replies.data), reading && document.visibilityState === "visible" && document.hasFocus());
    }
  }, [assistant, replies.data, replies.isError, reading, store]);
  useEffect(() => {
    if (!reading) return;
    const acknowledge = () => { if (document.visibilityState === "visible" && document.hasFocus()) store.markRead(); };
    acknowledge();
    window.addEventListener("focus", acknowledge);
    document.addEventListener("visibilitychange", acknowledge);
    return () => { window.removeEventListener("focus", acknowledge); document.removeEventListener("visibilitychange", acknowledge); };
  }, [reading, store]);
  const base = query.data;
  useEffect(() => {
    setCompletionUntil(base?.animationState === "celebrating" && showCompletion ? Date.now() + 1400 : 0);
  }, [base?.animationState, showCompletion]);
  useEffect(() => {
    const until = Math.min(...[replyState.pulseUntil, completionUntil].filter(value => value > Date.now()));
    setClock(Date.now());
    if (!Number.isFinite(until)) return;
    const timer = window.setTimeout(() => setClock(Date.now()), until - Date.now() + 1);
    return () => window.clearTimeout(timer);
  }, [replyState.pulseUntil, completionUntil]);
  const unavailable = query.isError || (assistant && (replies.isError
    || (replies.data && !personalAssistantSessionMatches(assistant, replies.data))));
  const unreadCount = assistant ? replyState.unread.length : 0;
  const attention = base?.aggregateTone === "approval" || base?.aggregateTone === "error";
  const messagePulse = unreadCount > 0 && replyState.pulseUntil > clock;
  let tone: PetActivityTone = base?.aggregateTone ?? "idle";
  let animationState: PetAnimationState = base?.animationState ?? "idle";
  if (unavailable || !enabled) { tone = "idle"; animationState = "idle"; }
  else if (!attention && unreadCount > 0) { tone = "completed"; animationState = messagePulse && !reduced ? "celebrating" : base?.aggregateTone === "running" ? base.animationState : "idle"; }
  else if (animationState === "celebrating" && (!showCompletion || reduced || completionUntil <= clock)) animationState = "idle";
  if (tone === "completed" && !showCompletion && !unreadCount) tone = "idle";
  const phaseLabel = base?.sessions.find(session => session.tone === base.aggregateTone)?.phase;
  const statusText = unavailable ? (lang === "zh" ? "暂时无法读取平台状态" : "Platform status is unavailable")
    : !base ? (lang === "zh" ? "正在读取平台状态…" : "Reading platform status…")
      : !attention && unreadCount > 0 ? (lang === "zh" ? `有 ${unreadCount} 条新消息` : `${unreadCount} new messages`)
        : tone === "running" && phaseLabel ? petPhaseLabel(phaseLabel, lang)
          : tone === "idle" && idleMessage.trim() ? idleMessage : petToneLabel(tone, lang);
  return { query, tone, animationState, statusText, unreadCount, markRead: store.markRead };
}
