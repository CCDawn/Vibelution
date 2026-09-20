/**
 * Repo-root guard for accidental full-tree vitest runs.
 *
 * `npx --prefix web vitest ...` (or any vitest invocation with cwd = repo
 * root) discovers no config, because the real test config lives in
 * web/vite.config.ts and vitest only searches upward from cwd. It then falls
 * back to the default glob, sweeping every web/src copy under .worktrees/ and
 * .runtime/ — each CLI filter matches by substring, so one test file executes
 * once per checkout copy (observed: a single contract test running 14+ times).
 *
 * Pointing `test.projects` at web/ makes the repo root load web/vite.config.ts
 * (with its plugins and test settings) and collect only web/src, regardless of
 * where in the repo vitest was started. `npm --prefix web run test` is
 * unaffected: it runs inside web/ and keeps using that config directly.
 *
 * Deliberately a plain object without importing `vitest/config`: the repo root
 * has no node_modules, so any package import in this file fails to resolve
 * when vitest loads it from a checkout root.
 */
export default {
  test: {
    projects: ["web"],
  },
};
