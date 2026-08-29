import type { AgentPersonaProfile } from "./agents";

export type AgentPluginBinding = {
  agentId: string;
  pluginId: string;
  enabled: boolean;
  configVersion: number;
  bindingRevision: number;
  timezone?: string;
  nightlyPlanningTime?: string;
  heartbeatIntervalSeconds?: number;
  autonomyLevel?: "assisted" | "autonomous" | string;
  proactiveMessagesEnabled?: boolean;
  proactiveDailyLimit?: number;
  proactiveMinimumIntervalMinutes?: number;
  quietHours?: { start?: string; end?: string };
  rhythmConfig?: Record<string, unknown>;
  toolBundleId?: string;
  promptPackId?: string;
};

export type AgentPluginCatalogEntry = {
  pluginId: string;
  displayName: string;
  description: string;
  version: string;
  trustedFirstParty: boolean;
  toolBundleId: string;
  promptPackId: string;
  toolNames: string[];
};

export type AgentPluginEntry = AgentPluginCatalogEntry & {
  binding: AgentPluginBinding | null;
};

export type AgentPluginList = {
  agentId: string;
  plugins: AgentPluginEntry[];
};

export type VirtualHumanMood = {
  label: string;
  valence: number;
  arousal: number;
  stability: number;
  causeEventIds?: string[];
  updatedAt: string;
};

export type VirtualHumanLocationSource = {
  movementId?: string;
  sourceKind?: string;
  sourceRef?: string;
  arrivedAt?: string;
};

export type VirtualHumanLifeState = {
  stateVersion: number;
  localDate: string;
  timezone: string;
  currentLocation: string;
  locationStatus?: "stationary" | "moving" | string;
  activeMovementId?: string;
  movingTo?: string;
  locationSource?: VirtualHumanLocationSource;
  currentActivityId: string;
  mood: VirtualHumanMood;
  energy: number;
  sleepState: string;
  socialNeed: number;
  relationshipSummary: string;
  lifePaused: boolean;
  lastHeartbeatAt: string;
};

export type VirtualHumanActivity = {
  activityId: string;
  title: string;
  kind: string;
  activityKind?: string;
  startAt: string;
  endAt: string;
  status: string;
  origin: string;
  driveLinks?: string[];
  driveReason?: string;
};

export type VirtualHumanSchedule = {
  agentId: string;
  localDate: string;
  scheduleVersion: number;
  activities: VirtualHumanActivity[];
  timezone?: string;
  planningMode?: string;
  createdAt?: string;
  updatedAt?: string;
};

export type VirtualHumanScheduleBundle = {
  agentId: string;
  today: VirtualHumanSchedule | null;
  tomorrow: VirtualHumanSchedule | null;
};

export type VirtualHumanCalendarOccurrence = {
  calendarEventId: string;
  calendarOccurrenceId: string;
  occurrenceDate: string;
  title: string;
  kind: string;
  startAt: string;
  endAt: string;
  timezone?: string;
};

export type VirtualHumanCalendarProjection = {
  localDate: string;
  timezone?: string;
  occurrences: VirtualHumanCalendarOccurrence[];
  conflicts: Array<{
    conflictId: string;
    eventIds?: string[];
    startAt?: string;
    endAt?: string;
    status?: string;
  }>;
  eventCount: number;
  conflictCount: number;
};

export type VirtualHumanRhythmNeed = {
  level: number;
  ratePerHour?: number;
  recoveryPerActivity?: number;
};

export type VirtualHumanRhythmProjection = {
  timezone?: string;
  chronotype?: {
    label?: string;
    evidenceCount?: number;
    confidence?: number;
    adaptationStatus?: string;
  };
  circadian?: {
    localHour?: number;
    phase?: string;
    energyFactor?: number;
    preferredSleepStart?: string;
    preferredWakeTime?: string;
  };
  needs?: Record<string, VirtualHumanRhythmNeed>;
  updatedAt?: string;
};

export type VirtualHumanLifeEventOutcome = {
  status?: string;
  kind?: string;
  summary?: string;
  recordedAt?: string;
  salienceScore?: number;
  [key: string]: unknown;
};

export type VirtualHumanLifeEvent = {
  eventId: string;
  agentId: string;
  activityId?: string;
  kind: string;
  title?: string;
  occurredAt?: string;
  outcome?: VirtualHumanLifeEventOutcome;
  simulatedAfterRestart?: boolean;
  failureReason?: string;
  [key: string]: unknown;
};

