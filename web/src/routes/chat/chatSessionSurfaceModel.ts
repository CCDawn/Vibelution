import type { PetSummary, RuntimeSummary, SessionDetail, SessionSummary } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import { petAvatarPresetLabel } from "../../i18n/petLabels";
import {
  buildVisiblePanelRows,
  getPetAvatarPresetKey,
  getPetAvatarSymbol,
  type CompactPanelRow,
} from "../chatCompactPanel";
import { clampPercent, formatRelativeTime } from "../chatShellFormat";
import { isChildSession } from "../DirectSessionIndexItem";

export type ActiveSkillContract = {
  status?: string;
  scope?: string;
  command?: string;
  args?: string;
  skillName?: string;
  skillPath?: string;
  skillHash?: string;
  description?: string;
  keyRules?: string[];
  activatedAt?: string;
  staleReason?: string;
};

export type ActiveSkillStatus = "active" | "stale" | "missing";

export type ChatActiveSkillViewModel = {
  activeSkillContract: ActiveSkillContract | null;
  activeSkillCommand: string;
  activeSkillName: string;
  activeSkillStatus: ActiveSkillStatus;
  activeSkillStatusLabel: string;
  activeSkillHash: string;
  activeSkillShortHash: string;
  activeSkillRuleCount: number;
  activeSkillSummary: string;
  activeSkillTitle: string;
  hasActiveSkill: boolean;
};

export function buildChatActiveSkillViewModel(options: {
  contract: ActiveSkillContract | null | undefined;
  lang: "zh" | "en";
  numberFormatter: Intl.NumberFormat;
  formatTime: (value: string) => string;
}): ChatActiveSkillViewModel {
  const { contract, lang, numberFormatter, formatTime } = options;
  const activeSkillContract = contract ?? null;
  const activeSkillCommand = String(activeSkillContract?.command ?? "").trim();
  const activeSkillName = String(activeSkillContract?.skillName ?? activeSkillCommand).trim();
  const activeSkillStatusValue = String(activeSkillContract?.status ?? "active").trim().toLowerCase();
  const activeSkillStatus: ActiveSkillStatus = ["active", "stale", "missing"].includes(activeSkillStatusValue)
    ? (activeSkillStatusValue as ActiveSkillStatus)
    : "active";
  const activeSkillStatusLabel = activeSkillStatus === "stale"
    ? (lang === "zh" ? "已变更" : "stale")
    : activeSkillStatus === "missing"
      ? (lang === "zh" ? "缺失" : "missing")
      : (lang === "zh" ? "生效中" : "active");
  const activeSkillHash = String(activeSkillContract?.skillHash ?? "").trim();
  const activeSkillShortHash = activeSkillHash ? activeSkillHash.slice(0, 8) : "";
  const activeSkillRuleCount = Array.isArray(activeSkillContract?.keyRules)
    ? activeSkillContract.keyRules.length
    : 0;
  const activeSkillSummary = activeSkillContract && (activeSkillName || activeSkillCommand)
    ? [
      activeSkillCommand ? `/${activeSkillCommand}` : "",
      activeSkillName,
      activeSkillStatusLabel,
      activeSkillShortHash ? `#${activeSkillShortHash}` : "",
    ].filter(Boolean).join(" · ")
    : "";
  const activeSkillTitle = activeSkillContract && (activeSkillName || activeSkillCommand)
    ? [
      lang === "zh" ? "当前 Skill Contract" : "Active Skill Contract",
      activeSkillCommand ? `/${activeSkillCommand}` : "",
      activeSkillName,
      activeSkillStatusLabel,
      activeSkillHash ? `hash ${activeSkillHash}` : "",
      activeSkillContract.scope ? `scope ${activeSkillContract.scope}` : "",
      activeSkillContract.activatedAt ? `${lang === "zh" ? "激活于" : "activated"} ${formatTime(activeSkillContract.activatedAt)}` : "",
      activeSkillRuleCount ? `${numberFormatter.format(activeSkillRuleCount)} ${lang === "zh" ? "条规则" : "rules"}` : "",
      activeSkillContract.staleReason ? `reason ${activeSkillContract.staleReason}` : "",
      activeSkillContract.skillPath || "",
    ].filter(Boolean).join(" · ")
    : "";

  return {
    activeSkillContract,
    activeSkillCommand,
    activeSkillName,
    activeSkillStatus,
    activeSkillStatusLabel,
    activeSkillHash,
    activeSkillShortHash,
    activeSkillRuleCount,
    activeSkillSummary,
    activeSkillTitle,
    hasActiveSkill: Boolean(activeSkillSummary),
  };
}

