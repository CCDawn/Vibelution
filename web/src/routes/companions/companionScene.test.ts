import { describe, expect, it } from "vitest";

import type { VirtualHumanSnapshot } from "../../api/types/virtualHumanLife";
import { selectCompanionScene } from "./companionScene";

function makeSnapshot(
  currentLocation: string,
  stateOverrides: Partial<NonNullable<VirtualHumanSnapshot["state"]>> = {},
  snapshotOverrides: Partial<VirtualHumanSnapshot> = {},
): VirtualHumanSnapshot {
  return {
    pluginId: "virtual-human-life",
    agentId: "agent/nora",
    installed: true,
    bound: true,
    binding: null,
    state: {
      stateVersion: 1,
      localDate: "2026-10-14",
      timezone: "Asia/Shanghai",
      currentLocation,
      currentActivityId: "",
      mood: { label: "calm", valence: 10, arousal: 20, stability: 70, updatedAt: "" },
      energy: 70,
      sleepState: "awake",
      socialNeed: 40,
      relationshipSummary: "",
      lifePaused: false,
      lastHeartbeatAt: "",
      ...stateOverrides,
    },
    todaySchedule: null,
    tomorrowSchedule: null,
    proactiveUsage: { delivered: 0, limit: 2, remaining: 2 },
    ...snapshotOverrides,
  };
}

describe("selectCompanionScene", () => {
  it.each([
    ["home", "home", "room-background-v1.png"],
    ["house", "home", "room-background-v1.png"],
    ["住处", "home", "room-background-v1.png"],
    ["家", "home", "room-background-v1.png"],
    ["library", "library", "library-background-v1.png"],
    ["reading-room", "library", "library-background-v1.png"],
    ["school-library", "library", "library-background-v1.png"],
    ["图书馆", "library", "library-background-v1.png"],
    ["阅览室", "library", "library-background-v1.png"],
    ["studio", "studio", "studio-background-v1.png"],
    ["music-studio", "studio", "studio-background-v1.png"],
    ["创作工作室", "studio", "studio-background-v1.png"],
    ["录音室", "studio", "studio-background-v1.png"],
    ["工作室", "studio", "studio-background-v1.png"],
    ["park", "park", "park-background-v1.png"],
    ["公园", "park", "park-background-v1.png"],
  ])("maps %s to the %s scene", (location, key, filename) => {
    const selection = selectCompanionScene(makeSnapshot(location));

    expect(selection.key).toBe(key);
    expect(selection.backgroundUrl).toContain(filename);
  });

  it.each(["", "office", "apartment-style", "homework", "parked", "home-office"]) (
    "uses the neutral scene for unsupported location %j",
    (currentLocation) => {
      expect(selectCompanionScene(makeSnapshot(currentLocation))).toEqual({ key: "neutral", backgroundUrl: null });
    },
  );

  it("uses neutral when the snapshot has no life state", () => {
    expect(selectCompanionScene(makeSnapshot("home", {}, { state: null }))).toEqual({ key: "neutral", backgroundUrl: null });
  });

  it("keeps the departure scene while moving toward another location", () => {
    const snapshot = makeSnapshot("home", { locationStatus: "moving", movingTo: "library" });

    expect(selectCompanionScene(snapshot).key).toBe("home");
  });

  it("keeps home while a planned activity mentions the library", () => {
    const snapshot = makeSnapshot("home", {}, {
      todaySchedule: {
        agentId: "agent/nora",
        localDate: "2026-10-14",
        scheduleVersion: 1,
        activities: [
          { activityId: "activity-1", title: "去图书馆阅读", kind: "simulated", startAt: "", endAt: "", status: "planned", origin: "plan" },
        ],
      },
    });

    expect(selectCompanionScene(snapshot).key).toBe("home");
  });

  it("does not infer a studio location from a creative current activity", () => {
    const snapshot = makeSnapshot("home", { currentActivityId: "activity-1" }, {
      todaySchedule: {
        agentId: "agent/nora",
        localDate: "2026-10-14",
        scheduleVersion: 1,
        activities: [
          { activityId: "activity-1", title: "在创作工作室录歌", kind: "simulated", startAt: "", endAt: "", status: "in_progress", origin: "plan" },
        ],
      },
    });

    expect(selectCompanionScene(snapshot).key).toBe("home");
  });

  it("recognizes school-library as a library alias", () => {
    expect(selectCompanionScene(makeSnapshot("school-library")).key).toBe("library");
  });

  it("normalizes case and punctuation without matching partial words", () => {
    expect(selectCompanionScene(makeSnapshot("MUSIC-Studio")).key).toBe("studio");
    expect(selectCompanionScene(makeSnapshot("parked")).key).toBe("neutral");
  });
});
