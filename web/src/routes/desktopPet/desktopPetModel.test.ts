import { describe, expect, it, vi } from "vitest";

import type { PetActivity } from "../../api/types/petActivity";
import {
  desktopPetBridge,
  openSessionFromDesktopPet,
  petActivityRefetchInterval,
  petPhaseLabel,
} from "./desktopPetModel";

const activity = (activeCount: number, attentionCount: number): PetActivity => ({
  schemaVersion: 1,
  aggregateTone: activeCount ? "running" : "idle",
  animationState: activeCount ? "thinking" : "idle",
  activeCount,
  attentionCount,
  generatedAt: "2026-09-08T02:00:00Z",
  sessions: [],
});

describe("desktop pet model", () => {
  it("polls quickly while work or attention is present and backs off while idle", () => {
    expect(petActivityRefetchInterval(undefined)).toBe(1_000);
    expect(petActivityRefetchInterval(activity(1, 0))).toBe(1_000);
    expect(petActivityRefetchInterval(activity(0, 1))).toBe(1_000);
    expect(petActivityRefetchInterval(activity(0, 0))).toBe(3_000);
  });

  it("keeps activity phases user-readable", () => {
    expect(petPhaseLabel("tooling", "zh")).toBe("操作工具中");
    expect(petPhaseLabel("verifying", "en")).toBe("Verifying");
  });

  it("uses only the narrow pet bridge and rejects unsafe session ids", async () => {
    const openConversationFromPet = vi.fn(async () => ({ opened: true }));
    const bridge = desktopPetBridge({ vibelutionLauncher: { openConversationFromPet, launcherInvoke: vi.fn() } });

    expect(bridge).toEqual({ openConversationFromPet });
    await expect(openSessionFromDesktopPet("session-1", bridge)).resolves.toBe(true);
    await expect(openSessionFromDesktopPet("../unsafe", bridge)).resolves.toBe(false);
    expect(openConversationFromPet).toHaveBeenCalledTimes(1);
    expect(openConversationFromPet).toHaveBeenCalledWith("session-1");
  });
});
