import type { FSWatcher } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  isActiveReleasePointerEvent,
  startLauncherActiveReleaseWatcher
} from "../src/process/launcherActiveReleaseWatcher.js";

type Listener = (event: string, filename: string | null) => void;

function makeFakeWatch(): {
  watchFn: (
    root: string,
    listener: (event: string, filename: string | null) => void
  ) => FSWatcher;
  emit: (event: string, filename: string | null) => void;
  close: ReturnType<typeof vi.fn>;
} {
  let listener: Listener | null = null;
  const close = vi.fn();
  const instance = {
    on: (_event: "error", _handler: (error: Error) => void) => instance,
    close: () => close()
  } as unknown as FSWatcher;
  const watchFn = vi.fn(
    (_root: string, nextListener: (event: string, filename: string | null) => void): FSWatcher => {
      listener = nextListener;
      return instance;
    }
  );
  return {
    watchFn: watchFn as unknown as (
      root: string,
      listener: (event: string, filename: string | null) => void
    ) => FSWatcher,
    emit: (event: string, filename: string | null) => listener?.(event, filename),
    close
  };
}

describe("launcherActiveReleaseWatcher", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("matches only events that may touch the active release pointer", () => {
    expect(isActiveReleasePointerEvent("active.json")).toBe(true);
    expect(isActiveReleasePointerEvent("builds\\active.json")).toBe(true);
    expect(isActiveReleasePointerEvent(null)).toBe(true);
    expect(isActiveReleasePointerEvent("release-a/index.html")).toBe(false);
    expect(isActiveReleasePointerEvent("stage-abc")).toBe(false);
  });

  it("ignores events that do not touch the active release pointer", () => {
    const fake = makeFakeWatch();
    const onChange = vi.fn();
    startLauncherActiveReleaseWatcher({
      buildsRoot: "C:/repo/web/.vibelution-builds",
      onChange,
      watchFn: fake.watchFn
    });
    fake.emit("change", "release-a/index.html");
    fake.emit("rename", "stage-xyz");
    vi.advanceTimersByTime(1000);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("fires a debounced change when the active pointer is replaced", () => {
    const fake = makeFakeWatch();
    const onChange = vi.fn();
    startLauncherActiveReleaseWatcher({
      buildsRoot: "C:/repo/web/.vibelution-builds",
      onChange,
      watchFn: fake.watchFn
    });
    fake.emit("rename", "active.json");
    expect(onChange).not.toHaveBeenCalled();
    vi.advanceTimersByTime(250);
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("coalesces bursts of pointer events into one change", () => {
    const fake = makeFakeWatch();
    const onChange = vi.fn();
    startLauncherActiveReleaseWatcher({
      buildsRoot: "C:/repo/web/.vibelution-builds",
      onChange,
      watchFn: fake.watchFn
    });
    fake.emit("rename", "active.json");
    fake.emit("change", "active.json");
    fake.emit("rename", null);
    vi.advanceTimersByTime(250);
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("stop cancels a pending change and closes the watcher", () => {
    const fake = makeFakeWatch();
    const onChange = vi.fn();
    const handle = startLauncherActiveReleaseWatcher({
      buildsRoot: "C:/repo/web/.vibelution-builds",
      onChange,
      watchFn: fake.watchFn
    });
    expect(handle).not.toBeNull();
    fake.emit("rename", "active.json");
    handle?.stop();
    vi.advanceTimersByTime(1000);
    expect(onChange).not.toHaveBeenCalled();
    expect(fake.close).toHaveBeenCalledTimes(1);
  });

  it("returns null when the builds root cannot be watched", () => {
    const onChange = vi.fn();
    const handle = startLauncherActiveReleaseWatcher({
      buildsRoot: "C:/missing/web/.vibelution-builds",
      onChange,
      watchFn: () => {
        throw new Error("ENOENT");
      }
    });
    expect(handle).toBeNull();
  });
});
