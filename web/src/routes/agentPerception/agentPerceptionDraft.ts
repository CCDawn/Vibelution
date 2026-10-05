import type {
  AgentPerceptionKnowledgePolicy,
  AgentPerceptionMode,
  AgentPerceptionPolicy,
  AgentPerceptionSourceId,
  AgentPerceptionTriggerId,
} from "./types";

const defaultTriggers = () => ({
  task: false,
  update: false,
  background: false,
});

export function defaultAgentPerceptionPolicy(): AgentPerceptionPolicy {
  return {
    schemaVersion: 1,
    enabled: false,
    sources: {
      personal: { mode: "off", triggers: defaultTriggers() },
      team: { mode: "off", teamIds: [], triggers: defaultTriggers() },
      knowledge: {
        mode: "off",
        scope: "selected",
        knowledgeBaseIds: [],
        excludedKnowledgeBaseIds: [],
        triggers: defaultTriggers(),
      },
      projects: { mode: "off", triggers: defaultTriggers() },
    },
    background: {
      enabled: false,
      intervalMinutes: 60,
      dailyMaxRuns: 4,
      maxCallsPerRun: 8,
      maxInputTokensPerRun: 16_000,
      maxConcurrent: 1,
      maxResultChars: 12_000,
      topics: [],
    },
    notifications: { mode: "important" },
  };
}

export function cloneAgentPerceptionPolicy(policy: AgentPerceptionPolicy): AgentPerceptionPolicy {
  return {
    ...policy,
    sources: {
      personal: { ...policy.sources.personal, triggers: { ...policy.sources.personal.triggers } },
      team: {
        ...policy.sources.team,
        teamIds: [...policy.sources.team.teamIds],
        triggers: { ...policy.sources.team.triggers },
      },
      knowledge: {
        ...policy.sources.knowledge,
        knowledgeBaseIds: [...policy.sources.knowledge.knowledgeBaseIds],
        excludedKnowledgeBaseIds: [...policy.sources.knowledge.excludedKnowledgeBaseIds],
        triggers: { ...policy.sources.knowledge.triggers },
      },
      projects: { ...policy.sources.projects, triggers: { ...policy.sources.projects.triggers } },
    },
    background: { ...policy.background, topics: [...policy.background.topics] },
    notifications: { ...policy.notifications },
  };
}

export function canonicalAgentPerceptionPolicy(policy: AgentPerceptionPolicy): AgentPerceptionPolicy {
  const uniqueSorted = (values: string[]) => Array.from(new Set(values.map((value) => value.trim()).filter(Boolean))).sort();
  const cloned = cloneAgentPerceptionPolicy(policy);
  cloned.sources.team.teamIds = uniqueSorted(cloned.sources.team.teamIds);
  cloned.sources.knowledge.knowledgeBaseIds = cloned.sources.knowledge.scope === "all_authorized"
    ? []
    : uniqueSorted(cloned.sources.knowledge.knowledgeBaseIds);
  cloned.sources.knowledge.excludedKnowledgeBaseIds = uniqueSorted(cloned.sources.knowledge.excludedKnowledgeBaseIds);
  cloned.background.topics = uniqueSorted(cloned.background.topics.map((topic) => topic.replace(/\s+/g, " ")));
  return cloned;
}

export function agentPerceptionPoliciesEqual(left: AgentPerceptionPolicy, right: AgentPerceptionPolicy) {
  return JSON.stringify(canonicalAgentPerceptionPolicy(left)) === JSON.stringify(canonicalAgentPerceptionPolicy(right));
}

export function setPerceptionSourceMode(
  policy: AgentPerceptionPolicy,
  source: AgentPerceptionSourceId,
  mode: AgentPerceptionMode,
): AgentPerceptionPolicy {
  const next = cloneAgentPerceptionPolicy(policy);
  next.sources[source].mode = mode;
  return next;
}

export function setPerceptionTrigger(
  policy: AgentPerceptionPolicy,
  source: AgentPerceptionSourceId,
  trigger: AgentPerceptionTriggerId,
  enabled: boolean,
): AgentPerceptionPolicy {
  const next = cloneAgentPerceptionPolicy(policy);
  next.sources[source].triggers[trigger] = enabled;
  return next;
}

export function togglePerceptionScopeId(
  policy: AgentPerceptionPolicy,
  source: "team" | "knowledge",
  id: string,
  selected: boolean,
): AgentPerceptionPolicy {
  const next = cloneAgentPerceptionPolicy(policy);
  const current = source === "team"
    ? next.sources.team.teamIds
    : next.sources.knowledge.knowledgeBaseIds;
  const updated = selected
    ? Array.from(new Set([...current, id]))
    : current.filter((value) => value !== id);
  if (source === "team") {
    next.sources.team.teamIds = updated;
  } else {
    next.sources.knowledge.knowledgeBaseIds = updated;
  }
  return next;
}

export function toggleExcludedKnowledgeBase(
  policy: AgentPerceptionPolicy,
  id: string,
  excluded: boolean,
): AgentPerceptionPolicy {
  const next = cloneAgentPerceptionPolicy(policy);
  const current = next.sources.knowledge.excludedKnowledgeBaseIds;
  next.sources.knowledge.excludedKnowledgeBaseIds = excluded
    ? Array.from(new Set([...current, id]))
    : current.filter((value) => value !== id);
  return next;
}

export function setKnowledgeBaseScope(
  policy: AgentPerceptionPolicy,
  scope: AgentPerceptionKnowledgePolicy["scope"],
): AgentPerceptionPolicy {
  const next = cloneAgentPerceptionPolicy(policy);
  next.sources.knowledge.scope = scope;
  if (scope === "all_authorized") {
    next.sources.knowledge.knowledgeBaseIds = [];
  }
  return next;
}

export function validateAgentPerceptionPolicy(policy: AgentPerceptionPolicy): string | null {
  const { background } = policy;
  if (!Number.isInteger(background.intervalMinutes) || background.intervalMinutes < 15 || background.intervalMinutes > 10_080) {
    return "background.intervalMinutes";
  }
  if (!Number.isInteger(background.dailyMaxRuns) || background.dailyMaxRuns < 0 || background.dailyMaxRuns > 96) {
    return "background.dailyMaxRuns";
  }
  if (!Number.isInteger(background.maxCallsPerRun) || background.maxCallsPerRun < 1 || background.maxCallsPerRun > 32) {
    return "background.maxCallsPerRun";
  }
  if (!Number.isInteger(background.maxInputTokensPerRun) || background.maxInputTokensPerRun < 1 || background.maxInputTokensPerRun > 131_072) {
    return "background.maxInputTokensPerRun";
  }
  if (!Number.isInteger(background.maxResultChars) || background.maxResultChars < 1 || background.maxResultChars > 50_000) {
    return "background.maxResultChars";
  }
  if (background.enabled && background.topics.length === 0) {
    return "background.topics.required";
  }
  if (background.topics.length > 8 || background.topics.some((topic) => topic.trim().length === 0 || topic.length > 200)) {
    return "background.topics.invalid";
  }
  if (background.maxConcurrent !== 1) {
    return "background.maxConcurrent";
  }
  return null;
}
