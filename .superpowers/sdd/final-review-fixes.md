# LLM Provider/Model Config Final Review Fixes

Status: READY

## Scope

This round fixes only the two Important findings from the final branch review:

1. Keep local runtime deployment metadata under the backend-owned `ProviderConfig.deployment` object.
2. Block v1-to-v2 migration when rows grouped by endpoint and credential disagree on provider classification.

The operator config, Launcher, root `main`, version files, remote state, quality gates, and allowlists were not modified.

## Fix 1: canonical Provider wizard draft

- Added `buildProviderWizardDraft(state, templateProvider)` as the single Provider payload builder.
- Reused it for both provider-ID suggestion and Provider creation.
- Local runtime metadata is emitted only as nested `deployment.runtime_framework` and `deployment.artifact_path`.
- Legacy top-level deployment keys are removed, including when present in a template.
- Nested deployment template values survive until explicitly overridden by wizard state.
- Non-local Providers do not receive a fabricated deployment object.
- Template hydration now reads deployment values from the nested backend-owned object.

TDD RED evidence:

- Frontend focused run failed 3 tests because the canonical helper and both call-site reuses were absent; the other 58 tests passed.
- The template-preservation regression then failed because blank wizard fields overwrote nested template values; the other 18 logic tests passed.

## Fix 2: fail-closed migration classification

- Each endpoint-plus-credential group now compares `_service_class(provider)`, `_vendor(base_url, provider)`, adapter, and driver across all rows.
- A mismatch creates one blocking `provider_classification_conflict` with sorted `modelIds` and sorted differing `fields`.
- Conflict output contains no credential reference or secret value.
- The proposed preview remains available, while `apply_v1_to_v2` rejects the `NEEDS_REVIEW` preview before writing.
- Transport and model protocol differences remain valid for multi-protocol gateways and still merge into one Provider.

TDD RED evidence:

- Migration tests failed at the new conflict lookup because no `provider_classification_conflict` existed; the preceding existing test passed.

## Fresh verification

- `npm --prefix web test -- src/routes/configProviderLogic.test.ts src/routes/ConfigRoute.layout.test.ts`: 62 passed.
- `python -m pytest tests/test_model_config_migration.py tests/test_llm_config_v2_integration.py -q`: 39 passed.
- Related backend matrix (`llm_provider_registry`, `provider_config_service`, migration, v2 integration, public model refs, config panel, web config routes): 265 passed.
- Full frontend suite: 192 files, 1954 tests passed.
- `npm --prefix web run build`: passed (`tsc -b` and Vite production build).
- Ruff on both changed Python files: passed.
- `git diff --check`: passed.

## Closeout decisions

- Logging: no new path required; the migration conflict is part of the bounded preview contract and existing Provider mutation/migration logging remains the owner.
- Launcher refresh: intentionally not performed in this fix round; parent integration owns final runtime/visual verification.
- Project memory: not updated; parent integration owns final memory synchronization.
- Version impact: no separate bump for this corrective commit; parent integration owns the feature-level version judgment.
- Remaining risk: no known code blocker in these two findings; final branch review and integration gates remain with the parent agent.
