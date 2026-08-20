export type InstanceLifecycleState =
  | "starting"
  | "restarting"
  | "stopping"
  | "error"
  | "running"
  | "partial"
  | "closed";

export type InstanceLifecycleProjectionInput = {
  phase?: string;
  observedState?: string;
  desiredState?: string;
  registryStatus?: string;
  backendAlive?: boolean;
  backendHealthy?: boolean;
  backendListening?: boolean;
  backendConflict?: boolean;
  frontendReady?: boolean;
  windowOpen?: boolean;
  failureMessage?: string;
  startSupervisorLost?: boolean;
};

export type InstanceLifecycleProjection = {
  lifecycleState: InstanceLifecycleState;
  errorCode: string;
};

function hasLiveRuntimeSignal(input: {
  backendAlive?: boolean;
  backendListening?: boolean;
  windowOpen?: boolean;
}): boolean {
  return Boolean(input.backendAlive || input.backendListening || input.windowOpen);
}

export function instanceLifecycleIsStartable(input: {
  lifecycleState: string;
  backendAlive?: boolean;
  backendListening?: boolean;
  windowOpen?: boolean;
}): boolean {
  const state = String(input.lifecycleState || "").trim().toLowerCase();
  if (state === "closed") {
    return true;
  }
  return state === "error" && !hasLiveRuntimeSignal(input);
}

export function projectInstanceLifecycle(
  input: InstanceLifecycleProjectionInput
): InstanceLifecycleProjection {
  const phase = String(input.phase || "").trim().toLowerCase();
  const registryStatus = String(input.registryStatus || "").trim().toLowerCase();
  const desiredState = String(input.desiredState || "").trim().toLowerCase();
  // Leftover disk observedState is not a live signal; keep the argument for Python ≡ TS.
  void String(input.observedState || "").trim().toLowerCase();
  const backendReady = Boolean(
    input.backendAlive && input.backendHealthy && input.backendListening && !input.backendConflict
  );
  if (input.startSupervisorLost && !backendReady && !input.windowOpen) {
    return { lifecycleState: "error", errorCode: "start_supervisor_lost" };
  }
  if (phase === "restarting" || phase === "restart" || registryStatus === "restarting") {
    return { lifecycleState: "restarting", errorCode: "" };
  }
  if (phase === "closing" || phase === "stopping" || phase === "force_stopping" || registryStatus === "stopping") {
    return { lifecycleState: "stopping", errorCode: "" };
  }
  const inFlightStart =
    ((registryStatus === "starting" || registryStatus === "restarting") && desiredState === "open")
    || phase === "opening"
    || phase === "starting";
  if (inFlightStart && !backendReady && !input.windowOpen) {
    return { lifecycleState: "starting", errorCode: "" };
  }
  if (input.backendConflict) {
    return { lifecycleState: "error", errorCode: "backend_port_conflict" };
  }
  if (phase === "failed") {
    return { lifecycleState: "error", errorCode: "lifecycle_failed" };
  }
  if (registryStatus === "failed") {
    return { lifecycleState: "error", errorCode: "registry_failed" };
  }
  if (String(input.failureMessage || "")) {
    return { lifecycleState: "error", errorCode: "runtime_error" };
  }
  if (backendReady && input.frontendReady === true && input.windowOpen) {
    return { lifecycleState: "running", errorCode: "" };
  }
  if (hasLiveRuntimeSignal(input)) {
    return { lifecycleState: "partial", errorCode: "" };
  }
  return { lifecycleState: "closed", errorCode: "" };
}

export function composeInstanceLifecycleState(
  input: InstanceLifecycleProjectionInput
): InstanceLifecycleState {
  return projectInstanceLifecycle(input).lifecycleState;
}
