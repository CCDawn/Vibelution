from __future__ import annotations

import json

import pytest

from core.web.services.personal_assistant_platform_api import api, catalog


def _spec(paths: dict, schemas: dict | None = None) -> dict:
    return {
        "openapi": "3.1.0",
        "paths": paths,
        "components": {"schemas": schemas or {}},
    }


def _operation(operation_id: str, *, summary: str = "", tags: list[str] | None = None) -> dict:
    return {"operationId": operation_id, "summary": summary, "tags": tags or []}


def _patch_spec(monkeypatch, spec: dict) -> None:
    monkeypatch.setattr(catalog, "get_spec", lambda: spec)


def _encoded(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def test_catalog_lists_standard_methods_and_excludes_non_api_and_nonstandard_methods(monkeypatch):
    spec = _spec(
        {
            "/api/agents": {
                "get": _operation("list_agents", summary="List agents", tags=["agents"]),
                "post": _operation("create_agent", tags=["agents"]),
                "delete": _operation("delete_agents", tags=["agents"]),
                "head": _operation("head_agents", tags=["agents"]),
            },
            "/api2/agents": {"get": _operation("not_api", tags=["agents"])},
            "/health": {"get": _operation("health", tags=["runtime"])},
        }
    )
    _patch_spec(monkeypatch, spec)

    result = catalog.api_catalog(limit=50)

    assert result["ok"] is True
    assert result["source"] == "registered-openapi"
    assert result["untrustedContent"] is True
    assert [item["operationId"] for item in result["operations"]] == [
        "list_agents",
        "create_agent",
        "delete_agents",
    ]
    assert {item["method"] for item in result["operations"]} == {"GET", "POST", "DELETE"}


def test_catalog_search_tag_and_pagination_are_composed(monkeypatch):
    spec = _spec(
        {
            "/api/agents": {
                "get": _operation("list_agents", summary="List agents", tags=["agents"]),
                "post": _operation("create_agent", summary="Create an agent", tags=["agents"]),
            },
            "/api/runtime/tasks": {
                "get": _operation("list_tasks", summary="List runtime tasks", tags=["runtime"])
            },
        }
    )
    _patch_spec(monkeypatch, spec)

    first_page = catalog.api_catalog(limit=2)
    second_page = catalog.api_catalog(offset=2, limit=2)
    filtered = catalog.api_catalog(query="LIST", tag="AGENTS")

    assert first_page["total"] == 3
    assert first_page["truncated"] is True
    assert [item["operationId"] for item in first_page["operations"]] == ["list_agents", "create_agent"]
    assert second_page["total"] == 3
    assert second_page["truncated"] is False
    assert [item["operationId"] for item in second_page["operations"]] == ["list_tasks"]
    assert [item["operationId"] for item in filtered["operations"]] == ["list_agents"]


@pytest.mark.parametrize(
    ("offset", "limit"),
    [(-1, 20), (0, 0), (0, 51), (True, 20), (0, False)],
)
def test_catalog_rejects_invalid_page_bounds(monkeypatch, offset, limit):
    _patch_spec(monkeypatch, _spec({}))

    result = catalog.api_catalog(offset=offset, limit=limit)

    assert result["ok"] is False
    assert result["source"] == "registered-openapi"
    assert result["untrustedContent"] is True


def test_discovery_does_not_authorize_unmapped_get_or_write_operations(monkeypatch):
    spec = _spec(
        {
            "/api/logs": {"get": _operation("read_logs", tags=["logs"])},
            "/api/agents/{agent_id}": {
                "delete": _operation("delete_agent", tags=["agents"]),
                "post": _operation("custom_agent_post", tags=["agents"]),
            },
            "/api/runtime/restart": {"post": _operation("restart_runtime", tags=["runtime"])},
        }
    )
    _patch_spec(monkeypatch, spec)
    monkeypatch.setattr(
        api,
        "_filter_get_endpoints",
        lambda paths: {},  # no GET in this fixture passes the existing gateway filter
    )

    listed = catalog.api_catalog(limit=50)
    by_id = {item["operationId"]: item for item in listed["operations"]}

    assert by_id["read_logs"]["access"] == "operator_only"
    assert by_id["read_logs"]["executable"] is False
    assert by_id["read_logs"]["tool"] is None
    assert by_id["delete_agent"]["access"] == "native_action"
    assert by_id["delete_agent"]["action"] == "agent_archive"
    assert by_id["delete_agent"]["approval"]["tool"] == "personal_assistant_manage_tool"
    assert by_id["delete_agent"]["approval"]["required"] == "native management approval"
    assert by_id["restart_runtime"]["executable"] is False
    assert by_id["restart_runtime"]["approval"]["required"] == "native management approval"
    assert by_id["custom_agent_post"]["executable"] is False


def test_allowlisted_get_is_marked_as_read_gateway_with_template_path(monkeypatch):
    path = "/api/sessions/{session_id}/llm-options"
    spec = _spec({path: {"get": _operation("session_llm_options", tags=["sessions"])}})
    _patch_spec(monkeypatch, spec)
    monkeypatch.setattr(
        api,
        "_filter_get_endpoints",
        lambda paths: {path: {"summary": "LLM options", "tags": {"sessions"}}},
    )

    result = catalog.api_catalog()
    entry = result["operations"][0]

    assert entry["access"] == "read_gateway"
    assert entry["tool"] == "personal_assistant_platform_api_tool"
    assert entry["execution"]["path"] == path
    assert "actual ID" in entry["execution"]["note"]


def test_describe_returns_only_reachable_schemas_and_preserves_refs(monkeypatch):
    spec = _spec(
        {
            "/api/agents": {
                "post": {
                    **_operation("create_agent", summary="Create an agent", tags=["agents"]),
                    "parameters": [
                        {"name": "trace", "in": "query", "schema": {"$ref": "#/components/schemas/Trace"}}
                    ],
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/AgentInput"}}
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "created",
                            "content": {
                                "application/json": {"schema": {"$ref": "#/components/schemas/AgentOutput"}}
                            },
                        }
                    },
                }
            }
        },
        {
            "AgentInput": {"type": "object", "properties": {"profile": {"$ref": "#/components/schemas/Profile"}}},
            "Profile": {"type": "object", "properties": {"owner": {"$ref": "#/components/schemas/AgentInput"}}},
            "Trace": {"type": "string"},
            "AgentOutput": {"type": "object", "properties": {"id": {"type": "string"}}},
            "Unused": {"type": "object", "description": "not reachable from this operation"},
        },
    )
    _patch_spec(monkeypatch, spec)
    monkeypatch.setattr(api, "_filter_get_endpoints", lambda paths: {})

    result = catalog.api_describe("create_agent")

    assert result["ok"] is True
    assert result["source"] == "registered-openapi"
    assert result["untrustedContent"] is True
    assert result["parameters"][0]["schema"]["$ref"] == "#/components/schemas/Trace"
    assert result["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/AgentInput"
    assert set(result["components"]["schemas"]) == {"AgentInput", "Profile", "Trace", "AgentOutput"}
    assert result["components"]["schemas"]["AgentInput"]["properties"]["profile"]["$ref"] == "#/components/schemas/Profile"
    assert "Unused" not in result["components"]["schemas"]
    assert result["truncated"] is False


def test_describe_caps_component_count_and_character_size(monkeypatch):
    properties = {f"child{index}": {"$ref": f"#/components/schemas/Child{index}"} for index in range(40)}
    schemas = {"Root": {"type": "object", "properties": properties}}
    schemas.update({f"Child{index}": {"type": "string"} for index in range(40)})
    schemas["Large"] = {"type": "string", "description": "x" * 50_000}
    spec = _spec(
        {
            "/api/schema": {
                "get": {
                    **_operation("schema_operation", tags=["runtime"]),
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Root"}}}}
                    },
                    "parameters": [{"name": "extra", "in": "query", "schema": {"$ref": "#/components/schemas/Large"}}],
                }
            }
        },
        schemas,
    )
    _patch_spec(monkeypatch, spec)
    monkeypatch.setattr(api, "_filter_get_endpoints", lambda paths: {})

    result = catalog.api_describe("schema_operation")
    returned_schemas = result["components"]["schemas"]

    assert result["truncated"] is True
    assert result["omittedSchemas"]
    assert "Large" in result["omittedSchemas"]
    assert len(returned_schemas) <= catalog.MAX_SCHEMA_COMPONENTS
    assert len(_encoded(result)) <= catalog.MAX_DESCRIPTION_CHARS


