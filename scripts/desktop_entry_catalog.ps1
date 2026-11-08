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

function Get-DesktopPublicProductEntry {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Catalog
    )

    if ($Catalog.schemaVersion -ne 1) {
        throw "Desktop entry catalog schemaVersion must be 1."
    }

    $publicEntries = @($Catalog.publicProductEntries)
    if ($publicEntries.Count -ne 1) {
        throw "Desktop entry catalog must declare exactly one public product entry."
    }

    $publicEntry = $publicEntries[0]
    if ([string]$publicEntry.id -cne "vibelution-desktop-package") {
        throw "Desktop public product entry id must be vibelution-desktop-package."
    }
    if ([string]$publicEntry.pathBase -cne "localAppData" -or
        [string]$publicEntry.path -cne "Vibelution/Launcher/VibelutionLauncher.exe") {
        throw "Desktop public product entry must be LocalApplicationData/Vibelution/Launcher/VibelutionLauncher.exe."
    }
    $arguments = @($publicEntry.arguments)
    if ($publicEntry.arguments -isnot [Array] -or $arguments.Count -ne 1 -or
        $arguments[0] -isnot [string] -or $arguments[0] -cne "--assistant") {
        throw "Desktop public product entry arguments must be exactly [--assistant]."
    }
    if ([string]$publicEntry.target -ne "launcher") {
        throw "Desktop public product entry must target launcher."
    }
    if ([string]$publicEntry.windowProvider -ne "electron") {
        throw "Desktop public product entry must use the electron window provider."
    }
    if ($publicEntry.shortcutAllowed -ne $true -or $publicEntry.publicProductEntry -ne $true) {
        throw "Desktop public product entry must be the only shortcut-allowed entry."
    }

    return $publicEntry
}

function Get-DesktopPackageArtifactEntry {
    param([Parameter(Mandatory = $true)][object]$Catalog)

    $entries = @($Catalog.operatorEntries | Where-Object { [string]$_.id -ceq "desktop-package-artifact" })
    if ($entries.Count -ne 1) {
        throw "Desktop entry catalog must declare exactly one desktop-package-artifact operator entry."
    }
    $entry = $entries[0]
    if ([string]$entry.pathBase -cne "project" -or
        [string]$entry.path -cne "dist/desktop/win-unpacked/Vibelution.exe" -or
        $entry.publicProductEntry -ne $false -or $entry.shortcutAllowed -ne $false) {
        throw "Desktop package artifact must remain a non-public checkout build artifact."
    }
    return $entry
}

function Assert-DesktopEntryCatalog {
    param([Parameter(Mandatory = $true)][string]$ProjectDir)

    $catalog = Read-DesktopEntryCatalog -ProjectDir $ProjectDir
    $null = Get-DesktopPublicProductEntry -Catalog $catalog
    $null = Get-DesktopPackageArtifactEntry -Catalog $catalog

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
        [object]$Catalog
    )

    $entry = Get-DesktopPublicProductEntry -Catalog $Catalog
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    if (-not $localAppData) {
        throw "Windows LocalApplicationData KnownFolder could not be resolved for the public Launcher entry."
    }
    return Join-Path $localAppData ([string]$entry.path)
}

function Resolve-DesktopPublicEntryArguments {
    param([Parameter(Mandatory = $true)][object]$Catalog)

    $entry = Get-DesktopPublicProductEntry -Catalog $Catalog
    return [string]$entry.arguments[0]
}

function Resolve-DesktopPackageEntryPath {
    param(
        [Parameter(Mandatory = $true)][object]$Catalog,
        [Parameter(Mandatory = $true)][string]$ProjectDir
    )

    $entry = Get-DesktopPackageArtifactEntry -Catalog $Catalog
    return Join-Path $ProjectDir ([string]$entry.path)
}

function Set-VibelutionLauncherShellShortcut {
    param(
        [Parameter(Mandatory = $true)][object]$Shell,
        [Parameter(Mandatory = $true)][string]$ShortcutPath,
        [Parameter(Mandatory = $true)][string]$TargetPath,
        [Parameter(Mandatory = $true)][string]$Arguments,
        [Parameter(Mandatory = $true)][string]$IconPath
    )

    $shortcut = $Shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = Split-Path -Parent $TargetPath
    $shortcut.IconLocation = ('{0},0' -f $IconPath)
    $shortcut.Description = "Vibelution Launcher"
    $shortcut.WindowStyle = 7
    $shortcut.Save()
}

function Set-VibelutionStartMenuLauncherShortcut {
    param(
        [Parameter(Mandatory = $true)][object]$Shell,
        [Parameter(Mandatory = $true)][string]$TargetPath,
        [Parameter(Mandatory = $true)][string]$Arguments,
        [Parameter(Mandatory = $true)][string]$IconPath,
        [string]$ProgramsDirectory = [Environment]::GetFolderPath("Programs")
    )

    if (-not $ProgramsDirectory) {
        throw "Windows Start Menu Programs KnownFolder could not be resolved."
    }
    if (-not (Test-Path -LiteralPath $ProgramsDirectory -PathType Container)) {
        $null = New-Item -ItemType Directory -Path $ProgramsDirectory -Force
    }
    $shortcutPath = Join-Path $ProgramsDirectory "Vibelution.lnk"
    Set-VibelutionLauncherShellShortcut -Shell $Shell -ShortcutPath $shortcutPath `
        -TargetPath $TargetPath -Arguments $Arguments -IconPath $IconPath
    return $shortcutPath
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
    Set-VibelutionLauncherShellShortcut -Shell $Shell -ShortcutPath $shortcutPath `
        -TargetPath $TargetPath -Arguments $Arguments -IconPath $IconPath

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
