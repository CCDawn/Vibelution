import { afterEach, describe, expect, it, vi } from "vitest";
import { createLauncherAssistantPanelTransport } from "./launcherAssistantPanels";

afterEach(() => { vi.unstubAllGlobals(); });
describe("resident assistant panel transport", () => {
  it("routes only closed operations for the fixed identity", async () => {
    const invoke = vi.fn(async () => ({ agentId: "resident", items: [] }));
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    const transport = createLauncherAssistantPanelTransport("resident");
    await transport.affairs.fetchPersonalAffairs("resident", { kind: "todo", status: "open" });
    expect(invoke).toHaveBeenCalledWith({ operation: "panelAffairs", kind: "todo", status: "open" });
    expect(() => transport.affairs.fetchPersonalAffairs("other")).toThrow("身份不匹配");
    expect(invoke).toHaveBeenCalledTimes(1);
    invoke.mockResolvedValueOnce({ agentId: "other", items: [] });
    await expect(transport.affairs.fetchPersonalAffairs("resident")).rejects.toThrow("身份不匹配");
  });
  it("does not leak URLs or agent identifiers and honors cancellation", async () => {
    const invoke = vi.fn(async () => ({ settings: null }));
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    const transport = createLauncherAssistantPanelTransport("resident");
    await transport.settings.updatePersonalAssistantModel("model-one");
    expect(invoke).toHaveBeenCalledWith({ operation: "panelModelUpdate", payload: { modelId: "model-one" } });
    const controller = new AbortController(); controller.abort();
    await expect(transport.settings.fetchPersonalAssistantSettings({ signal: controller.signal })).rejects.toThrow();
    expect(invoke).toHaveBeenCalledTimes(1);
  });
});
