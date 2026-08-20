import { peekAdmissionDecision } from "../lifecycle/instanceAdmissionStore.js";
import {
  instanceLifecycleIsStartable,
  projectInstanceLifecycle
} from "../lifecycle/instanceLifecycleProjection.js";

export type LauncherWindowTruth = {
  workbench: { open: boolean; rendererProcessId: number } | null;
  instances: Array<{ instanceId: string; open: boolean; rendererProcessId: number }>;
};

export { composeInstanceLifecycleState } from "../lifecycle/instanceLifecycleProjection.js";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function backendReadyFromBundle(bundle: Record<string, unknown>): boolean {
  const backend = isRecord(bundle.backend) ? bundle.backend : {};
  return backend.alive === true && backend.healthy === true && backend.portListening === true && backend.portConflict !== true;
}

function backendLiveFromBundle(bundle: Record<string, unknown>): boolean {
  const backend = isRecord(bundle.backend) ? bundle.backend : {};
  return backend.alive === true || backend.portListening === true;
}

function applyAdmissionOverlay(
  item: Record<string, unknown>,
  instanceId: string,
  nowMs = Date.now()
): void {
  const decision = peekAdmissionDecision(instanceId, nowMs, "start");
  if (decision.admitted) {
    if (item.startBlockReason === "rate_limited" || item.startBlockReason === "crash_loop_backoff") {
      item.startBlockReason = "";
    }
    delete item.admissionRetryAfterMs;
    delete item.admissionMessage;
    return;
  }
  item.startBlockReason = decision.code;
  item.admissionRetryAfterMs = decision.retryAfterMs;
  item.admissionMessage = decision.message;
}

function overlayRetiredControlPort(payload: Record<string, unknown>): Record<string, unknown> {
  const launcher = isRecord(payload.launcher) ? { ...payload.launcher } : null;
  if (launcher) {
    const controlPlane = isRecord(launcher.controlPlane) ? { ...launcher.controlPlane } : null;
    if (controlPlane) {
      controlPlane.port = 0;
      controlPlane.url = "";
      controlPlane.adapter = "electron_main";
      controlPlane.pid = 0;
      launcher.controlPlane = controlPlane;
    }
    if ("controlPort" in launcher || "effectiveControlPort" in launcher) {
      launcher.controlPort = 0;
      launcher.effectiveControlPort = 0;
    }
    payload.launcher = launcher;
  }
  const settings = isRecord(payload.settings) ? { ...payload.settings } : null;
  const startup = settings && isRecord(settings.startup) ? { ...settings.startup } : null;
  const startupLauncher = startup && isRecord(startup.launcher) ? { ...startup.launcher } : null;
  if (settings && startup && startupLauncher) {
    startupLauncher.controlPort = 0;
    startupLauncher.effectiveControlPort = 0;
    startup.launcher = startupLauncher;
    settings.startup = startup;
    payload.settings = settings;
  }
  return payload;
}

function overlayStatusWindowTruth(
  payload: Record<string, unknown>,
  truth: LauncherWindowTruth
): Record<string, unknown> {
  overlayRetiredControlPort(payload);
  const bundle = payload.projectBundle;
  if (!isRecord(bundle)) {
    return payload;
  }
  const workbenchOpen = truth.workbench?.open === true;
  const backendReady = backendReadyFromBundle(bundle);
  const backendLive = backendLiveFromBundle(bundle);
  const browser = isRecord(bundle.browser) ? { ...bundle.browser } : {};

  if (workbenchOpen && truth.workbench) {
    browser.alive = true;
    browser.managed = true;
    if (truth.workbench.rendererProcessId > 0) {
      browser.windowPid = truth.workbench.rendererProcessId;
    }
    const observed = String(bundle.observedState || "").toLowerCase();
    const consistency = String(bundle.lifecycleConsistency || "").toLowerCase();
    if (backendReady) {
      bundle.observedState = "open";
      if (
        observed === "closed"
        || ["browser_missing", "backend_missing"].includes(consistency)
      ) {
        bundle.lifecycleConsistency = "";
      }
    } else {
      bundle.observedState = "partial";
      bundle.lifecycleConsistency = "backend_missing";
    }
  } else {
    browser.alive = false;
    browser.managed = false;
    if (backendReady || backendLive) {
      bundle.observedState = "partial";
      bundle.lifecycleConsistency = "browser_missing";
    } else {
      bundle.observedState = "closed";
      if (["browser_missing", "backend_missing"].includes(String(bundle.lifecycleConsistency || "").toLowerCase())) {
        bundle.lifecycleConsistency = "";
      }
    }
    const phase = String(bundle.phase || "").toLowerCase();
    if ((phase === "opening" || phase === "starting") && backendReady) {
      bundle.phase = "steady";
    }
  }

  applyAdmissionOverlay(bundle, "main");
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
      if (truth.workbench) {
        windowOpen = truth.workbench.open === true;
        rendererPid = truth.workbench.rendererProcessId ?? 0;
      }
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
      runtime.window = window;
      const backend = isRecord(runtime.backend) ? runtime.backend : null;
      if (backend) {
        const frontend = isRecord(runtime.frontend) ? runtime.frontend : {};
        const error = isRecord(runtime.error) ? runtime.error : {};
        const projected = projectInstanceLifecycle({
          phase: String(runtime.phase || ""),
          observedState: String(runtime.observedState || ""),
          desiredState: String(runtime.desiredState || ""),
          registryStatus: String(runtime.registryStatus || ""),
          backendAlive: backend.alive === true,
          backendHealthy: backend.healthy === true,
          backendListening: backend.listening === true,
          backendConflict: backend.portConflict === true,
          frontendReady: frontend.ready === true,
          windowOpen,
          failureMessage: String(error.message || ""),
          startSupervisorLost: String(error.code || "") === "start_supervisor_lost"
        });
        runtime.lifecycleState = projected.lifecycleState;
        const backendLive = backend.alive === true || backend.listening === true;
        item.alive = windowOpen || backendLive;
        item.startable = instanceLifecycleIsStartable({
          lifecycleState: projected.lifecycleState,
          backendAlive: backend.alive === true,
          backendListening: backend.listening === true,
          windowOpen
        });
      } else if (windowOpen) {
        item.alive = true;
        item.startable = false;
      }
      item.runtime = runtime;
    }
    applyAdmissionOverlay(item, String(item.id || ""));
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
  if (path === "settings/startup") {
    return overlayRetiredControlPort(payload);
  }
  if (path === "branch-instances") {
    return overlayBranchInstancesWindowTruth(payload, truth);
  }
  return payload;
}
