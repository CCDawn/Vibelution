"""Research route imports must not initialize storage-backed domain services."""

import ast
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest

from core.web.services import research_service


def test_research_facade_import_does_not_construct_domain_service():
    # Execute the actual module body with dependencies already loaded so the
    # constructor sentinel observes this facade alone, without reloading shared
    # production modules or touching the operator's workspace.
    source_path = Path(research_service.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    tree.body = [
        node for node in tree.body
        if not isinstance(node, (ast.Import, ast.ImportFrom))
        or isinstance(node, ast.ImportFrom) and node.module == "__future__"
    ]
    constructor = Mock(side_effect=AssertionError("import constructed research storage"))
    namespace = dict(vars(research_service), ResearchThemeDiscoveryService=constructor)
    exec(compile(tree, str(source_path), "exec"), namespace)
    constructor.assert_not_called()
    assert namespace["_SERVICE"] is None


def test_first_research_request_initializes_once_and_reuses_service(monkeypatch):
    service = Mock()
    service.list_sessions.return_value = {"sessions": []}
    constructor = Mock(return_value=service)
    monkeypatch.setattr(research_service, "_SERVICE", None)
    monkeypatch.setattr(research_service, "ResearchThemeDiscoveryService", constructor)

    assert research_service.list_theme_discovery_sessions() == {"sessions": []}
    assert research_service.get_theme_discovery_session("session-1") is service.get_session.return_value
    constructor.assert_called_once_with()
    service.get_session.assert_called_once_with("session-1")


def test_concurrent_first_requests_share_one_complete_instance(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    service = object()

    def build():
        entered.set()
        assert release.wait(timeout=5)
        return service

    constructor = Mock(side_effect=build)
    monkeypatch.setattr(research_service, "_SERVICE", None)
    monkeypatch.setattr(research_service, "ResearchThemeDiscoveryService", constructor)
    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(research_service._get_research_service)
        assert entered.wait(timeout=5)
        others = [pool.submit(research_service._get_research_service) for _ in range(3)]
        release.set()
        assert all(future.result(timeout=5) is service for future in [first, *others])
    constructor.assert_called_once_with()


def test_failed_initialization_can_retry_without_publishing_partial_service(monkeypatch):
    service = object()
    constructor = Mock(side_effect=[OSError("storage unavailable"), service])
    monkeypatch.setattr(research_service, "_SERVICE", None)
    monkeypatch.setattr(research_service, "ResearchThemeDiscoveryService", constructor)

    with pytest.raises(OSError, match="storage unavailable"):
        research_service._get_research_service()
    assert research_service._SERVICE is None
    assert research_service._get_research_service() is service
    assert constructor.call_count == 2


def test_existing_injected_service_remains_authoritative(monkeypatch):
    service = Mock()
    constructor = Mock(side_effect=AssertionError("replaced injected service"))
    monkeypatch.setattr(research_service, "_SERVICE", service)
    monkeypatch.setattr(research_service, "ResearchThemeDiscoveryService", constructor)

    assert research_service._get_research_service() is service
    constructor.assert_not_called()
