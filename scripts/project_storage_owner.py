#!/usr/bin/env python3
"""Trusted operator CLI for an opt-in, no-copy configured data owner proof."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.infrastructure.storage_owner_handoff import (
    StorageOwnerHandoffError, apply_storage_owner_handoff, plan_storage_owner_handoff,
    read_storage_owner_handoff_receipt, revoke_storage_owner_handoff,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("plan", "apply", "receipt", "revoke"):
        command = sub.add_parser(action)
        command.add_argument("--project-root", required=True)
        if action != "plan":
            command.add_argument("--request-id", required=True)
        if action == "apply":
            command.add_argument("--plan-digest", required=True)
            command.add_argument("--confirm-relocated-data", action="store_true")
        if action == "revoke":
            command.add_argument("--record-digest", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "plan":
            payload = plan_storage_owner_handoff(Path(args.project_root))
        elif args.action == "receipt":
            payload = read_storage_owner_handoff_receipt(Path(args.project_root), request_id=args.request_id)
        elif args.action == "apply":
            payload = apply_storage_owner_handoff(Path(args.project_root), plan_digest=args.plan_digest,
                confirm_relocated_data=args.confirm_relocated_data, request_id=args.request_id)
        else:
            payload = revoke_storage_owner_handoff(Path(args.project_root), record_digest=args.record_digest,
                                                   request_id=args.request_id)
    except (StorageOwnerHandoffError, OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        # Source/config decoding errors can contain private values. Expose a
        # stable code only for errors deliberately raised by this authority.
        code = str(error) if isinstance(error, StorageOwnerHandoffError) else "owner_authority_unavailable"
        print(json.dumps({"ok": False, "error": code}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
