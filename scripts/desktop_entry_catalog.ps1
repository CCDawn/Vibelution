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

function Set-VibelutionDesktopLauncherShortcut {
    param(
        [Parameter(Mandatory = $true)][object]$Shell,
        [Parameter(Mandatory = $true)][string]$ProjectDir,
        [Parameter(Mandatory = $true)][string]$TargetPath,
        [Parameter(Mandatory = $true)][string]$Arguments,
        [Parameter(Mandatory = $true)][string]$IconPath,
        [string]$DesktopDirectory = [Environment]::GetFolderPath("Desktop")
    )

    if (-not $DesktopDirectory) {
        return ""
    }
    $shortcutPath = Join-Path $DesktopDirectory "Vibelution Launcher.lnk"
    $shortcut = $Shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $ProjectDir
    $shortcut.IconLocation = ('{0},0' -f $IconPath)
    $shortcut.Description = "Vibelution Launcher"
    $shortcut.WindowStyle = 7
    $shortcut.Save()

    # Save the canonical entry before retiring a positively identified alias.
    # A same-named shortcut for another project or program is not ours to remove.
    $legacyPath = Join-Path $DesktopDirectory "Vibelution.lnk"
    if (Test-Path -LiteralPath $legacyPath -PathType Leaf) {
        $legacyItem = Get-Item -LiteralPath $legacyPath -Force
        if (($legacyItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
            $legacy = $Shell.CreateShortcut($legacyPath)
            $packagedEntry = Join-Path $ProjectDir "dist\desktop\win-unpacked\Vibelution.exe"
            $projectArguments = '--workspace "{0}"' -f $ProjectDir
            $knownLegacyArguments = @(
                $projectArguments,
                ($projectArguments + ' "vibelution://launcher/focus"'),
                ($projectArguments + ' vibelution://launcher/focus')
            )
            $sameEntry = $legacy.TargetPath -eq $TargetPath -and $legacy.Arguments -eq $Arguments
            $projectEntry = $legacy.TargetPath -eq $packagedEntry -and $knownLegacyArguments -contains $legacy.Arguments.Trim()
            if ($sameEntry -or $projectEntry) {
                Remove-Item -LiteralPath $legacyPath -ErrorAction Stop
            }
        }
    }
    return $shortcutPath
}
