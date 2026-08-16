param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
$buildScript = Join-Path $ProjectDir "scripts\windows_launcher_entry\build_vibelution_launcher_entry.ps1"
$sourcePath = Join-Path $ProjectDir "scripts\windows_launcher_entry\VibelutionLauncher.cs"
$iconPath = Join-Path $ProjectDir "assets\icons\vibelution.ico"

if (-not (Test-Path -LiteralPath $buildScript)) {
    throw "Native launcher build script not found: $buildScript"
}
if (-not (Test-Path -LiteralPath $sourcePath)) {
    throw "Native launcher source not found: $sourcePath"
}

function Get-NativeEntryCacheKey {
    param(
        [string]$SourcePath,
        [string]$BuildScriptPath,
        [string]$IconPath
    )

    $parts = @(
        (Get-FileHash -LiteralPath $SourcePath -Algorithm SHA256).Hash
        (Get-FileHash -LiteralPath $BuildScriptPath -Algorithm SHA256).Hash
    )
    if (Test-Path -LiteralPath $IconPath) {
        $parts += (Get-FileHash -LiteralPath $IconPath -Algorithm SHA256).Hash
    }
    $combined = ($parts -join "|")
    return ($combined.Substring(0, [Math]::Min(16, $combined.Length))).ToLowerInvariant()
}

$localAppData = [Environment]::GetFolderPath("LocalApplicationData")
if (-not $localAppData) {
    $localAppData = Join-Path $ProjectDir ".runtime\launcher"
}
$cacheDir = Join-Path $localAppData "Vibelution\Launcher\entry-cache"
New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null

$cacheKey = Get-NativeEntryCacheKey -SourcePath $sourcePath -BuildScriptPath $buildScript -IconPath $iconPath
$entryExe = Join-Path $cacheDir ("VibelutionLauncher.{0}.exe" -f $cacheKey)

if (-not (Test-Path -LiteralPath $entryExe)) {
    $null = & $buildScript -ProjectDir $ProjectDir -OutputPath $entryExe
    if (-not (Test-Path -LiteralPath $entryExe)) {
        throw "Native launcher entry build did not produce: $entryExe"
    }
}

$startArgs = @(
    "--from-shortcut",
    "--project",
    $ProjectDir,
    "--action",
    "launcher"
)
Start-Process `
    -FilePath $entryExe `
    -ArgumentList $startArgs `
    -WorkingDirectory $ProjectDir `
    -WindowStyle Hidden | Out-Null
