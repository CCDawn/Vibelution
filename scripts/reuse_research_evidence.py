#!/usr/bin/env python3
"""Record bounded mature-project reuse evidence for the current task branch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.reuse_research_contract import (  # noqa: E402
    DECISIONS,
    LOCAL_REUSE_DECISIONS,
    RESEARCH_MODES,
    ReuseResearchEvidenceError,
    evidence_path,
    record_evidence,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    record = subparsers.add_parser("record")
    record.add_argument("--project-root", type=Path, default=Path.cwd())
    record.add_argument("--feature", required=True)
    record.add_argument("--mode", choices=sorted(RESEARCH_MODES), default="EXTERNAL")
    record.add_argument("--decision", choices=sorted(DECISIONS), required=True)
    record.add_argument(
        "--local-reuse-decision",
        choices=sorted(LOCAL_REUSE_DECISIONS),
        required=True,
    )
    record.add_argument("--local-owner", action="append", default=[], required=True)
    record.add_argument("--candidate", action="append", default=[])
    record.add_argument("--borrowed-slice", action="append", default=[])
    record.add_argument("--rejected-alternative", action="append", default=[])
    record.add_argument("--reason", required=True)
    record.add_argument("--implementation-boundary", required=True)
    record.add_argument("--verification-strategy", required=True)
    record.add_argument("--risk-note", action="append", default=[])
    record.add_argument("--source-ref", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = record_evidence(
            args.project_root,
            feature=args.feature,
            decision=args.decision,
            local_reuse_decision=args.local_reuse_decision,
            local_owner_paths=args.local_owner,
            candidate_ids=args.candidate,
            borrowed_slices=args.borrowed_slice,
            rejected_alternatives=args.rejected_alternative,
            reason=args.reason,
            implementation_boundary=args.implementation_boundary,
            verification_strategy=args.verification_strategy,
            risk_notes=args.risk_note,
            source_refs=args.source_ref,
            research_mode=args.mode,
            project_root=args.project_root,
        )
    except (OSError, RuntimeError, ValueError, ReuseResearchEvidenceError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True))
        return 1
    path = evidence_path(args.project_root, str(payload["taskId"]))
    print(
        json.dumps(
            {
                "ok": True,
                "path": str(path),
                "taskId": payload["taskId"],
                "decision": payload["decision"],
                "researchMode": payload["researchMode"],
                "candidates": [
                    {
                        "projectId": candidate["projectId"],
                        "headSha": candidate["headSha"],
                        "license": candidate["license"],
                    }
                    for candidate in payload["candidates"]
                ],
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
