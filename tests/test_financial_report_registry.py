"""Focused tests of real wrapper/catalog/policy functions without app startup.

The AST loader executes the current production function definitions; it does not
replace them with a second implementation. Full runtime tests remain separate.
"""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.tools import tool

from core.authorization.tool_policy_evaluator import (
    evaluate_tool_policy,
    normalize_legacy_tool_policy,
)
from core.authorization.tool_policy_models import TurnToolGrant
from core.web.services import tool_catalog
from tools import financial_report_tools as finance

ROOT = Path(__file__).resolve().parents[1]
NAME = "financial_report_query_tool"


def definition(path, name, namespace):
    source = ast.parse((ROOT / path).read_text(encoding="utf-8-sig"))
    node = next(
        node
        for node in ast.walk(source)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    exec(  # noqa: S102 - executes only a named local production definition
        compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / path), "exec"),
        namespace,
    )
    return namespace[name]


def registered_tool():
    return definition(
        "tools/Key_Tools.py",
        NAME,
        {
            "tool": tool,
            "_financial_report_query_impl": finance.financial_report_query_tool,
        },
    )


def test_canonical_wrapper_schema_and_dispatch(monkeypatch):
    for name in finance.REQUIRED_CONFIG:
        monkeypatch.delenv(name, raising=False)
    wrapper = registered_tool()
    assert wrapper.name == NAME
    schema = wrapper.args_schema.model_json_schema()
    assert set(schema["required"]) == {"question", "ticker", "report_period"}
    assert "not_configured" in wrapper.invoke(
        {"question": "测试", "ticker": "600519", "report_period": "2025FY"}
    )
    root = ast.parse((ROOT / "tools/Key_Tools.py").read_text(encoding="utf-8-sig"))
    builder = next(
        n
        for n in root.body
        if isinstance(n, ast.FunctionDef) and n.name == "_build_key_tools"
    )
    final_return = builder.body[-1]
    assert isinstance(final_return, ast.Return)
    assert (
        sum(isinstance(n, ast.Name) and n.id == NAME for n in final_return.value.elts)
        == 1
    )
    assert any(
        isinstance(n, ast.ImportFrom)
        and n.module == "tools.financial_report_tools"
        and any(a.asname == "_financial_report_query_impl" for a in n.names)
        for n in root.body
    )


def test_catalog_describes_network_cost_and_explicit_assignment():
    descriptor = tool_catalog.build_tool_descriptor(
        NAME, args_schema=registered_tool().args_schema.model_json_schema()
    )
    assert descriptor.risk == "network" and descriptor.approval == "on_request"
    assert descriptor.scopes == ("network",)
    assert NAME in tool_catalog.explicit_allow_tool_names()
    assert "model_cost" in tool_catalog.risk_tags_for_tool(NAME)
    bundle = next(
        b
        for b in tool_catalog.list_tool_bundles()
        if b["bundleId"] == "financial_reports"
    )
    assert NAME in bundle["toolNames"]
    assert "financial_market_screen_tool" in bundle["toolNames"]
    assert bundle["explicitAllowToolCount"] == 6


@pytest.mark.parametrize(
    "assigned,network,turn_network,denied,capabilities,approval,expected",
    [
        (
            False,
            "restricted",
            None,
            (),
            ("financial_reports",),
            "on_request",
            "not_assigned",
        ),
        (
            True,
            "none",
            None,
            (),
            ("financial_reports",),
            "on_request",
            "network_denied",
        ),
        (
            True,
            "restricted",
            "none",
            (),
            ("financial_reports",),
            "on_request",
            "network_denied",
        ),
        (
            True,
            "restricted",
            None,
            (NAME,),
            ("financial_reports",),
            "on_request",
            "turn_denied",
        ),
        (
            True,
            "restricted",
            None,
            (),
            ("workspace",),
            "on_request",
            "capability_mismatch",
        ),
        (
            True,
            "restricted",
            None,
            (),
            ("financial_reports",),
            "never",
            "approval_required",
        ),
        (True, "restricted", None, (), ("financial_reports",), "on_request", None),
    ],
)
def test_existing_deny_first_policy_controls_finance(
    assigned, network, turn_network, denied, capabilities, approval, expected
):
    descriptor = tool_catalog.build_tool_descriptor(
        NAME, args_schema=registered_tool().args_schema.model_json_schema()
    )
    policy = normalize_legacy_tool_policy(
        {
            "allowedTools": [NAME] if assigned else [],
            "networkAccess": network,
            "mutationAccess": "none",
        },
        registered_tool_names=[NAME],
        policy_id="test-finance",
    )
    grant = TurnToolGrant(
        turn_id="test-turn",
        source="session",
        allowed_capabilities=capabilities,
        denied_tools=denied,
        approval_mode=approval,
        network_access=turn_network,
    )
    result = evaluate_tool_policy(
        agent_id="test-agent",
        policy=policy,
        grant=grant,
        descriptors=[descriptor],
        registry_version=1,
        registry_fingerprint="test-fingerprint",
    )
    if expected:
        assert NAME not in result.executable_tools
        assert dict(result.denied)[NAME].code.value == expected
    else:
        assert result.executable_tools == (NAME,)


