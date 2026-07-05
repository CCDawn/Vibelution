import { describe, expect, it } from "vitest";

import routeSource from "./KernelTaskCenterRoute.tsx?raw";
import styles from "./KernelTaskCenterRoute.styles";
import stylesSource from "./KernelTaskCenterRoute.styles.ts?raw";
import routerSource from "../app/router.tsx?raw";

describe("KernelTaskCenterRoute layout contract", () => {
  it("routes Kernel task center controls through VUI primitives", () => {
    expect(routeSource).toContain('from "../components/vui"');
    expect(routeSource).toContain("<VButton");
    expect(routeSource).not.toMatch(/<button\b/);
  });

  it("is wired as a read-only kernel route", () => {
    expect(routerSource).toContain('path: "kernel"');
    expect(routerSource).toContain("<KernelTaskCenterRoute />");
    expect(routeSource).toContain("listKernelTasks(status, 120)");
    expect(routeSource).toContain("getKernelTaskTimeline(selectedTaskId)");
    expect(routeSource).toContain("useSearchParams");
    expect(routeSource).toContain("selectKernelTaskId(tasks, requestedTaskId)");
    expect(routeSource).not.toContain("useMutation");
    expect(routeSource).not.toContain('method: "POST"');
  });

  it("shows TaskLedger authority and delivery/wake evidence", () => {
    expect(routeSource).toContain("timeline.readModel.truthSource");
    expect(routeSource).toContain("timeline.readModel.projection");
    expect(routeSource).toContain("copy.factAuthority");
    expect(routeSource).toContain("timeline.deliveries.map");
    expect(routeSource).toContain("delivery.wake?.wakeStatus");
    expect(routeSource).toContain("timeline.projectionRefs");
    expect(routeSource).toContain("timeline.runtimeEvidenceRefs");
  });

  it("keeps the route local and shell-language only", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const COPY = {");
    expect(routeSource).not.toContain("useAppI18n");
  });

  it("keeps the route root background-aware", () => {
    expect(styles.routeClass).not.toContain("bg-[var(--surface-page)]");
    expect(styles.routeClass).toContain("grid-rows-[auto_minmax(0,1fr)]");
  });

  it("presents Kernel as a ledger-first task chain instead of a logs surface", () => {
    expect(routeSource).toContain("copy.taskChain");
    expect(routeSource).toContain("copy.evidenceRefs");
    expect(routeSource).toContain("copy.lifecycleTimeline");
    expect(routeSource).not.toContain("copy.runtimeRefs");
    expect(routeSource).not.toContain("copy.timeline");
    expect(routeSource).not.toContain("运行证据");
    expect(routeSource).not.toContain("Runtime evidence");
    expect(routeSource).not.toContain("时间线");
    expect(routeSource).not.toContain("/logs");

    expect(stylesSource).toContain("ledgerFlowClass");
    expect(stylesSource).toContain("ledgerBucketClass");
    expect(stylesSource).toContain("evidenceRefListClass");
    expect(stylesSource).toContain("lifecycleTimelineClass");
    expect(stylesSource).not.toContain("timelineListClass");
    expect(stylesSource).not.toContain("timelineRowClass");
  });

  it("allows Kernel task rows to render multiline content inside VButton", () => {
    expect(routeSource).toContain("<VButton");
    expect(stylesSource).toContain("data-slot=vui-button-content");
    expect(stylesSource).toContain("data-slot=vui-button-label");
    expect(stylesSource).toContain("!h-auto");
    expect(styles.taskRowClass).toContain("!min-h-[72px]");
    expect(styles.taskRowClass).not.toContain("!min-h-[112px]");
    expect(stylesSource).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(stylesSource).toContain("whitespace-normal");
  });
});
