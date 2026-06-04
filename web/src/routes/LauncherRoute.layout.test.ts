import { describe, expect, it } from "vitest";

import routeSource from "./LauncherRoute.tsx?raw";
import styles from "./LauncherRoute.module.css";
import routerSource from "../app/router.tsx?raw";
import shellSource from "../app/AppShell.tsx?raw";

describe("LauncherRoute layout contract", () => {
  it("mounts the Launcher as a first-class utility route", () => {
    expect(routerSource).toContain("const LauncherRoute = lazyRoute");
    expect(routerSource).toContain('path: "launcher"');
    expect(routerSource).toContain("lazyElement(<LauncherRoute />)");
    expect(shellSource).toContain('to="/launcher"');
    expect(shellSource).toContain('lang === "zh" ? "启动器" : "Launcher"');
  });

  it("uses the typed launcher lifecycle API client", () => {
    expect(routeSource).toContain("getLauncherStatus");
    expect(routeSource).toContain("startLauncherBundle");
    expect(routeSource).toContain("stopLauncherBundle");
    expect(routeSource).toContain("restartLauncherBundle(false)");
    expect(routeSource).toContain("reattachLauncherSupervisor");
    expect(routeSource).toContain("queryKeys.launcherStatus()");
    expect(routeSource).toContain("queryKeys.runtimeSummary()");
  });

  it("renders a dense lifecycle console rather than a landing page", () => {
    expect(routeSource).toContain("summaryStrip");
    expect(routeSource).toContain("statusTable");
    expect(routeSource).toContain("matrixPanel");
    expect(routeSource).toContain("specGrid");
    expect(routeSource).toContain("projectBundle");
    expect(routeSource).toContain("StatusRow");
    expect(routeSource).toContain("statusRows");
    expect(routeSource).toContain("controlPlane");
    expect(routeSource).toContain("controlPlaneEvidence");
    expect(routeSource).toContain("controlEvidence");
    expect(routeSource).toContain("guardianAdapter");
    expect(routeSource).toContain("activityPanel");
    expect(routeSource).toContain("CompactList");
    expect(routeSource).toContain("guardianTable");
    expect(routeSource).toContain("diagnosticsPanel");
    expect(routeSource).toContain("guardian?.supervisor?.stdoutPath");
    expect(routeSource).toContain("guardian?.supervisor?.stderrPath");
    expect(routeSource).not.toContain("hero");
    expect(routeSource).not.toContain("cardGrid");
    expect(styles.summaryStrip).toBeTypeOf("string");
    expect(styles.statusTable).toBeTypeOf("string");
    expect(styles.matrixPanel).toBeTypeOf("string");
    expect(styles.activityPanel).toBeTypeOf("string");
    expect(styles.guardianTable).toBeTypeOf("string");
    expect(styles.diagnosticsPanel).toBeTypeOf("string");
    expect(styles.specGrid).toBeTypeOf("string");
  });

  it("keeps lifecycle actions icon-backed and compact", () => {
    expect(routeSource).toContain("<Play size={15} />");
    expect(routeSource).toContain("<Square size={15} />");
    expect(routeSource).toContain("<RefreshCw size={15} />");
    expect(routeSource).toContain("<ExternalLink size={15} />");
    expect(routeSource).toContain('controlMutation.mutate("start")');
    expect(routeSource).toContain('controlMutation.mutate("stop")');
    expect(routeSource).toContain('controlMutation.mutate("restart")');
    expect(routeSource).toContain("supervisorMutation.mutate()");
  });
});
