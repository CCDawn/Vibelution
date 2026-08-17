"""SCI-096 neural spike-coding DEV fixture adapter.

Wraps the tracked spike-coding experiment identity without importing ignored
scripts, downloading DANDI assets, or emitting a real neural conclusion.
"""

from __future__ import annotations

from pathlib import Path

from ..workflow.contracts import sha256_hex
from ._dev_fixture import method_config, run_mode, scope_mismatch, unauthorized_real_run
from .protocol import phase_result

ADAPTER_ID = "neural_spike_coding"
ADAPTER_VERSION = "1.0.0"
PLANNED_ADAPTER_ID = "challenge_cup.neural_spike_coding"
REQUIRED_QUESTION = "SCI-096"
REQUIRED_THEME = "cc-neural-information-001"
REQUIRED_CAMPAIGN = "cc-campaign-neural-spike-001"
HYPOTHESIS_FAMILIES = ("rate_coding", "precise_temporal_coding", "population_coding")
TRACKED_FIXTURES = (
    "experiments/challenge_cup_neural_spike/NOTICE.md",
    "experiments/challenge_cup_neural_spike/fixtures/dev_fixture_v1.json",
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


class NeuralSpikeFixtureAdapter:
    adapterId = ADAPTER_ID
    adapterVersion = ADAPTER_VERSION
    methodId = "dataset_analysis_benchmark"

    def prepare(self, scope, contract, locator):
        mismatch = scope_mismatch(
            scope, question=REQUIRED_QUESTION, theme=REQUIRED_THEME, campaign=REQUIRED_CAMPAIGN
        )
        if mismatch is not None:
            return mismatch
        blocked = unauthorized_real_run(contract, extra_flags=("requireDandiAsset", "requireRealDevice"))
        if blocked is not None:
            return blocked
        root = _project_root()
        missing = [path for path in TRACKED_FIXTURES if not (root / path).is_file()]
        if missing:
            return phase_result("unavailable", reason="tracked_source_missing", missing=missing)
        return phase_result(
            "ok",
            adapterId=self.adapterId,
            plannedAdapterId=PLANNED_ADAPTER_ID,
            environment={"process": False, "gpu": False, "network": False, "dandi": False},
            trackedFixtures=list(TRACKED_FIXTURES),
            ignoredScriptsImported=False,
            runMode=run_mode(contract),
        )

    def validate(self, scope, contract, locator, *, prepared):
        config = method_config(contract)
        requested = tuple(config.get("hypothesisFamilies") or HYPOTHESIS_FAMILIES)
        unknown = [name for name in requested if name not in HYPOTHESIS_FAMILIES]
        if unknown:
            return phase_result("failed", reason="unknown_hypothesis_family", unknown=unknown)
        return phase_result("ok", contractValid=True, hypothesisFamilies=list(requested))

    def execute(self, scope, contract, locator, *, prepared, validated):
        families = tuple(validated.get("hypothesisFamilies") or HYPOTHESIS_FAMILIES)
        # Fixed fixture scores, labeled as non-scientific placeholders.
        fixture_scores = {
            "rate_coding": 0.61,
            "precise_temporal_coding": 0.64,
            "population_coding": 0.58,
        }
        units = [{"family": name, "status": "ok", "fixtureScore": fixture_scores[name]} for name in families]
        return phase_result(
            "ok",
            units=units,
            scientificClaim=False,
            dandiDownloaded=False,
        )

    def collect(self, scope, contract, locator, *, executed):
        artifacts = list(executed.get("units") or [])
        return phase_result("ok", artifacts=artifacts, artifactCount=len(artifacts))

    def evaluate(self, scope, contract, locator, *, collected):
        artifacts = list(collected.get("artifacts") or [])
        metrics = {
            "hypothesisFamilies": len(artifacts),
            "scientificClaim": False,
            "dandiDownloaded": False,
        }
        return phase_result("ok", metrics=metrics, decisionHint="fixture_only")

    def emit_receipt(self, scope, contract, locator, *, evaluated):
        metrics = evaluated.get("metrics") if isinstance(evaluated.get("metrics"), dict) else {}
        evidence = {
            "adapterId": self.adapterId,
            "scopeHash": scope.scopeHash,
            "contractHash": contract.contentHash,
            "locator": locator.to_dict(),
            "metrics": metrics,
        }
        evidence_hash = sha256_hex(evidence)
        return phase_result(
            "ok",
            evidenceHash=evidence_hash,
            artifactCount=int(metrics.get("hypothesisFamilies") or 0),
            logBytes=len(evidence_hash),
            metrics=metrics,
            payload={
                "plannedAdapterId": PLANNED_ADAPTER_ID,
                "scientificClaim": False,
                "ignoredImport": False,
            },
            boundaries=["no_process", "no_gpu", "no_network", "fixture_only", "no_dandi_download"],
        )
