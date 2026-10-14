import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { queryKeys } from "../../src/api/queryKeys";
import { seedControlTokenForTests } from "../../src/api/client";
import type {
  AgentPluginBinding,
  VirtualHumanCausalProjection,
  VirtualHumanCompanion,
  VirtualHumanDiaryEntry,
  VirtualHumanEpisodicMemory,
  VirtualHumanLifeEvent,
  VirtualHumanLifeRoutine,
  VirtualHumanRelationship,
  VirtualHumanSchedule,
  VirtualHumanLifeWorld,
} from "../../src/api/types";
import { VButton, VDialog, VuiProvider } from "../../src/components/vui";
import "../../src/design/tokens.css";
import "../../src/design/base.css";
import "../../src/design/tailwind.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/vui-native-controls.css";
import "../../src/design/workbench-shell.css";
import "../../src/design/workbench-frame.css";
import "../../src/design/route-css/companions.tailwind.css";
import "../../src/routes/companions/CompanionSceneWorkspace.css";
import { CompanionLifeRail } from "../../src/routes/companions/CompanionLifeRail";

const agentId = "companion-fixture-luo-tianyi";
const localDate = "2026-10-14";
const dateTime = (hour: number, minute = 0) =>
  `2026-10-14T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00+08:00`;

const homeLocation = {
  locationId: "fixture-shanghai-pudong",
  countryCode: "CN",
  countryName: "中国",
  regionCode: "SH",
  regionName: "上海市",
  cityCode: "SH-PD",
  cityName: "上海·浦东新区",
  timezone: "Asia/Shanghai",
  locale: "zh-CN",
  precision: "district",
  sourceKind: "fixture",
};

const binding: AgentPluginBinding = {
  agentId,
  pluginId: "virtual_human_life",
  enabled: true,
  configVersion: 8,
  bindingRevision: 8,
  timezone: "Asia/Shanghai",
  locale: "zh-CN",
  homeLocation,
  lifeIdentityKind: "student",
  steward: {
    enabled: false,
    agentId,
    sessionId: "fixture-life-steward-session",
    promptPackId: "virtual-human-life-v1",
    toolBundleId: "virtual-human-life-tools-v1",
    provisioningState: "missing",
  },
};

const routines: VirtualHumanLifeRoutine[] = [
  ["起床与洗漱", "06:30", "06:55", "personal"],
  ["早餐与收拾书包", "06:55", "07:25", "nourishment"],
  ["步行到地铁站", "07:25", "07:45", "commute"],
  ["早自习与单词复习", "07:45", "08:15", "study"],
  ["上午课程", "08:20", "12:00", "study"],
  ["午餐和短暂休息", "12:00", "13:00", "rest"],
  ["下午课程与小组讨论", "13:00", "16:35", "study"],
  ["回家路上听歌", "16:35", "17:10", "commute"],
  ["晚餐与家人聊天", "17:10", "18:00", "social"],
  ["数学作业与错题整理", "18:00", "19:30", "study"],
  ["练习键盘与写歌", "19:30", "20:15", "music"],
  ["自由阅读和消息回复", "20:15", "21:00", "rest"],
  ["睡前整理与放松", "21:00", "22:00", "sleep"],
].map(([title, startTime, endTime, activityKind], index) => ({
  routineId: `fixture-routine-${index + 1}`,
  dayType: "weekday",
  startTime,
  endTime,
  title,
  activityKind,
  timezone: "Asia/Shanghai",
}));

