import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
// @ts-expect-error Build entrypoints are plain JavaScript, outside the source TS project.
import { createIsolatedBuilderConfig, resolveInstalledElectronDistribution, runDesktopPackageBuild } from "../scripts/buildDesktopPackage.js";

const buildScriptPath = fileURLToPath(new URL("../../../scripts/build_desktop_package.ps1", import.meta.url));
const verifyScriptPath = fileURLToPath(new URL("../../../scripts/verify_desktop_package.ps1", import.meta.url));
const lifecycleScriptPath = fileURLToPath(new URL("../../../scripts/verify_desktop_lifecycle.ps1", import.meta.url));
const workbenchCloseCanaryScriptPath = fileURLToPath(
  new URL("../../../scripts/verify_desktop_workbench_close.ps1", import.meta.url)
);
const electronBuilderConfigPath = fileURLToPath(new URL("../electron-builder.json", import.meta.url));
const packageBuilderPath = fileURLToPath(new URL("../scripts/buildDesktopPackage.js", import.meta.url));
const packageOwnerPath = fileURLToPath(new URL("../scripts/runDesktopPackage.js", import.meta.url));
const provenanceWriterPath = fileURLToPath(new URL("../src/scripts/writePackageProvenance.ts", import.meta.url));
const frontendBundlePath = fileURLToPath(new URL("../src/packaging/frontendBundle.ts", import.meta.url));

describe("installed Electron package runtime", () => {
  function fixture(run: (root: string, dist: string) => void) {
    const root = mkdtempSync(join(tmpdir(), "vibelution-electron-dist-"));
    const installed = join(root, "node_modules", "electron");
    const dist = join(installed, "dist");
    mkdirSync(dist, { recursive: true });
    writeFileSync(join(installed, "package.json"), JSON.stringify({ version: "42.5.0" }));
    writeFileSync(join(dist, "version"), "42.5.0\n");
    writeFileSync(join(dist, "electron.exe"), "fixture");
    try { run(root, dist); } finally { rmSync(root, { recursive: true, force: true }); }
  }

  it("packages the matching installed runtime without changing its source directory", () => {
    fixture((root, dist) => {
      const baseConfig = { files: ["dist/**/*"] };
      const config = createIsolatedBuilderConfig({
        baseConfig, electronRoot: root, appRoot: join(root, "app"),
        outputRoot: join(root, "out"), frontendRoot: join(root, "web"),
        assistantRoot: join(root, "assistant"),
        electronDistribution: resolveInstalledElectronDistribution(root, "staging", "win32"),
      });
      expect(config.electronDist).toBe(dist);
      expect(config.electronVersion).toBe("42.5.0");
      expect(baseConfig).toEqual({ files: ["dist/**/*"] });
      expect(config.extraResources).toContainEqual({ from: join(root, "assistant"), to: "launcher-assistant" });
      expect(existsSync(join(dist, "electron.exe"))).toBe(true);
    });
  });

  it("rejects a mismatched or incomplete installed distribution", () => {
    fixture((root, dist) => {
      writeFileSync(join(dist, "version"), "41.0.0");
      expect(() => resolveInstalledElectronDistribution(root, "dir", "win32")).toThrow(/version/);
      writeFileSync(join(dist, "version"), "42.5.0");
      rmSync(join(dist, "electron.exe"));
      expect(() => resolveInstalledElectronDistribution(root, "dir", "win32")).toThrow(/incomplete/);
    });
  });

  it("does not reuse the host runtime for a Linux ARM64 cross-build", () => {
    expect(resolveInstalledElectronDistribution("missing-host-installation", "linux-arm64", "win32")).toEqual({});
  });

  it("rejects the unsupported migrated assistant cross-build before output", () => {
    expect(() => runDesktopPackageBuild({ mode: "linux-arm64" })).toThrow(/assistant.*Windows/);
  });

  it("refuses a production package configuration without its owned assistant", () => {
    expect(() => createIsolatedBuilderConfig({ baseConfig: {}, appRoot: "app", outputRoot: "out", frontendRoot: "web" }))
      .toThrow(/owner-built assistant/);
  });

  it.skipIf(process.platform !== "win32")("consumes only the one prepared payload session and refuses reuse", () => {
    fixture((root) => {
      const workspace = join(root, "workspace");
      const session = join(workspace, "dist", ".desktop-shell-build-fixture");
      const assistantRoot = join(session, "launcher-assistant");
      mkdirSync(assistantRoot, { recursive: true });
      writeFileSync(join(assistantRoot, "manifest.json"), "{}");
      writeFileSync(join(root, "package.json"), "{}");
      writeFileSync(join(root, "desktop-entry-catalog.json"), "{}");
      vi.stubEnv("VIBELUTION_DESKTOP_BUILD_MANAGED", "1");
      vi.stubEnv("VIBELUTION_DESKTOP_BUILD_ROOT", session);
      vi.stubEnv("VIBELUTION_ASSISTANT_PAYLOAD_ROOT", assistantRoot);
      vi.stubEnv("VIBELUTION_ASSISTANT_MANIFEST_SHA256", "c".repeat(64));
      let compilerReached = false;
      try {
        const options = { workspaceRoot: workspace, electronRoot: root, run: (_exe: string, args: string[]) => {
          compilerReached = args[0].endsWith("tsc");
          throw new Error("fixture compile gate");
        } };
        expect(() => runDesktopPackageBuild(options)).toThrow("fixture compile gate");
        expect(compilerReached).toBe(true);
        expect(() => runDesktopPackageBuild(options)).toThrow("only its owner-built assistant payload");
      } finally { vi.unstubAllEnvs(); }
    });
  });
});

