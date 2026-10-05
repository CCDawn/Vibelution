import { beforeEach, describe, expect, it, vi } from "vitest";
const fetchJson = vi.hoisted(() => vi.fn());
vi.mock("./client", () => ({ fetchJson }));
import { fetchFinancialPreferences, removeFinancialPreference, saveFinancialPreference } from "./financialPreferences";

describe("financial preferences transport", () => {
  beforeEach(() => fetchJson.mockReset().mockResolvedValue({}));
  it("encodes the selected owner and keeps writes out of GET", async () => {
    const controller = new AbortController();
    await fetchFinancialPreferences("owner/one", { signal: controller.signal });
    expect(fetchJson).toHaveBeenCalledWith("/api/financial-preferences/owner%2Fone", { signal: controller.signal });
    await saveFinancialPreference("owner/one", "现金流优先", "request-one");
    expect(fetchJson).toHaveBeenLastCalledWith("/api/financial-preferences/owner%2Fone", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: "现金流优先", clientRequestId: "request-one" }) });
    await removeFinancialPreference("owner/one", "item/one");
    expect(fetchJson).toHaveBeenLastCalledWith("/api/financial-preferences/owner%2Fone/item%2Fone", { method: "DELETE" });
  });
});
