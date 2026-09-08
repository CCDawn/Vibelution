"""Frozen measurement inputs and raw observations, separate from workflow state."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .contracts import (
    MEASUREMENT_PROTOCOL_ARTIFACT_KIND,
    ArtifactRef,
    Contract,
    Digest,
    Identity,
    MeasurementProtocolRef,
)


class WorkloadCase(Contract):
    caseId: Identity
    rows: int = Field(ge=1, le=1048576, strict=True)
    columns: int = Field(ge=2, le=65536, strict=True)
    dtype: Literal["float16", "float32"]
    distribution: Literal["normal", "large_magnitude", "constant"] = "normal"
    seed: int = Field(ge=0, le=2147483647, strict=True)


class MeasurementProtocol(Contract):
    schemaVersion: Literal[1] = 1
    protocolId: Identity
    cases: tuple[WorkloadCase, ...] = Field(min_length=1, max_length=64)
    split: Literal["tuning", "holdout"]
    warmup: int = Field(20, ge=1, le=1000, strict=True)
    pairs: int = Field(30, ge=10, le=1000, strict=True)
    bootstrapSamples: int = Field(2000, ge=1000, le=10000, strict=True)
    bootstrapSeed: int = Field(1729, ge=0, strict=True)
    minSpeedup: float = Field(1.02, gt=1, le=2)
    maxCaseRegression: float = Field(0.05, ge=0, le=0.5)
    atol: float = Field(1e-5, gt=0, le=0.01)
    rtol: float = Field(1e-3, gt=0, le=0.01)

    @model_validator(mode="after")
    def unique_cases(self):
        if len({case.caseId for case in self.cases}) != len(self.cases):
            raise ValueError("Workload case IDs must be unique")
        return self


class PairedTiming(Contract):
    baselineMs: float = Field(gt=0)
    parentMs: float = Field(gt=0)
    candidateMs: float = Field(gt=0)


class CaseMeasurement(Contract):
    caseId: Identity
    correctnessPassed: bool
    maxAbsoluteError: float | None = Field(ge=0)
    timings: tuple[PairedTiming, ...] = ()


class OperatorMeasurement(Contract):
    schemaVersion: Literal[1] = 1
    measurementId: Identity
    optimizationCampaignId: Identity
    runId: Identity
    protocolHash: Digest
    workloadHash: Digest
    environmentHash: Digest
    baselineSourceHash: Digest
    parentSourceHash: Digest
    candidateSourceHash: Digest
    runnerId: Literal["operator_cuda_v1"] = "operator_cuda_v1"
    deviceKind: Literal["cuda"] = "cuda"
    deviceName: str = Field(min_length=1, max_length=240)
    status: Literal["succeeded", "failed", "cancelled", "timed_out"]
    failureReason: str = Field("", max_length=2000)
    gpuSeconds: float = Field(ge=0)
    cases: tuple[CaseMeasurement, ...] = ()

    @model_validator(mode="after")
    def terminal_evidence(self):
        if len({case.caseId for case in self.cases}) != len(self.cases):
            raise ValueError("Measurements must not repeat workload cases")
        if self.status != "succeeded" and not self.failureReason:
            raise ValueError("Unsuccessful measurement requires a failure reason")
        return self
