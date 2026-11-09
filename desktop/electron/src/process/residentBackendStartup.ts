/**
 * Startup decisions that keep the resident shell and its backend in sync.
 *
 * Incident background (2026-11-09): a forced close retired the Workbench
 * backend and the shell relaunched itself with the argv it had started with
 * (`--workspace <root>` only, no `--open-workbench`). Nothing in that startup
 * path ever calls the lifecycle `start` owner — only the "open the workbench
 * window" path does — so the tray and the assistant window came up while port
 * 8000 stayed empty. The assistant rendered "waiting for the backend" forever
 * and the Launcher top bar reported every read as failed.
 *
 * Two rules come out of that incident, both kept pure here so they can be
 * unit-tested without Electron:
 *
 * 1. A resident shell that owns a project workspace must ensure a backend
 *    exists even when the user did not ask for a workbench window: the
 *    assistant is a first-class surface and it cannot work without one.
 * 2. A shell relaunch must carry the caller's workbench intent forward. When
 *    the shell is restarted while a workbench was open, the replacement must
 *    come back serving it instead of falling back to a tray-only shell.
 */

const OPEN_WORKBENCH_FLAG = "--open-workbench";

export type ResidentBackendStartupInput = {
  /** Smoke runs and the workbench-close canary must never start a backend. */
  smoke: boolean;
  /** Assistant-only shells have no project workspace to serve. */
  assistantOnly: boolean;
  /** The explicit open path already runs its own backend gate. */
  pendingOpenWorkbench: boolean;
  /** A startup lifecycle command (open/start/restart/...) owns its own start. */
  lifecycleCommand: string;
  /** False when the project control plane never attached (nothing to serve). */
  controlPlaneReady: boolean;
};

/**
 * True when the shell came up resident for a project and must make sure a
 * Workbench backend is serving before the assistant can be useful.
 *
 * The workbench window is deliberately NOT opened here: this only repairs the
 * missing backend, it does not change what the user sees on screen.
 */
export function shouldEnsureResidentBackend(input: ResidentBackendStartupInput): boolean {
  if (input.smoke || input.assistantOnly || !input.controlPlaneReady) return false;
  if (input.pendingOpenWorkbench) return false;
  // Any explicit lifecycle word (open, start, restart, stop, status, ...) is
  // dispatched by its own handler after this point and must not be doubled.
  if (String(input.lifecycleCommand || "").trim().length > 0) return false;
  return true;
}

export type ShellRelaunchArgsInput = {
  /** Arguments the shell was started with, without the executable. */
  argv: readonly string[];
  /** True when the replacement shell must restore the workbench. */
  restoreWorkbench: boolean;
};

/**
 * Build the argv for `app.relaunch({ args })`.
 *
 * Electron's default relaunch replays the current argv verbatim, which is how
 * a restart lost `--open-workbench` and produced a tray-only shell. Keeping
 * the pass-through explicit lets the caller add the intent back without
 * dropping any other flag (workspace, config path, debugging switches).
 */
export function buildShellRelaunchArgs(input: ShellRelaunchArgsInput): string[] {
  const withoutOpen = input.argv
    .map((value) => String(value))
    .filter((value) => value !== OPEN_WORKBENCH_FLAG);
  if (!input.restoreWorkbench) return withoutOpen;
  return [...withoutOpen, OPEN_WORKBENCH_FLAG];
}
