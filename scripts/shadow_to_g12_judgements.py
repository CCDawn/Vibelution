"""Turn shadow would-decide/human pairs into G12 calibration payloads.

The G12 calibration gate authorizes a specific policy's automation, and its
evidence (decision-#13) is a set of one-per-question judgements recording what
the automation *would* have done and what the human *actually* did.  Those
pairs already exist: the chain records them at real decision points whenever a
shadow policy is configured (``policy_shadow_evaluator``).  What was missing is
the transcription step — this command, so nobody hand-copies 100+ rows into a
privileged REST call.

It is deliberately strict about what counts as evidence:

* **Policy identity.** The gate reads manifests bound to
  ``(policyId, version, contentHash)``.  Only records carrying the *target*
  policy's identity are usable; records from an earlier or differently
  configured policy are excluded and named, because their would-decide values
  describe a configuration that is not the one being authorized.
* **No DEV fixtures.** Records whose ``scope.mode`` is ``dev`` are excluded: the
  project treats DEV fixtures as evidence of engineering behaviour only.
* **Comparable human outcomes only.** ``outcomeClass == "none"`` means no
  comparable human decision exists, so the pair cannot be judged.
* **Declared strata.** ``riskClass`` and ``catalogDomain`` come from the
  operator's pool declaration; this command never invents them, because they
  decide the stratification the gate tests.

Aggregation is per question and deliberately conservative: a question counts as
``auto_approve`` only when *every* usable record says the automation would have
acted, and as ``approve`` only when *every* usable record's human outcome was
``acted``.  Any hold or any escalation moves that side to the escalate value.
That matches the four-cell table the contract derives (``false_auto_approve``
is the costly error, so a question is only "auto-approvable" when the evidence
never disagrees).

Read-only by default.  ``--write`` records the manifest and judgements through
the same fail-closed store the privileged route uses, and requires an explicit
``--recorded-by`` for the audit trail.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.research.competition.calibration_stats import (
    AUTO_DECISION_AUTO_APPROVE,
    AUTO_DECISION_AUTO_ESCALATE,
    HUMAN_DECISION_APPROVE,
    HUMAN_DECISION_ESCALATE,
)
from core.research.workflow.contracts.policy_shadow import (
    POLICY_SHADOW_AUTO_ACTIONS,
)

EXIT_OK = 0
EXIT_GAPS = 1
EXIT_INPUT = 2

AUTO_DECISION_AUTO = AUTO_DECISION_AUTO_APPROVE
AUTO_DECISION_ESCALATE = AUTO_DECISION_AUTO_ESCALATE
HUMAN_DECISION_ACTED = HUMAN_DECISION_APPROVE
HUMAN_DECISION_ESCALATED = HUMAN_DECISION_ESCALATE

#: Human outcome classes that mean "asked for more work / refused", i.e. not
#: the automation-equivalent action.  ``none`` is excluded before this stage.
_HUMAN_ESCALATED_CLASSES = frozenset({"escalated", "vetoed"})

EXCLUSION_DEV_SCOPE = "dev_scope"
EXCLUSION_IDENTITY = "policy_identity_mismatch"
EXCLUSION_NO_OUTCOME = "no_human_outcome"


def map_auto_decision(would_decide: object) -> str:
    """Automation side of the pair: acted, or held back."""

    return (
        AUTO_DECISION_AUTO
        if str(would_decide or "").strip() in POLICY_SHADOW_AUTO_ACTIONS
        else AUTO_DECISION_ESCALATE
    )


def map_human_decision(outcome_class: object) -> str:
    """Human side of the pair: did the action, or escalated/refused."""

    normalized = str(outcome_class or "").strip()
    if normalized == "acted":
        return HUMAN_DECISION_ACTED
    if normalized in _HUMAN_ESCALATED_CLASSES:
        return HUMAN_DECISION_ESCALATED
    raise ValueError(f"outcome class {normalized!r} is not a comparable human decision")


def agreement_for_mapping(auto_decision: str, human_decision: str) -> str:
    """Reproduce the contract's four-cell agreement from the mapped pair.

    Mirrors ``policy_shadow.derive_shadow_agreement`` semantics over the
    judgement vocabulary, so ``--self-check`` can validate the mapping table
    against the agreement the system itself stored on each record.
    """

    auto_acted = auto_decision == AUTO_DECISION_AUTO
    human_acted = human_decision == HUMAN_DECISION_ACTED
    if auto_acted and human_acted:
        return "agree"
    if auto_acted and not human_acted:
        return "false_auto_approve"
    if not auto_acted and not human_acted:
        return "agree"
    return "false_escalate"


def policy_reference(policy: Any) -> tuple[str, str, str]:
    """The (policyId, version, contentHash) identity the gate filters on."""

    policy_id = str(getattr(policy, "policyId", "") or "").strip()
    version = str(getattr(policy, "version", "") or "").strip()
    content_hash = str(getattr(policy, "declaredContentHash", "") or "").strip().upper()
    if not policy_id or not version or not content_hash:
        raise ValueError("policy identity is incomplete (policyId/version/contentHash)")
    return policy_id, version, content_hash


def record_identity(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("policyId") or "").strip(),
        str(record.get("policyVersion") or "").strip(),
        str(record.get("policyContentHash") or "").strip().upper(),
    )


def exclusion_reason(
    record: dict[str, Any], target: tuple[str, str, str]
) -> str:
    """Why this record is not usable evidence, or "" when it is."""

    scope = record.get("scope") if isinstance(record.get("scope"), dict) else {}
    if str(scope.get("mode") or "").strip().lower() == "dev":
        return EXCLUSION_DEV_SCOPE
    if record_identity(record) != target:
        return EXCLUSION_IDENTITY
    outcome = (
        record.get("actualOutcome")
        if isinstance(record.get("actualOutcome"), dict)
        else {}
    )
    if str(outcome.get("outcomeClass") or "").strip() not in {
        "acted",
        *_HUMAN_ESCALATED_CLASSES,
    }:
        return EXCLUSION_NO_OUTCOME
    return ""


def load_shadow_records(team_id: str, store_path: Path | None = None) -> list[dict[str, Any]]:
    from core.web.services.team_workflow.research_runtime.policy_shadow_evaluator import (
        policy_shadow_store_path,
    )

    path = store_path if store_path is not None else policy_shadow_store_path(team_id)
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def partition_records(
    records: list[dict[str, Any]], target: tuple[str, str, str]
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int]]:
    """Split records into usable evidence and named exclusions."""

    usable: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    by_identity: dict[str, int] = {}
    for record in records:
        reason = exclusion_reason(record, target)
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
            if reason == EXCLUSION_IDENTITY:
                policy_id, version, content_hash = record_identity(record)
                key = f"{policy_id} v{version} {content_hash[:12]}…"
                by_identity[key] = by_identity.get(key, 0) + 1
            continue
        usable.append(record)
    return usable, counts, by_identity


def aggregate_per_question(
    usable: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """One conservative judgement per question (see the module docstring)."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in usable:
        question_id = str(record.get("questionId") or "").strip().upper()
        if question_id:
            grouped.setdefault(question_id, []).append(record)

    judgements: dict[str, dict[str, Any]] = {}
    for question_id, records in grouped.items():
        auto_acted_everywhere = True
        human_acted_everywhere = True
        for record in records:
            outcome = (
                record.get("actualOutcome")
                if isinstance(record.get("actualOutcome"), dict)
                else {}
            )
            if map_auto_decision(record.get("wouldDecide")) != AUTO_DECISION_AUTO:
                auto_acted_everywhere = False
            if map_human_decision(outcome.get("outcomeClass")) != HUMAN_DECISION_ACTED:
                human_acted_everywhere = False
        judgements[question_id] = {
            "questionId": question_id,
            "autoDecision": (
                AUTO_DECISION_AUTO if auto_acted_everywhere else AUTO_DECISION_ESCALATE
            ),
            "humanDecision": (
                HUMAN_DECISION_ACTED
                if human_acted_everywhere
                else HUMAN_DECISION_ESCALATED
            ),
            "decisionPoints": sorted(
                {str(record.get("decisionPoint") or "") for record in records}
            ),
            "recordIds": [str(record.get("recordId") or "") for record in records],
        }
    return judgements


