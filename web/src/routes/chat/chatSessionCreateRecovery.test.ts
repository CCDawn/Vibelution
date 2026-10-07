import { describe, expect, it } from "vitest";
import {
  SESSION_CREATE_RECOVERY_KEY, buildSessionCreateShell, forgetSessionCreateRecovery,
  readSessionCreateRecovery, rememberSessionCreateRecovery, type SessionCreateRecovery,
} from "./chatSessionCreateRecovery";

const intent: SessionCreateRecovery = {
  agentId: "agent-a", tempSessionId: "temp-session-a", idempotencyKey: "session-create:a",
  createdAt: "2026-10-07T00:00:00.000Z",
};
function storage() {
  const entries = new Map<string, string>();
  return { getItem: (key: string) => entries.get(key) ?? null, setItem: (key: string, value: string) => { entries.set(key, value); } };
}

describe("session create recovery identities", () => {
  it("retains only identity fields and never copies draft or transcript data", () => {
    const store = storage();
    rememberSessionCreateRecovery({ ...intent, draft: "private draft", messages: ["transcript"] } as SessionCreateRecovery, store);
    expect(readSessionCreateRecovery(intent.tempSessionId, store)).toEqual(intent);
    expect(store.getItem(SESSION_CREATE_RECOVERY_KEY)).not.toMatch(/private draft|transcript/);
    const shell = buildSessionCreateShell(intent, "新会话");
    expect(shell.id).toBe(intent.tempSessionId);
    expect(shell.messages).toEqual([]);
    expect(shell.createdAt).toBe(intent.createdAt);
  });

  it("keeps a committed tab title across a key rotation and still drops drafts", () => {
    const store = storage();
    rememberSessionCreateRecovery({
      ...intent, title: "探测名aa5815", draft: "private draft",
    } as SessionCreateRecovery, store);
    expect(readSessionCreateRecovery(intent.tempSessionId, store)).toEqual({ ...intent, title: "探测名aa5815" });
    expect(store.getItem(SESSION_CREATE_RECOVERY_KEY)).not.toMatch(/private draft/);
    rememberSessionCreateRecovery({ ...intent, idempotencyKey: "session-create:newer" }, store);
    expect(readSessionCreateRecovery(intent.tempSessionId, store)?.title).toBe("探测名aa5815");
  });

  it("preserves a newer intent when a late callback forgets an older key", () => {
    const store = storage();
    rememberSessionCreateRecovery(intent, store);
    rememberSessionCreateRecovery({ ...intent, idempotencyKey: "session-create:newer" }, store);
    forgetSessionCreateRecovery(intent.tempSessionId, intent.idempotencyKey, store);
    expect(readSessionCreateRecovery(intent.tempSessionId, store)?.idempotencyKey).toBe("session-create:newer");
    forgetSessionCreateRecovery(intent.tempSessionId, "session-create:newer", store);
    expect(readSessionCreateRecovery(intent.tempSessionId, store)).toBeUndefined();
  });

  it.each(["broken JSON", JSON.stringify([null, { ...intent, tempSessionId: "real-session" }]),
    JSON.stringify([{ ...intent, createdAt: "invalid" }]), " ".repeat(65537)])("rejects malformed or oversized storage", (raw) => {
    const store = storage();
    store.setItem(SESSION_CREATE_RECOVERY_KEY, raw);
    expect(readSessionCreateRecovery(intent.tempSessionId, store)).toBeUndefined();
  });

  it("bounds records and handles unavailable storage without breaking creation", () => {
    const store = storage();
    for (let index = 0; index < 51; index++) rememberSessionCreateRecovery({ ...intent, tempSessionId: `temp-session-${index}` }, store);
    expect(readSessionCreateRecovery("temp-session-0", store)).toBeUndefined();
    expect(readSessionCreateRecovery("temp-session-50", store)).toBeDefined();
    const blocked = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("quota"); } };
    expect(() => rememberSessionCreateRecovery(intent, blocked)).not.toThrow();
    expect(readSessionCreateRecovery(intent.tempSessionId, blocked)).toBeUndefined();
  });
});
