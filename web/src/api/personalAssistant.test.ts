import { afterEach, describe, expect, it, vi } from "vitest";
import { createPersonalAssistant, fetchPersonalAssistant, fetchPersonalAssistantHumanAttention, fetchPersonalAssistantOverview } from "./personalAssistant";
import { resetControlTokenForTests, seedControlTokenForTests } from "./client";
import type { PersonalAssistantOverview } from "./types/personalAssistant";

afterEach(() => { resetControlTokenForTests(); vi.unstubAllGlobals(); });
function page(offset: number, nextOffset: number | null): PersonalAssistantOverview {
  const total = offset === 0 && nextOffset === null ? 1 : 125;
  const indices = Array.from({ length: Math.min(100, total - offset) }, (_, index) => offset + index);
  return { generatedAt: "2026-10-16T13:00:00Z", counts: { agents: total, sessions: total, running: 1, waiting: 0, failed: 0 },
    agents: indices.map(index => ({ id: `agent-${index}`, displayName: "助手", status: "active" })),
    sessions: indices.map(index => ({ id: `session-${index}`, agentId: `agent-${index}`, title: "任务", status: "running", currentPhase: "reading", turnId: `turn-${index}` })),
    attention: [], pagination: { offset, limit: 100, nextOffset } };
}
describe("personal assistant overview transport", () => {
  it.each([{ humanAttention: [] }, { humanAttention: [{ id: "gate-1", kind: "human_gate", title: "待审批", actions: [{ label: "接受", decision: "accept" }], meta: { runId: "run-7" } }] }])(
    "reads human attention in one request without overview pagination: %j", async payload => {
      seedControlTokenForTests();
      const request = vi.fn<typeof fetch>().mockResolvedValue(Response.json(payload));
      vi.stubGlobal("fetch", request);
      const signal = new AbortController().signal;
      await expect(fetchPersonalAssistantHumanAttention({ signal })).resolves.toEqual(payload);
      expect(request).toHaveBeenCalledTimes(1);
      expect(request.mock.calls[0][0]).toBe("/api/personal-assistant/human-attention");
      expect(request.mock.calls[0][1]?.method ?? "GET").toBe("GET");
      expect(request.mock.calls[0][1]?.signal).toBe(signal);
    },
  );
  it("keeps discovery and overview read-only and provisions only through POST", async () => {
    seedControlTokenForTests();
    const request = vi.fn<typeof fetch>(async () => Response.json(page(0, null)));
    vi.stubGlobal("fetch", request);
    const signal = new AbortController().signal;
    await fetchPersonalAssistant({ signal });
    await fetchPersonalAssistantOverview({ signal });
    await createPersonalAssistant();
    await createPersonalAssistant("大肥鲸");
    expect(request.mock.calls[0][0]).toBe("/api/personal-assistant");
    expect(request.mock.calls[0][1]?.method ?? "GET").toBe("GET");
    expect(request.mock.calls[1][0]).toBe("/api/personal-assistant/overview");
    expect(request.mock.calls[1][1]?.method ?? "GET").toBe("GET");
    expect(request.mock.calls[2][1]).toMatchObject({ method: "POST", body: "{}" });
    expect(request.mock.calls[3][1]).toMatchObject({ method: "POST", body: JSON.stringify({ displayName: "大肥鲸" }) });
  });
  it("loads subsequent pages and preserves current native turn ids", async () => {
    seedControlTokenForTests();
    const request = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(page(0, 100))).mockResolvedValueOnce(Response.json(page(100, null)));
    vi.stubGlobal("fetch", request);
    const signal = new AbortController().signal;
    const result = await fetchPersonalAssistantOverview({ signal });
    expect(result.sessions).toHaveLength(125);
    expect(result.agents).toHaveLength(125);
    expect(result.sessions[100].turnId).toBe("turn-100");
    expect(String(request.mock.calls[1][0])).toContain("offset=100");
    expect(request.mock.calls.every(([, options]) => options?.signal === signal)).toBe(true);
  });
  it("rejects a page loop instead of reporting an incomplete overview", async () => {
    seedControlTokenForTests();
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json(page(0, 0))));
    await expect(fetchPersonalAssistantOverview()).rejects.toThrow("分页");
  });
  it("surfaces later page errors without returning a partial success", async () => {
    seedControlTokenForTests();
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(page(0, 100)))
      .mockResolvedValueOnce(Response.json({ detail: "page unavailable" }, { status: 503 })));
    await expect(fetchPersonalAssistantOverview()).rejects.toThrow("page unavailable");
  });
  it("rejects truncated or changing totals instead of claiming full coverage", async () => {
    seedControlTokenForTests();
    const incomplete = { ...page(0, null), counts: { ...page(0, null).counts, sessions: 117 } };
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json(incomplete)));
    await expect(fetchPersonalAssistantOverview()).rejects.toThrow("不完整");
  });
  it("rejects reordered attention pages that silently omit an approval", async () => {
    seedControlTokenForTests();
    const first = page(0, 100), last = page(100, null);
    first.counts.waiting = last.counts.waiting = 101;
    first.attention = Array.from({ length: 100 }, (_, id) => ({ id: `approval-${id}`, kind: "approval", title: "待确认" }));
    last.attention = [first.attention[99]];
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(first)).mockResolvedValueOnce(Response.json(last)));
    await expect(fetchPersonalAssistantOverview()).rejects.toThrow("不完整");
  });
  it("rejects a changed public snapshot even if totals stayed equal", async () => {
    seedControlTokenForTests();
    const first = page(0, 100), last = page(100, null);
    first.pagination!.revision = "before"; last.pagination!.revision = "after";
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(first)).mockResolvedValueOnce(Response.json(last)));
    await expect(fetchPersonalAssistantOverview()).rejects.toThrow("分页期间已变化");
  });
  it("accepts additive knowledge/anomaly docks without treating them as Session approvals", async () => {
    seedControlTokenForTests();
    const overview = page(0, null);
    overview.counts.waiting = 1;
    overview.attention = [
      { id: "approval-1", kind: "approval", title: "待审批" },
      { id: "review-1", kind: "knowledge_review", title: "待复核" },
      { id: "anomaly-1", kind: "anomaly", title: "异常" },
    ];
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json(overview)));
    expect((await fetchPersonalAssistantOverview()).attention).toHaveLength(3);
    overview.attention = overview.attention.filter(row => row.kind !== "approval");
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json(overview)));
    await expect(fetchPersonalAssistantOverview()).rejects.toThrow("不完整");
  });
});
