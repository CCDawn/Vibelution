import type { SessionSummary } from "../api/types";

/**
 * User-defined grouping for the horizontal Agent session tab strip.
 *
 * Grouping is a viewing affordance, exactly like `agentSessionTabOrder`: the
 * group list plus the session -> group map are persisted per Agent in
 * localStorage so a manual arrangement survives reloads and session refetches.
 *
 * Semantics (v1):
 * - Folder, not tag: one session belongs to at most one group.
 * - Empty groups are not rendered, so closing the last tab of a group does not
 *   leave a stray header behind. The group definition itself is kept, so
 *   reopening the session puts it back where it was.
 * - The ungrouped section is a fixed fallback: it cannot be renamed or deleted
 *   and always renders last.
 * - Deleting a group releases its members back to the ungrouped section.
 */
const STORAGE_KEY = "vibelution.agentSessionTabGroups.v1";

/** Section id of the fixed fallback bucket (sessions without a group). */
export const UNGROUPED_SECTION_ID = "ungrouped";

/**
 * Fixed palette. Group colour is an accent only: it tints the section rail
 * and the header dot, never the tab selection ring (that stays the VUI accent).
 */
export const TAB_GROUP_COLORS = ["gray", "blue", "green", "amber", "violet", "rose"] as const;
export type AgentSessionTabGroupColor = (typeof TAB_GROUP_COLORS)[number];

export type AgentSessionTabGroup = {
  id: string;
  name: string;
  collapsed: boolean;
  color?: AgentSessionTabGroupColor;
};

export type AgentSessionTabGroupState = {
  groups: AgentSessionTabGroup[];
  /** sessionId -> groupId. Ids missing here render in the ungrouped section. */
  membership: Record<string, string>;
};

export type AgentSessionTabGroupSection = {
  groupId: string;
  name: string;
  collapsed: boolean;
  ungrouped: boolean;
  sessions: SessionSummary[];
};

type AgentTabGroupStore = Record<string, AgentSessionTabGroupState>;

/** localStorage accessor that also works when only globalThis is stubbed. */
function sessionTabGroupStorage(): Storage | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export function emptyAgentSessionTabGroupState(): AgentSessionTabGroupState {
  return { groups: [], membership: {} };
}

function sanitizeGroup(raw: unknown): AgentSessionTabGroup | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return null;
  }
  const candidate = raw as Record<string, unknown>;
  const id = String(candidate.id ?? "").trim();
  const name = String(candidate.name ?? "").trim();
  if (!id || !name) {
    return null;
  }
  const rawColor = String(candidate.color ?? "").trim();
  const base = { id, name, collapsed: candidate.collapsed === true };
  if (!(TAB_GROUP_COLORS as readonly string[]).includes(rawColor)) {
    return base;
  }
  // Unknown colours degrade to the default accent instead of failing the load.
  return { ...base, color: rawColor as AgentSessionTabGroupColor };
}

function sanitizeState(raw: unknown): AgentSessionTabGroupState {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return emptyAgentSessionTabGroupState();
  }
  const candidate = raw as Record<string, unknown>;
  const groups: AgentSessionTabGroup[] = [];
  const known = new Set<string>();
  if (Array.isArray(candidate.groups)) {
    for (const entry of candidate.groups) {
      const group = sanitizeGroup(entry);
      if (!group || known.has(group.id)) {
        continue;
      }
      known.add(group.id);
      groups.push(group);
    }
  }
  const membership: Record<string, string> = {};
  const rawMembership = candidate.membership;
  if (rawMembership && typeof rawMembership === "object" && !Array.isArray(rawMembership)) {
    for (const [sessionId, groupId] of Object.entries(rawMembership as Record<string, unknown>)) {
      const sessionKey = String(sessionId || "").trim();
      const groupKey = String(groupId ?? "").trim();
      // Dangling membership (group already deleted) degrades to "ungrouped".
      if (!sessionKey || !groupKey || !known.has(groupKey)) {
        continue;
      }
      membership[sessionKey] = groupKey;
    }
  }
  return { groups, membership };
}

function readStore(): AgentTabGroupStore {
  try {
    const raw = sessionTabGroupStorage()?.getItem(STORAGE_KEY) ?? null;
    if (!raw) {
      return {};
    }
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    const store: AgentTabGroupStore = {};
    for (const [agentId, value] of Object.entries(parsed as Record<string, unknown>)) {
      const agentKey = String(agentId || "").trim();
      if (!agentKey) {
        continue;
      }
      store[agentKey] = sanitizeState(value);
    }
    return store;
  } catch {
    return {};
  }
}