export type ChatMentalStateViewModel = {
  mental: RuntimeSummary["mentalState"] | undefined;
  mentalCognitiveStateValue: string;
  mentalSourceValue: string;
  mentalCognitiveStateLabel: string;
  mentalSourceLabel: string;
  mentalStateLabel: string;
  mentalSummary: string;
  mentalWhisper: string;
  mentalConfidence: string;
  mentalRelativeTime: string;
  mentalCompactLine: string;
};

export function buildChatMentalStateViewModel(options: {
  mental: RuntimeSummary["mentalState"] | null | undefined;
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  locale: string;
  nowMs?: number;
}): ChatMentalStateViewModel {
  const { mental, t, locale, nowMs = Date.now() } = options;
  const mentalState = mental ?? undefined;
  const mentalCognitiveStateValue = String(mentalState?.cognitiveState ?? "unknown").trim().toLowerCase() || "unknown";
  const mentalSourceValue = String(mentalState?.source ?? "unavailable").trim().toLowerCase() || "unavailable";
  const mentalCognitiveStateLabel = (() => {
    switch (mentalCognitiveStateValue) {
      case "normal":
        return t("mentalCognitiveState_normal");
      case "productive":
        return t("mentalCognitiveState_productive");
      case "looping":
        return t("mentalCognitiveState_looping");
      case "thrashing":
        return t("mentalCognitiveState_thrashing");
      case "tunnel_vision":
        return t("mentalCognitiveState_tunnel_vision");
      case "disoriented":
        return t("mentalCognitiveState_disoriented");
      default:
        return t("mentalCognitiveState_unknown");
    }
  })();
  const mentalSourceLabel = (() => {
    switch (mentalSourceValue) {
      case "state":
        return t("mentalSourceState");
      case "diagnosis":
        return t("mentalSourceDiagnosis");
      default:
        return t("mentalSourceUnavailable");
    }
  })();
  const mentalStateLabel = mentalState?.mood?.trim() || mentalCognitiveStateLabel;
  const mentalSummary = mentalState?.feeling?.trim() || mentalState?.summary || t("mentalStatePending");
  const mentalWhisper = mentalState?.whisper?.trim() || t("mentalStatePending");
  const mentalConfidence =
    Number.isFinite(mentalState?.confidence)
      ? `${Math.round((mentalState?.confidence ?? 0) * 100)}%`
      : "--";
  const mentalRelativeTime = formatRelativeTime(mentalState?.updatedAt ?? "", nowMs, locale) || "--";
  const mentalCompactLine = [
    mentalSourceLabel,
    mentalConfidence !== "--" ? `${t("mentalConfidence")} ${mentalConfidence}` : "",
    mentalRelativeTime !== "--" ? mentalRelativeTime : "",
  ]
    .filter(Boolean)
    .join(" · ");

  return {
    mental: mentalState,
    mentalCognitiveStateValue,
    mentalSourceValue,
    mentalCognitiveStateLabel,
    mentalSourceLabel,
    mentalStateLabel,
    mentalSummary,
    mentalWhisper,
    mentalConfidence,
    mentalRelativeTime,
    mentalCompactLine,
  };
}

export type ChatPetCompanionViewModel = {
  petVitals: Array<{ key: string; label: string; value: number }>;
  petCompanionLine: string;
  petPresetLabel: string;
  petAvatarPresetKey: string;
  petAvatarSymbol: string;
  petCompactLine: string;
  petInteractionLabels: {
    group: string;
    pending: string;
    feed: string;
    talk: string;
    care: string;
    feedTitle: string;
    talkTitle: string;
    careTitle: string;
  };
};

