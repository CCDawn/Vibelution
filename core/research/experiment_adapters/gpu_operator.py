"""SCI-091 GPU operator DEV fixture adapter.

Development-state control flow only: tiny CPU fixtures prove correctness-first
gating, device receipts and cross-experiment isolation.  No CUDA kernel is
compiled or timed, and no performance number is emitted as a real result.
"""

from __future__ import annotations

from typing import Any

from ..workflow.contracts import sha256_hex
from ._dev_fixture import method_config, run_mode, scope_mismatch, unauthorized_real_run
from .protocol import phase_result

ADAPTER_ID = "gpu_operator_benchmark"
ADAPTER_VERSION = "1.0.0"
PLANNED_ADAPTER_ID = "challenge_cup.gpu_operator_benchmark"
REQUIRED_QUESTION = "SCI-091"
REQUIRED_THEME = "cc-gpu-operator-001"
REQUIRED_CAMPAIGN = "cc-campaign-gpu-operator-001"
OPERATOR_FAMILIES = (
    "elementwise_fusion",
    "reduction_softmax_or_layernorm",
    "matmul_epilogue_fusion",
)


def _cpu_fixture_ops() -> dict[str, Any]:
    elementwise = [1 + 4, 2 + 5, 3 + 6]
    reduction = sum((1.0, 2.0, 3.0, 4.0))
    matmul = [
        [1 * 5 + 2 * 7, 1 * 6 + 2 * 8],
        [3 * 5 + 4 * 7, 3 * 6 + 4 * 8],
    ]
    return {
        "elementwise_fusion": {"ok": elementwise == [5, 7, 9], "output": elementwise},
        "reduction_softmax_or_layernorm": {"ok": reduction == 10.0, "output": reduction},
        "matmul_epilogue_fusion": {"ok": matmul == [[19, 22], [43, 50]], "output": matmul},
    }


class GpuOperatorFixtureAdapter:
    adapterId = ADAPTER_ID
    adapterVersion = ADAPTER_VERSION
    methodId = "computational_kernel_benchmark"

    def prepare(self, scope, contract, locator):
        mismatch = scope_mismatch(
            scope, question=REQUIRED_QUESTION, theme=REQUIRED_THEME, campaign=REQUIRED_CAMPAIGN
        )
        if mismatch is not None:
            return mismatch
        blocked = unauthorized_real_run(contract, extra_flags=("requireCuda", "requireRealDevice"))
        if blocked is not None:
            return blocked
        return phase_result(
            "ok",
            adapterId=self.adapterId,
            plannedAdapterId=PLANNED_ADAPTER_ID,
            environment={"process": False, "gpu": False, "network": False, "device": "cpu_fixture"},
            operatorFamilies=list(OPERATOR_FAMILIES),
            runMode=run_mode(contract),
        )

    def validate(self, scope, contract, locator, *, prepared):
        config = method_config(contract)
        requested = tuple(config.get("operatorFamilies") or OPERATOR_FAMILIES)
        unknown = [name for name in requested if name not in OPERATOR_FAMILIES]
        if unknown:
            return phase_result("failed", reason="unknown_operator_family", unknown=unknown)
        return phase_result("ok", contractValid=True, operatorFamilies=list(requested))

    def execute(self, scope, contract, locator, *, prepared, validated):
        families = tuple(validated.get("operatorFamilies") or OPERATOR_FAMILIES)
        results = _cpu_fixture_ops()
        units = [
            {"family": name, "status": "ok" if results[name]["ok"] else "failed"}
            for name in families
        ]
        failed = sum(1 for unit in units if unit["status"] != "ok")
        return phase_result(
            "failed" if failed else "ok",
            units=units,
            okCount=len(units) - failed,
            failedCount=failed,
            correctnessFirst=True,
        )

    def collect(self, scope, contract, locator, *, executed):
        artifacts = list(executed.get("units") or [])
        return phase_result("ok", artifacts=artifacts, artifactCount=len(artifacts))

    def evaluate(self, scope, contract, locator, *, collected):
        artifacts = list(collected.get("artifacts") or [])
        failed = sum(1 for item in artifacts if item.get("status") != "ok")
        metrics = {
            "operatorFamilies": len(artifacts),
            "correctFamilies": len(artifacts) - failed,
            "failedFamilies": failed,
            "performanceClaimed": False,
        }
        return phase_result(
            "failed" if failed else "ok",
            metrics=metrics,
            decisionHint="reject_performance_claim",
        )

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
            artifactCount=int(metrics.get("operatorFamilies") or 0),
            logBytes=len(evidence_hash),
            metrics=metrics,
            payload={
                "plannedAdapterId": PLANNED_ADAPTER_ID,
                "device": "cpu_fixture",
                "performanceClaimed": False,
            },
            boundaries=["no_process", "no_gpu", "no_network", "fixture_only", "no_performance_claim"],
        )
