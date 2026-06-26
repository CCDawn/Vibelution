export type ManagedProcessRole = "python_launcher_service";

export type ManagedProcessStatus = "idle" | "starting" | "running" | "stopping" | "exited" | "failed";

export type ManagedProcessState = {
  role: ManagedProcessRole;
  status: ManagedProcessStatus;
  pid: number;
  startedAt: string;
  exitedAt: string;
  exitCode: number | null;
  signal: string;
  lastError: string;
};

export function initialManagedProcessState(role: ManagedProcessRole): ManagedProcessState {
  return {
    role,
    status: "idle",
    pid: 0,
    startedAt: "",
    exitedAt: "",
    exitCode: null,
    signal: "",
    lastError: ""
  };
}