export type VirtualHumanDiaryEntry = {
  diaryEntryId: string;
  agentId: string;
  localDate: string;
  title?: string;
  content?: string;
  sourceEventIds: string[];
  writtenAt?: string;
  projectionKind?: string;
  [key: string]: unknown;
};

export type VirtualHumanRelationship = {
  targetId: string;
  intimacy: number;
  trust: number;
  relationshipStage?: "getting_to_know" | "friend" | "close" | string;
  interactionCount?: number;
  lastInteractionKind?: string;
  lastInteractionAt?: string;
  updatedAt?: string;
  summary?: string;
  [key: string]: unknown;
};

export type VirtualHumanDriveItem = {
  driveId: string;
  title: string;
  status?: string;
  progress?: number;
  streak?: number;
  level?: number;
  experience?: number;
  updatedAt?: string;
};

export type VirtualHumanDriveProjection = {
  goals?: VirtualHumanDriveItem[];
  projects?: VirtualHumanDriveItem[];
  habits?: VirtualHumanDriveItem[];
  skills?: VirtualHumanDriveItem[];
  processedEventIds?: string[];
};

export type VirtualHumanAffectProjection = {
  expressionTier?: string;
  activeEpisodeIds?: string[];
  recoveredEpisodeIds?: string[];
  mood?: VirtualHumanMood;
};

export type VirtualHumanOpenLoop = {
  loopId: string;
  topicKey: string;
  kind?: string;
  summary: string;
  status: string;
  sourceTurnIds?: string[];
  sourceEventIds?: string[];
  expiresAt?: string;
};

export type VirtualHumanProactiveCandidate = {
  candidateId: string;
  sourceEventId?: string;
  topicKey?: string;
  reason?: string;
  score?: number;
  status?: string;
  decision?: string;
  suppressionReason?: string;
  evaluatedAt?: string;
  createdAt?: string;
};

export type VirtualHumanReflection = {
  proposalId: string;
  sourceKind: string;
  targetKind: string;
  text: string;
  status: string;
  validationReason?: string;
  sourceEventIds?: string[];
  sourceFactIds?: string[];
  localDate?: string;
  createdAt?: string;
  validatedAt?: string;
  reviewedAt?: string;
  reviewerKind?: string;
  reviewNote?: string;
  supersededByProposalId?: string;
};

export type VirtualHumanInterest = {
  interestKey: string;
  label: string;
  experience: number;
  level: number;
  completedCount: number;
  lastOutcomeSummary?: string;
  lastPracticedAt?: string;
  sourceEventIds?: string[];
};

export type VirtualHumanWorldPlace = {
  placeId: string;
  label: string;
  livingSpace?: boolean;
  visitCount?: number;
  lastVisitedAt?: string;
  sourceEventIds?: string[];
};

export type VirtualHumanImportantItem = {
  itemId: string;
  label: string;
  placeId?: string;
  significance?: string;
  sourceKind?: string;
  sourceRef?: string;
  recordedAt?: string;
};

export type VirtualHumanWorldProjection = {
  places?: VirtualHumanWorldPlace[];
  routes?: Array<{
    routeId: string;
    fromPlaceId: string;
    toPlaceId: string;
    typicalMinutes?: number;
  }>;
  importantItems?: VirtualHumanImportantItem[];
  updatedAt?: string;
};

export type VirtualHumanNpc = {
  npcId: string;
  kind: "npc" | string;
  displayName: string;
  role?: string;
  traits?: string[];
  sourceRefs?: string[];
  updatedAt?: string;
};

export type VirtualHumanLifeFeedItem = {
  feedId: string;
  kind: "life_event" | "diary" | "artifact" | string;
  title: string;
  summary?: string;
  occurredAt?: string;
  sourceEventIds?: string[];
  artifactKind?: string;
  localRef?: string;
};

export type VirtualHumanExpressionRule = {
  ruleId: string;
  scope: string;
  priority?: number;
  action?: Record<string, unknown>;
  explanation?: string;
};

export type VirtualHumanEmbodiment = {
  enabled?: boolean;
  requestedMode?: string;
  activeMode?: string;
  providerId?: string;
  assetRef?: string;
  fallbackReason?: string;
  textChatUnaffected?: boolean;
};

export type VirtualHumanEnvironmentFact = {
  factId: string;
  factKey: string;
  value: unknown;
  sourceKind: string;
  sourceRef: string;
  confidence?: number;
  observedAt?: string;
  status?: string;
};

