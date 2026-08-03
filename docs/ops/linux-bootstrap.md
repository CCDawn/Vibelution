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

## Configuration And Secrets

- Keep `VIBELUTION_CONFIG_PATH`, runtime environment files, data directories,
  and model-provider credentials outside the deployed source tree.
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
