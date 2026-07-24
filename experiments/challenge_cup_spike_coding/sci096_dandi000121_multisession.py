"""Manifest-gated multi-session runner for the SCI-096 DANDI 000121 branch.

Qualification, download, and formal execution are separate gates.  This module
can prepare an integrity-checked download plan without authorizing a decoder
run.  Formal execution additionally requires an independent human
authorization artifact bound to the qualification manifest hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from statistics import median
from typing import Any, Callable

from sci096_dandi000121_adapter import load_dandi000121_dataset
from sci096_dandi_probe import _scientific_modules, _stable_metrics
from sci096_epoch_discrimination import (
    STATIONARY_WINDOW,
    TRANSITION_WINDOW,
    EpochDiscriminationConfig,
    _evaluate_epoch,
    bootstrap_balanced_interaction_delta,
    classify_epoch_result,
)


QUALIFICATION_SCHEMA = "sci096.dandi000121.multisession-qualification.v2"
AUTHORIZATION_SCHEMA = "sci096.dandi000121.execution-authorization.v1"
DANDISET_ID = "000121"
DANDISET_VERSION = "0.220124.2156"
EXPERIMENT_ID = "sci096-dandi000121-multisession-epoch-discrimination-v1"
MAX_SOURCE_BYTES = 8_300_000_000
REQUIRED_SUBJECTS = frozenset({"Reggie", "JenkinsC"})
FROZEN_QUALIFICATION_SHA256 = (
    "fde5f9a1bfffd70e6fc7f131aee1f6f9ace109e6b418ede09273c6469383906b"
)
FROZEN_ASSETS = {
    "62082652-6403-495b-b918-8addb5352f4a": {
        "subject": "Reggie",
        "path": "sub-Reggie/sub-Reggie_ses-20170117T104643_behavior+ecephys.nwb",
        "contentSize": 2_880_141_464,
        "sha256": "81986d7eed4f61cae3a62d57d6dbb1f54f06dae72b8308979b845a5a1b98bb24",
    },
    "1433fe9c-d20b-426d-abfd-333593eaf438": {
        "subject": "JenkinsC",
        "path": "sub-JenkinsC/sub-JenkinsC_ses-20151015T151424_behavior+ecephys.nwb",
        "contentSize": 2_297_971_237,
        "sha256": "20ab8d5bed9de2d73cf790115418147766d56f2c5672735ee1d56fa7c8e474e3",
    },
    "40fd4865-2692-4994-a148-c2843d24f0b7": {
        "subject": "Reggie",
        "path": "sub-Reggie/sub-Reggie_ses-20170125T100800_behavior+ecephys.nwb",
        "contentSize": 3_037_103_600,
        "sha256": "5d5ee4f2aca3203aa340de55160c614ef792f407e0ffc47a18d11fa88d55e595",
    },
}


@dataclass(frozen=True)
class QualifiedSession:
    asset_id: str
    subject: str
    relative_path: str
    content_size: int
    sha256: str
    usable_trial_count: int
    nonempty_unit_count: int
    train_trial_count: int
    validation_trial_count: int


@dataclass(frozen=True)
class QualificationBundle:
    manifest_path: Path
    manifest_sha256: str
    sessions: tuple[QualifiedSession, ...]
    total_source_bytes: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    payload = path.read_bytes()
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value, payload


def _session_records(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for key in ("carriedForwardSessions", "newSessionsScanned"):
        raw_records = manifest.get(key)
        if not isinstance(raw_records, list):
            raise ValueError(f"qualification manifest requires list field {key}")
        for record in raw_records:
            if not isinstance(record, dict) or not record.get("assetId"):
                raise ValueError(f"{key} contains an invalid session record")
            asset_id = str(record["assetId"])
            if asset_id in records:
                raise ValueError(f"duplicate session record for asset {asset_id}")
            records[asset_id] = record
    return records


def _validate_relative_nwb_path(value: Any) -> str:
    path = PurePosixPath(str(value))
    if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".nwb":
        raise ValueError(f"unsafe or non-NWB asset path: {value}")
    return path.as_posix()


def load_qualification_manifest(path: Path) -> QualificationBundle:
    manifest_path = path.resolve()
    manifest, payload = _read_json(manifest_path)
    manifest_sha256 = hashlib.sha256(payload).hexdigest()
    if manifest_sha256 != FROZEN_QUALIFICATION_SHA256:
        raise ValueError(
            "qualification manifest SHA-256 does not match the frozen evidence"
        )
    if manifest.get("schemaVersion") != QUALIFICATION_SCHEMA:
        raise ValueError("qualification manifest schema is not the frozen v2 contract")
    if manifest.get("dandiset") != DANDISET_ID:
        raise ValueError("qualification manifest dandiset does not match 000121")
    if manifest.get("dandisetVersion") != DANDISET_VERSION:
        raise ValueError("qualification manifest version does not match the frozen version")
    if manifest.get("decision") != "qualified_for_bounded_download_and_runner_design":
        raise ValueError("qualification manifest is not approved for runner design")
    if manifest.get("formalExperimentAuthorized") is not False:
        raise ValueError(
            "qualification manifest must not double as formal execution authorization"
        )

    qualified_ids = manifest.get("qualifiedSessionAssetIds")
    if (
        not isinstance(qualified_ids, list)
        or len(qualified_ids) != len(FROZEN_ASSETS)
        or len(set(qualified_ids)) != len(qualified_ids)
        or set(qualified_ids) != set(FROZEN_ASSETS)
    ):
        raise ValueError("qualification manifest must select the three frozen assets exactly")
    records = _session_records(manifest)
    sessions = []
    for asset_id in qualified_ids:
        expected = FROZEN_ASSETS[asset_id]
        record = records.get(asset_id)
        if record is None or record.get("passed") is not True:
            raise ValueError(f"qualified asset is missing a passing record: {asset_id}")
        relative_path = _validate_relative_nwb_path(record.get("path"))
        observed = {
            "subject": str(record.get("subject")),
            "path": relative_path,
            "contentSize": int(record.get("contentSize", -1)),
            "sha256": str(record.get("sha256", "")).lower(),
        }
        if observed != expected:
            raise ValueError(f"qualified asset metadata drifted from frozen values: {asset_id}")
        octants = record.get("observedOctants")
        if octants != list(range(8)):
            raise ValueError(f"qualified asset lacks all eight octants: {asset_id}")
        usable_trials = int(record.get("usableTrialCount", 0))
        nonempty_units = int(record.get("nonemptyUnitCount", 0))
        split = record.get("splitCounts")
        if not isinstance(split, dict):
            raise ValueError(f"qualified asset lacks a split record: {asset_id}")
        train_trials = int(split.get("train", 0))
        validation_trials = int(split.get("validation", 0))
        if (
            usable_trials < 100
            or nonempty_units < 2
            or train_trials < 75
            or validation_trials < 25
            or train_trials + validation_trials != usable_trials
        ):
            raise ValueError(f"qualified asset no longer satisfies frozen gates: {asset_id}")
        sessions.append(
            QualifiedSession(
                asset_id=asset_id,
                subject=observed["subject"],
                relative_path=relative_path,
                content_size=observed["contentSize"],
                sha256=observed["sha256"],
                usable_trial_count=usable_trials,
                nonempty_unit_count=nonempty_units,
                train_trial_count=train_trials,
                validation_trial_count=validation_trials,
            )
        )

    subjects = {session.subject for session in sessions}
    if subjects != REQUIRED_SUBJECTS:
        raise ValueError("qualified sessions must span Reggie and JenkinsC")
    total_bytes = sum(session.content_size for session in sessions)
    if total_bytes > MAX_SOURCE_BYTES:
        raise ValueError(
            f"frozen source budget exceeds {MAX_SOURCE_BYTES} bytes: {total_bytes}"
        )
    return QualificationBundle(
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        sessions=tuple(sessions),
        total_source_bytes=total_bytes,
    )


def _local_asset_path(source_root: Path, relative_path: str) -> Path:
    root = source_root.resolve()
    candidate = (root / Path(*PurePosixPath(relative_path).parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"asset path escapes source root: {relative_path}") from exc
    return candidate


def build_download_plan(
    bundle: QualificationBundle,
    source_root: Path,
) -> dict[str, Any]:
    assets = []
    for session in bundle.sessions:
        local_path = _local_asset_path(source_root, session.relative_path)
        if not local_path.exists():
            local_status = "missing"
        elif local_path.stat().st_size != session.content_size:
            local_status = "size_mismatch"
        else:
            local_status = "present_unverified"
        assets.append(
            {
                "assetId": session.asset_id,
                "subject": session.subject,
                "relativePath": session.relative_path,
                "contentSize": session.content_size,
                "sha256": session.sha256,
                "dandiApiUrl": (
                    f"https://api.dandiarchive.org/api/assets/{session.asset_id}/"
                ),
                "localPath": str(local_path),
                "localStatus": local_status,
            }
        )
    return {
        "schemaVersion": "sci096.dandi000121.download-plan.v1",
        "qualificationManifest": str(bundle.manifest_path),
        "qualificationManifestSha256": bundle.manifest_sha256,
        "dandiset": DANDISET_ID,
        "dandisetVersion": DANDISET_VERSION,
        "assetCount": len(bundle.sessions),
        "totalSourceBytes": bundle.total_source_bytes,
        "maximumSourceBytes": MAX_SOURCE_BYTES,
        "formalExecutionAuthorized": False,
        "assets": assets,
    }


def validate_downloaded_asset(
    path: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    size_reader: Callable[[Path], int] | None = None,
    hash_reader: Callable[[Path], str] | None = None,
) -> None:
    size_reader = size_reader or (lambda item: item.stat().st_size)
    hash_reader = hash_reader or sha256_file
    if not path.is_file():
        raise FileNotFoundError(f"qualified asset is missing: {path}")
    observed_size = int(size_reader(path))
    if observed_size != expected_size:
        raise ValueError(
            f"qualified asset size mismatch for {path}: "
            f"expected {expected_size}, found {observed_size}"
        )
    observed_sha256 = hash_reader(path).lower()
    if observed_sha256 != expected_sha256:
        raise ValueError(
            f"qualified asset SHA-256 mismatch for {path}: "
            f"expected {expected_sha256}, found {observed_sha256}"
        )


def validate_local_assets(
    bundle: QualificationBundle,
    source_root: Path,
) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    for session in bundle.sessions:
        local_path = _local_asset_path(source_root, session.relative_path)
        validate_downloaded_asset(
            local_path,
            expected_size=session.content_size,
            expected_sha256=session.sha256,
        )
        resolved[session.asset_id] = local_path
    return resolved


def load_execution_authorization(
    path: Path,
    bundle: QualificationBundle,
) -> dict[str, Any]:
    authorization, payload = _read_json(path.resolve())
    if authorization.get("schemaVersion") != AUTHORIZATION_SCHEMA:
        raise ValueError("formal execution authorization schema is invalid")
    if authorization.get("experimentId") != EXPERIMENT_ID:
        raise ValueError("formal execution authorization targets another experiment")
    if authorization.get("qualificationManifestSha256") != bundle.manifest_sha256:
        raise ValueError("formal execution authorization is bound to another manifest")
    if authorization.get("formalExperimentAuthorized") is not True:
        raise PermissionError("formal experiment has not been authorized")
    if authorization.get("qualifiedSessionAssetIds") != [
        session.asset_id for session in bundle.sessions
    ]:
        raise ValueError("formal execution authorization changes the frozen asset order")
    if not str(authorization.get("authorizedBy", "")).strip():
        raise ValueError("formal execution authorization requires an accountable reviewer")
    authorized_at = str(authorization.get("authorizedAt", "")).strip()
    try:
        parsed_authorized_at = datetime.fromisoformat(
            authorized_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError(
            "formal execution authorization requires a valid UTC timestamp"
        ) from exc
    utc_offset = parsed_authorized_at.utcoffset()
    if (
        parsed_authorized_at.tzinfo is None
        or utc_offset is None
        or utc_offset.total_seconds() != 0
    ):
        raise ValueError(
            "formal execution authorization requires a valid UTC timestamp"
        )
    authorization = dict(authorization)
    authorization["authorizedAt"] = (
        parsed_authorized_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    )
    authorization["artifactSha256"] = hashlib.sha256(payload).hexdigest()
    return authorization


def classify_multisession_results(
    session_results: list[dict[str, Any]],
    *,
    minimum_supported_delta: float,
) -> dict[str, Any]:
    if len(session_results) != len(FROZEN_ASSETS):
        raise ValueError("multi-session decision requires exactly three session results")
    full_support = [
        all(result["decision"]["gates"].values()) for result in session_results
    ]
    supporting_subjects = {
        result["subject"]
        for result, supported in zip(session_results, full_support, strict=True)
        if supported
    }
    deltas = [
        float(
            result["decision"][
                "transition_vs_stationary_balanced_accuracy_interaction_delta"
            ]
        )
        for result in session_results
    ]
    subject_deltas = {
        subject: [
            delta
            for result, delta in zip(session_results, deltas, strict=True)
            if result["subject"] == subject
        ]
        for subject in REQUIRED_SUBJECTS
    }
    gates = {
        "at_least_two_sessions_pass_all_five_gates": sum(full_support) >= 2,
        "both_subjects_have_a_supporting_session": supporting_subjects
        == REQUIRED_SUBJECTS,
        "median_interaction_meets_threshold": median(deltas)
        >= minimum_supported_delta,
        "no_session_has_nonpositive_interaction": min(deltas) > 0.0,
    }
    if all(gates.values()):
        status = "supports_cross_subject_state_conditioned_temporal_utility"
        decision = "CONTINUE"
    elif median(deltas) <= 0.0 or any(
        max(values) <= 0.0 for values in subject_deltas.values()
    ):
        status = "does_not_support_cross_subject_replication"
        decision = "BRANCH"
    else:
        status = "inconclusive_cross_subject_replication"
        decision = "BRANCH"
    return {
        "status": status,
        "decision": decision,
        "gates": gates,
        "supportingSessionCount": sum(full_support),
        "supportingSubjects": sorted(supporting_subjects),
        "interactionDeltas": deltas,
        "subjectMeanInteractionDeltas": {
            subject: round(sum(values) / len(values), 6)
            for subject, values in sorted(subject_deltas.items())
        },
        "medianInteractionDelta": round(float(median(deltas)), 6),
        "claimBoundary": (
            "Support is limited to the three frozen DANDI 000121 sessions, two "
            "monkeys, registered epochs, and offline decoder controls. It does not "
            "establish a universal neural code or a biological readout mechanism."
        ),
    }


def retain_qualified_nonempty_units(
    dataset: dict[str, Any],
    session: QualifiedSession,
) -> dict[str, Any]:
    nonempty_units = [spikes for spikes in dataset["unit_spikes"] if len(spikes) > 0]
    if len(nonempty_units) != session.nonempty_unit_count:
        raise ValueError(
            f"nonempty unit count drifted for {session.asset_id}: "
            f"qualified {session.nonempty_unit_count}, loaded {len(nonempty_units)}"
        )
    prepared = {**dataset, "unit_spikes": nonempty_units}
    prepared["retained_unit_count"] = len(nonempty_units)
    prepared["excluded_empty_unit_count"] = (
        len(dataset["unit_spikes"]) - len(nonempty_units)
    )
    return prepared


def _run_session(
    session: QualifiedSession,
    path: Path,
    config: EpochDiscriminationConfig,
) -> dict[str, Any]:
    dataset = retain_qualified_nonempty_units(
        load_dandi000121_dataset(path),
        session,
    )
    stationary = _evaluate_epoch(dataset, window=STATIONARY_WINDOW, config=config)
    transition = _evaluate_epoch(dataset, window=TRANSITION_WINDOW, config=config)
    if (
        transition["temporal"]["validation_truth"]
        != stationary["temporal"]["validation_truth"]
    ):
        raise ValueError("frozen epochs must share the same validation trial order")
    interaction = bootstrap_balanced_interaction_delta(
        transition["temporal"]["validation_truth"],
        transition["temporal"]["validation_correct"],
        transition["rate"]["validation_correct"],
        stationary["temporal"]["validation_correct"],
        stationary["rate"]["validation_correct"],
        seed=config.seed,
        repeats=config.bootstrap_repeats,
    )
    decision = classify_epoch_result(
        stationary_rate_balanced=stationary["rate"]["balanced_accuracy"],
        stationary_temporal_balanced=stationary["temporal"]["balanced_accuracy"],
        transition_rate_balanced=transition["rate"]["balanced_accuracy"],
        transition_temporal_balanced=transition["temporal"]["balanced_accuracy"],
        transition_shuffle_mean_balanced=transition["count_preserving_shuffle"][
            "balanced_accuracy_mean"
        ],
        interaction=interaction,
        minimum_supported_delta=config.minimum_supported_delta,
    )
    return {
        "assetId": session.asset_id,
        "subject": session.subject,
        "relativePath": session.relative_path,
        "trialCount": int(len(dataset["labels"])),
        "retainedUnitCount": int(dataset["retained_unit_count"]),
        "excludedEmptyUnitCount": int(dataset["excluded_empty_unit_count"]),
        "rejectionCounts": dataset["rejection_counts"],
        "adapterProtocol": dataset["adapter_protocol"],
        "metrics": {
            "stationary": {
                **stationary,
                "rate": _stable_metrics(stationary["rate"]),
                "temporal": _stable_metrics(stationary["temporal"]),
            },
            "transition": {
                **transition,
                "rate": _stable_metrics(transition["rate"]),
                "temporal": _stable_metrics(transition["temporal"]),
            },
            "interactionBootstrap": interaction,
        },
        "decision": decision,
    }


def run_multisession(
    *,
    qualification_manifest: Path,
    source_root: Path,
    execution_authorization: Path,
    config: EpochDiscriminationConfig | None = None,
) -> dict[str, Any]:
    config = config or EpochDiscriminationConfig()
    bundle = load_qualification_manifest(qualification_manifest)
    authorization = load_execution_authorization(execution_authorization, bundle)
    local_assets = validate_local_assets(bundle, source_root)
    session_results = [
        _run_session(session, local_assets[session.asset_id], config)
        for session in bundle.sessions
    ]
    decision = classify_multisession_results(
        session_results,
        minimum_supported_delta=config.minimum_supported_delta,
    )
    modules = _scientific_modules()
    return {
        "schemaVersion": "sci096.dandi000121.multisession-result.v1",
        "experimentId": EXPERIMENT_ID,
        "questionId": "SCI-096",
        "parentQuestionRunId": "stage1-sci-096-v3",
        "status": "formal_complete",
        "createdAt": datetime.now(UTC).isoformat(),
        "qualificationManifest": str(bundle.manifest_path),
        "qualificationManifestSha256": bundle.manifest_sha256,
        "executionAuthorization": {
            "path": str(execution_authorization.resolve()),
            "sha256": authorization["artifactSha256"],
            "authorizedBy": authorization["authorizedBy"],
            "authorizedAt": authorization["authorizedAt"],
        },
        "dataset": {
            "source": "DANDI",
            "dandisetId": DANDISET_ID,
            "version": DANDISET_VERSION,
            "assetCount": len(bundle.sessions),
            "subjects": sorted(REQUIRED_SUBJECTS),
            "totalSourceBytes": bundle.total_source_bytes,
            "assets": [asdict(session) for session in bundle.sessions],
        },
        "preregistration": {
            **asdict(config),
            "stationaryEpochSeconds": list(STATIONARY_WINDOW),
            "transitionEpochSeconds": list(TRANSITION_WINDOW),
            "sessionEvaluation": "existing five-gate SCI-096 v3 decision per session",
            "crossSessionDecision": (
                "at least two of three sessions pass all five gates, both monkeys "
                "have a supporting session, median interaction delta reaches the "
                "registered threshold, and every session interaction is positive"
            ),
        },
        "sessions": session_results,
        "decision": decision,
        "environment": {
            "python": platform.python_version(),
            "numpy": modules["np"].__version__,
            "h5py": modules["h5py"].__version__,
            "scikitLearn": modules["sklearn"].__version__,
        },
    }


def _write_append_only(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite append-only artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--qualification-manifest", type=Path, required=True)
    plan.add_argument("--source-root", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--qualification-manifest", type=Path, required=True)
    run.add_argument("--source-root", type=Path, required=True)
    run.add_argument("--execution-authorization", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "plan":
        bundle = load_qualification_manifest(args.qualification_manifest)
        result = build_download_plan(bundle, args.source_root)
    else:
        result = run_multisession(
            qualification_manifest=args.qualification_manifest,
            source_root=args.source_root,
            execution_authorization=args.execution_authorization,
        )
    _write_append_only(args.output.resolve(), result)
    print(
        json.dumps(
            {
                "status": result.get("status", "planned"),
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
