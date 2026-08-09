"""Four-stage experiment campaign contract."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ._validation import (
    ContractValidationError,
    require_int,
    require_list,
    require_mapping,
    require_sha256,
    require_text,
)


class ExperimentCampaignStage(str, Enum):
    FEASIBILITY = "feasibility"
    BASELINE = "baseline"
    AGENDA = "agenda"
    ABLATION_REPLICATION = "ablation_replication"


@dataclass(frozen=True, slots=True)
class ExperimentCampaign:
    campaignId: str
    runId: str
    hypothesisCandidateId: str
    protocolHash: str
    environmentSnapshotHash: str
    datasetSnapshotRefs: tuple[str, ...]
    baselineRefs: tuple[str, ...]
    metricContractRef: str
    stage: ExperimentCampaignStage
    seedSet: tuple[int, ...]
    replicationCount: int
    budgetLedgerRef: str
    stopCriteria: dict[str, Any]
    experimentRunRefs: tuple[str, ...]
    resultArtifactRefs: tuple[str, ...]
    decision: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExperimentCampaign:
        stage_raw = require_text(payload, "stage")
        try:
            stage = ExperimentCampaignStage(stage_raw)
        except ValueError as exc:
            raise ContractValidationError(
                f"unsupported experiment campaign stage: {stage_raw}"
            ) from exc
        seeds = require_list(payload, "seedSet", non_empty=True)
        if any(isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds):
            raise ContractValidationError("seedSet must contain integers")
        if len(set(seeds)) != len(seeds):
            raise ContractValidationError("seedSet values must be unique")
        replication_count = require_int(payload, "replicationCount", minimum=1)
        if replication_count > len(seeds):
            raise ContractValidationError("replicationCount cannot exceed seedSet size")
        return cls(
            campaignId=require_text(payload, "campaignId"),
            runId=require_text(payload, "runId"),
            hypothesisCandidateId=require_text(payload, "hypothesisCandidateId"),
            protocolHash=require_sha256(payload, "protocolHash"),
            environmentSnapshotHash=require_sha256(payload, "environmentSnapshotHash"),
            datasetSnapshotRefs=tuple(
                str(item)
                for item in require_list(payload, "datasetSnapshotRefs", non_empty=True)
            ),
            baselineRefs=tuple(
                str(item)
                for item in require_list(payload, "baselineRefs", non_empty=True)
            ),
            metricContractRef=require_text(payload, "metricContractRef"),
            stage=stage,
            seedSet=tuple(seeds),
            replicationCount=replication_count,
            budgetLedgerRef=require_text(payload, "budgetLedgerRef"),
            stopCriteria=require_mapping(payload, "stopCriteria"),
            experimentRunRefs=tuple(
                str(item) for item in require_list(payload, "experimentRunRefs")
            ),
            resultArtifactRefs=tuple(
                str(item) for item in require_list(payload, "resultArtifactRefs")
            ),
            decision=require_text(payload, "decision"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaignId": self.campaignId,
            "runId": self.runId,
            "hypothesisCandidateId": self.hypothesisCandidateId,
            "protocolHash": self.protocolHash,
            "environmentSnapshotHash": self.environmentSnapshotHash,
            "datasetSnapshotRefs": list(self.datasetSnapshotRefs),
            "baselineRefs": list(self.baselineRefs),
            "metricContractRef": self.metricContractRef,
            "stage": self.stage.value,
            "seedSet": list(self.seedSet),
            "replicationCount": self.replicationCount,
            "budgetLedgerRef": self.budgetLedgerRef,
            "stopCriteria": copy.deepcopy(self.stopCriteria),
            "experimentRunRefs": list(self.experimentRunRefs),
            "resultArtifactRefs": list(self.resultArtifactRefs),
            "decision": self.decision,
        }