export type VirtualHumanEnvironmentProjection = {
  currentFacts?: VirtualHumanEnvironmentFact[];
  history?: VirtualHumanEnvironmentFact[];
};

export type VirtualHumanLocationMovement = {
  movementId: string;
  fromLocation: string;
  toLocation: string;
  status: string;
  sourceKind?: string;
  sourceRef?: string;
  startedAt?: string;
  earliestArrivalAt?: string;
  arrivedAt?: string;
};

export type VirtualHumanCausalProjection = {
  schemaVersion: number;
  drives?: VirtualHumanDriveProjection;
  affect?: VirtualHumanAffectProjection;
  relationships?: VirtualHumanRelationship[];
  openLoops?: {
    open?: VirtualHumanOpenLoop[];
    resolved?: VirtualHumanOpenLoop[];
    expired?: VirtualHumanOpenLoop[];
    updatedAt?: string;
  };
  proactiveCandidates?: VirtualHumanProactiveCandidate[];
  reflections?: {
    recent?: VirtualHumanReflection[];
    acceptedCount?: number;
    approvedCount?: number;
    pendingCount?: number;
    rejectedCount?: number;
    supersededCount?: number;
  };
  environment?: VirtualHumanEnvironmentProjection;
  locationMovements?: VirtualHumanLocationMovement[];
  interests?: {
    items?: VirtualHumanInterest[];
    processedEventIds?: string[];
  };
  world?: VirtualHumanWorldProjection;
  socialCircle?: { npcs?: VirtualHumanNpc[]; updatedAt?: string };
  lifeFeed?: VirtualHumanLifeFeedItem[];
  expression?: {
    applied?: VirtualHumanExpressionRule[];
    trace?: Array<{ ruleId?: string; matched?: boolean; reason?: string }>;
  };
  embodiment?: VirtualHumanEmbodiment;
};

/**
 * Runtime-only health facts for the virtual-human binding.
 *
 * Every field is optional so an older backend snapshot can still render the
 * life rail and plugin settings without pretending that a missing fact is a
 * successful initialization or delivery.
 */
export type VirtualHumanSnapshotHealth = {
  personaInitialized?: boolean;
  promptPackReady?: boolean;
  promptSegmentCount?: number;
  memoryPromotionCount?: number;
  latestPromotionAt?: string | null;
  heartbeatEnabled?: boolean;
  lastProactiveStatus?: string | null;
  lastProactiveAt?: string | null;
  lastProactiveError?: string | null;
};

/** A promoted episodic memory projected for the current Agent only. */
export type VirtualHumanEpisodicMemory = {
  episodeId: string;
  text: string;
  occurredAt?: string | null;
  salienceScore?: number | null;
  baseSalienceScore?: number | null;
  memoryStrengthScore?: number | null;
  scoreBreakdown?: {
    importance?: number;
    recency?: number;
    emotion?: number;
    unresolved?: number;
    reinforcement?: number;
  };
  sourceEventIds?: string[];
  promotedAt?: string | null;
  reinforcedAt?: string | null;
};

export type VirtualHumanSnapshot = {
  pluginId: string;
  agentId: string;
  installed: boolean;
  bound: boolean;
  binding: AgentPluginBinding | null;
  state: VirtualHumanLifeState | null;
  todaySchedule: VirtualHumanSchedule | null;
  tomorrowSchedule: VirtualHumanSchedule | null;
  todayCalendar?: VirtualHumanCalendarProjection | null;
  tomorrowCalendar?: VirtualHumanCalendarProjection | null;
  rhythms?: VirtualHumanRhythmProjection | null;
  proactiveUsage: {
    delivered: number;
    limit: number;
    remaining: number;
  };
  causal?: VirtualHumanCausalProjection | null;
  health?: VirtualHumanSnapshotHealth;
};

export type VirtualHumanCommandRequest = {
  agentId: string;
  command: string;
  expectedVersion: number;
  idempotencyKey: string;
  arguments: Record<string, unknown>;
};

export type VirtualHumanCommandResponse = {
  agentId: string;
  command: string;
  idempotencyKey: string;
  stateVersion: number;
  result: Record<string, unknown>;
};

export type VirtualHumanCompanion = {
  agentId: string;
  agentCode: string;
  displayName: string;
  directSessionId: string;
  avatarImageUrl: string;
  personaProfile: Partial<AgentPersonaProfile>;
  status: string;
  snapshot: VirtualHumanSnapshot;
};

export type AgentPluginBindingUpdate = {
  enabled: boolean;
  expectedVersion: number;
  config: Record<string, unknown>;
};
