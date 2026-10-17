import { describe, expect, it, vi } from "vitest";
import { applyConfigWorkspace, previewConfigDraft } from "../../api/config";
import { persistConfigChanges, rebaseConfigDraft } from "./configImmediateSave";

vi.mock("../../api/config", () => ({ applyConfigWorkspace: vi.fn(), previewConfigDraft: vi.fn() }));

describe("isolated immediate config changes", () => {
  it("applies only the requested value with the paired baseline and no pending secrets", async () => {
    const baseline = { llm: { providers: { relay: { enabled: true, base_url: "https://saved.example" } } } };
    const next = structuredClone(baseline);
    next.llm.providers.relay.enabled = false;
    vi.mocked(previewConfigDraft).mockResolvedValueOnce({ publicConfig: next } as never);
    vi.mocked(applyConfigWorkspace).mockResolvedValueOnce({ publicConfig: next } as never);
    await persistConfigChanges(baseline, "saved-hash", [{ path: ["llm", "providers", "relay", "enabled"], value: false }]);
    expect(previewConfigDraft).toHaveBeenLastCalledWith({ publicConfig: next, baseHash: "saved-hash", draftMeta: { pending_api_keys: {}, pending_cleared_api_keys: [] } });
    expect(applyConfigWorkspace).toHaveBeenLastCalledWith({ publicConfig: next, baseConfig: baseline, baseHash: "saved-hash", draftMeta: { pending_api_keys: {}, pending_cleared_api_keys: [] } });
  });

  it("does not retry conflicts as an unbound full snapshot", async () => {
    vi.mocked(previewConfigDraft).mockResolvedValueOnce({ publicConfig: { enabled: false } } as never);
    vi.mocked(applyConfigWorkspace).mockClear().mockRejectedValueOnce(new Error("edit baseline is stale"));
    await expect(persistConfigChanges({ enabled: true }, "old", [{ path: ["enabled"], value: false }])).rejects.toThrow("stale");
    expect(applyConfigWorkspace).toHaveBeenCalledTimes(1);
  });

  it("preserves local additions, deletions and arrays while adopting saved values and unrelated external edits", () => {
    const base = { enabled: true, name: "old", remove: { enabled: true }, models: { "model.v1": { enabled: true, label: "old" } }, list: ["old"] };
    const draft = { enabled: true, name: "edited", added: { token: "draft-only" }, models: { "model.v1": { enabled: true, label: "draft label" } }, list: ["edited"] };
    const saved = { ...base, enabled: false, external: "keep", models: { "model.v1": { enabled: false, label: "old" } } };
    expect(rebaseConfigDraft(base, draft, saved, [["enabled"], ["models", "model.v1", "enabled"]])).toEqual({
      enabled: false, name: "edited", added: { token: "draft-only" }, external: "keep",
      models: { "model.v1": { enabled: false, label: "draft label" } }, list: ["edited"],
    });
    expect(base.enabled).toBe(true);
    expect(draft.models["model.v1"].enabled).toBe(true);
  });

  it("overlays the saved field inside a locally edited array without replacing its other values", () => {
    const base = { rows: [{ enabled: true, label: "saved" }] };
    const local = { rows: [{ enabled: true, label: "draft" }] };
    const saved = { rows: [{ enabled: false, label: "saved" }] };
    expect(rebaseConfigDraft(base, local, saved, [["rows", "0", "enabled"]])).toEqual({ rows: [{ enabled: false, label: "draft" }] });
  });
});
