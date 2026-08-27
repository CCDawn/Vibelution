import type {
  VirtualHumanActivity,
  VirtualHumanCompanion,
  VirtualHumanSnapshot,
} from "../../api/types";

export function companionInitials(companion: Pick<VirtualHumanCompanion, "agentCode" | "displayName">): string {
  const code = String(companion.agentCode || "").trim().replace(/[^\p{L}\p{N}]+/gu, "");
  if (code.length >= 2) return code.slice(-2).toUpperCase();
  const name = String(companion.displayName || "").trim().replace(/\s+/g, "");
  return (name.slice(0, 2) || "AI").toUpperCase();
}

export function companionIdentity(companion: VirtualHumanCompanion): string {
  const profile = companion.personaProfile ?? {};
  const expertise = Array.isArray(profile.expertise)
    ? profile.expertise.filter(Boolean).slice(0, 2).join(" · ")
    : "";
  return String(
    profile.identityNotes
    || profile.personality
    || expertise
    || companion.agentCode
    || "独立生活中的虚拟人",
  ).trim();
}

export function companionAbout(companion: VirtualHumanCompanion): string {
  const profile = companion.personaProfile ?? {};
  return String(
    profile.background
    || profile.communicationStyle
    || profile.collaborationPreference
    || "她有自己的日程、心情和记忆，也会在合适的时候主动联系你。",
  ).trim();
}

export function currentLifeActivity(snapshot: VirtualHumanSnapshot): VirtualHumanActivity | null {
  const activities = snapshot.todaySchedule?.activities ?? [];
  const currentId = String(snapshot.state?.currentActivityId || "").trim();
  return (
    activities.find((activity) => activity.activityId === currentId)
    || activities.find((activity) => activity.status === "in_progress")
    || null
  );
}

export function upcomingLifeActivities(snapshot: VirtualHumanSnapshot, limit = 3): VirtualHumanActivity[] {
  return (snapshot.todaySchedule?.activities ?? [])
    .filter((activity) => ["planned", "in_progress"].includes(String(activity.status || "").toLowerCase()))
    .slice(0, Math.max(0, limit));
}

const MOOD_LABELS: Record<string, { zh: string; en: string }> = {
  calm: { zh: "平静", en: "Calm" },
  happy: { zh: "愉快", en: "Happy" },
  curious: { zh: "好奇", en: "Curious" },
  focused: { zh: "专注", en: "Focused" },
  tired: { zh: "有些疲惫", en: "A little tired" },
  sad: { zh: "低落", en: "Low" },
};

export function lifeMoodLabel(snapshot: VirtualHumanSnapshot, lang: "zh" | "en"): string {
  const mood = String(snapshot.state?.mood?.label || "calm").trim().toLowerCase();
  return MOOD_LABELS[mood]?.[lang] || mood || (lang === "zh" ? "平静" : "Calm");
}

export function formatLifeTime(value: string, lang: "zh" | "en"): string {
  const parsed = new Date(value);
  if (!value || Number.isNaN(parsed.getTime())) return "--:--";
  return parsed.toLocaleTimeString(lang === "zh" ? "zh-CN" : "en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function companionSessionRoute(companion: VirtualHumanCompanion, lang: "zh" | "en"): string {
  const search = new URLSearchParams({
    session: companion.directSessionId,
    returnTo: "/companions",
    returnLabel: lang === "zh" ? "人物大厅" : "Companion lobby",
  });
  return `/companions/${encodeURIComponent(companion.agentId)}?${search.toString()}`;
}
