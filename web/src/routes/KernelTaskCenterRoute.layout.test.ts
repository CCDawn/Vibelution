import { describe, expect, it } from "vitest";

import routeSource from "./KernelTaskCenterRoute.tsx?raw";
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
});
