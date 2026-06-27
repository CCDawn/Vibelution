$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-DesktopEntryCatalogPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    return Join-Path $ProjectDir "desktop/electron/desktop-entry-catalog.json"
}

function Read-DesktopEntryCatalog {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    $catalogPath = Get-DesktopEntryCatalogPath -ProjectDir $ProjectDir
    if (-not (Test-Path -LiteralPath $catalogPath)) {
        throw "Desktop entry catalog is missing: $catalogPath"
    }
    return Get-Content -LiteralPath $catalogPath -Raw | ConvertFrom-Json
}

function Assert-DesktopEntryCatalog {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    $catalog = Read-DesktopEntryCatalog -ProjectDir $ProjectDir
    if ($catalog.schemaVersion -ne 1) {
        throw "Desktop entry catalog schemaVersion must be 1."
    }

    $publicEntries = @()
    if ($null -ne $catalog.publicProductEntries) {
        $publicEntries = @($catalog.publicProductEntries)
    }
    if ($publicEntries.Count -ne 1) {
        throw "Desktop entry catalog must declare exactly one public product entry."
    }

    $publicEntry = $publicEntries[0]
    if ([string]$publicEntry.id -ne "vibelution-desktop-package") {
        throw "Desktop public product entry id must be vibelution-desktop-package."
    }
    if ([string]$publicEntry.path -ne "dist/desktop/win-unpacked/Vibelution.exe") {
        throw "Desktop public product entry path must be dist/desktop/win-unpacked/Vibelution.exe."
    }
    if ([string]$publicEntry.target -ne "launcher") {
        throw "Desktop public product entry must target launcher."
    }
    if ([string]$publicEntry.windowProvider -ne "electron") {
        throw "Desktop public product entry must use the electron window provider."
    }
    if ($publicEntry.shortcutAllowed -ne $true) {
        throw "Desktop public product entry must be the only shortcut-allowed entry."
    }

    $operatorPaths = @($catalog.operatorEntries | ForEach-Object { [string]$_.path })
    if ($operatorPaths -notcontains "scripts/vibelution_launcher.ps1" -or $operatorPaths -notcontains "scripts/vibelution_launcher.py") {
        throw "Desktop entry catalog must preserve launcher scripts as operator entries."
    }
    foreach ($operatorEntry in @($catalog.operatorEntries)) {
        if ($operatorEntry.publicProductEntry -eq $true) {
            throw "Operator entries must not be public product entries."
        }
    }

    $fallbackProviders = @($catalog.fallbackProviders | ForEach-Object { [string]$_.provider })
    if ($fallbackProviders -notcontains "edge_app") {
        throw "Desktop entry catalog must classify edge_app as a fallback provider."
    }
    foreach ($fallbackProvider in @($catalog.fallbackProviders)) {
        if ($fallbackProvider.publicProductEntry -eq $true) {
            throw "Fallback providers must not be public product entries."
        }
    }

    $forbiddenWorkbenchEntry = @($catalog.forbiddenProductEntries | Where-Object { [string]$_.target -eq "workbench" })
    if ($forbiddenWorkbenchEntry.Count -lt 1) {
        throw "Desktop entry catalog must forbid direct Workbench product entries."
    }

    $publicDeepLinks = @($catalog.deepLinks | Where-Object { $_.publicProductEntry -eq $true })
    if ($publicDeepLinks.Count -ne 1 -or [string]$publicDeepLinks[0].route -ne "vibelution://launcher/focus") {
        throw "Desktop entry catalog must expose only launcher focus as the public V1 deep link."
    }

    return $catalog
}

function Resolve-DesktopPublicEntryPath {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Catalog,
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    $publicEntries = @($Catalog.publicProductEntries)
    if ($publicEntries.Count -ne 1) {
        throw "Desktop entry catalog must be asserted before resolving the public entry path."
    }
    return Join-Path $ProjectDir ([string]$publicEntries[0].path)
}
