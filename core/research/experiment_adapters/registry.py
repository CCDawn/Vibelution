"""Register Challenge Cup DEV fixture adapters onto the D06 dispatcher."""

from __future__ import annotations

from .dispatcher import ExperimentDispatcher, OfflineFakeExperimentAdapter
from .fashion_mnist import FashionMnistFixtureAdapter
from .gpu_operator import GpuOperatorFixtureAdapter
from .neural_spike import NeuralSpikeFixtureAdapter


def challenge_cup_adapters():
    return (
        OfflineFakeExperimentAdapter(),
        FashionMnistFixtureAdapter(),
        GpuOperatorFixtureAdapter(),
        NeuralSpikeFixtureAdapter(),
    )


def challenge_cup_dispatcher() -> ExperimentDispatcher:
    return ExperimentDispatcher(adapters=challenge_cup_adapters())