export function buildChatPetCompanionViewModel(options: {
  pet: PetSummary | null | undefined;
  petQueryError: boolean;
  petQueryErrorMessage: string;
  petActionPending: boolean;
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  numberFormatter: Intl.NumberFormat;
}): ChatPetCompanionViewModel {
  const {
    pet,
    petQueryError,
    petQueryErrorMessage,
    petActionPending,
    lang,
    t,
    numberFormatter,
  } = options;

  const petVitals = [
    { key: "hunger", label: t("hunger"), value: clampPercent(pet?.hunger ?? 0) },
    { key: "energy", label: t("energy"), value: clampPercent(pet?.energy ?? 0) },
    { key: "health", label: t("health"), value: clampPercent(pet?.health ?? 0) },
    { key: "love", label: t("love"), value: clampPercent(pet?.love ?? 0) },
  ];
  const petCompanionLine = petQueryError
    ? petQueryErrorMessage
    : pet?.inDream
      ? t("petCompanionDreaming")
      : (pet?.health ?? 0) < 35
        ? t("petCompanionLowHealth")
        : (pet?.hunger ?? 0) < 30
          ? t("petCompanionLowFuel")
          : (pet?.energy ?? 0) < 35
            ? t("petCompanionLowEnergy")
            : t("petCompanionStable");
  const petPresetLabel = petAvatarPresetLabel(t, pet?.avatarPreset);
  const petAvatarPresetKey = getPetAvatarPresetKey(pet?.avatarPreset);
  const petAvatarSymbol = getPetAvatarSymbol(pet?.avatarPreset, pet?.name);
  const petCompactLine = [
    petCompanionLine,
    pet?.heartActive ? t("heartActive") : t("heartIdle"),
    pet?.inDream ? t("dreamSleeping") : t("dreamAwake"),
    `${t("tokens")} ${numberFormatter.format(pet?.totalTokens ?? 0)}`,
  ]
    .filter(Boolean)
    .join(" · ");
  const petInteractionLabels = {
    group: lang === "zh" ? "宠物互动" : "Pet interactions",
    pending: petActionPending
      ? lang === "zh" ? "处理中" : "Working"
      : lang === "zh" ? "即时生效" : "Live",
    feed: lang === "zh" ? "喂食" : "Feed",
    talk: lang === "zh" ? "沟通" : "Talk",
    care: lang === "zh" ? "照看" : "Care",
    feedTitle: lang === "zh" ? "喂食并刷新宠物状态" : "Feed and refresh pet state",
    talkTitle: lang === "zh" ? "和宠物沟通并刷新状态" : "Talk and refresh pet state",
    careTitle: lang === "zh" ? "照看宠物并刷新状态" : "Care and refresh pet state",
  };

  return {
    petVitals,
    petCompanionLine,
    petPresetLabel,
    petAvatarPresetKey,
    petAvatarSymbol,
    petCompactLine,
    petInteractionLabels,
  };
}

export type ChatSessionStateViewModel = {
  noActiveDirectSessionTitle: string;
  noActiveDirectSessionLine: string;
  activeSurfaceTitle: string;
  activeSurfaceStatus: string;
  activeSurfaceLine: string;
  sessionStateLabel: string;
  sessionStateLine: string;
  compactSessionStateLine: string;
  sessionStateValue: string;
  agentDirectSessionMismatch: boolean;
  agentPrimaryDirectSessionId: string;
  sessionBindingMismatchLine: string;
  currentTaskSummary: string;
  fileContextValue: string;
  sessionCompactRows: CompactPanelRow[];
};

