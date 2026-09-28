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
  const world = companion.snapshot.lifeWorld;
  // A draft is not a person fact until the operator confirms it.
  const identity = world?.setupState === "ready" ? world.facts.identities[0] : undefined;
  const affiliation = world?.setupState === "ready" ? world.facts.affiliations[0] : undefined;
  const cityName = String(
    companion.snapshot.binding?.homeLocation?.cityName
    || companion.snapshot.environment?.location?.cityName
    || "",
  ).trim();
  const structuredIdentity = Array.from(new Set([
    cityName,
    String(identity?.roleTitle || identity?.stage || "").trim(),
    String(affiliation?.name || "").trim(),
  ].filter(Boolean)));
  if (structuredIdentity.length >= 2) {
    return structuredIdentity.join(" · ");
  }
  const profile = companion.personaProfile ?? {};
  const personality = String(profile.personality || "").trim();
  const expertise = Array.isArray(profile.expertise) && !isDefaultPersonaExpertise(profile.expertise)
    ? profile.expertise.filter(Boolean).slice(0, 2).join(" · ")
    : "";
  return String(
    (personality && !isDefaultPersonaPersonality(personality) ? personality : "")
    || expertise
    || companion.agentCode
    || "独立生活中的虚拟人",
  ).trim();
}

export function companionAbout(companion: VirtualHumanCompanion): string {
  const profile = companion.personaProfile ?? {};
  const background = String(profile.background || "").trim();
  // Prompt rules are implementation guidance, not a user-facing biography.
  if (background && !isDefaultPersonaBackground(background, companion.displayName || companion.agentId)) return background;
  return "她有自己的日程、心情和记忆，也会在合适的时候主动联系你。";
}

function isDefaultPersonaBackground(value: string, displayName: string): boolean {
  return value === `我是${displayName.trim()}，一个独立存在的虚构人物。我会安排自己的生活、完成活动、形成日记，并在重要经历值得保留时积累长期记忆。`;
}

function isDefaultPersonaExpertise(value: string[]): boolean {
  const defaults = ["独立生活规划", "情绪表达", "长期陪伴"];
  return value.length === defaults.length && value.every((item, index) => item === defaults[index]);
}

function isDefaultPersonaPersonality(value: string): boolean {
  return value === "有自己的判断、情绪和边界；温和但不盲从，会认真经营每天的生活。";
}

const LOCATION_LABELS: Record<string, { zh: string; en: string }> = {
  home: { zh: "在家", en: "At home" },
  house: { zh: "在家", en: "At home" },
  campus: { zh: "在校园", en: "On campus" },
  school: { zh: "在学校", en: "At school" },
  university: { zh: "在大学", en: "At university" },
  office: { zh: "在办公室", en: "At the office" },
  workplace: { zh: "在工作地点", en: "At work" },
  outdoors: { zh: "在户外", en: "Outdoors" },
  park: { zh: "在公园", en: "At the park" },
  cafe: { zh: "在咖啡馆", en: "At a cafe" },
  street: { zh: "在街上", en: "On the street" },
};

export function companionLocationLabel(value: string | null | undefined, lang: "zh" | "en"): string {
  const raw = String(value || "").trim();
  if (!raw) return lang === "zh" ? "未记录" : "Not recorded";
  return LOCATION_LABELS[raw.toLowerCase()]?.[lang] || raw;
}

export function companionReturnTarget(
  companion: Pick<VirtualHumanCompanion, "agentId" | "directSessionId">,
): string {
  const search = new URLSearchParams({
    session: companion.directSessionId,
    companion: companion.agentId,
  });
  return `/chat?${search.toString()}`;
}

export function formatCompanionLocalTime(
  snapshot: VirtualHumanSnapshot,
  lang: "zh" | "en",
  now = new Date(),
): string {
  if (Number.isNaN(now.getTime())) return "--:--";
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  const timezone = String(snapshot.state?.timezone || snapshot.binding?.timezone || "").trim();
  const options: Intl.DateTimeFormatOptions = {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  };
  try {
    return new Intl.DateTimeFormat(locale, timezone ? { ...options, timeZone: timezone } : options).format(now);
  } catch {
    return new Intl.DateTimeFormat(locale, options).format(now);
  }
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

export function currentLifeActivityLabel(
  snapshot: VirtualHumanSnapshot,
  lang: "zh" | "en",
): string {
  const activity = currentLifeActivity(snapshot);
  if (activity?.title) return activity.title;
  const sleepState = String(snapshot.state?.sleepState || "awake").trim().toLowerCase();
  if (sleepState === "sleeping") return lang === "zh" ? "正在睡觉" : "Sleeping";
  if (sleepState === "resting") return lang === "zh" ? "正在放松休息" : "Taking a break";
  return lang === "zh" ? "自由活动" : "Unscheduled time";
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
  bright: { zh: "愉悦", en: "Bright" },
  low: { zh: "低落", en: "Low" },
  neutral: { zh: "平常", en: "Neutral" },
  surprised: { zh: "惊讶", en: "Surprised" },
};

const MOOD_SYMBOLS: Record<string, string> = {
  calm: "😌",
  happy: "😊",
  curious: "🤔",
  focused: "🧐",
  tired: "😴",
  sad: "😔",
  bright: "🌞",
  low: "😔",
  neutral: "🙂",
  surprised: "😮",
};

export function lifeMoodLabel(snapshot: VirtualHumanSnapshot, lang: "zh" | "en"): string {
  const mood = String(snapshot.state?.mood?.label || "calm").trim().toLowerCase();
  return MOOD_LABELS[mood]?.[lang] || (lang === "zh" ? "平静" : "Calm");
}

export function lifeMoodSymbol(snapshot: VirtualHumanSnapshot): string {
  const mood = String(snapshot.state?.mood?.label || "calm").trim().toLowerCase();
  return MOOD_SYMBOLS[mood] || MOOD_SYMBOLS.calm;
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
