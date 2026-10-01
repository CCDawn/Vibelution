# Launcher topbar update preview

Status: APPROVED. The preview now renders the production LauncherUpdateTopbarView.

Open `/preview/launcher-update/index.html` on this worktree's Vite server.
Use `?scene=active|building|error|current|unknown` or the bottom selector.

## Proposed contract

- A persistent top-right update control, shared by Launcher home and tools.
- Closing details does not dismiss the update control.
- Details distinguish the running version from the local checkout version.
- Unknown detection never becomes "current"; build failure retains retry.
- An active task blocks update; updating requires explicit confirmation.
- Pending status remains visible in the topbar until the update settles.
- Existing OS window controls and lifecycle guard remain unchanged.

This preview uses the production topbar view, existing VUI controls, the dense ops recipe and the actual
startup settings panel. All update, lifecycle and settings actions are local
simulation only. There are no real update requests or backend mutations.
Commit labels are deterministic sample data, not a live version report.

## Integration boundary after approval

Reuse the AppShell topbar update-popover pattern; place the shared control in
LauncherShell instead of a home-only automatically opened dialog. Reuse the
existing Launcher freshness and shell-update APIs without bypassing active-work
guards. Production detection must not equate a current Electron source tree
with current packaged frontend assets; the packaging mismatch diagnosed in the
previous turn must be accounted for before claiming reliable detection.
This proposal compares local source/build versions; remote release discovery
is not implemented or implied.

## Preview evidence

- Root `tsc -b --pretty false` and this directory's dedicated TypeScript check pass.
- Existing VUI route/design contracts pass.
- Browser checks pass for persistent notification, confirmation, pending,
  active-task blocking, failure retry, current/unknown distinction and theme.
- Checked 1280x800 and 390x844; no document horizontal overflow at 390px.
- No page or console errors observed.
- Real version detection, packaging, rebuild/restart and live task guarding are
  not exercised by this preview.
