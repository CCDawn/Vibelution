import { describe, expect, it } from "vitest";

import type { VirtualHumanCompanion } from "../../api/types";
import {
  companionReturnTarget,
  companionIdentity,
  currentLifeActivity,
  currentLifeActivityLabel,
  formatCompanionLocalTime,
  upcomingLifeActivities,
} from "./companionPresentation";

const companion: VirtualHumanCompanion = {
  agentId: "agent/nora",
  agentCode: "nora",
  displayName: "Nora",
  directSessionId: "session 1",
  avatarImageUrl: "",
  personaProfile: { personality: "安静、直接" },
  status: "active",
  snapshot: {
    pluginId: "virtual-human-life",
    agentId: "agent/nora",
    installed: true,
    bound: true,
    binding: null,
    state: {
      stateVersion: 1,
      localDate: "2026-08-28",
      timezone: "Asia/Shanghai",
      currentLocation: "home",
      currentActivityId: "activity-2",
      mood: { label: "calm", valence: 10, arousal: 20, stability: 70, updatedAt: "" },
      energy: 70,
      sleepState: "awake",
      socialNeed: 40,
      relationshipSummary: "",
      lifePaused: false,
      lastHeartbeatAt: "",
    },
    todaySchedule: {
      agentId: "agent/nora",
      localDate: "2026-08-28",
      scheduleVersion: 1,
      activities: [
        { activityId: "activity-1", title: "早餐", kind: "simulated", startAt: "", endAt: "", status: "completed", origin: "plan" },
        { activityId: "activity-2", title: "阅读", kind: "simulated", startAt: "", endAt: "", status: "in_progress", origin: "plan" },
        { activityId: "activity-3", title: "散步", kind: "simulated", startAt: "", endAt: "", status: "planned", origin: "plan" },
      ],
    },
    tomorrowSchedule: null,
    proactiveUsage: { delivered: 0, limit: 2, remaining: 2 },
  },
};

describe("companion presentation", () => {
  it("derives identity and life slices without inventing events", () => {
    expect(companionIdentity(companion)).toBe("安静、直接");
    expect(currentLifeActivity(companion.snapshot)?.title).toBe("阅读");
    expect(upcomingLifeActivities(companion.snapshot).map((item) => item.title)).toEqual(["阅读", "散步"]);
  });

  it("keeps settings returns on the same native companion Session", () => {
    expect(companionReturnTarget(companion)).toBe("/chat?session=session+1&companion=agent%2Fnora");
  });

  it("formats the person's real timezone without persisting a second clock", () => {
    expect(formatCompanionLocalTime(companion.snapshot, "zh", new Date("2026-08-28T00:42:00Z"))).toBe("08:42");
  });

  it("uses one human-readable fallback for sleeping, resting, and unscheduled time", () => {
    expect(currentLifeActivityLabel(companion.snapshot, "zh")).toBe("阅读");

    const withoutActivity = {
      ...companion.snapshot,
      todaySchedule: { ...companion.snapshot.todaySchedule!, activities: [] },
      state: { ...companion.snapshot.state!, currentActivityId: "", sleepState: "sleeping" },
    };
    expect(currentLifeActivityLabel(withoutActivity, "zh")).toBe("正在睡觉");
    expect(currentLifeActivityLabel(withoutActivity, "en")).toBe("Sleeping");

    const resting = {
      ...withoutActivity,
      state: { ...withoutActivity.state!, sleepState: "resting" },
    };
    expect(currentLifeActivityLabel(resting, "zh")).toBe("正在放松休息");

    const awake = {
      ...withoutActivity,
      state: { ...withoutActivity.state!, sleepState: "awake" },
    };
    expect(currentLifeActivityLabel(awake, "zh")).toBe("自由活动");
  });

});
