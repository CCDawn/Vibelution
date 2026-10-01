"""Offline transport/schema tests. These never prove live retrieval/model quality."""

import copy
import json
from http.client import IncompleteRead
from io import BytesIO
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

from tools import financial_report_tools as finance

QUESTION = "贵州茅台2025年年度报告营业收入是多少？"
SCOPE = {"ticker": "600519", "report_period": "2025FY"}


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    for name in (*finance.REQUIRED_CONFIG, finance.PREFIX + "TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    # A forgotten test stub must fail rather than access a configured account.
    monkeypatch.setattr(
        finance, "build_opener", Mock(side_effect=AssertionError("unexpected network"))
    )


@pytest.fixture
def configured(monkeypatch):
    for suffix, value in {
        "BASE_URL": "https://finance.example.test",
        "API_KEY": "test-only-key",
        "CHAT_ID": "finance-chat",
        "TIMEOUT_SECONDS": "12",
    }.items():
        monkeypatch.setenv(finance.PREFIX + suffix, value)


def completion():
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "status": "answer",
                            "value": "123.45",
                            "unit": "CNY",
                            "explanation": "营业收入为123.45元。[ID:0]",
                            "formula": "",
                            "evidence": [{"source_id": "issuer-2025", "page": 7}],
                        }
                    ),
                    "reference": [
                        {
                            "document_metadata": {
                                **SCOPE,
                                "source_id": "issuer-2025",
                                "source_url": "https://issuer.example.test/report.pdf",
                                "input_track": "full_original_pdf",
                            },
                            "positions": [[7, 0, 100, 0, 100]],
                        }
                    ],
                }
            }
        ]
    }


def mock_http(monkeypatch, payload=None, *, body=None, error=None):
    opener = Mock()
    if error:
        opener.open.side_effect = error
    else:
        opener.open.return_value = BytesIO(
            body if body is not None else json.dumps(payload or completion()).encode()
        )
    monkeypatch.setattr(finance, "build_opener", Mock(return_value=opener))
    return opener


def ask(**overrides):
    return json.loads(
        finance.financial_report_query_tool(
            **{"question": QUESTION, **SCOPE, **overrides}
        )
    )


def change_answer(payload, **changes):
    msg = payload["choices"][0]["message"]
    answer = json.loads(msg["content"])
    answer.update(changes)
    msg["content"] = json.dumps(answer)


def test_missing_configuration_does_not_access_network():
    result = ask()
    assert result["status"] == "not_configured"
    assert result["answer"] is None and result["citations"] == []
    finance.build_opener.assert_not_called()
    availability = finance.financial_report_availability()
    assert availability["available"] is False
    assert availability["connectivityVerified"] is False


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.example",
        "file:///tmp/data",
        "https://user:pass@example.test",
        "https://example.test/api",
        "https://example.test?a=1",
        "https://example.test/#x",
        "https://example.test:bad",
        "https://example.test:0",
        "https://exam ple.test",
        "https://example.test\x01",
        "https://exämple.test",
    ],
)
def test_invalid_origin_fails_before_network(configured, monkeypatch, url):
    monkeypatch.setenv(finance.PREFIX + "BASE_URL", url)
    assert ask()["status"] == "invalid_config"
    finance.build_opener.assert_not_called()


@pytest.mark.parametrize(
    "suffix,value",
    [
        ("TIMEOUT_SECONDS", "nan"),
        ("TIMEOUT_SECONDS", "inf"),
        ("TIMEOUT_SECONDS", "0"),
        ("TIMEOUT_SECONDS", "121"),
        ("TIMEOUT_SECONDS", "garbage"),
        ("CHAT_ID", "../secret"),
        ("API_KEY", "key\r\nInjected: true"),
    ],
)
def test_invalid_config_is_redacted(configured, monkeypatch, suffix, value):
    monkeypatch.setenv(finance.PREFIX + suffix, value)
    result = ask()
    assert result["status"] == "invalid_config"
    assert "test-only-key" not in json.dumps(result)
    assert value not in result["message"]
    finance.build_opener.assert_not_called()


