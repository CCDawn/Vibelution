import json
from pathlib import Path

import core
from core.launcher.app import create_launcher_app
from core.version import get_product_version
from core.web.app import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_product_version_comes_from_root_version_file():
    expected = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()

    assert expected
    assert get_product_version() == expected
    assert core.__version__ == expected


def test_frontend_package_metadata_matches_product_version():
    expected = get_product_version()
    package_json = json.loads((PROJECT_ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads((PROJECT_ROOT / "web" / "package-lock.json").read_text(encoding="utf-8"))

    assert package_json["version"] == expected
    assert package_lock["version"] == expected
    assert package_lock["packages"][""]["version"] == expected


def test_fastapi_apps_use_product_version_metadata():
    expected = get_product_version()

    assert create_app().version == expected
    assert create_launcher_app().version == expected
