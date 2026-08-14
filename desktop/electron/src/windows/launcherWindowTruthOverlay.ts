export type LauncherWindowTruth = {
  workbench: { open: boolean; rendererProcessId: number } | null;
  instances: Array<{ instanceId: string; open: boolean; rendererProcessId: number }>;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function overlayStatusWindowTruth(
  payload: Record<string, unknown>,
  truth: LauncherWindowTruth
): Record<string, unknown> {
  const bundle = payload.projectBundle;
  if (!isRecord(bundle)) {
    return payload;
  }
  const workbenchOpen = truth.workbench?.open === true;
  const browser = isRecord(bundle.browser) ? { ...bundle.browser } : {};

  if (workbenchOpen && truth.workbench) {
    browser.alive = true;
    browser.managed = true;
    if (truth.workbench.rendererProcessId > 0) {
      browser.windowPid = truth.workbench.rendererProcessId;
    }
    const observed = String(bundle.observedState || "").toLowerCase();
    const consistency = String(bundle.lifecycleConsistency || "").toLowerCase();
    if (observed === "closed") {
      bundle.observedState = "open";
    } else if (observed === "partial" && consistency === "browser_missing") {
      bundle.observedState = "open";
      bundle.lifecycleConsistency = "";
    }
  } else {
    browser.alive = false;
    browser.managed = false;
    const observed = String(bundle.observedState || "").toLowerCase();
    if (observed === "open") {
      bundle.observedState = "partial";
      if (!String(bundle.lifecycleConsistency || "").trim()) {
        bundle.lifecycleConsistency = "browser_missing";
      }
    }
  }

  bundle.browser = browser;
  if (Array.isArray(bundle.components)) {
    bundle.components = bundle.components.map((component) => {
      if (!isRecord(component) || component.id !== "browser") {
        return component;
      }
      return {
        ...component,
        ok: workbenchOpen,
        state: workbenchOpen ? "alive" : "closed",
        pid: workbenchOpen && truth.workbench ? Math.max(0, truth.workbench.rendererProcessId) : 0
      };
    });
  }
  return payload;
}

function overlayBranchInstancesWindowTruth(
  payload: Record<string, unknown>,
  truth: LauncherWindowTruth
): Record<string, unknown> {
  const items = payload.items;
  if (!Array.isArray(items)) {
    return payload;
  }
  const instancesById = new Map(
    truth.instances.map((entry) => [String(entry.instanceId || ""), entry])
  );
  payload.items = items.map((item) => {
    if (!isRecord(item)) {
      return item;
    }
    const runtime = isRecord(item.runtime) ? item.runtime : null;
    if (!runtime) {
      return item;
    }
    const window = isRecord(runtime.window) ? { ...runtime.window } : {};
    let windowOpen: boolean | null = null;
    let rendererPid = 0;
    if (item.current === true) {
      windowOpen = truth.workbench?.open === true;
      rendererPid = truth.workbench?.rendererProcessId ?? 0;
    } else {
      const instanceState = instancesById.get(String(item.id || ""));
      if (instanceState) {
        windowOpen = instanceState.open === true;
        rendererPid = instanceState.rendererProcessId;
      }
    }
    if (windowOpen !== null) {
      window.open = windowOpen;
      window.pid = windowOpen ? Math.max(0, rendererPid) : 0;
      if (windowOpen) {
        item.alive = true;
        item.startable = false;
        runtime.window = window;
      } else {
        runtime.window = window;
      }
      item.runtime = runtime;
    }
    return item;
  });
  return payload;
}

export function overlayLauncherWindowTruth(
  path: string,
  payload: unknown,
  truth: LauncherWindowTruth
): unknown {
  if (!isRecord(payload)) {
    return payload;
  }
  if (path === "status") {
    return overlayStatusWindowTruth(payload, truth);
  }
  if (path === "branch-instances") {
    return overlayBranchInstancesWindowTruth(payload, truth);
  }
  return payload;
}