export function buildChatSessionStateViewModel(options: {
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  statusLabel: (value: string) => string;
  groupPanelActive: boolean;
  projectBusActive: boolean;
  activeSessionId: string | null | undefined;
  activeGroupRoomTitle: string | null | undefined;
  activeGroupRoomStatus: string | null | undefined;
  activeGroupRoomMode: string | null | undefined;
  activeGroupRoomPurpose: string | null | undefined;
  activeGroupRoundSummary: string | null | undefined;
  availableGroupParticipantCount: number;
  projectBusActiveAgentCount: number;
  detail: SessionDetail | null | undefined;
  directSessionActiveSummary: SessionSummary | null | undefined;
  runtimeMatchesSelectedSession: boolean;
  runtimeSessionState: string | null | undefined;
  runtimeSessionStateLine: string | null | undefined;
  runtimeTaskSummary: string | null | undefined;
  runtimeDefaultRoute: string | null | undefined;
  runtimeMismatchLine: string;
  sessionDetailBlockingError: boolean;
  sessionDetailErrorMessage: string;
  sessionDetailLoadingForActiveSession: boolean;
  activeAgentStatusMessage: string;
  latestControlSignalLine: string;
  latestControlSignalTitle: string;
  hasLatestControlSignal: boolean;
}): ChatSessionStateViewModel {
  const {
    lang,
    t,
    statusLabel,
    groupPanelActive,
    projectBusActive,
    activeSessionId,
    activeGroupRoomTitle,
    activeGroupRoomStatus,
    activeGroupRoomMode,
    activeGroupRoomPurpose,
    activeGroupRoundSummary,
    availableGroupParticipantCount,
    projectBusActiveAgentCount,
    detail,
    directSessionActiveSummary,
    runtimeMatchesSelectedSession,
    runtimeSessionState,
    runtimeSessionStateLine,
    runtimeTaskSummary,
    runtimeDefaultRoute,
    runtimeMismatchLine,
    sessionDetailBlockingError,
    sessionDetailErrorMessage,
    sessionDetailLoadingForActiveSession,
    activeAgentStatusMessage,
    latestControlSignalLine,
    latestControlSignalTitle,
    hasLatestControlSignal,
  } = options;

  const noActiveDirectSessionTitle = lang === "zh" ? "未选择会话" : "No session selected";
  const noActiveDirectSessionLine = lang === "zh" ? "选择或新建会话" : "Select or create a chat";
  const loadingDirectSessionTitle = t("loadingSession");
  const activeSurfaceTitle = groupPanelActive
    ? (
      projectBusActive
        ? (lang === "zh" ? "助手通知流" : "Agent notice stream")
        : activeGroupRoomTitle ?? (lang === "zh" ? "群聊加载中" : "Loading group")
    )
    : !activeSessionId
      ? noActiveDirectSessionTitle
      : detail?.agentDisplayName ?? detail?.title ?? directSessionActiveSummary?.agentDisplayName ?? directSessionActiveSummary?.title ?? loadingDirectSessionTitle;
  const activeSurfaceStatus = groupPanelActive
    ? (
      projectBusActive
        ? (lang === "zh" ? "全局广播" : "global broadcast")
        : statusLabel(activeGroupRoomStatus ?? "ready")
    )
    : statusLabel(detail?.status || detail?.currentPhase || "idle");
  const activeSurfaceLine = groupPanelActive
    ? (
      projectBusActive
        ? `${projectBusActiveAgentCount} ${lang === "zh" ? "位 active Agent · 全局广播/私信投递记录" : "active agents · broadcast/private delivery log"}`
        : (
          activeGroupRoundSummary
          || (lang === "zh"
            ? `${availableGroupParticipantCount} 位可用助手`
            : `${availableGroupParticipantCount} available agents · ${activeGroupRoomMode ?? "round_robin"} · ${activeGroupRoomPurpose ?? "discussion"}`)
        )
    )
    : "";

  const sessionStateLabel = (() => {
    if (groupPanelActive) {
      return activeSurfaceStatus;
    }
    const runtimeState = runtimeMatchesSelectedSession ? (runtimeSessionState || "") : "";
    switch (runtimeState) {
      case "thinking":
        return t("sessionStateThinking");
      case "tooling":
        return t("sessionStateTooling");
      case "answering":
        return t("sessionStateAnswering");
      default:
        return statusLabel(runtimeState || detail?.currentPhase || directSessionActiveSummary?.currentPhase || directSessionActiveSummary?.status || "idle");
    }
  })();
  const sessionStateLine = groupPanelActive
    ? activeSurfaceLine
    : !activeSessionId
      ? noActiveDirectSessionLine
      : runtimeMatchesSelectedSession && runtimeSessionStateLine
        ? runtimeSessionStateLine
        : runtimeMismatchLine || (sessionDetailBlockingError
          ? sessionDetailErrorMessage
          : activeAgentStatusMessage || detail?.taskSummary || directSessionActiveSummary?.taskSummary || (sessionDetailLoadingForActiveSession ? t("loadingSession") : t("preparingShell")));
  const compactSessionStateLine = detail?.lastTurnError
    ? [sessionStateLabel, detail.lastTurnError.httpStatus || detail.lastTurnError.reasonCode].filter(Boolean).join(" · ")
    : sessionStateLine;
  const agentDirectSessionMismatch = Boolean(detail?.agentDirectSessionMismatch);
  const agentPrimaryDirectSessionId = String(detail?.agentPrimaryDirectSessionId ?? "").trim();
  const sessionBindingMismatchLine = agentDirectSessionMismatch ? t("sessionBindingMismatchLine") : "";
  const sessionStateValue = String(
    groupPanelActive
      ? (projectBusActive ? "ready" : activeGroupRoomStatus ?? "ready")
      : (runtimeMatchesSelectedSession ? runtimeSessionState : "")
        || detail?.currentPhase
        || directSessionActiveSummary?.currentPhase
        || directSessionActiveSummary?.status
        || "idle",
  )
    .trim()
    .toLowerCase();

  const activeTask = detail?.activeTask ?? null;
  const activeTaskSummary = agentDirectSessionMismatch
    ? ""
    : activeTask?.goal
      || activeTask?.title
      || activeTask?.nextAction
      || activeTask?.latestSummary
      || "";
  const currentTaskSummary =
    activeTaskSummary
    || detail?.taskSummary
    || directSessionActiveSummary?.taskSummary
    || (runtimeMatchesSelectedSession ? runtimeTaskSummary : "")
    || t("preparingShell");
  const fileContextValue = detail?.defaultFileContext ?? (runtimeMatchesSelectedSession ? runtimeDefaultRoute : undefined) ?? "workspace";
  const sessionCompactRows = buildVisiblePanelRows(
    [
      {
        label: t("fileContext"),
        value: fileContextValue,
        title: fileContextValue,
      },
      ...(agentDirectSessionMismatch ? [{
        label: t("sessionBinding"),
        value: t("sessionBindingHistorical"),
        title: `${sessionBindingMismatchLine} ${agentPrimaryDirectSessionId}`,
      }] : []),
      ...(hasLatestControlSignal ? [{
        label: t("nextStateSignalsLabel"),
        value: latestControlSignalLine,
        title: latestControlSignalTitle,
      }] : []),
    ],
    [t("preparingShell"), t("loadingSession"), t("loadingContext")],
  );

  return {
    noActiveDirectSessionTitle,
    noActiveDirectSessionLine,
    activeSurfaceTitle,
    activeSurfaceStatus,
    activeSurfaceLine,
    sessionStateLabel,
    sessionStateLine,
    compactSessionStateLine,
    sessionStateValue,
    agentDirectSessionMismatch,
    agentPrimaryDirectSessionId,
    sessionBindingMismatchLine,
    currentTaskSummary,
    fileContextValue,
    sessionCompactRows,
  };
}

export function buildAgentSessionTabs(options: {
  sessions: SessionSummary[] | null | undefined;
  selectedChatAgentDirectSessionId: string | null | undefined;
}): SessionSummary[] {
  const sessions = options.sessions ?? [];
  const directSessionId = String(options.selectedChatAgentDirectSessionId ?? "").trim();
  return sessions
    .filter((session): session is SessionSummary => Boolean(session))
    .filter((session, index, items) => items.findIndex((item) => item.id === session.id) === index)
    .sort((left, right) => {
      const leftPriority = left.id === directSessionId ? 0 : isChildSession(left) ? 2 : 1;
      const rightPriority = right.id === directSessionId ? 0 : isChildSession(right) ? 2 : 1;
      if (leftPriority !== rightPriority) {
        return leftPriority - rightPriority;
      }
      return String(right.updatedAt || right.lastActive || "").localeCompare(String(left.updatedAt || left.lastActive || ""));
    });
}