def build_manifest_and_judgements(
    *,
    team_id: str,
    pool: list[dict[str, Any]],
    policy: Any,
    judgements: dict[str, dict[str, Any]],
    seed: str,
    manifest_id: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], list[str]]:
    """Build the manifest payload and the judgement payloads.

    Returns ``(manifest_payload, judgement_payloads, missing_records, undeclared)``
    where ``missing_records`` are declared questions with no usable pair and
    ``undeclared`` are judged questions absent from the declaration.
    """

    from core.research.competition.calibration_records import G12JudgementRecord
    from core.research.workflow.contracts.audit_sampling import SampleKind
    from core.web.services.team_workflow.research_runtime.audit_sampling_service import (
        generate_g12_calibration_manifest,
    )

    declared = {str(entry.get("questionId") or "").strip().upper() for entry in pool}
    judged = set(judgements)
    missing_records = sorted(declared - judged)
    undeclared = sorted(judged - declared)
    included = [entry for entry in pool if str(entry.get("questionId") or "").strip().upper() in judged]

    if not included:
        return {}, [], missing_records, undeclared

    policy_dict = {
        "policyId": policy.policyId,
        "version": policy.version,
        "contentHash": policy.declaredContentHash,
    }
    manifest = generate_g12_calibration_manifest(
        pool=included,
        policy=policy_dict,
        seed=seed,
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        manifest_id=manifest_id,
    )
    manifest_payload = manifest.to_dict()

    by_question = {
        str(entry.get("questionId") or "").strip().upper(): entry for entry in included
    }
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payloads: list[dict[str, Any]] = []
    for question_id in sorted(by_question):
        judgement = judgements[question_id]
        entry = by_question[question_id]
        record = G12JudgementRecord(
            questionId=question_id,
            sampleKind=SampleKind.G12_CALIBRATION,
            autoDecision=judgement["autoDecision"],
            humanDecision=judgement["humanDecision"],
            riskClass=str(entry.get("riskClass") or "").strip(),
            domain=str(entry.get("catalogDomain") or "").strip(),
            recordedAt=now,
            evidenceRef=(
                "policy_shadow:" + ",".join(item for item in judgement["recordIds"] if item)
            ),
        )
        payloads.append(record.to_dict())
    return manifest_payload, payloads, missing_records, undeclared


