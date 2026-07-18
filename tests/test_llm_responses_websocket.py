from __future__ import annotations

from types import SimpleNamespace

import openai

from core.llm.responses_websocket import ResponsesWebSocketBackend


class _FakeConnection:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self._events: list[SimpleNamespace] = []
        self.response = SimpleNamespace(create=self._create)

    def _create(
        self,
        *,
        model: str,
        input: list[dict],
        stream: bool,
        previous_response_id: str | None = None,
    ) -> None:
        payload = {"model": model, "input": input, "stream": stream}
        if previous_response_id is not None:
            payload["previous_response_id"] = previous_response_id
        self.sent.append(payload)
        response_id = f"resp-{len(self.sent)}"
        self._events.extend(
            [
                SimpleNamespace(type="response.created", response={"id": response_id}),
                SimpleNamespace(type="response.completed", response={"id": response_id}),
            ]
        )

    def recv(self):
        return self._events.pop(0)


class _FakeManager:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.closed = False

    def enter(self):
        return self.connection

    def __exit__(self, *_args) -> None:
        self.closed = True


class _RejectedConnection(_FakeConnection):
    def recv(self):
        error = RuntimeError("provider unavailable")
        error.code = 1013
        raise error


class _PreSendTypeErrorConnection(_FakeConnection):
    def _create(
        self,
        *,
        model: str,
        input: list[dict],
        stream: bool,
        previous_response_id: str | None = None,
    ) -> None:
        raise TypeError("unexpected keyword argument 'future_option'")


def _payload(*, previous_response_id: str = "") -> dict:
    payload = {
        "model": "openai/gpt-5.6-terra",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "full"}]}],
        "stream": True,
        "api_key": "secret",
        "base_url": "https://provider.example/v1/responses",
        "timeout": 30,
        "extra_headers": {"X-Provider": "test"},
        "_vibelution_responses_websocket": {"enabled": True},
    }
    if previous_response_id:
        payload["_vibelution_responses_websocket"].update(
            {
                "previous_response_id": previous_response_id,
                "input": [{"role": "user", "content": [{"type": "input_text", "text": "delta"}]}],
            }
        )
    return payload


def test_responses_websocket_reuses_connection_and_sends_incremental_payload(monkeypatch):
    connection = _FakeConnection()
    managers: list[_FakeManager] = []
    clients: list[dict] = []

    class _FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            clients.append(kwargs)
            self.responses = SimpleNamespace(connect=self._connect)

        def _connect(self, **_kwargs):
            manager = _FakeManager(connection)
            managers.append(manager)
            return manager

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    states: list[tuple[str, dict]] = []
    backend = ResponsesWebSocketBackend(
        lambda _payload: (),
        state_sink=lambda state, fields: states.append((state, fields)),
    )

    first_events = list(backend(_payload()))
    second_events = list(backend(_payload(previous_response_id="resp-1")))

    assert [event.type for event in first_events] == ["response.created", "response.completed"]
    assert [event.type for event in second_events] == ["response.created", "response.completed"]
    assert len(clients) == 1
    assert len(managers) == 1
    assert clients[0]["base_url"] == "https://provider.example/v1"
    assert clients[0]["default_headers"] == {"X-Provider": "test"}
    assert connection.sent[0]["model"] == "gpt-5.6-terra"
    assert connection.sent[1]["previous_response_id"] == "resp-1"
    assert connection.sent[1]["input"][0]["content"][0]["text"] == "delta"
    assert not any(
        key in connection.sent[1]
        for key in ("api_key", "base_url", "extra_headers", "timeout", "_vibelution_responses_websocket")
    )
    assert [state for state, _fields in states] == ["connected", "reused"]


def test_responses_websocket_never_sends_internal_client_callback_to_sdk(monkeypatch):
    connection = _FakeConnection()

    class _FakeOpenAI:
        def __init__(self, **_kwargs) -> None:
            self.responses = SimpleNamespace(
                connect=lambda **_options: _FakeManager(connection)
            )

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    backend = ResponsesWebSocketBackend(lambda _payload: ())
    payload = _payload()
    payload["client"] = object()

    events = list(backend(payload))

    assert [event.type for event in events] == ["response.created", "response.completed"]
    assert "client" not in connection.sent[0]


def test_responses_websocket_pre_send_type_error_falls_back_once(monkeypatch):
    connection = _PreSendTypeErrorConnection()

    class _FakeOpenAI:
        def __init__(self, **_kwargs) -> None:
            self.responses = SimpleNamespace(
                connect=lambda **_options: _FakeManager(connection)
            )

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    http_payloads: list[dict] = []
    states: list[tuple[str, dict]] = []

    def http_backend(payload):
        http_payloads.append(payload)
        return iter(({"type": "response.completed", "response": {"id": "http-1"}},))

    backend = ResponsesWebSocketBackend(
        http_backend,
        state_sink=lambda state, fields: states.append((state, fields)),
    )
    result = list(backend(_payload()))

    assert result[0]["type"] == "response.completed"
    assert len(http_payloads) == 1
    assert states[-1] == (
        "fallback",
        {
            "reasonType": "TypeError",
            "fallbackTransport": "http",
            "preSendValidationFailure": True,
        },
    )


def test_responses_websocket_connect_failure_falls_back_with_full_http_payload(monkeypatch):
    class _FailingOpenAI:
        def __init__(self, **_kwargs) -> None:
            self.responses = SimpleNamespace(connect=self._connect)

        @staticmethod
        def _connect(**_kwargs):
            raise RuntimeError("upgrade rejected")

    monkeypatch.setattr(openai, "OpenAI", _FailingOpenAI)
    http_payloads: list[dict] = []
    states: list[tuple[str, dict]] = []

    def http_backend(payload):
        http_payloads.append(payload)
        return iter(({"type": "response.completed", "response": {"id": "http-1"}},))

    backend = ResponsesWebSocketBackend(
        http_backend,
        state_sink=lambda state, fields: states.append((state, fields)),
    )
    result = list(backend(_payload(previous_response_id="resp-1")))

    assert result[0]["type"] == "response.completed"
    assert len(http_payloads) == 1
    assert "previous_response_id" not in http_payloads[0]
    assert http_payloads[0]["input"][0]["content"][0]["text"] == "full"
    assert "_vibelution_responses_websocket" not in http_payloads[0]
    assert states == [
        (
            "fallback",
            {"reasonType": "RuntimeError", "fallbackTransport": "http"},
        )
    ]


def test_responses_websocket_explicit_1013_rejection_falls_back_before_any_event(monkeypatch):
    connection = _RejectedConnection()

    class _FakeOpenAI:
        def __init__(self, **_kwargs) -> None:
            self.responses = SimpleNamespace(
                connect=lambda **_options: _FakeManager(connection)
            )

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    http_payloads: list[dict] = []
    states: list[tuple[str, dict]] = []

    def http_backend(payload):
        http_payloads.append(payload)
        return iter(({"type": "response.completed", "response": {"id": "http-1"}},))

    backend = ResponsesWebSocketBackend(
        http_backend,
        state_sink=lambda state, fields: states.append((state, fields)),
    )
    result = list(backend(_payload(previous_response_id="resp-1")))

    assert result[0]["type"] == "response.completed"
    assert http_payloads[0]["input"][0]["content"][0]["text"] == "full"
    assert "previous_response_id" not in http_payloads[0]
    assert states[-1] == (
        "fallback",
        {
            "reasonType": "RuntimeError",
            "closeCode": 1013,
            "fallbackTransport": "http",
        },
    )