@pytest.mark.parametrize(
    "origin", ["http://localhost:9380", "http://127.0.0.1:9380/", "http://[::1]:9380"]
)
def test_loopback_development_origin_allowed(configured, monkeypatch, origin):
    monkeypatch.setenv(finance.PREFIX + "BASE_URL", origin)
    assert finance.financial_report_availability()["available"] is True
    assert finance.financial_report_availability()["connectivityVerified"] is False


@pytest.mark.parametrize(
    "override",
    [
        {"question": ""},
        {"question": "q" * 2001},
        {"question": None},
        {"ticker": ""},
        {"ticker": "600519,000001"},
        {"ticker": None},
        {"report_period": "2025"},
        {"report_period": "2025Q5"},
        {"report_period": None},
    ],
)
def test_explicit_scope_is_required(configured, override):
    assert ask(**override)["status"] == "invalid_request"
    finance.build_opener.assert_not_called()


def test_real_http_request_shape_and_bounded_answer(configured, monkeypatch):
    opener = mock_http(monkeypatch)
    result = ask()
    assert result["ok"] is True and result["status"] == "answer"
    assert result["answer"]["value"] == "123.45"
    assert result["citations"][0]["page"] == 7
    assert result["citations"][0]["source_id"] == "issuer-2025"
    assert result["citations"][0]["reference_indexes"] == [0]
    assert "document_metadata" not in json.dumps(result)
    request = opener.open.call_args.args[0]
    assert (
        request.full_url
        == "https://finance.example.test/api/v1/openai/finance-chat/chat/completions"
    )
    assert request.get_header("Authorization") == "Bearer test-only-key"
    assert opener.open.call_args.kwargs["timeout"] == 12
    body = json.loads(request.data)
    assert body["model"] == "model" and body["stream"] is False
    assert body["messages"] == [{"role": "user", "content": QUESTION}]
    assert body["extra_body"]["metadata_condition"] == {
        "logic": "and",
        "conditions": [
            {"name": "ticker", "comparison_operator": "=", "value": "600519"},
            {"name": "report_period", "comparison_operator": "=", "value": "2025FY"},
        ],
    }
    assert body["extra_body"]["reference"] is True
    assert "input_track" in body["extra_body"]["reference_metadata"]["fields"]
    opener.open.assert_called_once()


@pytest.mark.parametrize(
    "error,status",
    [
        (TimeoutError(), "timeout"),
        (URLError(TimeoutError()), "timeout"),
        (URLError("test-only-key"), "unavailable"),
        (OSError("private"), "unavailable"),
        (IncompleteRead(b"private"), "unavailable"),
    ],
)
def test_transport_errors_do_not_leak_or_retry(configured, monkeypatch, error, status):
    opener = mock_http(monkeypatch, error=error)
    result = ask()
    assert result["status"] == status and result["ok"] is False
    assert "test-only-key" not in json.dumps(result) and "private" not in json.dumps(
        result
    )
    assert result["timedOut"] is (status == "timeout")
    opener.open.assert_called_once()


@pytest.mark.parametrize(
    "code,status",
    [
        (401, "authentication_failed"),
        (403, "authentication_failed"),
        (404, "upstream_error"),
        (429, "unavailable"),
        (503, "unavailable"),
    ],
)
def test_http_errors_do_not_expose_body(configured, monkeypatch, code, status):
    mock_http(
        monkeypatch,
        error=HTTPError(
            "https://private.invalid", code, "secret", {}, BytesIO(b"key:secret")
        ),
    )
    result = ask()
    assert result["status"] == status
    assert "secret" not in json.dumps(result) and "private.invalid" not in json.dumps(
        result
    )


def test_redirect_is_refused_without_forwarding():
    with pytest.raises(finance.FinanceError) as error:
        finance._NoRedirect().redirect_request(
            None, None, 307, "", {}, "https://attacker.test"
        )
    assert error.value.status == "upstream_error"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"<html>failed</html>", id="html"),
        pytest.param(b"[]", id="array"),
        pytest.param(b"null", id="null"),
        pytest.param(b"\xff", id="binary"),
        pytest.param(b"x" * (finance.MAX_RESPONSE_BYTES + 1), id="oversized"),
    ],
)
def test_invalid_and_oversized_responses(configured, monkeypatch, body):
    mock_http(monkeypatch, body=body)
    assert ask()["status"] == "invalid_response"


