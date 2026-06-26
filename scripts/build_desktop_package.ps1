$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$electronDir = Join-Path $projectDir "desktop/electron"

npm --prefix $electronDir install
npm --prefix $electronDir run package:dir
