from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.evaluation.supervised_evidence_integrity import build_supervised_evidence_preview
from core.infrastructure import developer_sandbox


def main() -> int:
    parser = argparse.ArgumentParser(description="监督进化证据维护（当前仅支持只读预览）")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    evidence_root = args.evidence_root or developer_sandbox.formal_workspace_path(
        project_root, "supervised_evolution"
    )
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