def test_describe_rejects_unknown_and_duplicate_operation_ids(monkeypatch):
    spec = _spec(
        {
            "/api/one": {"get": _operation("duplicate")},
            "/api/two": {"post": _operation("duplicate")},
        }
    )
    _patch_spec(monkeypatch, spec)

    duplicate = catalog.api_describe("duplicate")
    unknown = catalog.api_describe("missing")

    assert duplicate["ok"] is False
    assert "duplicated" in duplicate["message"]
    assert unknown["ok"] is False
    assert "not present" in unknown["message"]


@pytest.mark.parametrize(
    ("method", "path", "operation_id", "action"),
    [
        ("post", "/api/agents", "agent_create_op", "agent_create"),
        ("patch", "/api/agents/{agent_id}", "agent_update_op", "agent_update"),
        ("patch", "/api/agents/{agent_id}/avatar", "agent_avatar_op", "agent_avatar"),
        ("put", "/api/config/language", "language_op", "settings_update"),
        (
            "post",
            "/api/config/draft/providers/{provider_id}/models",
            "model_add_op",
            "model_add",
        ),
    ],
)
def test_exact_native_action_mappings_are_bounded(monkeypatch, method, path, operation_id, action):
    spec = _spec({path: {method: _operation(operation_id, tags=["agents"])}})
    _patch_spec(monkeypatch, spec)

    entry = catalog.api_catalog()["operations"][0]

    assert entry["operationId"] == operation_id
    assert entry["access"] == "native_action"
    assert entry["tool"] == "personal_assistant_action_tool"
    assert entry["action"] == action
    assert entry["executable"] is True
    if action == "agent_create":
        assert any("fixed message-collaboration permission" in text for text in entry["constraints"])
    if action == "agent_update":
        assert entry["allowedFields"] == list(catalog._SAFE_AGENT_FIELDS)
        assert "roleKey" not in entry["allowedFields"]
    if action == "model_add":
        assert any("existing provider" in text for text in entry["constraints"])
        assert any("not arbitrary HTTP writing" in text for text in entry["constraints"])


