# Windows Installation Guide (End Users)

Other platforms: [macOS](install-macos.md) · [Linux](install-linux.md)

Goal: open the Vibelution workbench on your machine with as few steps as possible.

## What you need

### Phase 1 (current)

Already installed locally:

| Dependency | Recommended version | Check command |
|------|----------|----------|
| Windows | 10/11 | — |
| Python | 3.11+ (3.12 recommended) | `py -3.12 --version` or `python --version` |
| Node.js | 22.12+ recommended (includes npm; Vite 8 requires 20.19+ of 20.x, or 22.12+) | `node --version` / `npm --version` |
| Git | any recent version | `git --version` |
| Browser | Edge (recommended) | — |

> **Phase 2 plan**: the official portable package is intended to remove the Python/Node preinstall requirement. For now, use the one-command script below.

### What you do not need to know

- How to type multi-step `pip` / `npm` commands (the script handles them)
- How to start uvicorn / vite manually

## One-command install (recommended)

Open **PowerShell**, change into the project directory, and run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1
```

Optional:

```powershell
# Start the Launcher automatically after install
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1 -Start

# Skip the frontend build (when a usable web/dist already exists)
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1 -SkipFrontendBuild
```

The script will:

1. Check Python / Node / Git
2. Create the project `.venv` and install `requirements.txt`
3. Run `npm install` in `web/` (if `node_modules` is missing)
4. Build `web/dist` (if needed)
5. Sync the **Vibelution Launcher** entry used by the desktop / Start menu (when the local toolchain is available)
6. Print the config path and how to start

## Start

**Recommended**: double-click **Vibelution Launcher** on the desktop (or the same-named Start menu entry).

Or:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/vibelution_launcher.ps1 -Action start
```

The control plane is the **Electron Launcher control window** (IPC, not a browser URL); the Python `:8765` control plane is retired ([ADR 0009](../adr/0009-launcher-control-plane-lives-in-electron-main.md)).
The Launcher opens the workbench (commonly `http://127.0.0.1:8000` or `:8002`; trust the UI/logs).

## Configure your model key (before the first conversation)

The config file defaults to:

`%USERPROFILE%\Documents\Vibelution\config\config.toml`

- On the first Launcher start, the directory and a starter file are usually created automatically
- Fill in your model provider / API key with a text editor (**do not** commit files containing keys to git)
- You can also point elsewhere with the `VIBELUTION_CONFIG_HOME` / `VIBELUTION_CONFIG_PATH` environment variables

## Troubleshooting

| Symptom | Check first |
|------|----------|
| The script reports missing Python/Node | Install the runtime, then rerun `install_windows.ps1` |
| The Launcher does not start | The `activePaths.runtime/launcher/` entries in the output of `python scripts/migrate_project_storage.py inventory` |
| The workbench does not open / rebuild fails | The latest directory under `activePaths.logs/runtime_scenes/` in the inventory output; on a dev machine, confirm git is on **main** |
| A black console window flashes | Use the official Launcher / pythonw path; do not hand-roll persistent `python.exe` services |

## Developers

Full development dependencies, tests, and source layout: see the repository root [README.md](../../README.md) and [CONTRIBUTING.md](../../CONTRIBUTING.md).