function writeStore(store: AgentTabGroupStore): void {
  try {
    const storage = sessionTabGroupStorage();
    if (!storage) {
      return;
    }
    for (const [agentId, state] of Object.entries(store)) {
      if (!state.groups.length) {
        delete store[agentId];
      }
    }
    if (!Object.keys(store).length) {
      storage.removeItem(STORAGE_KEY);
      return;
    }
    storage.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    // Storage full or blocked: the strip falls back to one ungrouped section.
  }
}

export function readAgentSessionTabGroupState(agentId: string): AgentSessionTabGroupState {
  const normalized = String(agentId || "").trim();
  if (!normalized) {
    return emptyAgentSessionTabGroupState();
  }
  return readStore()[normalized] ?? emptyAgentSessionTabGroupState();
}

export function writeAgentSessionTabGroupState(
  agentId: string,
  state: AgentSessionTabGroupState,
): void {
  const normalized = String(agentId || "").trim();
  if (!normalized) {
    return;
  }
  const store = readStore();
  const next = sanitizeState(state);
  if (!next.groups.length) {
    delete store[normalized];
  } else {
    store[normalized] = next;
  }
  writeStore(store);
}

function createGroupId(): string {
  return `grp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Next free default name so two quick creations never collide. */
export function defaultAgentSessionTabGroupName(
  state: AgentSessionTabGroupState,
  fallbackPrefix = "分组",
): string {
  const used = new Set(state.groups.map((group) => group.name));
  let index = state.groups.length + 1;
  let name = `${fallbackPrefix} ${index}`;
  while (used.has(name)) {
    index += 1;
    name = `${fallbackPrefix} ${index}`;
  }
  return name;
}

export function createAgentSessionTabGroup(
  state: AgentSessionTabGroupState,
  name: string,
  options?: { id?: string },
): { state: AgentSessionTabGroupState; groupId: string } {
  const requestedId = String(options?.id ?? "").trim();
  const groupId = requestedId || createGroupId();
  if (state.groups.some((group) => group.id === groupId)) {
    return { state, groupId };
  }
  const trimmedName = String(name || "").trim() || defaultAgentSessionTabGroupName(state);
  return {
    state: {
      groups: [...state.groups, { id: groupId, name: trimmedName, collapsed: false }],
      membership: { ...state.membership },
    },
    groupId,
  };
}

export function renameAgentSessionTabGroup(
  state: AgentSessionTabGroupState,
  groupId: string,
  name: string,
): AgentSessionTabGroupState {
  const trimmed = String(name || "").trim();
  if (!trimmed) {
    // Empty input is a cancel, not a rename to blank.
    return state;
  }
  if (!state.groups.some((group) => group.id === groupId && group.name !== trimmed)) {
    return state;
  }
  return {
    groups: state.groups.map((group) =>
      group.id === groupId ? { ...group, name: trimmed } : group,
    ),
    membership: { ...state.membership },
  };
}

export function deleteAgentSessionTabGroup(
  state: AgentSessionTabGroupState,
  groupId: string,
): AgentSessionTabGroupState {
  if (!state.groups.some((group) => group.id === groupId)) {
    return state;
  }
  const membership: Record<string, string> = {};
  for (const [sessionId, value] of Object.entries(state.membership)) {
    if (value !== groupId) {
      membership[sessionId] = value;
    }
  }
  return {
    groups: state.groups.filter((group) => group.id !== groupId),
    membership,
  };
}

export function setAgentSessionTabGroupCollapsed(
  state: AgentSessionTabGroupState,
  groupId: string,
  collapsed: boolean,
): AgentSessionTabGroupState {
  const target = state.groups.find((group) => group.id === groupId);
  if (!target || target.collapsed === collapsed) {
    return state;
  }
  return {
    groups: state.groups.map((group) =>
      group.id === groupId ? { ...group, collapsed } : group,
    ),
    membership: { ...state.membership },
  };
}

/**
 * Move one session into `groupId`, or out of any group when `groupId` is null.
 * An unknown group id is a no-op so a stale drop target cannot invent members.
 */
export function assignSessionToTabGroup(
  state: AgentSessionTabGroupState,
  sessionId: string,
  groupId: string | null,
): AgentSessionTabGroupState {
  const sessionKey = String(sessionId || "").trim();
  if (!sessionKey) {
    return state;
  }
  const membership = { ...state.membership };
  if (!groupId) {
    if (!(sessionKey in membership)) {
      return state;
    }
    delete membership[sessionKey];
    return { groups: state.groups, membership };
  }
  if (!state.groups.some((group) => group.id === groupId)) {
    return state;
  }
  if (membership[sessionKey] === groupId) {
    return state;
  }
  membership[sessionKey] = groupId;
  return { groups: state.groups, membership };
}

/** Group id a session currently renders under, using the fallback section id. */
export function sessionTabGroupIdFor(
  state: AgentSessionTabGroupState,
  sessionId: string,
): string {
  const groupId = state.membership[String(sessionId || "").trim()];
  if (!groupId) {
    return UNGROUPED_SECTION_ID;
  }
  return state.groups.some((group) => group.id === groupId) ? groupId : UNGROUPED_SECTION_ID;
}

/**
 * Drop membership of sessions that are no longer present (deleted, archived,
 * or belonging to another agent). Without this the store grows forever.
 */
export function pruneSessionTabGroupMembership(
  state: AgentSessionTabGroupState,
  liveSessionIds: Iterable<string>,
): AgentSessionTabGroupState {
  const live = new Set<string>();
  for (const id of liveSessionIds) {
    const key = String(id || "").trim();
    if (key) {
      live.add(key);
    }
  }
  const membership: Record<string, string> = {};
  let dropped = false;
  for (const [sessionId, groupId] of Object.entries(state.membership)) {
    if (live.has(sessionId)) {
      membership[sessionId] = groupId;
    } else {
      dropped = true;
    }
  }
  return dropped ? { groups: state.groups, membership } : state;
}

/**
 * Split an already ordered session list into renderable sections. Groups keep
 * their stored order; the ungrouped section always renders last and only when
 * it has members.
 */
export function resolveSessionTabGroupSections(
  sessions: readonly SessionSummary[],
  state: AgentSessionTabGroupState,
  options?: { ungroupedName?: string },
): AgentSessionTabGroupSection[] {
  const buckets = new Map<string, SessionSummary[]>();
  for (const group of state.groups) {
    buckets.set(group.id, []);
  }
  const ungrouped: SessionSummary[] = [];
  for (const session of sessions) {
    const groupId = state.membership[session.id];
    const bucket = groupId ? buckets.get(groupId) : undefined;
    if (bucket) {
      bucket.push(session);
    } else {
      ungrouped.push(session);
    }
  }
  const sections: AgentSessionTabGroupSection[] = [];
  for (const group of state.groups) {
    const members = buckets.get(group.id) ?? [];
    sections.push({
      groupId: group.id,
      name: group.name,
      collapsed: group.collapsed,
      ungrouped: false,
      sessions: members,
    });
  }
  if (ungrouped.length) {
    sections.push({
      groupId: UNGROUPED_SECTION_ID,
      name: options?.ungroupedName || "未分组",
      collapsed: false,
      ungrouped: true,
      sessions: ungrouped,
    });
  }
  return sections;
}

export function setAgentSessionTabGroupColor(
  state: AgentSessionTabGroupState,
  groupId: string,
  color: AgentSessionTabGroupColor | null,
): AgentSessionTabGroupState {
  const target = state.groups.find((group) => group.id === groupId);
  if (!target || (target.color ?? null) === (color ?? null)) {
    return state;
  }
  return {
    groups: state.groups.map((group) => {
      if (group.id !== groupId) {
        return group;
      }
      if (!color) {
        const stripped: AgentSessionTabGroup = {
          id: group.id,
          name: group.name,
          collapsed: group.collapsed,
        };
        return stripped;
      }
      return { ...group, color };
    }),
    membership: { ...state.membership },
  };
}

/**
 * Folder-style merge: put every listed session into one brand-new group.
 *
 * Used by "drop a tab on the middle of another tab", which must not extend an
 * existing group (one session belongs to one group). Fewer than two distinct
 * sessions is a no-op so a stray drop cannot create an empty group.
 */
export function mergeSessionsIntoTabGroup(
  state: AgentSessionTabGroupState,
  sessionIds: readonly string[],
  name: string,
  options?: { id?: string },
): { state: AgentSessionTabGroupState; groupId: string } {
  const unique: string[] = [];
  for (const raw of sessionIds) {
    const key = String(raw || "").trim();
    if (key && !unique.includes(key)) {
      unique.push(key);
    }
  }
  if (unique.length < 2) {
    return { state, groupId: "" };
  }
  const created = createAgentSessionTabGroup(state, name, options);
  let next = created.state;
  for (const sessionId of unique) {
    next = assignSessionToTabGroup(next, sessionId, created.groupId);
  }
  return { state: next, groupId: created.groupId };
}

/** Accent colour of a group, or null when the group has no colour set. */
export function sessionTabGroupColorFor(
  state: AgentSessionTabGroupState,
  groupId: string,
): AgentSessionTabGroupColor | null {
  const group = state.groups.find((item) => item.id === groupId);
  return group?.color ?? null;
}
