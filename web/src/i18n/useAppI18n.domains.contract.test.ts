import { describe, expect, it } from "vitest";

import chatRouteSource from "../routes/chat/ChatCodingRouteWorkbench.tsx?raw";
import evolutionRouteSource from "../routes/EvolutionRoute.tsx?raw";
import toolsRouteSource from "../routes/ToolsRoute.tsx?raw";
import logsRouteSource from "../routes/LogsRoute.tsx?raw";
import petRouteSource from "../routes/PetRoute.tsx?raw";
import conversationViewSource from "../components/conversation/ConversationView.tsx?raw";

import appShellSource from "../app/AppShell.tsx?raw";
import useAppI18nSource from "./useAppI18n.ts?raw";
import loadSource from "./loadDictionaryDomains.ts?raw";

describe("useAppI18n domain wiring (D1 follow-up)", () => {
  it("keeps useAppI18n free of static full dictionary merges", () => {
    expect(useAppI18nSource).toContain("loadDictionaryDomains");
    expect(useAppI18nSource).not.toContain('from "./dictionary"');
    expect(loadSource).toContain("prefetchDictionaryDomains");
  });

  it("scopes primary routes to domain packs", () => {
    // Chat status rail retired (57fae148a): chat keeps chat/agents/evolution packs,
    // and no chat-route component reads pet-domain copy anymore.
    expect(chatRouteSource).toContain(
      'useAppI18n({ domains: ["chat", "agents", "evolution"] })',
    );
    expect(conversationViewSource).toContain('useAppI18n({ domains: ["chat"] })');
    expect(evolutionRouteSource).toContain('useAppI18n({ domains: ["evolution"] })');
    expect(toolsRouteSource).toContain('useAppI18n({ domains: ["tools"] })');
    expect(logsRouteSource).toContain('useAppI18n({ domains: ["logs"] })');
    expect(petRouteSource).toContain('useAppI18n({ domains: ["pet"] })');
    // Task 9: ResearchRoute retired (redirect shell); teams domain remains via Teams workbench packs.
  });

  it("warms chat dictionary packs during AppShell soft chat preload", () => {
    expect(appShellSource).toContain("prefetchDictionaryDomains");
    expect(appShellSource).toContain('prefetchDictionaryDomains(["chat"])');
  });
});