def registry_items(monkeypatch):
    wrapper = registered_tool()
    monkeypatch.setitem(
        sys.modules,
        "tools.Key_Tools",
        SimpleNamespace(
            create_key_tools=lambda: [wrapper],
            create_llm_facing_tools=lambda: [wrapper],
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "tools.web_search_tool",
        SimpleNamespace(autoglm_search_tool_availability=dict),
    )
    namespace = {
        "Any": object,
        "metadata_for_tool": tool_catalog.metadata_for_tool,
        "bundle_ids_for_tool": tool_catalog.bundle_ids_for_tool,
        "_description_for_tool": lambda t: t.description,
        "_args_schema_for_tool": lambda t: t.args_schema.model_json_schema(),
        "_builtin_test_policy": lambda _: {},
        "_permission_policy_for_tool": lambda _: {},
    }
    return definition(
        "core/web/services/tool_registry_service.py", "_builtin_tool_items", namespace
    )()


def test_registry_reports_unconfigured_without_secrets_or_network(monkeypatch):
    for name in finance.REQUIRED_CONFIG:
        monkeypatch.delenv(name, raising=False)
    items = registry_items(monkeypatch)
    assert len(items) == 1
    assert items[0]["llmVisible"] is False
    assert items[0]["dependencyStatus"]["status"] == "not_configured"
    assert items[0]["dependencyStatus"]["connectivityVerified"] is False


def test_registry_configured_is_not_live_connectivity_claim(monkeypatch):
    monkeypatch.setenv(finance.PREFIX + "BASE_URL", "https://finance.example.test")
    monkeypatch.setenv(finance.PREFIX + "CHAT_ID", "finance-chat")
    monkeypatch.setenv(finance.PREFIX + "API_KEY", "test-only-secret")
    item = registry_items(monkeypatch)[0]
    assert (
        item["llmVisible"] is True
        and item["dependencyStatus"]["status"] == "configured"
    )
    assert item["dependencyStatus"]["connectivityVerified"] is False
    assert "test-only-secret" not in str(item)


def test_registry_descriptor_carries_safe_dependency_token(monkeypatch):
    for name in finance.REQUIRED_CONFIG:
        monkeypatch.delenv(name, raising=False)
    items = registry_items(monkeypatch)
    namespace = {
        "Any": object,
        "ToolDescriptor": tool_catalog.ToolDescriptor,
        "ToolDescriptorError": tool_catalog.ToolDescriptorError,
        "ToolRegistryError": ValueError,
        "build_tool_descriptor": tool_catalog.build_tool_descriptor,
        "validate_tool_descriptors": tool_catalog.validate_tool_descriptors,
    }
    descriptors = definition(
        "core/web/services/tool_registry_service.py",
        "_canonical_registry_descriptors",
        namespace,
    )(items)
    assert descriptors[0].availability.required_config == ("financial_report_service",)
    assert items[0]["dependencyStatus"]["requiredConfig"] == list(
        finance.REQUIRED_CONFIG
    )


def test_executor_timeout_covers_finance_socket_budget():
    tree = ast.parse(
        (ROOT / "core/infrastructure/tool_executor.py").read_text(encoding="utf-8-sig")
    )
    timeout_map = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Attribute) and target.attr == "_timeout_map"
            for target in node.targets
        )
    )
    finance_timeout = next(
        ast.literal_eval(value)
        for key, value in zip(timeout_map.keys, timeout_map.values, strict=True)
        if isinstance(key, ast.Constant) and key.value == NAME
    )
    assert finance_timeout > 2 * finance.MAX_SOCKET_TIMEOUT_SECONDS


def test_actual_executor_registration_dispatches_finance_wrapper(monkeypatch):
    for name in finance.REQUIRED_CONFIG:
        monkeypatch.delenv(name, raising=False)
    wrapper = registered_tool()
    monkeypatch.setitem(
        sys.modules,
        "tools.Key_Tools",
        SimpleNamespace(create_key_tools=lambda: [wrapper]),
    )
    monkeypatch.setitem(
        sys.modules, "tools.agent_tools", SimpleNamespace(spawn_agent=lambda: None)
    )
    executor = SimpleNamespace(_tool_map={})
    namespace = {"IMAGE2_TOOL_TIMEOUT_SECONDS": 300}
    definition(
        "core/infrastructure/tool_executor.py", "_register_default_tools", namespace
    )(executor)
    assert NAME in executor._tool_map
    assert "not_configured" in executor._tool_map[NAME](
        question="测试", ticker="600519", report_period="2025FY"
    )
    resolve_timeout = definition(
        "core/infrastructure/tool_executor.py", "_resolve_timeout", {}
    )
    assert resolve_timeout(executor, NAME, {}) == 300
    assert NAME not in executor._retryable_tools


def test_unconfigured_finance_is_not_executable_when_registry_marks_unavailable():
    descriptor = tool_catalog.build_tool_descriptor(
        NAME, args_schema=registered_tool().args_schema.model_json_schema()
    )
    policy = normalize_legacy_tool_policy(
        {"allowedTools": [NAME], "networkAccess": "restricted"},
        registered_tool_names=[NAME],
        policy_id="test-finance",
    )
    grant = TurnToolGrant(
        turn_id="test-turn",
        source="session",
        allowed_capabilities=("financial_reports",),
        denied_tools=(),
        approval_mode="on_request",
    )
    result = evaluate_tool_policy(
        agent_id="test-agent",
        policy=policy,
        grant=grant,
        descriptors=[descriptor],
        registry_version=1,
        registry_fingerprint="test-fingerprint",
        available_tool_names=[],
    )
    assert NAME not in result.executable_tools
    assert dict(result.denied)[NAME].code.value == "environment_unavailable"
