export const CONFIG_DRAFT_PRESENCE_KEY = "vibelution.config-draft-presence.v1";
export const CONFIG_DRAFT_PRESENCE_EVENT = "vibelution:config-draft-presence";

const MAX_AGE_MS = 30 * 60 * 1_000;

type PresenceStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;
type PresenceDeps = {
  now: () => number;
  storage: PresenceStorage;
};

function browserDeps(): PresenceDeps | null {
  if (typeof window === "undefined") {
    return null;
  }
  return { now: () => Date.now(), storage: window.localStorage };
}

function notifySameWindow() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(CONFIG_DRAFT_PRESENCE_EVENT));
  }
}

export function publishConfigDraftPresence(
  dirty: boolean,
  deps: PresenceDeps | null = browserDeps(),
) {
  if (!deps) {
    return;
  }
  try {
    deps.storage.setItem(
      CONFIG_DRAFT_PRESENCE_KEY,
      JSON.stringify({ dirty: dirty === true, updatedAt: deps.now() }),
    );
    notifySameWindow();
  } catch {
    // Storage can be unavailable in hardened browser profiles. The caller
    // still keeps its local dirty-state guard.
  }
}

export function readConfigDraftPresence(
  deps: PresenceDeps | null = browserDeps(),
) {
  if (!deps) {
    return false;
  }
  try {
    const value = JSON.parse(
      deps.storage.getItem(CONFIG_DRAFT_PRESENCE_KEY) || "{}",
    ) as { dirty?: unknown; updatedAt?: unknown };
    const updatedAt = Number(value.updatedAt);
    const age = deps.now() - updatedAt;
    return value.dirty === true
      && Number.isFinite(updatedAt)
      && updatedAt > 0
      && age >= 0
      && age <= MAX_AGE_MS;
  } catch {
    return false;
  }
}
