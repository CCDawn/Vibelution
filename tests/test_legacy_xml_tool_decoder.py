from core.llm.legacy_xml_tool_decoder import decode_legacy_xml_tool_calls
from core.llm.semantic_messages import InvocationScope


def _scope():
    return InvocationScope(
        session_id="session-xml",
        turn_id="turn-xml",
        invocation_id="invocation-xml",
        iteration=0,
    )


def test_invoke_xml_decodes_to_canonical_tool_call_without_control_markup():
    decoded = decode_legacy_xml_tool_calls(
        '先读取。<invoke name="read_memory_tool"><parameter name="query">moon</parameter></invoke>',
        scope=_scope(),
    )

    assert decoded.matched is True
    assert decoded.error == ""
    assert decoded.commentary == "先读取。"
    assert decoded.tool_calls[0].call_id == "xml_0"
    assert decoded.tool_calls[0].name == "read_memory_tool"
    assert decoded.tool_calls[0].arguments == {"query": "moon"}


def test_tool_call_xml_supports_hidden_and_close_tools_through_same_decoder():
    hidden = decode_legacy_xml_tool_calls(
        '<tool_call><function>{"name":"hidden_tool","arguments":{}}</function></tool_call>',
        scope=_scope(),
    )
    close = decode_legacy_xml_tool_calls(
        '<invoke name="close_evolution_transaction_tool"></invoke>',
        scope=_scope(),
    )

    assert hidden.tool_calls[0].call_id == "xml_0"
    assert hidden.tool_calls[0].name == "hidden_tool"
    assert close.tool_calls[0].call_id == "xml_0"
    assert close.tool_calls[0].name == "close_evolution_transaction_tool"


def test_recognized_malformed_xml_fails_closed_with_bounded_error():
    decoded = decode_legacy_xml_tool_calls('<invoke name="read_memory_tool">', scope=_scope())

    assert decoded.matched is True
    assert decoded.tool_calls == ()
    assert decoded.error == "tool_call_decode_error"


def test_plain_text_is_not_claimed_by_legacy_decoder():
    decoded = decode_legacy_xml_tool_calls("plain answer", scope=_scope())

    assert decoded.matched is False
    assert decoded.commentary == "plain answer"
    assert decoded.tool_calls == ()
