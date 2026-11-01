import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchPersonalAssistantHumanAttention } from "./personalAssistant";
import { resetControlTokenForTests, seedControlTokenForTests } from "./client";

afterEach(() => { resetControlTokenForTests(); vi.unstubAllGlobals(); });
describe("personal assistant transport", () => {
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
});
