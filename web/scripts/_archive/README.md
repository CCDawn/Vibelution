# Archived one-shot frontend scripts

These files are **completed 2026-07 VUI / route extract-migrate helpers**. They are not on CI and must not be treated as current tooling.

Keep in `web/scripts/` (live):

- `checkBundleBudget.mjs` — `npm run check:bundle` / `web/bundleBudget.test.ts`
- `checkElkWorkerHandshake.mjs` — `npm run check:elk-worker-handshake`

Do not re-run the archived scripts against the current tree: several still enumerate deleted `Research*Route` files (`bake-style-maps.ts`, `migrate_vui_wave2e_hotspots.py`, `unify_vui_shell_fills.py`, `audit-style-migration.mjs`).

Historical comments in `*.styles.ts` may still mention `web/scripts/<name>`; that is origin, not an active path.