const lifeWorld: VirtualHumanLifeWorld = {
  schemaVersion: 1,
  setupState: "ready",
  revision: 8,
  draft: null,
  updatedAt: dateTime(7, 20),
  facts: {
    identities: [{
      identityId: "fixture-student-identity",
      kind: "student",
      roleTitle: "上海市浦东新区实验学校高二学生与校园乐队键盘手",
      stage: "高二·准备期中考试与校园音乐节",
      effectiveFrom: "2025-09-01",
    }],
    affiliations: [{
      affiliationId: "fixture-school-affiliation",
      organizationKind: "school",
      name: "上海市浦东新区实验学校（虚构人物生活档案）",
      department: "高中部·理科实验班·校园音乐社",
      role: "学生、键盘手与周五排练协调人",
      cityLocationId: homeLocation.locationId,
    }],
    routines,
    items: [
      { itemId: "fixture-phone", category: "phone", name: "日常通讯手机", brand: "Pixel", model: "9a" },
      { itemId: "fixture-laptop", category: "computer", name: "学习与编曲笔记本", brand: "ThinkPad", model: "X1 Carbon" },
      { itemId: "fixture-keyboard", category: "instrument", name: "社团排练用 MIDI 键盘", brand: "Roland", model: "GO:KEYS 5" },
      { itemId: "fixture-headphones", category: "audio", name: "通勤与练习用耳机", brand: "Sony", model: "WH-1000XM6" },
      { itemId: "fixture-notebook", category: "study", name: "错题整理与创作灵感手账", status: "active" },
    ],
    accounts: [
      { accountId: "fixture-pocket", name: "每月生活费（虚构）", accountType: "allowance", currency: "CNY", balanceMinor: 68000 },
      { accountId: "fixture-savings", name: "音乐节与设备储蓄（虚构）", accountType: "savings", currency: "CNY", balanceMinor: 142000 },
      { accountId: "fixture-transit", name: "通勤交通预算（虚构）", accountType: "budget", currency: "CNY", balanceMinor: 9600 },
    ],
    recurringRules: [
      { ruleId: "fixture-rule-transit", kind: "expense", accountId: "fixture-transit", title: "每月交通卡充值（虚构）", amountMinor: 12000, currency: "CNY", frequency: "monthly", nextDueOn: "2026-11-01", status: "active" },
      { ruleId: "fixture-rule-music", kind: "saving", accountId: "fixture-savings", title: "音乐节设备基金（虚构）", amountMinor: 5000, currency: "CNY", frequency: "monthly", nextDueOn: "2026-11-05", status: "active" },
    ],
    transactions: [],
  },
};

const events: VirtualHumanLifeEvent[] = [
  {
    eventId: "fixture-event-simulation",
    agentId,
    activityId: "fixture-simulated-walk",
    kind: "activity_completed",
    activityKind: "simulated",
    sourceKind: "simulation",
    title: "计划中的校园散步",
    occurredAt: dateTime(8, 10),
    simulatedAfterRestart: false,
    outcome: { kind: "deterministic_simulation", status: "succeeded", summary: "日程模拟记录，仅用于验证来源标记。" },
  },
  {
    eventId: "fixture-event-verified",
    agentId,
    activityId: "fixture-practice-keyboard",
    kind: "activity_completed",
    activityKind: "practice",
    sourceKind: "verified_action",
    title: "完成十五分钟键盘练习",
    occurredAt: dateTime(9, 35),
    outcome: { kind: "verified_tool_outcome", status: "succeeded", summary: "练习回执已保存，可用于展示有回执的行动来源。" },
  },
  {
    eventId: "fixture-event-report",
    agentId,
    kind: "character_report",
    sourceKind: "character_report",
    title: "记录了早晨的心情",
    occurredAt: dateTime(10, 15),
    outcome: { kind: "character_report", status: "recorded", summary: "人物自述来源示例。" },
  },
  {
    eventId: "fixture-event-unknown",
    agentId,
    kind: "activity_completed",
    sourceKind: "unknown",
    title: "来源待核对的记录",
    occurredAt: dateTime(11, 5),
    outcome: { kind: "legacy_event", status: "recorded", summary: "这条记录的来源尚未核实。" },
  },
];