def self_check(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate the mapping table against each record's stored agreement.

    Runs over *every* record regardless of identity or scope: the stored
    ``agreement`` was derived by the contract itself, so it is the authority
    this command's mapping must reproduce.
    """

    checked = 0
    mismatches: list[dict[str, str]] = []
    skipped = 0
    for record in records:
        outcome = (
            record.get("actualOutcome")
            if isinstance(record.get("actualOutcome"), dict)
            else {}
        )
        outcome_class = str(outcome.get("outcomeClass") or "").strip()
        stored = str(record.get("agreement") or "").strip()
        if outcome_class not in {"acted", *_HUMAN_ESCALATED_CLASSES}:
            skipped += 1
            continue
        derived = agreement_for_mapping(
            map_auto_decision(record.get("wouldDecide")),
            map_human_decision(outcome_class),
        )
        checked += 1
        if derived != stored:
            mismatches.append(
                {
                    "recordId": str(record.get("recordId") or ""),
                    "wouldDecide": str(record.get("wouldDecide") or ""),
                    "outcomeClass": outcome_class,
                    "stored": stored,
                    "derived": derived,
                }
            )
    return {"checked": checked, "skipped": skipped, "mismatches": mismatches}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert shadow would-decide/human pairs into G12 calibration "
            "manifest + judgement payloads.  Read-only unless --write."
        )
    )
    parser.add_argument("--team-id", required=True, help="team whose shadow store is read")
    parser.add_argument(
        "--store",
        type=Path,
        default=None,
        help=(
            "explicit shadow store JSONL to read (default: the store the live "
            "runtime would resolve for this team)"
        ),
    )
    parser.add_argument(
        "--pool",
        type=Path,
        default=None,
        help="declared pilot pool JSON: [{questionId, riskClass, catalogDomain}]",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=None,
        help="policy document to bind evidence to (default: the resolved active policy)",
    )
    parser.add_argument("--seed", default="g12-calibration-pilot", help="manifest seed")
    parser.add_argument("--manifest-id", default=None)
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="validate the mapping table against stored agreements, then exit",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    parser.add_argument(
        "--write",
        action="store_true",
        help="record the manifest and judgements through the calibration store",
    )
    parser.add_argument(
        "--recorded-by",
        default="",
        help="operator identity for the audit trail (required with --write)",
    )
    args = parser.parse_args(argv)

    records = load_shadow_records(args.team_id, args.store)

    if args.self_check:
        report = {"teamId": args.team_id, "records": len(records), **self_check(records)}
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"shadow records read: {report['records']}")
            print(f"  comparable pairs checked: {report['checked']}")
            print(f"  records without a comparable human outcome (skipped): {report['skipped']}")
            print(f"  mapping mismatches vs stored agreement: {len(report['mismatches'])}")
            for item in report["mismatches"][:10]:
                print(f"    {item}")
            print(
                "RESULT: mapping table reproduces the contract's agreement"
                if not report["mismatches"]
                else "RESULT: mapping table DISAGREES with the stored agreement"
            )
        return EXIT_OK if not report["mismatches"] else EXIT_GAPS

    if args.pool is None:
        print("--pool is required (riskClass and catalogDomain are never invented)", file=sys.stderr)
        return EXIT_INPUT
    if args.write and not args.recorded_by.strip():
        print("--write requires --recorded-by", file=sys.stderr)
        return EXIT_INPUT

    try:
        pool_payload = json.loads(args.pool.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"pool declaration is unreadable: {exc}", file=sys.stderr)
        return EXIT_INPUT
    pool = pool_payload.get("pool") if isinstance(pool_payload, dict) else pool_payload
    if not isinstance(pool, list) or not pool:
        print("pool declaration must be a non-empty list", file=sys.stderr)
        return EXIT_INPUT

    try:
        if args.policy is not None:
            from core.web.services.team_workflow.research_runtime.automation_policy_service import (
                load_auto_advance_policy_v2,
            )

            policy = load_auto_advance_policy_v2(args.policy, stage="activation")
        else:
            from core.web.services.team_workflow.research_runtime.automation_policy_executor import (
                load_active_policy_from_environment,
            )

            policy = load_active_policy_from_environment()
    except Exception as exc:  # noqa: BLE001 - a broken policy is an input problem
        print(f"target policy is unusable: {exc}", file=sys.stderr)
        return EXIT_INPUT
    if policy is None:
        print("no target policy resolved (configure the activation policy first)", file=sys.stderr)
        return EXIT_INPUT

    target = policy_reference(policy)
    usable, exclusions, by_identity = partition_records(records, target)
    judgements = aggregate_per_question(usable)
    manifest_payload, judgement_payloads, missing_records, undeclared = (
        build_manifest_and_judgements(
            team_id=args.team_id,
            pool=pool,
            policy=policy,
            judgements=judgements,
            seed=args.seed,
            manifest_id=args.manifest_id,
        )
    )

    report: dict[str, Any] = {
        "teamId": args.team_id,
        "targetPolicy": {
            "policyId": target[0],
            "version": target[1],
            "contentHash": target[2],
        },
        "shadowRecords": len(records),
        "usableRecords": len(usable),
        "exclusions": exclusions,
        "excludedIdentities": by_identity,
        "judgedQuestions": sorted(judgements),
        "declaredQuestions": len(pool),
        "missingRecords": missing_records,
        "undeclaredQuestions": undeclared,
        "manifestId": manifest_payload.get("manifestId"),
        "manifestQuestionCount": len(manifest_payload.get("questionIds") or []),
        "manifest": manifest_payload,
        "judgements": judgement_payloads,
    }

    written = ""
    if args.write and judgement_payloads:
        from core.web.services.team_workflow.research_runtime.g12_calibration_store import (
            record_g12_calibration_manifest,
            record_g12_judgements,
        )

        manifest_result = record_g12_calibration_manifest(
            args.team_id, manifest_payload, recorded_by=args.recorded_by
        )
        judgement_result = record_g12_judgements(
            args.team_id,
            {"manifestId": manifest_payload["manifestId"], "judgements": judgement_payloads},
            recorded_by=args.recorded_by,
        )
        report["manifestWrite"] = manifest_result
        report["judgementWrite"] = judgement_result
        written = str(manifest_result.get("status") or "")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"team: {args.team_id}")
        print(f"target policy: {target[0]} v{target[1]} {target[2][:12]}…")
        print(f"shadow records read: {len(records)}")
        print(f"  usable: {len(usable)}")
        for reason, count in sorted(exclusions.items()):
            print(f"  excluded ({reason}): {count}")
        for identity, count in sorted(by_identity.items()):
            print(f"      from {identity}: {count}")
        print(f"judged questions: {len(judgements)}  -> {sorted(judgements)}")
        print(f"declared pool: {len(pool)}")
        if missing_records:
            print(f"  declared but with no usable pair (dropped): {missing_records}")
        if undeclared:
            print(f"  judged but not declared (dropped): {undeclared}")
        print(f"manifest: {report['manifestId']} with {report['manifestQuestionCount']} question(s)")
        for payload in judgement_payloads:
            print(
                f"  {payload['questionId']}: auto={payload['autoDecision']} "
                f"human={payload['humanDecision']} "
                f"risk={payload['riskClass']} domain={payload['domain']}"
            )
        if args.write:
            print(f"write: {written or 'nothing to write'}")
        else:
            print("(dry run; pass --write --recorded-by <operator> to record)")

    has_evidence = bool(judgement_payloads)
    complete = has_evidence and not missing_records and not undeclared
    return EXIT_OK if complete else EXIT_GAPS


if __name__ == "__main__":
    raise SystemExit(main())
