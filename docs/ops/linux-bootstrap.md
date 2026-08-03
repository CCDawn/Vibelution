# Linux Deployment Bootstrap

Status: current operational procedure. This document covers source acquisition
and runtime boundaries for a private-repository Linux deployment.

## Source Acquisition

Do not rely on an unauthenticated HTTPS clone of a private GitHub repository.
Use one of these two paths:

1. Configure a repository-scoped, read-only deploy key and clone through the
   Git SSH URL.
2. When a deploy key is not available, create a Git bundle from a verified,
   committed source revision and transfer the bundle over the already approved
   server SSH channel:

   ```sh
   git bundle create vibelution.bundle <verified-commit>
   scp vibelution.bundle operator@server:/tmp/
   ssh operator@server 'git clone /tmp/vibelution.bundle /srv/vibelution && cd /srv/vibelution && git switch -c main'
   ```

The bundle path preserves Git metadata required by the Python launcher source
identity check. Record the source commit in the deployment log before startup.
`scripts/remote_test_runner.py` is a test-only archive tool: it intentionally
excludes `.git` and must not be used as the production deployment source.

For a Linux checkout, activate the tracked hooks after the source is present:

```sh
git config core.autocrlf false
git config core.hooksPath .githooks
git checkout-index -f -- .githooks/pre-commit .githooks/post-merge
chmod 755 .githooks/pre-commit .githooks/post-merge
```

This is intentionally targeted: it preserves the worktree while restoring the
LF, executable hook files Git expects.

## Configuration And Secrets

- Keep `VIBELUTION_CONFIG_PATH`, runtime environment files, data directories,
  and model-provider credentials outside the deployed source tree.
- Provider credentials referenced through `env:VARIABLE_NAME` are read after
  trimming surrounding whitespace, so a copied line ending cannot become part
  of an HTTP authorization header.
- Never put a provider key, SSH private key, password, or production data into
  the Git bundle, repository config, shell history, or deployment logs.
- Bind the first acceptance runtime to `127.0.0.1`; use an authenticated tunnel
  for remote access until a separate LAN exposure review is approved.

## First Start And Evidence

From the deployed source root, start the headless launcher with the project
configuration selected through `VIBELUTION_CONFIG_PATH`:

```sh
python scripts/vibelution_launcher.py --action start --no-browser
```

The launcher now creates or repairs the project virtual environment before it
starts the backend. Validate these independently:

1. the source worktree is clean and identifies the recorded commit;
2. the backend owns the expected loopback listener;
3. `/api/health` responds successfully; and
4. one bounded application-path model request succeeds with the configured
   provider.

Do not treat a reachable page, a listening port, or a provider credential check
as a substitute for the final application-path request.

## Codex CLI Sandbox (workspace_write)

Agent shell tools (`exec_command` / `cli_tool` / `write_stdin`) run through the
native Codex CLI sandbox. The backend auto-selects the host platform, the Codex
executable and the Unix shell; no Agent-facing configuration or command flag
chooses a platform.

### Install And Pin The ARM64 Codex CLI

Use the pinned official npm platform artifact for `linux-arm64`. Unlike the
single-binary GitHub release archive, this artifact keeps `codex-resources/bwrap`
and the other native resources beside the Codex executable. That matters on
hosts whose system bubblewrap is too old for the current Codex sandbox.

```sh
CODEX_VERSION=<pinned-version-without-rust-v-prefix>
mkdir -p /opt/codex-cli
npm view "@openai/codex@${CODEX_VERSION}-linux-arm64" dist.integrity
npm pack \
  "@openai/codex@${CODEX_VERSION}-linux-arm64" \
  --pack-destination /tmp
tar -xzf \
  "/tmp/openai-codex-${CODEX_VERSION}-linux-arm64.tgz" \
  -C /opt/codex-cli \
  --strip-components=3
chmod 0755 \
  /opt/codex-cli/bin/codex \
  /opt/codex-cli/codex-resources/bwrap \
  /opt/codex-cli/codex-path/rg
/opt/codex-cli/bin/codex --version
```

Record the exact version, npm integrity value and downloaded archive checksum in
the deployment log. To force a specific binary without relying on `PATH`, export
`VIBELUTION_CODEX_PATH=/opt/codex-cli/bin/codex` for the launcher process. The
resolver checks, in order: `VIBELUTION_CODEX_PATH`, `PATH` lookup of `codex` (on
Windows additionally the OpenAI local install directory and `codex.exe`); when
no binary is found the sandbox fails closed and Agent shell commands are refused
instead of falling back to an unsandboxed mode.

### Startup Capability Probe

On first use the backend resolves the Codex binary and host shell automatically.
Validate the deployment before accepting traffic:

```sh
/opt/codex-cli/bin/codex --version
/opt/codex-cli/bin/codex sandbox --help
/opt/codex-cli/bin/codex \
  sandbox \
  -c sandbox_mode=workspace-write \
  -- /bin/sh -c 'printf CODEX_LINUX_SANDBOX_OK'
```

The final command must print `CODEX_LINUX_SANDBOX_OK`; checking only
`codex sandbox --help` does not prove that a suitable system or bundled
bubblewrap is available. A missing Codex executable returns
`CODEX_SANDBOX_UNAVAILABLE`; a missing sandbox backend returns the native Codex
failure. Both paths fail closed and never execute the command outside the
sandbox.

### Real Sandbox Acceptance

From a workspace-write Agent turn, run a bounded command and verify the child
process behavior:

1. the argv uses `codex sandbox -c 'sandbox_mode="workspace-write"' -- <shell> -c ...`
   with **no** `windows.sandbox` configuration on Linux;
2. the sandbox temp directory under `<workspace>/.runtime/codex-cli/` is created
   with mode `0700` and contains no `sitecustomize.py`;
3. `VIBELUTION_CONFIG_PATH` points into the sandbox temp directory
   (`.../vibelution-config/config.toml`);
4. no provider/API/token/secret/password/credential/SSH environment variable is
   inherited by the child (PATH, locale and runtime variables are preserved);
5. timeout/cancel/`write_stdin` sessions terminate the process group without
   invoking `taskkill` (POSIX uses the existing descendant-termination
   mechanism plus the sandbox's own process group);
6. `danger_full_access` commands still run without a Codex binary, through the
   host Unix shell, under the same security classification and cwd boundary.
