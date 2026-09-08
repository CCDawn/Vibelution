"""Controlled CUDA candidate identity and immutable artifact references."""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.research.workflow.contracts._canonical import sha256_hex

Text = Annotated[str, Field(min_length=1, max_length=4000)]
Identity = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class CudaCandidate(Contract):
    """The bounded parameter set the CUDA runner is allowed to execute.

    The implementation enum is deliberately closed.  A plan can select one
    of these implementations and a small warp configuration, but cannot pass
    arbitrary source paths or shell commands to the worker.
    """

    implementation: Literal["torch_softmax", "triton_row_softmax"]
    numWarps: Literal[4, 8, 16] = 4


def source_hash(candidate: CudaCandidate) -> str:
    """Return the source identity used by measurements and candidate refs.

    Keep this calculation tied to the same runner files that are executed.
    The candidate parameters are included so two configurations cannot share
    a source identity merely because they use the same implementation file.
    """

    paths = [Path(__file__), Path(__file__).with_name("cuda_runner.py")]
    if candidate.implementation == "triton_row_softmax":
        paths.append(Path(__file__).with_name("triton_softmax.py"))
    return sha256_hex({
        "candidate": candidate.model_dump(mode="json"),
        "sources": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        },
    })


class CudaCandidateArtifact(Contract):
    """Payload stored in the canonical workflow artifact store."""

    schemaVersion: Literal[1] = 1
    candidateId: Identity
    optimizationCampaignId: Identity
    runId: Identity
    roundId: str = ""
    candidate: CudaCandidate
    sourceHash: Digest

    @property
    def params(self) -> dict[str, Any]:
        """Expose the bounded implementation parameters for recovery tools."""

        return self.candidate.model_dump(mode="json")

    @classmethod
    def from_candidate(
        cls,
        *,
        candidate_id: str,
        optimization_campaign_id: str,
        run_id: str,
        candidate: CudaCandidate,
        round_id: str = "",
    ) -> CudaCandidateArtifact:
        return cls(
            candidateId=candidate_id,
            optimizationCampaignId=optimization_campaign_id,
            runId=run_id,
            roundId=round_id,
            candidate=candidate,
            sourceHash=source_hash(candidate),
        )

    @classmethod
    def default_baseline(
        cls, *, candidate_id: str, optimization_campaign_id: str, run_id: str,
    ) -> CudaCandidateArtifact:
        return cls.from_candidate(
            candidate_id=candidate_id,
            optimization_campaign_id=optimization_campaign_id,
            run_id=run_id,
            candidate=CudaCandidate(implementation="torch_softmax"),
        )


class CudaCandidateRef(Contract):
    """A recoverable candidate reference carried by campaigns and rounds."""

    artifactId: Identity
    kind: Literal["operator_candidate"] = "operator_candidate"
    sha256: Digest
    runId: Identity
    candidate: CudaCandidate
    sourceHash: Digest

    @property
    def params(self) -> dict[str, Any]:
        return self.candidate.model_dump(mode="json")


def ensure_current_source_hash(
    candidate: CudaCandidate, frozen_source_hash: str,
) -> CudaCandidate:
    """Reject execution when the frozen source identity no longer matches.

    Historical candidate artifacts remain readable after the runner source is
    upgraded.  This check belongs at execution admission, where silently
    running a changed implementation would invalidate the measurement.
    """

    if source_hash(candidate) != frozen_source_hash:
        raise ValueError("candidate sourceHash does not match the current controlled implementation")
    return candidate


def candidate_ref_from_artifact(
    envelope: Mapping[str, Any],
    *,
    artifact_id: str = "",
    run_id: str = "",
) -> CudaCandidateRef:
    """Parse a canonical candidate artifact into a recoverable reference."""

    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise TypeError("candidate artifact envelope must contain a payload")
    artifact = CudaCandidateArtifact.model_validate(payload)
    actual_kind = str(envelope.get("kind") or "").strip()
    if actual_kind and actual_kind != "operator_candidate":
        raise ValueError("candidate artifact kind is not operator_candidate")
    actual_id = str(artifact_id or envelope.get("recordId") or artifact.candidateId).strip()
    if actual_id != artifact.candidateId:
        raise ValueError("candidate artifact identity differs from candidateId")
    actual_run = str(run_id or envelope.get("workflowRunId") or artifact.runId).strip()
    if actual_run != artifact.runId:
        raise ValueError("candidate artifact run identity differs from runId")
    return CudaCandidateRef(
        artifactId=actual_id,
        sha256=sha256_hex(envelope),
        runId=actual_run,
        candidate=artifact.candidate,
        sourceHash=artifact.sourceHash,
    )


BASELINE_CUDA_CANDIDATE = CudaCandidate(implementation="torch_softmax")


__all__ = [
    "BASELINE_CUDA_CANDIDATE",
    "CudaCandidate",
    "CudaCandidateArtifact",
    "CudaCandidateRef",
    "candidate_ref_from_artifact",
    "ensure_current_source_hash",
    "source_hash",
]
