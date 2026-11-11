import json
from pathlib import Path

import pytest

from core.launcher import frontend_build as fb


def _write_release(root: Path, name: str, build_key: str, *, complete: bool = True) -> Path:
    release = root / "web" / fb.RELEASES_DIR_NAME / name
    release.mkdir(parents=True)
    (release / "index.html").write_text('<script src="/assets/app.js"></script>', encoding="utf-8")
    assets = release / "assets"
    assets.mkdir()
    if complete:
        (assets / "app.js").write_text("console.log(1)", encoding="utf-8")
    (release / ".vibelution-build.json").write_text(
        json.dumps({"schemaVersion": fb.BUILD_SCHEMA_VERSION, "buildKey": build_key}),
        encoding="utf-8",
    )
    return release


def _write_pointer(root: Path, name: str, build_key: str, published_at: float = 1000.0) -> None:
    pointer = root / "web" / fb.RELEASES_DIR_NAME / fb.ACTIVE_RELEASE_NAME
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(
        json.dumps(
            {
                "schemaVersion": fb.BUILD_SCHEMA_VERSION,
                "release": name,
                "buildKey": build_key,
                "publishedAt": published_at,
            }
        ),
        encoding="utf-8",
    )


def _write_legacy(root: Path) -> Path:
    dist = root / "web" / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    return dist


@pytest.fixture(autouse=True)
def _clear_warning_memo():
    fb._SERVING_FALLBACKS_WARNED.clear()
    yield
    fb._SERVING_FALLBACKS_WARNED.clear()


def test_healthy_pointer_serves_the_named_release(tmp_path: Path) -> None:
    release = _write_release(tmp_path, "release-aaa", "key-a")
    _write_pointer(tmp_path, "release-aaa", "key-a", published_at=1234.5)
    _write_legacy(tmp_path)

    target = fb.resolve_frontend_serving_target(tmp_path)

    assert target["source"] == fb.SERVING_SOURCE_RELEASE
    assert target["release"] == "release-aaa"
    assert target["buildKey"] == "key-a"
    assert target["publishedAt"] == 1234.5
    assert target["fallbackReason"] == ""
    assert Path(target["dist"]) == release
    assert fb.resolve_active_frontend_dist(tmp_path) == release


def test_missing_pointer_reports_the_unreferenced_release_without_serving_it(tmp_path: Path) -> None:
    release = _write_release(tmp_path, "release-bbb", "key-b")
    legacy = _write_legacy(tmp_path)

    target = fb.resolve_frontend_serving_target(tmp_path)

    assert target["source"] == fb.SERVING_SOURCE_LEGACY_DIST
    assert Path(target["dist"]) == legacy
    assert target["fallbackReason"] == "active_release_missing"
    assert target["recoverableRelease"] == release.name


def test_pointer_to_deleted_release_reports_a_recoverable_release(tmp_path: Path) -> None:
    older = _write_release(tmp_path, "release-old", "key-old")
    newer = _write_release(tmp_path, "release-new", "key-new")
    newer.touch()
    _write_pointer(tmp_path, "release-gone", "key-gone")
    legacy = _write_legacy(tmp_path)

    target = fb.resolve_frontend_serving_target(tmp_path)

    assert target["source"] == fb.SERVING_SOURCE_LEGACY_DIST
    assert Path(target["dist"]) == legacy
    assert target["fallbackReason"] == "active_release_invalid"
    assert target["recoverableRelease"] in {older.name, newer.name}


def test_incomplete_release_without_any_alternative_is_reported_as_legacy_fallback(tmp_path: Path) -> None:
    _write_release(tmp_path, "release-broken", "key-broken", complete=False)
    _write_pointer(tmp_path, "release-broken", "key-broken")
    legacy = _write_legacy(tmp_path)

    target = fb.resolve_frontend_serving_target(tmp_path)

    assert target["source"] == fb.SERVING_SOURCE_LEGACY_DIST
    assert Path(target["dist"]) == legacy
    assert target["fallbackReason"] == "active_release_invalid"


def test_pointer_cannot_name_a_path_outside_the_release_pool(tmp_path: Path) -> None:
    outside = tmp_path / "somewhere-else"
    outside.mkdir()
    (outside / "index.html").write_text('<script src="/assets/app.js"></script>', encoding="utf-8")
    _write_pointer(tmp_path, "../somewhere-else", "key-x")
    legacy = _write_legacy(tmp_path)

    target = fb.resolve_frontend_serving_target(tmp_path)

    assert target["source"] == fb.SERVING_SOURCE_LEGACY_DIST
    assert Path(target["dist"]) == legacy


def test_nothing_published_reports_missing_instead_of_a_fake_legacy_tree(tmp_path: Path) -> None:
    target = fb.resolve_frontend_serving_target(tmp_path)

    assert target["source"] == fb.SERVING_SOURCE_MISSING
    assert target["fallbackReason"] == "active_release_missing"


def test_status_merges_build_identity_with_the_served_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release = _write_release(tmp_path, "release-ccc", "key-c")
    _write_pointer(tmp_path, "release-ccc", "key-c", published_at=2000.0)
    monkeypatch.setattr(
        fb,
        "inspect_frontend_build",
        lambda root, **kwargs: {
            "current": True,
            "reason": "frontend build is current",
            "buildKey": "key-c",
            "dist": str(release),
        },
    )

    status = fb.frontend_build_status(tmp_path)

    assert status["current"] is True
    assert status["reason"] == "frontend build is current"
    assert status["source"] == fb.SERVING_SOURCE_RELEASE
    assert status["release"] == "release-ccc"
    assert status["buildKey"] == "key-c"
    assert status["servedBuildKey"] == "key-c"
    assert status["legacyDistUsed"] is False
    assert status["publishedAtISO"]


def test_status_marks_the_legacy_tree_when_it_is_what_gets_served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = _write_legacy(tmp_path)
    monkeypatch.setattr(
        fb,
        "inspect_frontend_build",
        lambda root, **kwargs: {
            "current": False,
            "reason": "frontend build key differs from active release",
            "buildKey": "key-d",
        },
    )

    status = fb.frontend_build_status(tmp_path)

    assert status["current"] is False
    assert status["source"] == fb.SERVING_SOURCE_LEGACY_DIST
    assert status["legacyDistUsed"] is True
    assert status["legacyDist"] == str(legacy)
    assert status["fallbackReason"] == "active_release_missing"


def test_cli_prints_json_and_exit_code_follows_freshness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_release(tmp_path, "release-ddd", "key-e")
    _write_pointer(tmp_path, "release-ddd", "key-e")
    monkeypatch.setattr(
        fb,
        "inspect_frontend_build",
        lambda root, **kwargs: {
            "current": False,
            "reason": "frontend build key differs from active release",
            "buildKey": "key-other",
        },
    )

    code = fb.main(["status", "--project-root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["current"] is False
    assert payload["source"] == fb.SERVING_SOURCE_RELEASE
    assert payload["release"] == "release-ddd"