describe("desktop package script", () => {
  it("does not mask npm or node failures before writing the launch profile", () => {
    const script = readFileSync(buildScriptPath, "utf8");

    expect(script).toContain("function Invoke-CheckedNative");
    expect(script).toContain("if ($LASTEXITCODE -ne 0)");
    expect(script).toMatch(/Invoke-CheckedNative npm @\("--prefix", \$electronDir, "install"\)/);
    expect(script).toMatch(/Invoke-CheckedNative npm @\("--prefix", \$electronDir, "run", "package:dir"\)/);
    expect(script).toMatch(/Invoke-CheckedNative node @\(/);
    expect(script).not.toMatch(/^\s*npm --prefix/m);
    expect(script).not.toMatch(/^\s*node \$desktopLaunchProfileWriter/m);
  });

  it("uses the project virtual environment and validates its Launcher dependency before packaging", () => {
    const script = readFileSync(buildScriptPath, "utf8");

    expect(script).toContain('$projectVenvPythonPath = Join-Path $projectDir ".venv\\Scripts\\python.exe"');
    expect(script).toMatch(
      /if \(Test-Path -LiteralPath \$projectVenvPythonPath\) \{\s*return \(Resolve-Path -LiteralPath \$projectVenvPythonPath\)\.Path\s*\}/
    );
    expect(script).toContain("function Assert-DesktopProfilePython");
    expect(script).toContain('Invoke-CheckedNative $PythonPath @("-c", "import uvicorn")');
    expect(script).toContain("Assert-DesktopProfilePython -PythonPath $pythonPath");
  });

  it("packages the desktop executable with the shared Vibelution icon", () => {
    const config = JSON.parse(readFileSync(electronBuilderConfigPath, "utf8")) as {
      files?: string[];
      asarUnpack?: string[];
      win?: { icon?: string };
    };

    expect(config.win?.icon).toBe("../../assets/icons/vibelution.ico");
    expect(config.files).toContain("desktop-entry-catalog.json");
    expect(config.files).toContain("package-provenance.json");
    expect(config.asarUnpack).toContain("package-provenance.json");
  });

  it("routes package entrypoints through the bounded Python build owner", () => {
    const packageJson = JSON.parse(readFileSync(fileURLToPath(new URL("../package.json", import.meta.url)), "utf8")) as {
      scripts?: Record<string, string>;
    };
    const owner = readFileSync(packageOwnerPath, "utf8");
    const builder = readFileSync(packageBuilderPath, "utf8");

    expect(packageJson.scripts?.["package:dir"]).toContain("runDesktopPackage.js --mode dir");
    expect(packageJson.scripts?.["package:staging"]).toContain("runDesktopPackage.js --mode staging");
    expect(packageJson.scripts?.["package:linux-arm64:dir"]).toContain("runDesktopPackage.js --mode linux-arm64");
    for (const entry of ["build", "build:preload", "build:job"]) {
      expect(packageJson.scripts?.[entry]).toContain("runDesktopPackage.js --mode unpackaged");
    }
    expect(owner).toContain("build_desktop_shell_package.py");
    expect(builder).toContain("VIBELUTION_DESKTOP_BUILD_MANAGED");
    expect(builder).toContain("Invoke desktop packaging through the Python build owner.");
  });

  it("packages the verified active frontend release and binds its copied bytes", () => {
    const config = JSON.parse(readFileSync(electronBuilderConfigPath, "utf8")) as {
      extraResources?: Array<{ from?: string; to?: string }>;
    };
    const writer = readFileSync(provenanceWriterPath, "utf8");
    const frontendBundle = readFileSync(frontendBundlePath, "utf8");
    const packageJson = JSON.parse(readFileSync(fileURLToPath(new URL("../package.json", import.meta.url)), "utf8")) as {
      scripts?: Record<string, string>;
    };

    expect(JSON.stringify(config)).not.toContain("node_modules/.cache/vibelution-package-web-dist");
    expect((config.extraResources ?? []).some((entry) => entry.from === "../../web/dist")).toBe(false);
    expect(writer).toContain("preparePackagedFrontend");
    expect(frontendBundle).toContain("ensure-frontend-build");
    expect(frontendBundle).toContain("frontendContentSha256");
    expect(readFileSync(packageBuilderPath, "utf8")).toContain("frontendRoot");
    expect(readFileSync(packageBuilderPath, "utf8")).toContain('{ from: resolve(input.frontendRoot), to: "web-dist" }');
    expect(readFileSync(packageBuilderPath, "utf8")).toContain('{ from: resolve(input.assistantRoot), to: "launcher-assistant" }');
    expect(packageJson.scripts?.["package:linux-arm64:dir"]).toContain("runDesktopPackage.js --mode linux-arm64");
  });

  it("provides a reusable package verification entrypoint", () => {
    const script = readFileSync(verifyScriptPath, "utf8");

    expect(script).toContain("param(");
    expect(script).toContain("function Invoke-CheckedNative");
    expect(script).toContain("$entryCatalogScript = Join-Path $projectDir \"scripts/desktop_entry_catalog.ps1\"");
    expect(script).toContain(". $entryCatalogScript");
    expect(script).toContain("$desktopExe = Resolve-DesktopPublicEntryPath");
    expect(script).toContain("Assert-DesktopEntryCatalog");
    expect(script).toContain("function Assert-NoDesktopPackageProcesses");
    expect(script).toContain("function Wait-ForNoNewDesktopPackageProcesses");
    expect(script).toContain("[AllowEmptyCollection()]");
    expect(script).toContain("$buildScript = Join-Path $projectDir \"scripts/build_desktop_package.ps1\"");
    expect(script).not.toContain("$desktopExe = Join-Path $projectDir \"dist/desktop/win-unpacked/Vibelution.exe\"");
    expect(script).toContain("$launchProfilePath = Join-Path $desktopResourcesDir \"vibelution-launch-profile.json\"");
    expect(script).toContain("$summaryPath = Join-Path $projectDir \".runtime/launcher/electron-smoke-summary.json\"");
    expect(script).toContain("Invoke-CheckedNative powershell @(\"-ExecutionPolicy\", \"Bypass\", \"-File\", $buildScript)");
    expect(script).toContain("Start-Process -FilePath $desktopExe -ArgumentList @(\"--smoke\") -PassThru");
    expect(script).toContain("ConvertFrom-Json");
    expect(script).toContain("$summary.bootstrap.parsed -ne $true");
    expect(script).toContain("$summary.bootstrap.mode -eq \"started\"");
    expect(script).toContain("$summary.shutdown.stopStatus -ne \"stopped\"");
    expect(script).not.toContain("taskkill");
    expect(script).not.toContain("Stop-Process -Name Vibelution");
  });

  it("promotes public shortcuts only from a clean main package after smoke and cleanup", () => {
    const script = readFileSync(verifyScriptPath, "utf8");
    const smokeIndex = script.indexOf("$summary = Assert-SmokeSummary");
    const cleanupIndex = script.indexOf("Wait-ForNoNewDesktopPackageProcesses $baselineProcessIds");
    const sourceRecheckIndex = script.indexOf(
      "Assert-PublicEntryPromotionSourceStillCurrent -ExpectedSource $expectedPromotionSource"
    );
    const shortcutIndex = script.indexOf('$null = & $launcherScript -Action "repair-shortcut"');

    expect(script).toContain('$launcherScript = Join-Path $projectDir "scripts/vibelution_launcher.ps1"');
    expect(script).toContain("[switch]$PromotePublicEntry");
    expect(script).toContain("function Assert-PublicEntryPromotionSource");
    expect(script).toContain("Public entry promotion requires a clean main checkout.");
    expect(script).toContain('Invoke-GitText @("status", "--porcelain", "--untracked-files=all")');
    expect(script).toContain("function Assert-PublicEntryPackageProvenance");
    expect(script).toContain("function Assert-PublicEntryPromotionSourceStillCurrent");
    expect(script).toContain("Public entry promotion source changed during package verification.");
    expect(script).toContain("$packageProvenance.sourceCommit -ne $ExpectedSource.sourceCommit");
    expect(script).toContain("$packageProvenance.electronTreeHash -ne $ExpectedSource.electronTreeHash");
    expect(smokeIndex).toBeGreaterThanOrEqual(0);
    expect(cleanupIndex).toBeGreaterThan(smokeIndex);
    expect(sourceRecheckIndex).toBeGreaterThan(cleanupIndex);
    expect(shortcutIndex).toBeGreaterThan(sourceRecheckIndex);
    expect(script).toContain("if ($PromotePublicEntry -and $SkipBuild)");
    expect(script).toContain("if ($PromotePublicEntry)");
    expect(script).toContain('$null = & $launcherScript -Action "repair-shortcut"');
    expect(script).not.toContain("Start-Process -FilePath powershell");
  });

  it("verifies the packaged executable embeds the shared Vibelution icon", () => {
    const script = readFileSync(verifyScriptPath, "utf8");

    expect(script).toContain("$desktopIconPath = Join-Path $projectDir \"assets/icons/vibelution.ico\"");
    expect(script).toContain("function Assert-DesktopExeIcon");
    expect(script).toContain("[System.Drawing.Icon]::ExtractAssociatedIcon($desktopExe)");
    expect(script).toContain("[System.Drawing.Icon]::ExtractAssociatedIcon($desktopIconPath)");
    expect(script).toContain("Desktop package executable icon does not match shared Vibelution icon.");
    expect(script).toContain("Assert-DesktopExeIcon");
  });

  it("provides a reusable lifecycle verification entrypoint without duplicating package checks", () => {
    const script = readFileSync(lifecycleScriptPath, "utf8");

    expect(script).toContain("param(");
    expect(script).toContain("function Invoke-CheckedNative");
    expect(script).toContain("$entryCatalogScript = Join-Path $projectDir \"scripts/desktop_entry_catalog.ps1\"");
    expect(script).toContain(". $entryCatalogScript");
    expect(script).toContain("$desktopExe = Resolve-DesktopPublicEntryPath");
    expect(script).toContain("Assert-DesktopEntryCatalog");
    expect(script).toContain("function Get-AllVibelutionDesktopProcesses");
    expect(script).toContain("function Get-DesktopPackageProcesses");
    expect(script).toContain("function Assert-NoOtherVibelutionDesktopProcesses");
    expect(script).toContain("function Format-DesktopCommandLine");
    expect(script).toContain("$MaxCommandLineLength = 260");
    expect(script).toContain("function Wait-ForDesktopRootProcess");
    expect(script).toContain("function Stop-OwnedDesktopProcesses");
    expect(script).toContain("function Wait-ForNoOwnedDesktopProcesses");
    expect(script).toContain("$packageVerifier = Join-Path $projectDir \"scripts/verify_desktop_package.ps1\"");
    expect(script).toContain("$canaryUserDataRoot = Join-Path $projectDir \".runtime/electron-package-canary-user-data\"");
    expect(script).toContain('$env:VIBELUTION_ELECTRON_REGISTER_DEEP_LINKS = "0"');
    expect(script).not.toContain("$desktopExe = Join-Path $projectDir \"dist/desktop/win-unpacked/Vibelution.exe\"");
    expect(script).toContain("Invoke-CheckedNative powershell @(\"-ExecutionPolicy\", \"Bypass\", \"-File\", $packageVerifier");
    expect(script).toContain('Start-Process -FilePath $desktopExe -ArgumentList @("--user-data-dir=$canaryUserDataRoot") -PassThru');
    expect(script).toContain("function Request-OwnedDesktopClose");
    expect(script).toContain("CloseMainWindow()");
    expect(script).toContain("Request-OwnedDesktopClose $ownedProcessIds");
    expect(script).toContain("Stop-Process -Id");
    expect(script).toContain("First desktop launch did not remain running.");
    expect(script).toContain("firstInstanceStayedRunning");
    expect(script).toContain("secondInstanceCreatedExtraRoot");
    expect(script).not.toContain("taskkill");
    expect(script).not.toContain("Stop-Process -Name Vibelution");
    expect(script).not.toContain("scripts/build_desktop_package.ps1");
  });

  it("provides a native Workbench-close canary that drives the packaged Electron close event", () => {
    const script = readFileSync(workbenchCloseCanaryScriptPath, "utf8");

    expect(script).toContain("$packageVerifier = Join-Path $projectDir \"scripts/verify_desktop_package.ps1\"");
    expect(script).toContain("$canarySummaryPath = Join-Path $projectDir \".runtime/launcher/electron-workbench-close-canary-summary.json\"");
    expect(script).toContain("--workbench-close-canary");
    expect(script).toContain('$workbenchWindowTitle = "Vibelution Workbench"');
    expect(script).toContain('$workbenchWindowTitleSuffix = " 台"');
    expect(script).toContain("EndsWith($workbenchWindowTitleSuffix)");
    expect(script).toContain("PostMessage");
    expect(script).toContain("WM_CLOSE");
    expect(script).toContain("function Assert-NoActiveWorkbenchWork");
    expect(script).toContain("$status.lifecycleProof.activeWorkRuns.count");
    expect(script).toContain("$activeWorkCountBeforeCanary = Assert-NoActiveWorkbenchWork\nif (-not $SkipPackageVerification)");
    expect(script).toContain("function Wait-ForWorkbenchCloseCanarySummary");
    expect(script).toContain("function Restore-ManagedWorkbench");
    expect(script).toContain("VibelutionLauncher.exe");
    expect(script).toContain("Workbench-close canary did not restore the managed Workbench.");
    expect(script).toContain('$summary.phase -ne "succeeded"');
    expect(script).toContain("Request-OwnedDesktopClose $ownedProcessIds");
    expect(script).not.toContain("taskkill");
    expect(script).not.toContain("Stop-Process -Name Vibelution");
  });
});
