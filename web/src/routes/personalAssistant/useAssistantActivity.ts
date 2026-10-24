import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { fetchSessionDetail } from "../../api/chat";
import { fetchPetActivity } from "../../api/pet";
import { fetchPersonalAssistantComputer } from "../../api/personalAssistantComputer";
import { queryKeys } from "../../api/queryKeys";
import type { PersonalAssistant } from "../../api/types/personalAssistant";
import type { PetActivityTone, PetAnimationState } from "../../api/types/petActivity";
import { useShellI18n } from "../../i18n/useShellI18n";
import { petActivityRefetchInterval, petPhaseLabel, petToneLabel } from "../desktopPet/desktopPetModel";
import { PET_PREFERENCES_REFRESH_EVENT } from "../desktopPet/usePetPreferences";
import { personalAssistantSessionMatches } from "./personalAssistantModel";
import { assistantReplyIds, assistantReplyStore } from "./assistantReplyActivity";

// Shared by mounted surfaces and retained across remounts, bounded to native IDs.
const settingsRefreshes = new WeakMap<QueryClient, Set<string>>();

/** Read-only adapter. Native Session transcript, admission and SSE are unchanged. */
export function useAssistantActivity({ enabled, assistant, reading, showCompletion = true, idleMessage = "" }: {
  enabled: boolean; assistant?: PersonalAssistant | null; reading: boolean; showCompletion?: boolean; idleMessage?: string;
}) {
  const { lang } = useShellI18n();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: queryKeys.petActivity(), queryFn: fetchPetActivity, enabled,
    refetchInterval: q => petActivityRefetchInterval(q.state.data), refetchIntervalInBackground: false, retry: false });
  const sessionId = assistant?.directSessionId ?? "";
  const ownActivity = query.data?.sessions.find(row => row.sessionId === sessionId && row.agentId === assistant?.agentId);
  const repliesActive = reading || !query.data || query.isError
    || Boolean(ownActivity);
  const computer = useQuery({ queryKey: queryKeys.personalAssistantComputer(), queryFn: ({ signal }) => fetchPersonalAssistantComputer({ signal }),
    enabled: enabled && Boolean(assistant),
    refetchInterval: q => reading || !q.state.data || q.state.data.grantId ? 1000 : 15_000,
    refetchIntervalInBackground: false, retry: false });
  const replies = useQuery({ queryKey: queryKeys.personalAssistantReplies(assistant?.agentId ?? "", sessionId),
    queryFn: ({ signal }) => fetchSessionDetail(sessionId, { signal, transcriptScope: "window", messageLimit: 12, includeSecondary: false }),
    enabled: enabled && Boolean(assistant),
    refetchInterval: q => repliesActive || q.state.status === "error" ? 3000 : 30_000,
    refetchIntervalInBackground: false, retry: false });
  // Activity is only a refresh hint. Native Session remains the message authority;
  // the bounded fallback also catches replies absent from the activity projection.
  const activityHint = JSON.stringify([ownActivity?.updatedAt, ownActivity?.tone, ownActivity?.phase]);
  const identity = `${assistant?.agentId ?? ""}:${sessionId}`;
  useEffect(() => {
    if (!enabled || !assistant || replies.isError || !personalAssistantSessionMatches(assistant, replies.data)) return;
    const seen = settingsRefreshes.get(queryClient) ?? new Set<string>();
    settingsRefreshes.set(queryClient, seen);
    let refreshAssistant = false;
    let refreshConfig = false;
    for (const message of replies.data!.messages ?? []) {
      if (message.role !== "assistant" || !message.turnId) continue;
      for (const item of message.turnItems ?? []) {
        if (item.type !== "tool_call" || !["personal_assistant_action_tool", "personal_assistant_manage_tool"].includes(item.toolName)
          || item.status !== "completed" || !item.callId) continue;
        // Only the native call's own arguments are a hint. Tool output/text is never interpreted.
        let action: unknown;
        try { action = (JSON.parse(item.input ?? "null") as { action?: unknown } | null)?.action; } catch { continue; }
        const assistantAction = ["assistant_settings_update", "assistant_model_set", "dialogue_settings_update"].includes(String(action));
        const configAction = ["settings_update", "config_update"].includes(String(action));
        if (!assistantAction && !configAction) continue;
        const id = `${identity}:${message.turnId}:${item.callId}`;
        if (seen.has(id)) continue;
        seen.add(id);
        while (seen.size > 128) seen.delete(seen.values().next().value!);
        refreshAssistant ||= assistantAction;
        refreshConfig ||= configAction;
      }
    }
    if (refreshAssistant) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.personalAssistant(), exact: true });
      void queryClient.invalidateQueries({ queryKey: ["personal-assistant", "settings"], exact: true });
      void queryClient.invalidateQueries({ queryKey: queryKeys.virtualHumanDialogueSettings(assistant.agentId), exact: true });
      window.dispatchEvent(new Event(PET_PREFERENCES_REFRESH_EVENT));
    }
    if (refreshConfig) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.configPublic(), exact: true });
      void queryClient.invalidateQueries({ queryKey: queryKeys.configWorkspace(), exact: true });
    }
  }, [enabled, assistant, identity, replies.data, replies.isError, queryClient]);
  const previousHint = useRef({ identity, hint: activityHint });
  const { refetch: refreshReplies } = replies;
  useEffect(() => {
    const previous = previousHint.current;
    previousHint.current = { identity, hint: activityHint };
    if (enabled && assistant && !reading && ownActivity?.tone !== "running"
      && previous.identity === identity && previous.hint !== activityHint) {
      void refreshReplies();
    }
  }, [enabled, assistant, identity, activityHint, reading, ownActivity?.tone, refreshReplies]);
  const store = useMemo(() => assistantReplyStore(`${assistant?.agentId ?? ""}:${sessionId}`), [assistant?.agentId, sessionId]);
  const replyState = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  const [clock, setClock] = useState(0);
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
    const now = Date.now();
    const until = Math.min(...[replyState.pulseUntil, completionUntil].filter(value => value > now));
    if (!Number.isFinite(until)) return;
    const timer = window.setTimeout(() => setClock(value => value + 1), until - now + 1);
    return () => window.clearTimeout(timer);
  }, [replyState.pulseUntil, completionUntil, clock]);
  const unavailable = query.isError || (assistant && (replies.isError
    || (replies.data && !personalAssistantSessionMatches(assistant, replies.data))));
  const unreadCount = assistant ? replyState.unread.length : 0;
  const attention = base?.aggregateTone === "approval" || base?.aggregateTone === "error";
  const messagePulse = unreadCount > 0 && replyState.pulseUntil > Date.now();
  let tone: PetActivityTone = base?.aggregateTone ?? "idle";
  let animationState: PetAnimationState = base?.animationState ?? "idle";
  if (unavailable || !enabled) { tone = "idle"; animationState = "idle"; }
  else if (!attention && unreadCount > 0) { tone = "completed"; animationState = messagePulse && !reduced ? "celebrating" : base?.aggregateTone === "running" ? base.animationState : "idle"; }
  else if (animationState === "celebrating" && (!showCompletion || reduced || completionUntil <= Date.now())) animationState = "idle";
  if (tone === "completed" && !showCompletion && !unreadCount) tone = "idle";
  const phaseLabel = base?.sessions.find(session => session.tone === base.aggregateTone)?.phase;
  let statusText = unavailable ? (lang === "zh" ? "暂时无法读取平台状态" : "Platform status is unavailable")
    : !base ? (lang === "zh" ? "正在读取平台状态…" : "Reading platform status…")
      : !attention && unreadCount > 0 ? (lang === "zh" ? `有 ${unreadCount} 条新消息` : `${unreadCount} new messages`)
        : tone === "running" && phaseLabel ? petPhaseLabel(phaseLabel, lang)
          : tone === "idle" && idleMessage.trim() ? idleMessage : petToneLabel(tone, lang);
  if (enabled && !unavailable && !attention && !computer.isError && computer.data?.grantId) {
    const state = computer.data;
    if (state.status === "working") { tone = "running"; animationState = reduced ? "idle" : "tooling"; statusText = lang === "zh" ? "正在操作已授权窗口" : "Working in the authorized window"; }
    else if (state.status === "waiting_confirmation") { tone = "approval"; animationState = "waiting"; statusText = lang === "zh" ? "电脑操作等待你确认" : "Computer action needs your confirmation"; }
    else if (state.status === "paused" || state.status === "manual") { tone = "idle"; animationState = "idle"; statusText = lang === "zh" ? state.status === "manual" ? "你正在操作电脑" : "电脑操作已暂停" : "Computer control is paused"; }
    else if (state.status === "error") { tone = "error"; animationState = "alert"; statusText = state.message; }
  }
  return { query, tone, animationState, statusText, unreadCount, unavailable: Boolean(unavailable), markRead: store.markRead };
}