@pytest.mark.parametrize(
    "payload", [{"code": 102, "message": "private"}, {"error": {"message": "private"}}]
)
def test_application_error(configured, monkeypatch, payload):
    mock_http(monkeypatch, payload=payload)
    assert ask()["status"] == "upstream_error"


@pytest.mark.parametrize(
    "answer",
    [
        {"value": "NaN"},
        {"value": "Infinity"},
        {"value": 123},
        {"unit": "USD"},
        {"unit": []},
        {"formula": []},
        {"explanation": None},
        {"status": "other"},
    ],
)
def test_malformed_structured_answers_fail_closed(configured, monkeypatch, answer):
    payload = completion()
    change_answer(payload, **answer)
    mock_http(monkeypatch, payload)
    assert ask()["status"] == "invalid_response"


@pytest.mark.parametrize(
    "malformation",
    [
        "missing_marker",
        "outside_index",
        "missing_refs",
        "wrong_ticker",
        "wrong_period",
        "missing_meta",
        "wrong_track",
        "missing_page",
        "zero_page",
        "bool_page",
        "fabricated_evidence_page",
        "fabricated_source",
        "uncited_evidence",
        "empty_evidence",
    ],
)
def test_unverifiable_citations_withhold_numeric_answer(
    configured, monkeypatch, malformation
):
    payload = completion()
    msg = payload["choices"][0]["message"]
    ref = msg["reference"][0]
    if malformation == "missing_marker":
        change_answer(payload, explanation="123.45元")
    elif malformation == "outside_index":
        change_answer(payload, explanation="123.45元[ID:99]")
    elif malformation == "missing_refs":
        msg.pop("reference")
    elif malformation == "wrong_ticker":
        ref["document_metadata"]["ticker"] = "000001"
    elif malformation == "wrong_period":
        ref["document_metadata"]["report_period"] = "2024FY"
    elif malformation == "missing_meta":
        ref.pop("document_metadata")
    elif malformation == "wrong_track":
        ref["document_metadata"]["input_track"] = "fixture"
    elif malformation == "missing_page":
        ref.pop("positions")
    elif malformation == "zero_page":
        ref["positions"] = [[0]]
    elif malformation == "bool_page":
        ref["positions"] = [[True]]
    elif malformation == "fabricated_evidence_page":
        change_answer(payload, evidence=[{"source_id": "issuer-2025", "page": 99}])
    elif malformation == "fabricated_source":
        change_answer(payload, evidence=[{"source_id": "fabricated", "page": 7}])
    elif malformation == "uncited_evidence":
        extra = copy.deepcopy(ref)
        extra["positions"] = [[8]]
        msg["reference"].append(extra)
        change_answer(payload, evidence=[{"source_id": "issuer-2025", "page": 8}])
    elif malformation == "empty_evidence":
        change_answer(payload, evidence=[])
    mock_http(monkeypatch, payload)
    result = ask()
    assert result["status"] == "insufficient_evidence"
    assert result["answer"] is None and result["citations"] == []


def test_uncited_out_of_scope_reference_rejected(configured, monkeypatch):
    payload = completion()
    refs = payload["choices"][0]["message"]["reference"]
    refs.append(copy.deepcopy(refs[0]))
    refs[1]["document_metadata"]["ticker"] = "other"
    mock_http(monkeypatch, payload)
    assert ask()["status"] == "insufficient_evidence"


def test_multiple_markers_on_same_page_and_spanning_pages(configured, monkeypatch):
    payload = completion()
    refs = payload["choices"][0]["message"]["reference"]
    refs.append(copy.deepcopy(refs[0]))
    refs[0]["positions"].append([8])
    change_answer(
        payload,
        explanation="两个段落[ID:0][1]",
        evidence=[{"source_id": "issuer-2025", "page": 7}],
    )
    mock_http(monkeypatch, payload)
    result = ask()
    assert result["status"] == "answer"
    assert len(result["citations"]) == 1 and result["citations"][0][
        "reference_indexes"
    ] == [0, 1]


