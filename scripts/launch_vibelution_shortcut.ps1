param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ProjectDir supplies installation metadata and identifies legacy aliases only.
$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
$catalogScript = Join-Path $ProjectDir "scripts\desktop_entry_catalog.ps1"
if (-not (Test-Path -LiteralPath $catalogScript -PathType Leaf)) {
    throw "Desktop entry catalog helper is missing: $catalogScript. Run scripts\install_windows.ps1."
}
. $catalogScript
$catalog = Assert-DesktopEntryCatalog -ProjectDir $ProjectDir
$entryExe = Resolve-DesktopPublicEntryPath -Catalog $catalog
$startArgs = Resolve-DesktopPublicEntryArguments -Catalog $catalog
if (-not (Test-Path -LiteralPath $entryExe -PathType Leaf)) {
    throw "Managed native Launcher entry is missing: $entryExe. Run scripts\install_windows.ps1 before launching the assistant."
}

$shell = New-Object -ComObject WScript.Shell
$null = Set-VibelutionStartMenuLauncherShortcut -Shell $shell `
    -TargetPath $entryExe -Arguments $startArgs -IconPath $entryExe
$null = Set-VibelutionDesktopLauncherShortcut -Shell $shell -ProjectDir $ProjectDir `
    -TargetPath $entryExe -Arguments $startArgs -IconPath $entryExe

Start-Process `
    -FilePath $entryExe `
    -ArgumentList $startArgs `
    -WorkingDirectory (Split-Path -Parent $entryExe) `
    -WindowStyle Hidden | Out-Null
