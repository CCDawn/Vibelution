export const WORKBENCH_EXIT_GUARD_EVENT = "vibelution:workbench-exit-guard";

export type WorkbenchExitGuardAction = "shutdown" | "restart";

export type WorkbenchExitGuardDetail = {
  action: WorkbenchExitGuardAction;
  proceed: () => void;
};

export function requestWorkbenchExitGuard(action: WorkbenchExitGuardAction, proceed: () => void) {
  const event = new CustomEvent<WorkbenchExitGuardDetail>(WORKBENCH_EXIT_GUARD_EVENT, {
    cancelable: true,
    detail: { action, proceed },
  });
  return window.dispatchEvent(event);
}
