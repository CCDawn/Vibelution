import { describe, expect, it } from "vitest";

import {
  toolApprovalActionPreview,
  toolApprovalSessionGrantDescription,
} from "./toolApprovalPreview";

describe("toolApprovalPreview", () => {
  it("shows the real command and cwd", () => {
    expect(toolApprovalActionPreview({
      commandPreview: '.\\.venv\\Scripts\\python.exe -c "print(123)"',
      cwdPreview: "C:\\workspace\\repo",
    }, "exec_command")).toBe([
      '$ .\\.venv\\Scripts\\python.exe -c "print(123)"',
      "cwd: C:\\workspace\\repo",
    ].join("\n"));
  });

  it("shows stdin and describes a terminal-bound session grant truthfully", () => {
    expect(toolApprovalActionPreview({
      terminalSessionId: "sandbox-terminal-a",
      stdinPreview: "ORBIT-71\n",
      stdinChars: 9,
    }, "write_stdin")).toContain("stdin (9 chars):\nORBIT-71\n");
    expect(toolApprovalSessionGrantDescription({ kind: "terminal_session" }, "zh"))
      .toContain("同一终端");
  });
});