const todaySchedule: VirtualHumanSchedule = {
  agentId,
  localDate,
  scheduleVersion: 8,
  timezone: "Asia/Shanghai",
  planningMode: "fictional_fixture",
  activities: [
    { activityId: "fixture-current-class", title: "完成物理课题的小组讨论", kind: "study", activityKind: "study", startAt: dateTime(13), endAt: dateTime(14), status: "active", origin: "routine" },
    { activityId: "fixture-next-reading", title: "整理长篇阅读笔记", kind: "study", activityKind: "study", startAt: dateTime(14), endAt: dateTime(15), status: "planned", origin: "routine" },
    { activityId: "fixture-music-practice", title: "和社团同学练习音乐节曲目", kind: "practice", activityKind: "music", startAt: dateTime(16), endAt: dateTime(17), status: "planned", origin: "routine" },
    { activityId: "fixture-evening-homework", title: "整理本周错题并完成数学作业", kind: "study", activityKind: "study", startAt: dateTime(19), endAt: dateTime(20, 30), status: "planned", origin: "routine" },
  ],
};

const memories: VirtualHumanEpisodicMemory[] = Array.from({ length: 13 }, (_, index) => {
  const episodeId = `fixture-memory-${String(index + 1).padStart(2, "0")}`;
  const sourceKinds: NonNullable<VirtualHumanEpisodicMemory["sourceKind"]>[] = [
    "simulation",
    "simulation",
    "verified_action",
    "character_report",
    "unknown",
    "verified_action",
    "character_report",
    "unknown",
    "verified_action",
    "character_report",
    "unknown",
    "verified_action",
    "character_report",
  ];
  const sourceKind = sourceKinds[index];
  const occurredAt = new Date(Date.UTC(2026, 9, 14, 12 - index)).toISOString();
  const sourceEventIds = index === 0
    ? ["fixture-event-simulation"]
    : index === 2
      ? ["fixture-event-verified"]
      : [];
  return {
    episodeId,
    text: `第 ${index + 1} 条长期记忆：放学后的路灯、教室里尚未收好的谱架、和同学讨论时留下的细节。${"这段较长的正文用于检查真实记忆详情弹窗能否完整滚动。".repeat(3)}`,
    occurredAt,
    promotedAt: new Date(Date.parse(occurredAt) + 3_600_000).toISOString(),
    reinforcedAt: index < 3 ? dateTime(12, 10) : null,
    sourceKind,
    excludedFromRecall: index === 0 ? true : index === 1 ? false : undefined,
    sourceEventIds,
    sourceRefs: [{ type: "fixture_episode", id: episodeId }],
    salienceScore: Math.max(0.25, 0.92 - index * 0.045),
  };
});

const diaryEntries: VirtualHumanDiaryEntry[] = [
  { diaryEntryId: "fixture-diary-1", agentId, localDate, title: "社团排练前的准备", content: "把曲谱标注好，再确认大家到场的时间。", sourceEventIds: ["fixture-event-verified"], sourceKind: "verified_action", writtenAt: dateTime(12, 15) },
  { diaryEntryId: "fixture-diary-2", agentId, localDate, title: "早晨的灵感", content: "走过校门时突然想到副歌的和弦走向。", sourceEventIds: ["fixture-event-report"], sourceKind: "character_report", writtenAt: dateTime(11, 20) },
  { diaryEntryId: "fixture-diary-3", agentId, localDate, title: "来源仍待核对", content: "保留这条记录，等关联事件确认后再补充。", sourceEventIds: ["fixture-event-unknown"], sourceKind: "unknown", writtenAt: dateTime(10, 55) },
];

const relationships: VirtualHumanRelationship[] = [
  { targetId: "user", intimacy: 62, trust: 70, relationshipStage: "friend", interactionCount: 34, lastInteractionKind: "supportive_conversation", summary: "能自然分享日常，也保留各自的生活节奏。" },
  { targetId: "林澄", intimacy: 54, trust: 58, relationshipStage: "friend", interactionCount: 18, lastInteractionKind: "shared_activity", summary: "同班同学和乐队朋友。" },
];

