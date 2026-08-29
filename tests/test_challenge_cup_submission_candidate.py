from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import validate_challenge_cup_submission_candidate as validator


def _manifest() -> dict:
    slots = []
    for key, path, required in (
        ("technical_proposal_pdf", "01-最终作品PDF", True),
        ("full_catalog_results", "02-125题逐题结果", True),
        ("source_code", "03-源码与复现", True),
        ("qwen_official_evidence", "04-Qwen调用证据", True),
        ("deep_experiment_suite", "05-深实验", True),
        ("demo_video", "06-可选演示视频", False),
        ("official_submission_receipt", "07-官方提交回执", False),
        ("test_api", "API与前端提交说明.md", True),
    ):
        slots.append(
            {
                "key": key,
                "path": path,
                "required": required,
                "status": "MISSING" if required else "OPTIONAL",
                "files": [],
            }
        )
    return {
        "schemaVersion": 1,
        "candidateKind": "challenge_cup_submission_candidate",
        "candidateId": "challenge-cup-2026-primary",
        "current": True,
        "status": "NOT_READY",
        "authority": {
            "uploadAuthorized": False,
            "officiallySubmitted": False,
            "completionClaimsAllowed": False,
        },
        "slots": slots,
    }


def _write_candidate(root: Path, payload: dict) -> Path:
    candidate = root / validator.CANONICAL_FILENAME
    candidate.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return candidate


def test_incomplete_current_candidate_is_valid_but_not_ready(tmp_path: Path) -> None:
    payload = _manifest()
    for slot in payload["slots"]:
        path = tmp_path / slot["path"]
        if Path(slot["path"]).suffix:
            path.write_text("placeholder", encoding="utf-8")
        else:
            path.mkdir()

    report = validator.validate_candidate(_write_candidate(tmp_path, payload))

    assert report["valid"] is True
    assert report["ready"] is False
    assert report["requiredReady"] == 0
    assert report["requiredCount"] == 6
    assert "required_slots_missing" in report["blockers"]


def test_ready_slot_requires_matching_file_hash(tmp_path: Path) -> None:
    payload = _manifest()
    pdf_dir = tmp_path / "01-最终作品PDF"
    pdf_dir.mkdir()
    pdf = pdf_dir / "proposal.pdf"
    pdf.write_bytes(b"real-candidate")
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    pdf_slot = next(slot for slot in payload["slots"] if slot["key"] == "technical_proposal_pdf")
    pdf_slot["status"] = "READY"
    pdf_slot["files"] = [{"path": "01-最终作品PDF/proposal.pdf", "sha256": digest}]
    for slot in payload["slots"]:
        path = tmp_path / slot["path"]
        if not path.exists():
            if Path(slot["path"]).suffix:
                path.write_text("placeholder", encoding="utf-8")
            else:
                path.mkdir()

    report = validator.validate_candidate(_write_candidate(tmp_path, payload))

    assert report["valid"] is True
    assert report["requiredReady"] == 1


def test_candidate_rejects_path_escape(tmp_path: Path) -> None:
    payload = _manifest()
    payload["slots"][0]["path"] = "../outside"

    report = validator.validate_candidate(_write_candidate(tmp_path, payload))

    assert report["valid"] is False
    assert "unsafe_slot_path" in {error["code"] for error in report["errors"]}
