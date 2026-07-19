from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.evaluation.supervised_evidence_integrity import (
    archive_supervised_test_contamination,
    build_supervised_evidence_preview,
)
from core.infrastructure import developer_sandbox


def main() -> int:
    parser = argparse.ArgumentParser(description="监督进化证据维护（当前仅支持只读预览）")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    parser.add_argument(
        "--archive-session",
        action="append",
        default=[],
        help="归档一个已由强证据确认的测试污染 session；可重复传入",
    )
    parser.add_argument("--archive-root", type=Path, help="不可已存在的归档目标目录")
    parser.add_argument(
        "--confirm-archive",
        action="store_true",
        help="确认先备份并校验，再定点移除指定污染记录",
    )
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    evidence_root = args.evidence_root or developer_sandbox.formal_workspace_path(
        project_root, "supervised_evolution"
    )
    if args.archive_session:
        if not args.confirm_archive:
            parser.error("归档属于正式数据变更，必须同时传入 --confirm-archive")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive_root = args.archive_root or (
            evidence_root.parent.parent
            / "backups"
            / "supervised_evolution"
            / f"test-contamination-{timestamp}"
        )
        result = archive_supervised_test_contamination(
            evidence_root=evidence_root,
            session_ids=args.archive_session,
            archive_root=archive_root,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    preview = build_supervised_evidence_preview(evidence_root)
    if args.json:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
    else:
        summary = preview["summary"]
        print(
            "只读预览："
            f"总会话 {summary['total_sessions']}，"
            f"疑似测试污染 {summary['contaminated_sessions']}，"
            f"未验证 {summary['unverified_sessions']}"
        )
        for session in preview["sessions"]:
            if session["classification"] == "test_contamination":
                print(
                    f"- {session['session_id']}: {', '.join(session['strong_signals'])}; "
                    f"关联路径 {len(session['associated_paths'])}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
