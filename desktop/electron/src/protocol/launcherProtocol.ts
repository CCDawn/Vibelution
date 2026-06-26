export type LauncherCommand =
  | "status"
  | "start"
  | "stop"
  | "restart"
  | "focus"
  | "lifecycle_intent";

export type LauncherCommandStatus = "ok" | "accepted" | "rejected" | "failed";

export type LauncherProvider = "edge_app" | "electron" | "launcher_protocol";

export type LauncherChildProcessStatus = "starting" | "running" | "stopping" | "exited" | "failed";

export type LauncherCommandResponse = {
  schemaVersion: 1;
  commandId: string;
  command: LauncherCommand;
  status: LauncherCommandStatus;
  provider: LauncherProvider;
  message: string;
  activeWorkBlocked: boolean;
  runtimeSceneRef?: string;
  childProcesses?: Array<{
    role: "fastapi_backend" | "runtime_manager" | "self_evolution_worker" | "tool_worker";
    pid: number;
    status: LauncherChildProcessStatus;
  }>;
};

export function launcherCommandAccepted(
  commandId: string,
  command: LauncherCommand,
  message: string
): LauncherCommandResponse {
  return {
    schemaVersion: 1,
    commandId,
    command,
    status: "accepted",
    provider: "launcher_protocol",
    message,
    activeWorkBlocked: false
  };
}