def test_invalid_reference_is_reported_as_truncated(monkeypatch):
    spec = _spec(
        {
            "/api/example": {
                "get": {
                    **_operation("missing_schema_ref"),
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Missing"}}}}
                    },
                }
            }
        }
    )
    _patch_spec(monkeypatch, spec)

    result = catalog.api_describe("missing_schema_ref")

    assert result["truncated"] is True
    assert "Missing" in result["omittedSchemas"]


def test_internal_spec_and_entry_projector_skip_bootstrap_and_legacy_contracts(monkeypatch):
    spec = _spec({"/api/example": {"get": _operation("example")}})
    monkeypatch.setattr(catalog, "get_spec", lambda: pytest.fail("explicit spec must not bootstrap"))
    monkeypatch.setattr(catalog, "_allowlisted_read_paths", lambda _: pytest.fail("neutral projection needs no PA read gate"))
    monkeypatch.setattr(catalog, "_extended_action", lambda *_: pytest.fail("neutral projection needs no PA contracts"))

    def entry(method, path, operation):
        return {**catalog._catalog_identity_entry(method, path, operation), "access": "operator_only", "executable": False}

    assert catalog.api_catalog(spec=spec, entry_projector=entry)["operations"][0]["operationId"] == "example"
    assert catalog.api_describe("example", spec=spec, entry_projector=entry)["operation"]["executable"] is False
