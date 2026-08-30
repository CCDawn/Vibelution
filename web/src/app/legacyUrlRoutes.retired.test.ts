import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import routerSource from "./router.tsx?raw";

const routesRoot = resolve(import.meta.dirname, "../routes");

describe("legacy frontend URL redirects retired", () => {
  it("does not mount compatibility redirect routes or components", () => {
    expect(routerSource).not.toContain("LegacyChatRoomsRedirect");
    expect(routerSource).not.toContain("LegacyTeamsRedirect");
    expect(routerSource).not.toContain("LegacyMemoryRedirect");
    expect(routerSource).not.toContain("LegacyEvolutionRedirect");
    expect(routerSource).not.toContain("research-workflow");
    expect(routerSource).not.toContain('path: "chat-rooms"');
    expect(routerSource).not.toContain('path: "agents/teams"');
    expect(routerSource).not.toContain('path: "agents/memory"');
    expect(routerSource).not.toMatch(/path:\s*"evolution"/);
    expect(routerSource).toContain('path: "chat"');
    expect(routerSource).toContain('path: "teams"');
    expect(routerSource).toContain('path: "memory"');
    expect(routerSource).toContain('path: "supervised-evolution"');
  });

  it("removes leftover Legacy*Redirect modules", () => {
    for (const name of [
      "LegacyChatRoomsRedirect.tsx",
      "LegacyTeamsRedirect.tsx",
      "LegacyMemoryRedirect.tsx",
      "LegacyEvolutionRedirect.tsx",
    ]) {
      expect(existsSync(resolve(routesRoot, name))).toBe(false);
    }
  });
});