const causal: VirtualHumanCausalProjection = {
  schemaVersion: 1,
  drives: {
    goals: [
      { driveId: "fixture-goal-music", title: "准备校园音乐节演出", status: "active", progressBasis: "ongoing", verifiedActivityCount: 4 },
      { driveId: "fixture-goal-study", title: "稳步整理物理错题", status: "active", progressBasis: "ongoing", verifiedActivityCount: 7 },
    ],
    projects: [{ driveId: "fixture-project-song", title: "完成一首原创歌曲的编曲草稿", status: "active", progressBasis: "ongoing", verifiedActivityCount: 3 }],
    habits: [],
    skills: [],
  },
  affect: { expressionTier: "warm", activeEpisodeIds: ["fixture-affect-1"] },
  relationships,
  openLoops: {
    open: [
      { loopId: "fixture-loop-song", topicKey: "music-festival", summary: "还没决定演出最后一首歌。", status: "open", sourceEventIds: ["fixture-event-verified"] },
      { loopId: "fixture-loop-book", topicKey: "borrowed-book", summary: "记得把借来的诗集还给林澄。", status: "open" },
    ],
    resolved: [],
    expired: [],
  },
  proactiveCandidates: [{ candidateId: "fixture-candidate-song", topicKey: "music-festival", reason: "eligible", status: "selected", decision: "wait_for_natural_moment", evaluatedAt: dateTime(12, 20) }],
  reflections: {
    recent: [
      { proposalId: "fixture-reflection-approved", sourceKind: "lived_event", targetKind: "value", text: "愿意多花一点时间，把一件喜欢的事认真做好。", status: "approved", sourceEventIds: ["fixture-event-verified"], localDate },
      { proposalId: "fixture-reflection-pending", sourceKind: "lived_event", targetKind: "interest", text: "也许可以试试为乐队写一段新的前奏。", status: "pending", sourceEventIds: ["fixture-event-report"], localDate },
    ],
    approvedCount: 1,
    pendingCount: 1,
  },
  interests: {
    items: [
      { interestKey: "keyboard", label: "键盘与编曲", experience: 7, level: 3, completedCount: 12, lastOutcomeSummary: "完成了键盘练习并保存回执。", lastPracticedAt: dateTime(9, 35), sourceEventIds: ["fixture-event-verified"] },
      { interestKey: "poetry", label: "现代诗与歌词", experience: 4, level: 2, completedCount: 8, lastOutcomeSummary: "在手账里记下了新的歌词意象。", lastPracticedAt: dateTime(11, 15) },
    ],
  },
  world: {
    places: [
      { placeId: "fixture-home", label: "浦东家中书桌", livingSpace: true, visitCount: 35, lastVisitedAt: dateTime(7, 30) },
      { placeId: "fixture-school", label: "实验学校音乐教室", visitCount: 17, lastVisitedAt: dateTime(9, 35), sourceEventIds: ["fixture-event-verified"] },
      { placeId: "fixture-bookshop", label: "世纪大道附近的旧书店", visitCount: 3, lastVisitedAt: dateTime(12, 5) },
    ],
    routes: [{ routeId: "fixture-route-home-school", fromPlaceId: "fixture-home", toPlaceId: "fixture-school", typicalMinutes: 38 }],
    importantItems: [{ itemId: "fixture-important-pick", label: "演出时用的蓝色拨片", significance: "朋友送的，放在键盘琴包侧袋里。", sourceKind: "verified_action", sourceRef: "fixture-event-verified" }],
  },
  socialCircle: {
    npcs: [
      { npcId: "lin-cheng", kind: "npc", displayName: "林澄", role: "同班同学与吉他手", traits: ["细心", "喜欢旧书"], updatedAt: dateTime(11, 20) },
      { npcId: "zhou-xia", kind: "npc", displayName: "周夏", role: "社团主唱", traits: ["行动快", "喜欢即兴"], updatedAt: dateTime(10, 10) },
      { npcId: "chen-yu", kind: "npc", displayName: "陈屿", role: "物理课同桌", traits: ["安静", "擅长做题"], updatedAt: dateTime(8, 20) },
    ],
  },
  lifeFeed: [
    { feedId: "fixture-feed-verified", kind: "life_event", title: "练习了键盘", summary: "完成十五分钟练习并留下行动回执。", occurredAt: dateTime(9, 35), sourceEventIds: ["fixture-event-verified"], sourceKind: "verified_action" },
    { feedId: "fixture-feed-report", kind: "diary", title: "记下早晨的灵感", summary: "把副歌和弦的想法写进手账。", occurredAt: dateTime(11, 20), sourceEventIds: ["fixture-event-report"], sourceKind: "character_report" },
    { feedId: "fixture-feed-simulation", kind: "life_event", title: "校园散步计划", summary: "计划记录不代表已经真实发生。", occurredAt: dateTime(8, 10), sourceEventIds: ["fixture-event-simulation"], sourceKind: "simulation" },
    { feedId: "fixture-feed-unknown", kind: "artifact", title: "待核对的生活片段", summary: "来源没有完整回执。", occurredAt: dateTime(10, 55), sourceEventIds: ["fixture-event-unknown"], sourceKind: "unknown" },
  ],
  expression: { applied: [{ ruleId: "fixture-expression-warm", scope: "conversation", priority: 2, explanation: "表达自然、轻快，不替用户做决定。" }] },
  companionPreferences: {
    schemaVersion: 1,
    cards: [{ preferenceKind: "response_length", value: "balanced", episodeId: "fixture-preference-1", reviewStatus: "user_confirmed", occurredAt: dateTime(7, 0) }],
    values: { response_length: "balanced" },
  },
};

