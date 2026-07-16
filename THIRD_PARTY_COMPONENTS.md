# Third-party research components

This registry covers optional components reviewed for the Vibelution research workflow. It does not enable them at runtime. External outputs remain candidate or derived artifacts; Vibelution owns Team, CandidateStore, ClaimEvidence, experiment promotion, and formal knowledge state.

| Component | Source / pin | License | Integration | Default | Canonical writes |
|---|---|---|---|---|---|
| PaperQA2 | `Future-House/paper-qa`; `paper-qa==2026.3.18` | Apache-2.0 | Isolated Python dependency behind a future evidence adapter | Disabled | Forbidden |
| Agent Skills reference | `agentskills/agentskills@38a2ff82958afee88dadf4831509e6f7e9d8ef4e` | Apache-2.0 | Parser/validator component behind the existing managed skill library | Disabled | Forbidden |

## Governance requirements

- Keep exact source, version/commit, license, checksum where available, adapter boundary, feature flag, and rollback evidence.
- Preserve upstream copyright, license, and NOTICE requirements when code is redistributed or modified.
- Run external code only in the approved adapter or managed-skill boundary. Do not expose provider keys, local prompts, or unrestricted file/network access.
- Imports of scientific `SKILL.md` files start as non-executable candidates. Enabling scripts requires the existing manifest allowlist plus a separate security and fixture review.
- If an optional component is unavailable, report `degraded` with a reason and continue through the project-native path. Do not report fallback evidence as canonical full-text evidence.

## T0 compatibility status

- PaperQA2: `paper-qa==2026.3.18` installed in an external isolated Windows/Python 3.12.10 venv; `paperqa.Docs` import passed. It remains disabled because the offline document/query adapter fixture has not been implemented yet.
- Agent Skills reference: upstream commit pinned and source archive downloaded. The isolated package build could not complete because downloading a build dependency timed out; status is `compatibility_unverified`, not failed compatibility. It remains disabled pending a deterministic offline conformance fixture.
