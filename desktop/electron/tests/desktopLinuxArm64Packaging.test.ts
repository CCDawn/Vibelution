import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const packageJsonPath = fileURLToPath(new URL("../package.json", import.meta.url));
const electronBuilderConfigPath = fileURLToPath(new URL("../electron-builder.json", import.meta.url));
const builderSource = readFileSync(fileURLToPath(new URL("../scripts/buildDesktopPackage.js", import.meta.url)), "utf8");

const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf8")) as {
  main?: string;
  scripts?: Record<string, string>;
  devDependencies?: Record<string, string>;
};
const builderConfig = JSON.parse(readFileSync(electronBuilderConfigPath, "utf8")) as {
  files?: string[];
  linux?: {
    target?: string[];
    artifactName?: string;
    files?: string[];
  };
};

describe("linux arm64 packaging", () => {
  it("exposes a deterministic Linux ARM64 unpacked packaging command", () => {
    const script = packageJson.scripts?.["package:linux-arm64:dir"];

    expect(script).toBeDefined();
    expect(script).toContain("runDesktopPackage.js --mode linux-arm64");
    expect(builderSource).toContain('builderArgs.push("--linux", "dir", "--arm64")');
    expect(builderSource).toContain('"--config", generatedConfigPath');
    expect(script).not.toMatch(/--x64|--ia32/);
    expect(script).not.toContain("npm run build &&");
  });

  it("configures electron-builder for a Linux dir target", () => {
    expect(builderConfig.linux).toBeDefined();
    expect(builderConfig.linux?.target).toEqual(["dir"]);
    expect(builderConfig.linux?.artifactName).toMatch(/Vibelution-\$\{version\}-\$\{arch\}\.\$\{ext\}/);
  });

  it("preserves the Electron main/preload output contract for the Linux bundle", () => {
    // Runtime entry points: tsc emits dist/main.js, the preload build emits dist/preload.cjs.
    expect(packageJson.main).toBe("dist/main.js");
    expect(packageJson.scripts?.["build:preload"]).toContain("runDesktopPackage.js --mode unpackaged");
    expect(builderSource).toContain('`--outfile=${join(distRoot, "preload.cjs")}`');
    expect(builderSource).toContain('"--external:electron"');

    // The shared top-level files list must still ship both outputs; the Linux
    // block must not override it with a narrower set.
    expect(builderConfig.files).toContain("dist/**/*");
    expect(builderConfig.linux?.files).toBeUndefined();
  });

  it("packages the Electron runtime for Linux ARM64", () => {
    // electron-builder assembles the unpacked bundle from the pinned Electron
    // devDependency; without either the bundle cannot contain the runtime.
    expect(packageJson.devDependencies?.["electron"]).toBeDefined();
    expect(packageJson.devDependencies?.["electron-builder"]).toBeDefined();
  });
});
