/** @vitest-environment happy-dom */
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetControlTokenForTests } from "../api/client";
import { fetchResearchWorkflowLaunchOptions } from "../api/researchWorkflow";
import { createPreviewFetch } from "../../preview/frontend-ux-polish/previewApiFixture";

const fixture = { workflowId: "preview-workflow", teamId: "preview-team", questions: [], experiments: [] };
const baseUrl = "http://127.0.0.1:5298/preview/frontend-ux-polish/index.html";

afterEach(() => { resetControlTokenForTests(); vi.unstubAllGlobals(); });

describe("offline frontend preview transport", () => {
  it("serves native transport bootstrap and repeated directory reads without upstream requests", async () => {
    const fetch = vi.fn(createPreviewFetch(baseUrl, fixture));
    vi.stubGlobal("fetch", fetch);
    resetControlTokenForTests();
    expect(await fetchResearchWorkflowLaunchOptions(fixture.workflowId, { teamId: fixture.teamId })).toEqual(fixture);
    expect(await fetchResearchWorkflowLaunchOptions(fixture.workflowId, { teamId: fixture.teamId })).toEqual(fixture);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("blocks mutations, foreign teams, unrelated endpoints and foreign origins", async () => {
    const fetch = createPreviewFetch(baseUrl, fixture);
    for (const [url, method] of [
      ["/api/config/public", "POST"],
      ["/api/research/workflows/preview-workflow/launch-options?teamId=actual-team", "GET"],
      ["/api/research/workflows/preview-workflow/runs", "POST"],
      ["/api/config", "GET"],
      ["http://127.0.0.1:5173/api/config/public", "GET"],
    ]) expect((await fetch(url, { method })).status).toBe(403);
  });
});
