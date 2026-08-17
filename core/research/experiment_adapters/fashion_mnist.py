"""FashionMNIST predictive-coding DEV fixture adapter.

Migrates the existing formal-runner identity onto the D06 dispatcher without
invoking the trusted training script.  Full training remains unauthorized.
"""

from __future__ import annotations

from pathlib import Path

from ..workflow.contracts import sha256_hex
from ._dev_fixture import run_mode, unauthorized_real_run
from .protocol import phase_result

ADAPTER_ID = "fashion_mnist_predictive_coding_multi_seed"
ADAPTER_VERSION = "1.0.0"
TRUSTED_SCRIPT = Path("experiments/challenge_cup_predictive_coding/fashion_mnist_smoke.py")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


class FashionMnistFixtureAdapter:
    adapterId = ADAPTER_ID
    adapterVersion = ADAPTER_VERSION
    methodId = "model_training_inference"

    def prepare(self, scope, contract, locator):
        # Compatibility adapter: it may run under the neural campaign in DEV,
        # but still refuses to share GPU-operator scope.
        if scope.theme == "cc-gpu-operator-001" or scope.question == "SCI-091":
            return phase_result(
                "failed",
                reason="scope_mismatch",
                mismatches=[f"theme:{scope.theme}", f"question:{scope.question}"],
            )
        blocked = unauthorized_real_run(contract, extra_flags=("requireTraining", "requireRealDevice"))
        if blocked is not None:
            return blocked
        script = _project_root() / TRUSTED_SCRIPT
        if not script.is_file():
            return phase_result("unavailable", reason="trusted_script_missing", path=str(TRUSTED_SCRIPT).replace("\\", "/"))
        return phase_result(
            "ok",
            adapterId=self.adapterId,
            environment={"process": False, "gpu": False, "network": False, "training": False},
            trustedScript=str(TRUSTED_SCRIPT).replace("\\", "/"),
            runMode=run_mode(contract),
        )

    def validate(self, scope, contract, locator, *, prepared):
        return phase_result("ok", contractValid=True, adapterId=self.adapterId)

    def execute(self, scope, contract, locator, *, prepared, validated):
        return phase_result(
            "ok",
            units=[{"seed": 1, "status": "ok"}, {"seed": 2, "status": "ok"}, {"seed": 3, "status": "ok"}],
            trained=False,
        )

    def collect(self, scope, contract, locator, *, executed):
        artifacts = list(executed.get("units") or [])
        return phase_result("ok", artifacts=artifacts, artifactCount=len(artifacts))

    def evaluate(self, scope, contract, locator, *, collected):
        artifacts = list(collected.get("artifacts") or [])
        metrics = {"seeds": len(artifacts), "trained": False}
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
            artifactCount=int(metrics.get("seeds") or 0),
            logBytes=len(evidence_hash),
            metrics=metrics,
            payload={"trained": False, "trustedScript": str(TRUSTED_SCRIPT).replace("\\", "/")},
            boundaries=["no_process", "no_gpu", "no_network", "fixture_only", "no_training"],
        )
