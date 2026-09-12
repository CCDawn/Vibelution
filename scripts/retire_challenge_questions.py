"""Retire old Challenge Cup question experiments through the product service.

Dry-run by default: prints the exact per-question preview and only mutates
state with ``--apply``.  Every guard the service enforces (golden sample,
required deep experiments, approved runs, active discussions) still applies.
Run from the repo root (or pass ``--project``) so product data resolves to the
same instance the running backend uses.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project",
        default=str(_repo_root()),
        help="project root whose product data instance should be used",
    )
    parser.add_argument("--team", default="research-team", help="team id")
    parser.add_argument(
        "--questions",
        required=True,
        help="comma separated question ids, e.g. SCI-092,SCI-024",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="execute the retire; without it the script is a pure dry-run",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    project_root = str(Path(args.project).resolve())
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from core.web.services.team_workflow import challenge_question_retire

    question_ids = [
        item.strip().upper() for item in str(args.questions).split(",") if item.strip()
    ]
    if not question_ids:
        print("no questions requested", file=sys.stderr)
        return 2

    reports: list[dict[str, object]] = []
    exit_code = 0
    for question_id in question_ids:
        try:
            preview = challenge_question_retire.preview_question_retire(
                args.team, question_id
            )
        except Exception as exc:  # noqa: BLE001 - report per question
            reports.append(
                {"questionId": question_id, "status": "preview_failed", "error": str(exc)}
            )
            exit_code = 1
            continue
        entry: dict[str, object] = {
            "questionId": question_id,
            "status": "preview",
            "preview": preview,
        }
        if args.apply:
            if not preview.get("canRetire"):
                entry["status"] = "blocked"
                exit_code = 1
            else:
                try:
                    entry["result"] = challenge_question_retire.retire_question_experiment(
                        args.team,
                        question_id,
                        confirmation_question_id=question_id,
                    )
                    entry["status"] = "retired"
                except (
                    challenge_question_retire.ChallengeQuestionRetirePartialError
                ) as exc:
                    entry["status"] = "partial"
                    entry["error"] = str(exc)
                    entry["result"] = exc.result
                    exit_code = 1
                except Exception as exc:  # noqa: BLE001 - report per question
                    entry["status"] = "failed"
                    entry["error"] = str(exc)
                    exit_code = 1
        reports.append(entry)

    print(
        json.dumps(
            {"teamId": args.team, "applied": bool(args.apply), "reports": reports},
            ensure_ascii=False,
            indent=2,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