def test_upstream_refusal_is_distinct_from_unavailable(configured, monkeypatch):
    payload = completion()
    change_answer(payload, status="insufficient_evidence", value=None, evidence=[])
    mock_http(monkeypatch, payload)
    assert ask()["status"] == "insufficient_evidence"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,script",
        "https://secret@example.test/doc",
        "https://example.test/\nsecret",
    ],
)
def test_unsafe_source_links_are_not_returned(configured, monkeypatch, url):
    payload = completion()
    payload["choices"][0]["message"]["reference"][0]["document_metadata"][
        "source_url"
    ] = url
    mock_http(monkeypatch, payload)
    result = ask()
    assert result["status"] == "answer" and result["citations"][0]["source_url"] is None
    assert url not in json.dumps(result)


def test_config_repr_does_not_contain_api_key(configured):
    assert "test-only-key" not in repr(finance._load_config())


def test_deep_json_is_a_safe_invalid_response(configured, monkeypatch):
    mock_http(monkeypatch, body=b"[" * 2000 + b"0" + b"]" * 2000)
    assert ask()["status"] == "invalid_response"


def test_surrogate_question_rejected_before_network(configured):
    assert ask(question="bad\ud800")["status"] == "invalid_request"
    finance.build_opener.assert_not_called()


def test_loopback_http_roundtrip_uses_the_real_transport(configured, monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.request import build_opener

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(
                (
                    self.path,
                    self.headers.get("Authorization"),
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
            )
            data = json.dumps(completion()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            monkeypatch.setenv(
                finance.PREFIX + "BASE_URL", f"http://127.0.0.1:{server.server_port}"
            )
            monkeypatch.setattr(finance, "build_opener", build_opener)
            result = ask()
        finally:
            server.shutdown()
            worker.join(timeout=3)
    assert result["status"] == "answer"
    assert result["citations"][0]["page"] == 7
    assert len(received) == 1
    assert received[0][0] == "/api/v1/openai/finance-chat/chat/completions"
    assert received[0][1] == "Bearer test-only-key"
    assert received[0][2]["extra_body"]["metadata_condition"]["logic"] == "and"


def test_loopback_redirect_never_reaches_second_endpoint(configured, monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.request import build_opener

    reached = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            reached.append(self.path)
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(307)
            self.send_header(
                "Location", f"http://127.0.0.1:{self.server.server_port}/stolen"
            )
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            monkeypatch.setenv(
                finance.PREFIX + "BASE_URL", f"http://127.0.0.1:{server.server_port}"
            )
            monkeypatch.setattr(finance, "build_opener", build_opener)
            result = ask()
        finally:
            server.shutdown()
            worker.join(timeout=3)
    assert result["status"] == "upstream_error"
    assert reached == ["/api/v1/openai/finance-chat/chat/completions"]


@pytest.mark.parametrize("field", ["explanation", "formula", "source_url"])
def test_invalid_unicode_from_upstream_is_not_returned(configured, monkeypatch, field):
    payload = completion()
    if field == "source_url":
        payload["choices"][0]["message"]["reference"][0]["document_metadata"][field] = (
            "https://issuer.example.test/\ud800.pdf"
        )
    else:
        change_answer(payload, **{field: "bad\ud800[ID:0]"})
    mock_http(monkeypatch, payload)
    result = ask()
    assert result["status"] == "invalid_response"
    json.dumps(result, ensure_ascii=False).encode("utf-8")


def test_response_reading_has_a_total_deadline(configured, monkeypatch):
    mock_http(monkeypatch)
    clock = iter([0, 0, 13])
    monkeypatch.setattr(finance.time, "monotonic", lambda: next(clock))
    assert ask()["status"] == "timeout"


def test_financial_answer_exceeding_native_result_budget_fails_without_partial_citations(
    configured, monkeypatch
):
    payload = completion()
    change_answer(payload, explanation="收入" * 1400 + "[ID:0]")
    mock_http(monkeypatch, payload)
    result = ask()
    assert result["status"] == "invalid_response"
    assert result["answer"] is None and result["citations"] == []
