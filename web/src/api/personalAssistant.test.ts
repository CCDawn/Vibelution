import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchJson } from "./client";
import { createPersonalAssistant, fetchPersonalAssistant, fetchPersonalAssistantOverview } from "./personalAssistant";

vi.mock("./client", () => ({ fetchJson: vi.fn() }));
describe("personal assistant API ownership", () => {
  beforeEach(() => vi.mocked(fetchJson).mockReset());
  it("keeps discovery and overview as reads, and provisions only through POST", async () => {
    const signal = new AbortController().signal;
    await fetchPersonalAssistant({ signal });
    expect(fetchJson).toHaveBeenLastCalledWith("/api/personal-assistant", { signal });
    await fetchPersonalAssistantOverview({ signal });
    expect(fetchJson).toHaveBeenLastCalledWith("/api/personal-assistant/overview", { signal });
    await createPersonalAssistant();
    expect(fetchJson).toHaveBeenLastCalledWith("/api/personal-assistant", expect.objectContaining({ method: "POST", body: "{}" }));
    await createPersonalAssistant("大肥鲸");
    expect(fetchJson).toHaveBeenLastCalledWith("/api/personal-assistant", expect.objectContaining({ body: JSON.stringify({ displayName: "大肥鲸" }) }));
  });
});
