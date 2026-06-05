"""XML fallback tool-call parsing regression tests."""

from core.infrastructure.llm_utils import parse_xml_tool_calls


def test_parse_xml_tool_calls_handles_tool_call_function_json_blocks():
    content = """
    <state>专注</state>
    <tool_call>
    <function>{"name": "open_evolution_transaction_tool", "arguments": {"summary": "probe"}}</function>
    </tool_call>
    然后检查。
    <tool_call>
    <function>{"name": "close_evolution_transaction_tool", "arguments": {"status": "success"}}</function>
    </tool_call>
    """

    tool_calls = parse_xml_tool_calls(content)

    assert tool_calls == [
        {
            "name": "open_evolution_transaction_tool",
            "args": {"summary": "probe"},
            "id": "xml_0",
        },
        {
            "name": "close_evolution_transaction_tool",
            "args": {"status": "success"},
            "id": "xml_1",
        },
    ]
