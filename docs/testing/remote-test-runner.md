# Remote Test Runner

`scripts/remote_test_runner.py` runs Vibelution tests on an SSH-accessible Linux
worker. The first supported target is the local SSH alias `bossai-server-b`.

The runner is intentionally small:

- it does not require local `rsync`;
- it creates a source archive while excluding `.git`, `.venv`, `node_modules`,
  `web/dist`, `logs`, `.runtime`, secrets, databases, build outputs, and cache
  directories;
- it uploads through `scp`;
- it writes a minimal remote-only `.remote-test/config.toml` with the
  `safe_remote` runtime profile and points `VIBELUTION_CONFIG_PATH` at it;
- it can run through the default cached remote virtualenv backend or a
  reproducible Docker backend;
- the virtualenv backend prepares or reuses a cached venv under
  `/home/enrigin/Vibelution-test/cache` and reinstalls Python dependencies only
  when `requirements.txt` changes;
- the Docker backend builds a `requirements.txt` hash-tagged image from a small
  cached build context and fixes `NO_PROXY`, `TERM`, `COLUMNS`, `HOME`,
  `XDG_CACHE_HOME`, and the container-local config path;
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

## Reproducible Docker Backend

```powershell
python scripts/remote_test_runner.py --backend docker --suite parallel --workers 8
```

The first Docker run builds an image similar to:

```text
vibelution-test:py311-<requirements-hash>
```

Later runs reuse that image until `requirements.txt` changes. Force a rebuild
with:

```powershell
python scripts/remote_test_runner.py --backend docker --rebuild-image --suite environment-smoke
```

The remote host must have Docker available to the SSH user. `bossai-server-b`
currently satisfies this through the `docker` group.

The Docker image build context contains only the generated Dockerfile and
`requirements.txt`; the full uploaded source tree is mounted at runtime as
`/workspace`.

## Safer First Probe

```powershell
python scripts/remote_test_runner.py --backend docker --suite environment-smoke
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