const companion: VirtualHumanCompanion = {
  agentId,
  agentCode: "luo-tianyi-fixture",
  displayName: "洛天依",
  directSessionId: "fixture-session",
  avatarImageUrl: "",
  personaProfile: {},
  status: "active",
  snapshot: {
    pluginId: "virtual_human_life",
    agentId,
    installed: true,
    bound: true,
    binding,
    state: {
      stateVersion: 8,
      localDate,
      timezone: "Asia/Shanghai",
      currentLocation: "浦东新区",
      locationStatus: "stationary",
      locationSource: { sourceKind: "fixture", sourceRef: "fixture-location" },
      currentActivityId: "fixture-current-class",
      mood: { label: "平静而专注", valence: 0.3, arousal: 0.25, stability: 0.8, updatedAt: dateTime(13, 5) },
      energy: 72,
      sleepState: "awake",
      socialNeed: 46,
      relationshipSummary: "熟悉之后能自然分享日常，也尊重彼此的节奏。",
      lifePaused: false,
      lastHeartbeatAt: dateTime(12, 55),
    },
    todaySchedule,
    tomorrowSchedule: { agentId, localDate: "2026-10-15", scheduleVersion: 8, timezone: "Asia/Shanghai", activities: [] },
    proactiveUsage: { delivered: 1, limit: 3, remaining: 2 },
    todayCalendar: { localDate, timezone: "Asia/Shanghai", occurrences: [], conflicts: [], eventCount: 0, conflictCount: 0 },
    rhythms: {
      timezone: "Asia/Shanghai",
      chronotype: { label: "evening", evidenceCount: 12 },
      circadian: { localHour: 13, phase: "day", preferredSleepStart: "22:00", preferredWakeTime: "06:30" },
      needs: { focus: { level: 0.68 }, rest: { level: 0.36 }, social: { level: 0.44 }, nourishment: { level: 0.57 } },
      updatedAt: dateTime(12, 55),
    },
    causal,
    lifeWorld,
    health: { personaInitialized: true, heartbeatEnabled: true, memoryPromotionCount: 12, latestPromotionAt: dateTime(12, 0) },
  },
};

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: Number.POSITIVE_INFINITY,
      gcTime: Number.POSITIVE_INFINITY,
      retry: false,
      refetchOnMount: false,
      refetchOnReconnect: false,
      refetchOnWindowFocus: false,
    },
    mutations: { retry: false },
  },
});

