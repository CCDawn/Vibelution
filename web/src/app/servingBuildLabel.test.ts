import { describe, expect, it } from "vitest";

import type { BackendHealth } from "../api/types";
import { clockLabel, describeServingBuild, shortReleaseId } from "./servingBuildLabel";

function health(patch: Partial<BackendHealth>): BackendHealth {
  return { status: "ok", ...patch };
}

describe("shortReleaseId", () => {
  it("drops the release prefix and keeps a dense bar readable", () => {
    expect(shortReleaseId("release-8fb7a9925ffad3e6")).toBe("8fb7a9925f");
    expect(shortReleaseId("")).toBe("");
    expect(shortReleaseId("   ")).toBe("");
  });
});

describe("clockLabel", () => {
  it("renders HH:MM and refuses unparseable stamps", () => {
    expect(clockLabel("2026-11-23T09:05:00+00:00")).toMatch(/^\d{2}:\d{2}$/);
    expect(clockLabel("")).toBe("");
    expect(clockLabel("not-a-date")).toBe("");
  });
});

describe("describeServingBuild", () => {
  it("reports nothing rather than inventing a release for an empty payload", () => {
    const label = describeServingBuild(undefined);
    expect(label.release).toBe("");
    expect(label.startedAt).toBe("");
    expect(label.warning).toBe("");
  });

  it("states the pinned release and backend start when everything is current", () => {
    const label = describeServingBuild(
      health({
        servingRelease: "release-8fb7a9925ffad3e6",
        activeRelease: "release-8fb7a9925ffad3e6",
        servingSource: "release",
        backendStartedAt: "2026-11-23T09:05:00+00:00",
        releaseStale: false,
      }),
    );
    expect(label.release).toBe("8fb7a9925f");
    expect(label.startedAt).toMatch(/^\d{2}:\d{2}$/);
    expect(label.warning).toBe("");
  });

  it("marks a stale pointer as restart-pending and names the newer release", () => {
    const label = describeServingBuild(
      health({
        servingRelease: "release-8fb7a9925ffad3e6",
        activeRelease: "release-aeba91e48163aef1",
        servingSource: "release",
        releaseStale: true,
      }),
    );
    expect(label.warning).toBe("restart");
    expect(label.title).toContain("aeba91e481");
  });

  it("marks the legacy fallback so it can never pass as a release", () => {
    const label = describeServingBuild(
      health({
        servingRelease: "",
        servingSource: "legacy-dist",
        servingFallbackReason: "active_release_missing",
      }),
    );
    expect(label.warning).toBe("fallback");
    expect(label.release).toBe("");
    expect(label.title).toContain("active_release_missing");
  });

  it("prefers the restart marker over the fallback marker", () => {
    const label = describeServingBuild(
      health({ servingSource: "legacy-dist", releaseStale: true, activeRelease: "release-abcdef123456" }),
    );
    expect(label.warning).toBe("restart");
  });
});
