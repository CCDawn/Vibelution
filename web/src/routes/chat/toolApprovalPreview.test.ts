import { describe, expect, it } from "vitest";

import {
  toolApprovalActionPreview,
  toolApprovalCodexButtonLabels,
  toolApprovalCodexTitle,
  toolApprovalDisplayName,
  toolApprovalSessionGrantDescription,
} from "./toolApprovalPreview";

describe("toolApprovalPreview", () => {
  it("prefers command preview for shell tools like Codex", () => {
    expect(toolApprovalActionPreview({
      commandPreview: "curl https://example.com",
      argumentKeys: ["cmd"],
    }, "web_fetch_tool")).toBe("$ curl https://example.com");
  });

  it("shows cwd and stdin while keeping session grants truthful", () => {
    expect(toolApprovalActionPreview({
      commandPreview: '.\\.venv\\Scripts\\python.exe -c "print(123)"',
      cwdPreview: "C:\\workspace\\repo",
    }, "exec_command")).toContain("cwd: C:\\workspace\\repo");
    expect(toolApprovalActionPreview({
      terminalSessionId: "sandbox-terminal-a",
      stdinPreview: "ORBIT-71\n",
      stdinChars: 9,
    }, "write_stdin")).toContain("stdin (9 chars):\nORBIT-71\n");
    expect(toolApprovalSessionGrantDescription({ kind: "terminal_session" }, "zh"))
      .toContain("同一终端");
  });

  it("falls back to path preview then tool label", () => {
    expect(toolApprovalActionPreview({
      pathPreview: "docs/readme.md",
    }, "read_file_tool")).toBe("docs/readme.md");
    expect(toolApprovalDisplayName("web_fetch_tool", "zh")).toBe("读取网页");
  });

  it("uses Codex-style title and Yes/Always/No labels", () => {
    expect(toolApprovalCodexTitle("zh")).toBe("允许执行？");
    expect(toolApprovalCodexTitle("en")).toBe("Allow this action?");
    expect(toolApprovalCodexButtonLabels("en")).toMatchObject({
      yes: "Yes",
      always: "Always (session)",
      no: "No",
    });
    expect(toolApprovalCodexButtonLabels("zh")).toMatchObject({
      yes: "是",
      always: "始终（本会话）",
      no: "否",
    });
  });
});
