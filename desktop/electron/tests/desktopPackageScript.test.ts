import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const buildScriptPath = fileURLToPath(new URL("../../../scripts/build_desktop_package.ps1", import.meta.url));
const verifyScriptPath = fileURLToPath(new URL("../../../scripts/verify_desktop_package.ps1", import.meta.url));
const lifecycleScriptPath = fileURLToPath(new URL("../../../scripts/verify_desktop_lifecycle.ps1", import.meta.url));
const electronBuilderConfigPath = fileURLToPath(new URL("../electron-builder.json", import.meta.url));

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

  it("packages the desktop executable with the shared Vibelution icon", () => {
    const config = JSON.parse(readFileSync(electronBuilderConfigPath, "utf8")) as {
      files?: string[];
      win?: { icon?: string };
    };

    expect(config.win?.icon).toBe("../../assets/icons/vibelution.ico");
    expect(config.files).toContain("desktop-entry-catalog.json");
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
    expect(script).not.toContain("$desktopExe = Join-Path $projectDir \"dist/desktop/win-unpacked/Vibelution.exe\"");
    expect(script).toContain("Invoke-CheckedNative powershell @(\"-ExecutionPolicy\", \"Bypass\", \"-File\", $packageVerifier");
    expect(script).toContain("Start-Process -FilePath $desktopExe -PassThru");
    expect(script).toContain("Start-Process -FilePath $desktopExe -PassThru");
    expect(script).toContain("Stop-Process -Id");
    expect(script).toContain("First desktop launch did not remain running.");
    expect(script).toContain("firstInstanceStayedRunning");
    expect(script).toContain("secondInstanceCreatedExtraRoot");
    expect(script).not.toContain("taskkill");
    expect(script).not.toContain("Stop-Process -Name Vibelution");
    expect(script).not.toContain("scripts/build_desktop_package.ps1");
  });
});
