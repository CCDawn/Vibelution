# Remote Test Runner

`scripts/remote_test_runner.py` runs Vibelution tests on an SSH-accessible Linux
worker. The first supported target is the local SSH alias `bossai-server-b`.

The runner is intentionally small:

- it does not require local `rsync`;
- it creates a source archive while excluding `.git`, `.venv`, `node_modules`,
  `web/dist`, `logs`, `.runtime`, secrets, databases, build outputs, and cache
  directories;
- it uploads through `scp`;
- it prepares or reuses a cached remote virtualenv under
  `/home/enrigin/Vibelution-test/cache`;
- it reinstalls Python dependencies only when `requirements.txt` changes;
- it runs the selected test command;
- it copies `remote-test.log` back under `logs/remote_test_runs/<run-id>/`.

## Default Backend Parallel Run

```powershell
python scripts/remote_test_runner.py
```

Equivalent remote test command:

```bash
python tests/test_runner.py --parallel --workers 8
```

## Safer First Probe

```powershell
python scripts/remote_test_runner.py --suite environment-smoke
```

Run this before the first full remote suite on a new server or after changing
SSH host/root options.

## Full Hybrid Run

```powershell
python scripts/remote_test_runner.py --suite hybrid --workers 8
```

## Dry Run

```powershell
python scripts/remote_test_runner.py --dry-run
```

Use dry-run before changing host, remote root, or command arguments.

## Custom Command

```powershell
python scripts/remote_test_runner.py --remote-command "python -m pytest tests/test_runner.py -q"
```

Custom commands run inside the uploaded remote source directory after the
virtualenv is activated.

## Boundary

Windows-only, Launcher lifecycle, real local port/process, and operator-config
tests should remain local unless they are explicitly made remote-safe.

The default server target is the local SSH alias `bossai-server-b`. The public
deployment-style target found in `bossai-shared` is not used by this runner
unless the operator explicitly passes a matching `--host`.
