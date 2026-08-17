#!/usr/bin/env python3
"""DEV smoke: import adapters and refuse to start real research side effects."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.research.experiment_adapters import (
    ExperimentDispatcher,
    challenge_cup_dispatcher,
)


def main(argv: list[str] | None = None) -> int:
    del argv
    challenge = challenge_cup_dispatcher()
    default = ExperimentDispatcher()
    payload = {
        "challengeAdapterIds": sorted(challenge._registry),
        "defaultAdapterIds": sorted(default._registry),
        "startsRealResearch": False,
    }
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    expected = {
        "offline_fake",
        "fashion_mnist_predictive_coding_multi_seed",
        "gpu_operator_benchmark",
        "neural_spike_coding",
    }
    if not expected.issubset(set(challenge._registry)):
        return 1
    if "gpu_operator_benchmark" in default._registry:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
