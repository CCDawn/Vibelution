import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";
import type { PersonalAssistant } from "../../api/types/personalAssistant";
import { personalAssistantReturnTarget, personalAssistantSessionMatches, validPersonalAssistant } from "./personalAssistantModel";
import hostSource from "../chat/ChatCodingRouteWorkbench.tsx?raw";
import tabSource from "../chat/ChatCodingCenterTabs.tsx?raw";
import conversationSurfaceSource from "../chat/useChatConversationSurfaceModel.tsx?raw";
import desktopSource from "../desktopPet/DesktopAssistantRoute.tsx?raw";
import routeSource from "../PersonalAssistantRoute.tsx?raw";
import routerSource from "../../app/router.tsx?raw";
import shellSource from "../../app/AppShell.tsx?raw";
import returnSource from "./DesktopAssistantReturnNotice.tsx?raw";
const styleSource = readFileSync(new URL("./personal-assistant.tailwind.css", import.meta.url), "utf8");

const assistant: PersonalAssistant = { agentId: "assistant-agent", directSessionId: "assistant-session", displayName: "个人助理",
  status: "active", setupStatus: "ready", profile: "personal_assistant_v1", renderer: "whale" };

describe("personal assistant native identity and presentation", () => {
  it("requires ready canonical Agent and direct Session identity, rather than a URL marker", () => {
    expect(validPersonalAssistant(assistant)).toBe(true);
    expect(validPersonalAssistant({ ...assistant, setupStatus: "session_missing" })).toBe(false);
    for (const session of [undefined, { id: "other", agentId: assistant.agentId },
      { id: assistant.directSessionId, agentId: "other" }, { id: assistant.directSessionId, agentId: assistant.agentId, agentMissing: true },
      { id: assistant.directSessionId, agentId: assistant.agentId, sessionKind: "child" }]) {
      expect(personalAssistantSessionMatches(assistant, session)).toBe(false);
    }
    expect(personalAssistantSessionMatches(assistant, { id: assistant.directSessionId, agentId: assistant.agentId, sessionKind: "main" })).toBe(true);
  });
  it("shares native chat and layout memory while preserving the existing finance-specific features", () => {
    expect(routeSource).toContain("state.verified ? nativeWorkspace");
    expect(desktopSource).toContain("state.verified ? nativeWorkspace");
    expect(desktopSource).toContain("queryFn: getDesktopAssistantContext");
    expect(desktopSource).toContain("usePersonalAssistant(context.isSuccess)");
    expect(hostSource).toContain('const financeSurface = location.pathname === "/finance"');
    expect(hostSource).toContain('const personalAssistantSurface = location.pathname === "/personal-assistant" || location.pathname === "/desktop-assistant"');
    expect(hostSource).toContain("const embeddedSurface = financeSurface || personalAssistantSurface");
    expect(hostSource).toContain("indexRailEnabled: !embeddedSurface");
    expect(hostSource).toContain("financeSurface={embeddedSurface}");
    expect(tabSource).toContain("showSessionTabs={!financeSurface");
    expect(hostSource).toContain("{financeSurface ? <FinancialResearchLiveProjection");
    expect(conversationSurfaceSource).toContain('composer: financeSurface ?');
    expect(hostSource).toContain("turnModelSelection: financeSurface &&");
    expect(conversationSurfaceSource).toContain("turnModelControl: financeSurface || verifiedCompanionMode");
    expect(WORKBENCH_LAYOUT_IDS.personalAssistant).toBe("personal-assistant");
    expect(WORKBENCH_LAYOUT_IDS.desktopAssistant).toBe("desktop-assistant");
    expect(styleSource).toContain('@source "../PersonalAssistantRoute.tsx"');
    expect(styleSource).toContain('@source "../desktopPet/DesktopAssistantRoute.tsx"');
  });
  it("returns only to the fixed assistant surface and leaves final Session verification to that page", () => {
    expect(personalAssistantReturnTarget("session:a")).toEqual({ pathname: "/personal-assistant", search: "?session=session%3Aa" });
    expect(shellSource).toContain("<DesktopAssistantReturnNotice />");
    expect(returnSource).toContain("subscribeDesktopAssistantOpened(browserDesktopNotificationBridge()");
    expect(returnSource).toContain("navigate(personalAssistantReturnTarget(sessionId))");
  });
  it("unifies the floating pet window and the personal assistant into one surface with one identity", () => {
    expect(routerSource).toContain('path: "/desktop-assistant"');
    expect(routerSource).toContain('path: "/desktop-pet"');
    expect(routerSource).toContain('<Navigate to="/desktop-assistant" replace />');
    expect(routerSource).not.toContain("DesktopPetRoute");
    // One identity: the collapsed body is the same assistant (one Agent, one Session);
    // the visible character is an appearance preference, not a second companion.
    expect(desktopSource).toContain("DesktopPetCharacter");
    expect(desktopSource).toContain("usePetPreferences(state.verified)");
    expect(desktopSource).toContain("nextDesktopPetCharacter");
    expect(desktopSource).not.toContain("WhaleRigCharacter");
    // The legacy pet interactions stay: IPC window drag, privacy switches, live sessions.
    expect(desktopSource).toContain("desktopPetWindowDragBridge");
    expect(desktopSource).toContain("persistPreferences(patch)");
    expect(desktopSource).toContain("<PersonalAssistantSettings");
    expect(desktopSource).toContain("openSessionFromDesktopPet");
    expect(desktopSource).toContain("useAssistantActivity");
    expect(desktopSource).toContain('data-assistant-chat="compact"');
    expect(desktopSource).not.toContain("PersonalAssistantOverview");
    expect(desktopSource).toContain('data-vui-domain-recipe="desktop-assistant"');
    expect(desktopSource).not.toContain('data-vui-domain-recipe="desktop-pet"');
  });
});
