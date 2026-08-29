import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { VirtualHumanCompanion } from "../../api/types";
import { CompanionProactiveSettingsPopover } from "./CompanionProactiveSettingsPopover";
import source from "./CompanionProactiveSettingsPopover.tsx?raw";

const companion: VirtualHumanCompanion = {
  agentId: "agent-luo",
  agentCode: "luo",
  displayName: "洛天依",
  directSessionId: "session-luo",
  avatarImageUrl: "/avatars/luotianyi.png",
  personaProfile: {},
  status: "online",
  snapshot: {
    pluginId: "virtual-human-life",
    agentId: "agent-luo",
    installed: true,
    bound: true,
    binding: {
      agentId: "agent-luo",
      pluginId: "virtual-human-life",
      enabled: true,
      configVersion: 4,
      bindingRevision: 7,
      proactiveMessagesEnabled: true,
      proactiveDailyLimit: 10,
      proactiveMinimumIntervalMinutes: 60,
    },
    state: null,
    todaySchedule: null,
    tomorrowSchedule: null,
    proactiveUsage: { delivered: 2, limit: 10, remaining: 8 },
  },
};

describe("CompanionProactiveSettingsPopover", () => {
  it("renders the current proactive profile from the companion binding", () => {
    const queryClient = new QueryClient();
    const html = renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <CompanionProactiveSettingsPopover companion={companion} lang="zh" />
      </QueryClientProvider>,
    );

    expect(html).toContain("主动联系");
    expect(html).toContain("自然");
  });

  it("updates the existing Agent-scoped binding without replacing unrelated config", () => {
    expect(source).toContain("updateAgentPluginBinding(companion.agentId, PLUGIN_ID");
    expect(source).toContain("expectedVersion: binding.configVersion");
    expect(source).toContain("mergeVirtualHumanBindingConfig(binding");
    expect(source).toContain("queryKeys.virtualHumanCompanions()");
    expect(source).toContain("VIRTUAL_HUMAN_PROACTIVE_PRESETS");
  });
});
