import { statSync } from "node:fs";
import { dirname } from "node:path";
import { resolveDeferredProjectLaunchSettings, type DesktopLaunchSettingsInput } from "../launch/desktopLaunchSettings.js";
import { resolveDataHomeForProject, resolveRuntimeManagerDir } from "../lifecycle/projectStoragePaths.js";
import { readRuntimeManagerLauncherStatusSummary } from "../lifecycle/runtimeManagerStatusSnapshot.js";
import type { RunWorkbenchLifecycleInput, WorkbenchLifecycleResult } from "../process/workbenchLifecycle.js";
import { createAssistantProjectLifecycle } from "./projectLifecycle.js";
import { createAssistantProjectLifecycleRequests } from "./projectLifecycleRequests.js";
import { AssistantProjectLifecycleRequestStore } from "./projectLifecycleRequestStore.js";
import type { AssistantProjectRegistryConnection } from "./projectRegistryConnection.js";
import { parseMainControlClaim, type MainControlRequest } from "./mainControlTransport.js";

/** Production composition for the existing main-owned native lifecycle engine.
 * No assistant Python fallback, global environment switching, bootstrap or SDK.
 */
export function createAssistantProjectMainControl(options: {
  directory: string;
  registry: Pick<AssistantProjectRegistryConnection, "snapshot" | "registration">;
  launch: DesktopLaunchSettingsInput;
  operatorConfigPath: string;
  runLifecycle?: (input: RunWorkbenchLifecycleInput) => Promise<WorkbenchLifecycleResult>;
  readStatusSummary?: typeof readRuntimeManagerLauncherStatusSummary;
  resolveDataHome?: (root: string) => string;
}): (request: MainControlRequest) => Promise<unknown> {
  const launch = { ...options.launch, env: { ...options.launch.env }, cliArgs: { ...options.launch.cliArgs } };
  const registry = options.registry;
  const isMainTarget = (projectId: string, root: string) => {
    const registration = registry.registration(projectId);
    return Boolean(registration && registration.root === root && registration.integrationRoot === root);
  };
  const facade = createAssistantProjectLifecycle({
    getPermissionSnapshot: () => registry.snapshot(),
    resolveRuntimeContext: async target => {
      // Branch instances use their existing supervisor/instances owner. A
      // per-root main-line queue must not silently replace that lifecycle.
      if (!isMainTarget(target.projectId, target.workspaceRoot)) return null;
      const resolved = resolveDeferredProjectLaunchSettings(launch, target.workspaceRoot, options.operatorConfigPath);
      if (resolved.workspaceRoot !== target.workspaceRoot || !resolved.pythonPath || !resolved.configPath) return null;
      try { if (!statSync(resolved.pythonPath).isFile() || !statSync(resolved.configPath).isFile()) return null; }
      catch { return null; }
      const environment: NodeJS.ProcessEnv = { ...launch.env };
      const isolated = new Set([
        "VIBELUTION_WORKSPACE_ROOT", "VIBELUTION_PYTHON_PATH", "PYTHON", "PYTHONPATH", "PYTHONHOME", "VIBELUTION_PROCESS_ROLE",
        "VIBELUTION_PORT", "AGENT_WORKBENCH_BACKEND_PORT", "VIBELUTION_LAUNCHER_PORT", "AGENT_LAUNCHER_CONTROL_PORT",
        "VIBELUTION_WEB_CONTROL_TOKEN", "VIBELUTION_WORKBENCH_URL", "VIBELUTION_INSTANCE_ID", "VIBELUTION_DATA_HOME",
        "VIBELUTION_ALLOW_DIRTY_LAUNCH", "VIBELUTION_ALLOW_NON_MAIN_LAUNCH",
      ]);
      for (const key of Object.keys(environment)) if (isolated.has(key.toUpperCase()) || key.toUpperCase().startsWith("VIBELUTION_ASSISTANT_")) delete environment[key];
      environment.VIBELUTION_WORKSPACE_ROOT = target.workspaceRoot;
      environment.VIBELUTION_CONFIG_PATH = resolved.configPath;
      environment.VIBELUTION_CONFIG_HOME = dirname(resolved.configPath);
      environment.VIBELUTION_DATA_HOME = (options.resolveDataHome ?? resolveDataHomeForProject)(target.workspaceRoot);
      environment.VIBELUTION_PYTHON_PATH = resolved.pythonPath;
      environment.PYTHON = resolved.pythonPath;
      return { workspaceRoot: target.workspaceRoot, pythonPath: resolved.pythonPath, operatorConfigPath: resolved.configPath,
        runtimeManagerDir: resolveRuntimeManagerDir(target.workspaceRoot), environment };
    },
    readStatus: async target => {
      if (!isMainTarget(target.projectId, target.workspaceRoot)) throw new Error("unsupported target");
      const summary = (options.readStatusSummary ?? readRuntimeManagerLauncherStatusSummary)(target.workspaceRoot);
      const phase = summary.phase.toLowerCase(), observed = summary.observedState.toLowerCase();
      let state = "unknown";
      if (["failed", "error"].includes(phase) || observed === "failed") state = "failed";
      else if (["closing", "stopping", "force_stopping"].includes(phase)) state = "stopping";
      else if (["starting", "booting", "opening", "building"].includes(phase)) state = "starting";
      else if (summary.backendHealthy && summary.backendPortListening) state = "running";
      else if (observed === "closed" && !summary.backendHealthy && !summary.backendPortListening) state = "stopped";
      return { state };
    },
    ...(options.runLifecycle ? { runLifecycle: options.runLifecycle } : {}),
  });
  const requests = createAssistantProjectLifecycleRequests({ facade,
    store: new AssistantProjectLifecycleRequestStore({ directory: options.directory }) });
  return async input => {
    const request = parseMainControlClaim({ schemaVersion: 1, request: input })!;
    let code: "project_unavailable" | "prerequisite_required" | undefined;
    try {
      const registered = registry.registration(request.projectId);
      if (!registered) code = "project_unavailable";
      else if (registered.root !== registered.integrationRoot) code = "prerequisite_required";
    } catch { code = "project_unavailable"; }
    if (code) return { schemaVersion: 1, projectId: request.projectId, operation: request.operation, code,
      ...(request.action === "project_status" ? { accepted: false } : { requestId: request.requestId, state: "rejected" }) };
    if (request.action === "project_status") return facade.dispatch({ projectId: request.projectId, operation: "status" });
    const identity = { requestId: request.requestId, projectId: request.projectId, operation: request.operation };
    return request.action === "project_lifecycle" ? requests.dispatch(identity) : requests.receipt(identity);
  };
}
