import { VButton } from "../../../../components/vui";
import { useLauncherTasks } from "../LauncherTaskContext";
import { COPY } from "../assistantTaskCopy";

/** Model lifecycle controls for regression tests; production navigation has no toolbar. */
export function LauncherTaskModelControls({ lang = "zh" }: { lang?: "zh" | "en" }) {
  const model = useLauncherTasks();
  if (!model) throw new Error("LauncherTaskModelControls requires the shared task provider");
  const copy = COPY[lang];
  return <div data-task-model-controls>
    {/* A failed identity read disables cleanup, but manual refresh must still allow recovery. */}
    <VButton data-task-model-refresh aria-label={copy.refresh}
      isPending={model.refreshing} onClick={() => { void model.refresh(); }}>{copy.refresh}</VButton>
    <VButton data-task-model-cleanup isDisabled={!model.enabled || model.cleanupBusy || !model.canCleanCompleted}
      isPending={model.cleanupBusy} onClick={model.cleanCompleted}>{copy.cleanup}</VButton>
  </div>;
}
