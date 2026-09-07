"""Register one externally executed research batch into the workflow ledger.

This is the operator entry point for the ``external_batch_registrations``
certified-copy registry (schema v8).  It validates the batch manifest and
every referenced projection/summary file against the manifest's own sha256
records, then writes ONE registration row.  It never fabricates workflow
events: the ledger keeps only the receipt, not a replay of the batch.

Usage:
  python -m core.research.workflow.ledger.register_external_batch \
      --ledger <workflow-ledger.sqlite> \
      --plane external_agent --layer hypothesis_generation \
      --manifest <path/to/manifest.json> --root <batch root dir> \
      --registered-by agent-jska [--note "..."]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .records import ExternalBatchRegistration
from .store import WorkflowLedgerStore

_VALID_PLANES = {"external_agent", "content_conversion"}
_VALID_LAYERS = {
    "raw_hypothesis_reports",
    "hypothesis_generation",
    "content_layer",
}
_HASH_FILE_CHUNK = 1 << 20


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_FILE_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("manifest.documents must be a non-empty list")
    if not manifest.get("generated_at"):
        raise ValueError("manifest.generated_at is required")
    return manifest


def _verify_documents(manifest: dict, root: Path) -> list[str]:
    """Full sha256 re-verification of every referenced document file.

    Returns the list of human-readable problems; empty means verified.
    """
    problems: list[str] = []
    for doc in manifest["documents"]:
        question_id = str(doc.get("question_id", "<missing-id>"))
        for sha_key, path_key in (
            ("summary_sha256", "summary_path"),
            ("projection_sha256", "projection_path"),
        ):
            expected = doc.get(sha_key)
            rel_path = doc.get(path_key)
            if not expected or not rel_path:
                problems.append(f"{question_id}: missing {sha_key}/{path_key}")
                continue
            file_path = root / str(rel_path)
            if not file_path.is_file():
                problems.append(f"{question_id}: file missing {rel_path}")
                continue
            actual = _sha256_file(file_path)
            if actual != expected:
                problems.append(
                    f"{question_id}: hash mismatch for {rel_path} "
                    f"(manifest={expected[:12]} actual={actual[:12]})"
                )
    return problems


def _parse_generated_at_ms(value: str) -> int:
    text = value.strip().replace("Z", "+00:00")
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp() * 1000)


def register(
    *,
    ledger_path: Path,
    plane: str,
    layer: str,
    manifest_path: Path,
    root: Path,
    registered_by: str,
    note: str | None,
) -> tuple[ExternalBatchRegistration, bool]:
    """Validate + register. Raises ValueError on any verification failure."""
    if plane not in _VALID_PLANES:
        raise ValueError(f"invalid plane: {plane}")
    if layer not in _VALID_LAYERS:
        raise ValueError(f"invalid layer: {layer}")

    manifest_sha256 = _sha256_file(manifest_path)
    manifest = _load_manifest(manifest_path)
    problems = _verify_documents(manifest, root)
    if problems:
        raise ValueError(
            "manifest verification failed:\n  " + "\n  ".join(problems[:20])
        )

    generated_at_ms = _parse_generated_at_ms(str(manifest["generated_at"]))
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    batch_id = f"{layer}-{manifest_sha256[:12]}"
    manifest_ref = {
        "manifest_path": str(manifest_path.resolve()),
        "root_path": str(root.resolve()),
        "generated_at": manifest["generated_at"],
        "status": manifest.get("status"),
    }

    record = ExternalBatchRegistration(
        batch_id=batch_id,
        plane=plane,
        layer=layer,
        manifest_sha256=manifest_sha256,
        manifest_ref_json=json.dumps(manifest_ref, ensure_ascii=False),
        question_count=len(manifest["documents"]),
        batch_generated_at_ms=generated_at_ms,
        registered_by=registered_by,
        registered_at_ms=now_ms,
        verified=1,
        related_run_id=None,
        note=note,
    )

    store = WorkflowLedgerStore(ledger_path)
    store.open()
    try:
        registered, created = store.register_external_batch(record)
    finally:
        store.close()
    return registered, created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Register an external research batch receipt."
    )
    parser.add_argument("--ledger", required=True, help="workflow ledger sqlite path")
    parser.add_argument("--plane", required=True, choices=sorted(_VALID_PLANES))
    parser.add_argument("--layer", required=True, choices=sorted(_VALID_LAYERS))
    parser.add_argument("--manifest", required=True, help="manifest.json path")
    parser.add_argument(
        "--root", required=True, help="batch root dir the manifest paths resolve against"
    )
    parser.add_argument("--registered-by", required=True)
    parser.add_argument("--note", default=None)
    args = parser.parse_args(argv)

    try:
        registered, created = register(
            ledger_path=Path(args.ledger),
            plane=args.plane,
            layer=args.layer,
            manifest_path=Path(args.manifest),
            root=Path(args.root),
            registered_by=args.registered_by,
            note=args.note,
        )
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"REGISTRATION REJECTED: {exc}", file=sys.stderr)
        return 2

    state = "created" if created else "already-registered"
    print(f"OK {state} batch_id={registered.batch_id}")
    print(
        f"  plane={registered.plane} layer={registered.layer} "
        f"questions={registered.question_count} "
        f"manifest_sha256={registered.manifest_sha256[:16]}…"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
