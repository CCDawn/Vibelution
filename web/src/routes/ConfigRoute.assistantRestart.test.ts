import { describe, expect, it } from "vitest";

import routeSourceRaw from "./ConfigRoute.tsx?raw";
import copySourceRaw from "./config/configCopy.ts?raw";
import apiSourceRaw from "../api/config.ts?raw";

/** B1/B5 contract: the saved provider config reaches the resident assistant
 * host through an automatic post-save restart, and an explicit restart action
 * exists for the exhausted-respawn-budget recovery. The bridge is desktop
 * only; the api layer is best-effort and never throws. */
describe("ConfigRoute assistant host restart contract", () => {
  it("restarts the host on the save success path before returning true", () => {
    // Slice CRLF-agnostically: take the whole handleApply body.
    const applyBody = routeSourceRaw.slice(
      routeSourceRaw.indexOf("async function handleApply("),
      routeSourceRaw.indexOf("async function handleSaveAndLeave"),
    );
    expect(applyBody).toContain("hasAssistantHostRestartBridge()");
    expect(applyBody).toContain("void restartAssistantHostWithNotice(\"save\")");
    expect(applyBody).toContain("text: copy.saveAssistantRestarting");
    // Order: the save already succeeded (workspace synced) before restarting.
    expect(applyBody.indexOf("syncWorkspace(response")).toBeGreaterThan(-1);
    expect(applyBody.indexOf("syncWorkspace(response")).toBeLessThan(applyBody.indexOf("saveAssistantRestarting"));
    expect(applyBody.indexOf("saveAssistantRestarting")).toBeLessThan(applyBody.indexOf("return true;"));
  });

  it("keeps the restart behind the desktop bridge probe with a pending notice", () => {
    expect(routeSourceRaw).toContain("const [assistantBridgeAvailable] = useState(() => hasAssistantHostRestartBridge());");
    expect(routeSourceRaw).toContain("text: copy.saveAssistantRestarting");
    expect(routeSourceRaw).toContain("restartAssistantHost(context === \"save\" ? \"config_apply\" : \"user_request\")");
  });

  it("renders the explicit restart action with a hint and busy gating", () => {
    expect(routeSourceRaw).toContain("title={copy.restartAssistantHint}");
    expect(routeSourceRaw).toContain("void restartAssistantHostWithNotice(\"manual\")");
    expect(routeSourceRaw).toContain("isDisabled={Boolean(busyAction) || assistantRestarting}");
  });

  it("carries bilingual restart copy for save and manual contexts", () => {
    for (const key of [
      "restartAssistant:",
      "restartAssistantHint:",
      "restartAssistantPending:",
      "restartAssistantDone:",
      "restartAssistantFailed:",
      "saveAssistantRestartDone:",
      "saveAssistantRestarting:",
      "saveAssistantRestartFailed:",
    ]) {
      const hits = copySourceRaw.split(key).length - 1;
      expect(hits).toBeGreaterThanOrEqual(2);
    }
  });

  it("keeps the api layer best-effort: no bridge means null, errors never throw", () => {
    expect(apiSourceRaw).toContain("if (typeof bridge?.invoke !== \"function\") return null;");
    expect(apiSourceRaw).toContain("} catch (error) {");
    expect(apiSourceRaw).toContain("operation: \"restartHost\"");
    expect(apiSourceRaw).toContain("\"config_apply\" | \"user_request\"");
  });
});
