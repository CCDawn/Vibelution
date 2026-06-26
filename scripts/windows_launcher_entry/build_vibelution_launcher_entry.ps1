param(
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $OutputPath) {
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    if (-not $localAppData) {
        $localAppData = Join-Path $ProjectDir ".runtime\launcher"
    }
    $OutputPath = Join-Path $localAppData "Vibelution\Launcher\VibelutionLauncher.exe"
}

$sourcePath = Join-Path $PSScriptRoot "VibelutionLauncher.cs"
$iconPath = Join-Path $ProjectDir "assets\icons\vibelution.ico"
if (-not (Test-Path -LiteralPath $sourcePath)) {
    throw "Native launcher entry source not found: $sourcePath"
}
if (-not (Test-Path -LiteralPath $iconPath)) {
    throw "Vibelution icon not found: $iconPath"
}

$candidateCompilers = @(
    (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v3.5\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework\v3.5\csc.exe")
)
$compilerPath = $candidateCompilers | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $compilerPath) {
    throw "C# compiler not found. Install .NET Framework compiler support or use the script-host fallback shortcut."
}

$outputDir = Split-Path -Parent $OutputPath
if (-not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

$arguments = @(
    "/nologo",
    "/target:winexe",
    "/optimize+",
    "/platform:anycpu",
    "/reference:System.Windows.Forms.dll",
    "/reference:System.Drawing.dll",
    ("/win32icon:{0}" -f $iconPath),
    ("/out:{0}" -f $OutputPath),
    $sourcePath
)

& $compilerPath @arguments
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $OutputPath)) {
    throw "Failed to build native launcher entry: $OutputPath"
}

[pscustomobject]@{
    outputPath = $OutputPath
    compilerPath = $compilerPath
    sourcePath = $sourcePath
    iconPath = $iconPath
} | ConvertTo-Json -Depth 3
