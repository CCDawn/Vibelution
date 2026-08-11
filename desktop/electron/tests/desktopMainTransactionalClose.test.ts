import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSourcePath = fileURLToPath(new URL("../src/main.ts", import.meta.url));

describe("Electron main transactional Workbench close", () => {
  it("advertises the Electron close capability instead of reusing only Launcher capabilities", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain('WORKBENCH_CLOSE_TRANSACTION_CAPABILITY = "workbench_close.transaction.v1"');
    expect(source).toContain("function desktopSessionCapabilities(bootstrap: LauncherBootstrapResult): string[]");
    expect(source).toContain("capabilities: desktopSessionCapabilities(bootstrap)");
  });

  it("routes Workbench X and desktop actions through the same transaction before approval", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain('from "./protocol/workbenchCloseTransactionClient.js"');
    expect(source).toContain("shouldInterceptWorkbenchClose: () => true");
    expect(source).toContain("onWorkbenchCloseRequest: () =>");
    expect(source).toContain("requestTransactionalWorkbenchClose(paths, bootstrap)");
    expect(source).toContain("closeWorkbench: () => requestTransactionalWorkbenchClose(paths, bootstrap)");
    expect(source).toContain("await provider.approveWorkbenchCloseOnce()");
    expect(source).toContain("buttons: [\"重试\", \"取消\"]");
  });

  it("waits from Launcher transaction metadata and acknowledges only after the window closed callback", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain("transaction.nextPollAfterMs");
    expect(source).toContain("transaction.deadlineAt");
    expect(source).toContain("onWorkbenchClosed: () =>");
    expect(source).toContain("acknowledgeWorkbenchCloseWindowClosed");
    expect(source).toContain("desktopSessionRevision");
  });
});
