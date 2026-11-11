/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetNowTickForTests, useNowTick } from "./useNowTick";

function Probe({ active, intervalMs = 1000 }: { active: boolean; intervalMs?: number }) {
  const now = useNowTick(active, intervalMs);
  return <span data-now={now} />;
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.useFakeTimers();
  resetNowTickForTests();
  setVisibility("visible");
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetNowTickForTests();
  setVisibility("visible");
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useNowTick", () => {
  it("does not own a timer while inactive", async () => {
    const setIntervalSpy = vi.spyOn(window, "setInterval");
    await act(async () => {
      root.render(<Probe active={false} />);
    });
    expect(setIntervalSpy).not.toHaveBeenCalled();
  });

  it("shares one timer per cadence across consumers", async () => {
    const setIntervalSpy = vi.spyOn(window, "setInterval");
    await act(async () => {
      root.render(
        <>
          <Probe active />
          <Probe active />
          <Probe active intervalMs={500} />
        </>,
      );
    });
    // Two cadences, three consumers: two timers total.
    expect(setIntervalSpy).toHaveBeenCalledTimes(2);
  });

  it("advances every subscriber on the shared tick", async () => {
    await act(async () => {
      root.render(
        <>
          <Probe active />
          <Probe active />
        </>,
      );
    });
    const before = Array.from(container.querySelectorAll("span")).map((node) =>
      Number(node.getAttribute("data-now")),
    );

    vi.setSystemTime(Date.now() + 2_000);
    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });

    const after = Array.from(container.querySelectorAll("span")).map((node) =>
      Number(node.getAttribute("data-now")),
    );
    expect(after[0]).toBeGreaterThan(before[0]);
    expect(after[0]).toBe(after[1]);
  });

  it("stops while the document is hidden and resumes when visible again", async () => {
    const setIntervalSpy = vi.spyOn(window, "setInterval");
    const clearIntervalSpy = vi.spyOn(window, "clearInterval");

    await act(async () => {
      root.render(<Probe active />);
    });
    expect(setIntervalSpy).toHaveBeenCalledTimes(1);

    await act(async () => {
      setVisibility("hidden");
    });
    expect(clearIntervalSpy).toHaveBeenCalled();

    await act(async () => {
      setVisibility("visible");
    });
    expect(setIntervalSpy).toHaveBeenCalledTimes(2);
  });

  it("does not start a timer while the document is already hidden", async () => {
    setVisibility("hidden");
    const setIntervalSpy = vi.spyOn(window, "setInterval");
    await act(async () => {
      root.render(<Probe active />);
    });
    expect(setIntervalSpy).not.toHaveBeenCalled();
  });

  it("releases the timer when the last consumer goes inactive", async () => {
    const clearIntervalSpy = vi.spyOn(window, "clearInterval");
    const setIntervalSpy = vi.spyOn(window, "setInterval");

    await act(async () => {
      root.render(<Probe active />);
    });
    expect(setIntervalSpy).toHaveBeenCalledTimes(1);

    await act(async () => {
      root.render(<Probe active={false} />);
    });
    expect(clearIntervalSpy).toHaveBeenCalled();

    const callsAfterRelease = setIntervalSpy.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(5_000);
    });
    expect(setIntervalSpy.mock.calls.length).toBe(callsAfterRelease);
  });
});