queryClient.setQueryData(queryKeys.virtualHumanMemories(agentId, 100), memories);
queryClient.setQueryData(queryKeys.virtualHumanDiary(agentId, "", 100), diaryEntries);
queryClient.setQueryData(queryKeys.virtualHumanRelationships(agentId), relationships);
queryClient.setQueryData(queryKeys.virtualHumanEvents(agentId, localDate, 100), events);

const sourceDates = new Set<string>();
for (const memory of memories) {
  if (!memory.sourceEventIds?.length || !memory.occurredAt) continue;
  const occurredAt = Date.parse(memory.occurredAt);
  if (!Number.isFinite(occurredAt)) continue;
  for (const offset of [-1, 0, 1]) {
    sourceDates.add(new Date(occurredAt + offset * 86_400_000).toISOString().slice(0, 10));
  }
}
for (const sourceDate of sourceDates) {
  queryClient.setQueryData(queryKeys.virtualHumanEvents(agentId, sourceDate, 500), events);
}

const nativeFetch = window.fetch.bind(window);
seedControlTokenForTests("companion-preview-local-token");
window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const request = input instanceof Request ? input : null;
  const requestUrl = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  const url = new URL(requestUrl, window.location.href);
  const pathname = url.pathname;
  if (pathname.startsWith("/api/")) {
    const method = (init?.method ?? request?.method ?? "GET").toUpperCase();
    const fixtureApiPath = `/api/agents/${encodeURIComponent(agentId)}/plugins/virtual-human-life`;
    const fixtureResponse = (value: unknown) => new Response(JSON.stringify(value), {
      headers: { "Content-Type": "application/json" },
    });
    const limitRows = <T,>(rows: T[]): T[] => {
      const rawLimit = url.searchParams.get("limit");
      if (rawLimit === null) return rows;
      const limit = Number(rawLimit);
      return Number.isInteger(limit) && limit >= 0 ? rows.slice(0, limit) : rows;
    };

    if (method === "GET" && pathname === `${fixtureApiPath}/events`) {
      const requestedDate = url.searchParams.get("localDate");
      const referencedEventIds = new Set(memories.flatMap((memory) => memory.sourceEventIds ?? []));
      const matchingEvents = requestedDate && requestedDate !== localDate
        ? events.filter((event) => referencedEventIds.has(event.eventId))
        : events;
      return fixtureResponse(limitRows(matchingEvents));
    }
    if (method === "GET" && pathname === `${fixtureApiPath}/diary`) {
      return fixtureResponse(limitRows(diaryEntries));
    }
    if (method === "GET" && pathname === `${fixtureApiPath}/relationships`) {
      return fixtureResponse(relationships);
    }
    if (method === "GET" && pathname === `${fixtureApiPath}/memories`) {
      return fixtureResponse(limitRows(memories));
    }

    document.documentElement.dataset.fixtureApiRequestBlocked = "true";
    throw new Error("Fixture API request blocked; only local fixture GET endpoints are available.");
  }
  return nativeFetch(input, init);
}) as typeof window.fetch;

function ProductionFixture() {
  const [open, setOpen] = useState(true);
  return (
    <QueryClientProvider client={queryClient}>
      <VuiProvider>
        {!open ? (
          <main style={{ display: "grid", height: "100%", placeItems: "center" }}>
            <VButton onPress={() => setOpen(true)}>重新打开生活面板验收页</VButton>
          </main>
        ) : null}
        <VDialog
          open={open}
          onOpenChange={setOpen}
          title="洛天依的生活 · 正式组件验收"
          description="正式 CompanionLifeRail 与 CompanionMemoryRecords；全部数据来自本地 QueryClient fixture，/api 请求会被拦截。"
          className="companion-scene-life-dialog"
        >
          <CompanionLifeRail
            className="companion-scene-life-content"
            collapsed={false}
            overlayOpen={false}
            companion={companion}
            state="ready"
            lang="zh"
            onOpenLifeSteward={() => undefined}
          />
        </VDialog>
      </VuiProvider>
    </QueryClientProvider>
  );
}

createRoot(document.getElementById("root")!).render(<ProductionFixture />);
