import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const scriptPath = fileURLToPath(new URL("../../../scripts/build_desktop_package.ps1", import.meta.url));

describe("desktop package script", () => {
  it("does not mask npm or node failures before writing the launch profile", () => {
    const script = readFileSync(scriptPath, "utf8");

    expect(script).toContain("function Invoke-CheckedNative");
    expect(script).toContain("if ($LASTEXITCODE -ne 0)");
    expect(script).toMatch(/Invoke-CheckedNative npm @\("--prefix", \$electronDir, "install"\)/);
    expect(script).toMatch(/Invoke-CheckedNative npm @\("--prefix", \$electronDir, "run", "package:dir"\)/);
    expect(script).toMatch(/Invoke-CheckedNative node @\(/);
    expect(script).not.toMatch(/^\s*npm --prefix/m);
    expect(script).not.toMatch(/^\s*node \$desktopLaunchProfileWriter/m);
  });
});
