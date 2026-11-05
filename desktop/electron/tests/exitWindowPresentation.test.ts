import { describe, expect, it, vi } from "vitest";
import { hideDesktopShellWindowsForExit } from "../src/shutdown/exitWindowPresentation.js";

function windowFixture(initial: { visible?: boolean; destroyed?: boolean; minimized?: boolean; maximized?: boolean } = {}) {
  const state = {
    visible: true,
    destroyed: false,
    minimized: false,
    maximized: false,
    ...initial,
    bounds: { x: 120, y: 80, width: 900, height: 650 },
  };
  return {
    state,
    isDestroyed: vi.fn(() => state.destroyed),
    isVisible: vi.fn(() => state.visible && !state.minimized),
    isMinimized: vi.fn(() => state.minimized),
    hide: vi.fn(() => { state.visible = false; }),
    showInactive: vi.fn(() => { state.visible = true; state.minimized = false; }),
    minimize: vi.fn(() => { state.minimized = true; }),
    setBounds: vi.fn(),
    restore: vi.fn(),
    maximize: vi.fn(),
    unmaximize: vi.fn(),
    close: vi.fn(),
    destroy: vi.fn(),
  };
}

describe("hideDesktopShellWindowsForExit", () => {
  it("synchronously hides only visible live windows and restores their visibility once", () => {
    const visible = windowFixture();
    const secondVisible = windowFixture();
    const hidden = windowFixture({ visible: false });
    const destroyed = windowFixture({ destroyed: true });

    const presentation = hideDesktopShellWindowsForExit([visible, hidden, destroyed, secondVisible]);

    expect(visible.state.visible).toBe(false);
    expect(secondVisible.state.visible).toBe(false);
    expect(hidden.hide).not.toHaveBeenCalled();
    expect(destroyed.hide).not.toHaveBeenCalled();
    expect(destroyed.isVisible).not.toHaveBeenCalled();
    expect(destroyed.isMinimized).not.toHaveBeenCalled();

    presentation.restore();
    presentation.restore();

    expect(visible.state.visible).toBe(true);
    expect(secondVisible.state.visible).toBe(true);
    expect(visible.showInactive).toHaveBeenCalledOnce();
    expect(secondVisible.showInactive).toHaveBeenCalledOnce();
    expect(hidden.showInactive).not.toHaveBeenCalled();
    expect(destroyed.showInactive).not.toHaveBeenCalled();
  });

  it("hides an originally minimized window whose isVisible returns false and re-minimizes it on restoration", () => {
    const window = windowFixture({ minimized: true });
    expect(window.isVisible()).toBe(false);
    expect(window.isMinimized()).toBe(true);

    const presentation = hideDesktopShellWindowsForExit([window]);

    expect(window.hide).toHaveBeenCalledOnce();
    expect(window.state.visible).toBe(false);
    presentation.restore();

    expect(window.showInactive).toHaveBeenCalledOnce();
    expect(window.minimize).toHaveBeenCalledOnce();
    expect(window.showInactive.mock.invocationCallOrder[0]).toBeLessThan(window.minimize.mock.invocationCallOrder[0]);
    expect(window.state.visible).toBe(true);
    expect(window.isMinimized()).toBe(true);
    expect(window.isVisible()).toBe(false);
  });

  it("preserves bounds and maximization, and re-minimizes originally minimized windows after showing", () => {
    const maximized = windowFixture({ maximized: true });
    const minimized = windowFixture({ minimized: true, maximized: true });
    const initialStates = [structuredClone(maximized.state), structuredClone(minimized.state)];
    const presentation = hideDesktopShellWindowsForExit([maximized, minimized]);

    presentation.restore();

    expect([maximized.state, minimized.state]).toEqual(initialStates);
    expect(maximized.minimize).not.toHaveBeenCalled();
    expect(minimized.minimize).toHaveBeenCalledOnce();
    expect(minimized.showInactive.mock.invocationCallOrder[0]).toBeLessThan(minimized.minimize.mock.invocationCallOrder[0]);
    for (const window of [maximized, minimized]) {
      for (const method of [window.setBounds, window.restore, window.maximize, window.unmaximize, window.close, window.destroy]) {
        expect(method).not.toHaveBeenCalled();
      }
    }
  });

  it("captures all original visibility before hide events can reveal another window", () => {
    const visible = windowFixture();
    const hidden = windowFixture({ visible: false });
    visible.hide.mockImplementation(() => { visible.state.visible = false; hidden.state.visible = true; });

    const presentation = hideDesktopShellWindowsForExit([visible, hidden]);

    expect(visible.hide).toHaveBeenCalledOnce();
    expect(visible.state.visible).toBe(false);
    expect(hidden.hide).not.toHaveBeenCalled();
    hidden.state.visible = false;
    presentation.restore();
    expect(hidden.showInactive).not.toHaveBeenCalled();
    expect(hidden.state.visible).toBe(false);
  });

  it.each(["isDestroyed", "isVisible", "isMinimized", "hide"] as const)(
    "continues hiding and restoring other windows when one window's %s throws",
    (method) => {
      const failing = windowFixture();
      const healthy = windowFixture();
      failing[method].mockImplementation(() => { throw new Error("window unavailable"); });
      const presentation = hideDesktopShellWindowsForExit([failing, healthy]);

      expect(healthy.state.visible).toBe(false);
      expect(() => presentation.restore()).not.toThrow();
      expect(healthy.showInactive).toHaveBeenCalledOnce();
      if (method !== "hide") {
        expect(failing.hide).not.toHaveBeenCalled();
        expect(failing.showInactive).not.toHaveBeenCalled();
      }
    },
  );

  it("restores a visible window even if hide takes effect before throwing", () => {
    const window = windowFixture();
    window.hide.mockImplementation(() => { window.state.visible = false; throw new Error("hide failed late"); });
    const presentation = hideDesktopShellWindowsForExit([window]);
    expect(window.state.visible).toBe(false);

    presentation.restore();

    expect(window.showInactive).toHaveBeenCalledOnce();
    expect(window.state.visible).toBe(true);
  });

  it("skips windows destroyed by another window's hide event", () => {
    const first = windowFixture();
    const destroyed = windowFixture();
    first.hide.mockImplementation(() => { first.state.visible = false; destroyed.state.destroyed = true; });

    const presentation = hideDesktopShellWindowsForExit([first, destroyed]);
    expect(destroyed.hide).not.toHaveBeenCalled();
    presentation.restore();

    expect(first.showInactive).toHaveBeenCalledOnce();
    expect(destroyed.showInactive).not.toHaveBeenCalled();
  });

  it("skips a window destroyed during shutdown while restoring the others", () => {
    const destroyed = windowFixture({ minimized: true });
    const healthy = windowFixture();
    const presentation = hideDesktopShellWindowsForExit([destroyed, healthy]);
    destroyed.state.destroyed = true;

    presentation.restore();

    expect(destroyed.showInactive).not.toHaveBeenCalled();
    expect(destroyed.minimize).not.toHaveBeenCalled();
    expect(healthy.showInactive).toHaveBeenCalledOnce();
  });

  it("continues when a window handle starts throwing after the visibility snapshot", () => {
    const first = windowFixture();
    const stale = windowFixture();
    const healthy = windowFixture();
    first.hide.mockImplementation(() => {
      first.state.visible = false;
      stale.isDestroyed.mockImplementation(() => { throw new Error("stale window"); });
    });

    const presentation = hideDesktopShellWindowsForExit([first, stale, healthy]);

    expect(stale.hide).not.toHaveBeenCalled();
    expect(healthy.state.visible).toBe(false);
    expect(() => presentation.restore()).not.toThrow();
    expect(first.showInactive).toHaveBeenCalledOnce();
    expect(healthy.showInactive).toHaveBeenCalledOnce();
    expect(stale.showInactive).not.toHaveBeenCalled();
  });

  it.each(["isDestroyed", "showInactive", "minimize"] as const)(
    "restores later windows once even when %s throws during restoration",
    (method) => {
      const failing = windowFixture({ minimized: true });
      const healthy = windowFixture();
      const presentation = hideDesktopShellWindowsForExit([failing, healthy]);
      failing[method].mockImplementation(() => { throw new Error("restore failed"); });

      expect(() => presentation.restore()).not.toThrow();
      const failureCalls = failing[method].mock.calls.length;
      expect(failing[method].mock.results.at(-1)?.type).toBe("throw");
      expect(() => presentation.restore()).not.toThrow();

      expect(healthy.showInactive).toHaveBeenCalledOnce();
      expect(failing[method]).toHaveBeenCalledTimes(failureCalls);
    },
  );

  it("does not minimize a window destroyed by its show event", () => {
    const window = windowFixture({ minimized: true });
    const presentation = hideDesktopShellWindowsForExit([window]);
    window.showInactive.mockImplementation(() => { window.state.destroyed = true; });

    presentation.restore();

    expect(window.showInactive).toHaveBeenCalledOnce();
    expect(window.minimize).not.toHaveBeenCalled();
  });
});
