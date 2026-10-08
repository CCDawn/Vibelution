"""Local d1-3B choice stays optional: only a legal high probability is kept."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.research.operator_optimization import d1_action
from core.research.operator_optimization.d1_action import (
    choose_iteration_action,
    decision_reason_name,
    min_probability,
    systemone_url,
)

_INPUTS = {
    "roundId": "round-1",
    "inputHash": "a" * 64,
    "feedback": "the retry was faster",
    "evaluation": {"speed": "fast"},
    "actionPolicy": {
        "availableActions": ["discuss", "stop"],
    },
}


class _Server(ThreadingHTTPServer):
    def __init__(self, response, status=200):
        self.response = response
        self.status = status
        self.bodies = []
        super().__init__(("127.0.0.1", 0), _Handler)


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        self.server.bodies.append(json.loads(raw.decode("utf-8")))
        payload = self.server.response
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(self.server.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


@pytest.fixture
def endpoint(monkeypatch):
    servers = []

    def serve(response, status=200):
        server = _Server(response, status)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        host, port = server.server_address
        monkeypatch.setenv("VIBELUTION_D1_SYSTEMONE_URL", f"http://{host}:{port}/v1/systemone")
        return server

    yield serve
    for server in servers:
        server.shutdown()
        server.server_close()


def _answer(choice, probability, *, confidence=0.99, probabilities=None):
    return {
        "model": "LiquidAI/d1-3B",
        "answers": {
            "next": {
                "type": "choice",
                "choice": choice,
                "probabilities": probabilities or {choice: probability, "discuss": 1 - probability},
                "confidence": confidence,
            }
        },
        "usage": {"input_tokens": 18, "output_tokens": 0},
    }


def test_high_probability_keeps_the_offered_action(endpoint):
    server = endpoint(_answer("stop", 0.91))
    choice = choose_iteration_action(_INPUTS)
    assert choice == {
        "kind": "stop",
        "probability": 0.91,
        "inputHash": "a" * 64,
        "model": "LiquidAI/d1-3B",
        "inputTokens": 18,
    }
    criteria = server.bodies[0]["questions"]["next"]["criteria"]
    assert set(criteria) == {"discuss", "stop"}
    assert "repair_baseline" not in criteria


def test_low_option_probability_falls_through_even_when_confidence_is_high(endpoint):
    endpoint(_answer("stop", 0.42, confidence=0.99))
    assert choose_iteration_action(_INPUTS) is None


def test_illegal_or_malformed_answers_fall_through(endpoint):
    endpoint(_answer("fly", 0.99, probabilities={"fly": 0.99}))
    assert choose_iteration_action(_INPUTS) is None
    endpoint(b"not-json")
    assert choose_iteration_action(_INPUTS) is None
    endpoint({"answers": {}})
    assert choose_iteration_action(_INPUTS) is None


def test_unreachable_server_falls_through(monkeypatch):
    monkeypatch.setenv("VIBELUTION_D1_SYSTEMONE_URL", "http://127.0.0.1:9/v1/systemone")
    assert choose_iteration_action(_INPUTS) is None


def test_blank_url_disables_the_call(monkeypatch):
    monkeypatch.setenv("VIBELUTION_D1_SYSTEMONE_URL", "  ")
    assert systemone_url() == ""
    assert choose_iteration_action(_INPUTS) is None


def test_missing_env_without_a_binding_does_not_call(monkeypatch):
    monkeypatch.delenv("VIBELUTION_D1_SYSTEMONE_URL", raising=False)
    monkeypatch.setattr(d1_action, "_load_bound_entry", lambda: None)
    assert systemone_url() == ""
    assert choose_iteration_action(_INPUTS) is None


def test_probability_cutoff_rejects_bad_env_and_a_single_option(monkeypatch):
    monkeypatch.delenv("VIBELUTION_D1_SYSTEMONE_URL", raising=False)
    monkeypatch.setattr(d1_action, "_load_bound_entry", lambda: None)
    monkeypatch.setenv("VIBELUTION_D1_MIN_PROBABILITY", "nope")
    assert min_probability() == 0.80
    monkeypatch.setenv("VIBELUTION_D1_MIN_PROBABILITY", "0.95")
    assert min_probability() == 0.95
    assert choose_iteration_action({
        **_INPUTS,
        "actionPolicy": {"availableActions": ["stop"]},
    }) is None


def _serve(response):
    server = _Server(response)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _bind(monkeypatch, server, *, model_id, cutoff):
    host, port = server.server_address
    monkeypatch.delenv("VIBELUTION_D1_SYSTEMONE_URL", raising=False)
    monkeypatch.setattr(d1_action, "_load_bound_entry", lambda: {
        "id": "julia-1",
        "model_id": model_id,
        "base_url": f"http://{host}:{port}/v1/systemone",
        "min_probability": cutoff,
    })


def test_bound_catalog_entry_posts_its_model_id(monkeypatch):
    monkeypatch.delenv("VIBELUTION_D1_MIN_PROBABILITY", raising=False)
    server = _serve(_answer("stop", 0.88))
    try:
        _bind(monkeypatch, server, model_id="ggml-org/Julia-1-GGUF", cutoff=0.80)
        choice = choose_iteration_action(_INPUTS)
        assert choice["kind"] == "stop"
        assert choice["model"] == "ggml-org/Julia-1-GGUF"
        assert server.bodies[0]["model"] == "ggml-org/Julia-1-GGUF"
        assert decision_reason_name(choice["model"]) == "ggml-org/Julia-1-GGUF"
    finally:
        server.shutdown()
        server.server_close()


def test_catalog_cutoff_is_the_entry_probability(monkeypatch):
    monkeypatch.setenv("VIBELUTION_D1_MIN_PROBABILITY", "0.50")
    server = _serve(_answer("stop", 0.91))
    try:
        _bind(monkeypatch, server, model_id="ggml-org/Julia-1-GGUF", cutoff=0.95)
        assert choose_iteration_action(_INPUTS) is None
        assert server.bodies
    finally:
        server.shutdown()
        server.server_close()


def test_blank_env_disables_a_bound_catalog_entry(monkeypatch):
    server = _serve(_answer("stop", 0.99))
    try:
        _bind(monkeypatch, server, model_id="ggml-org/Julia-1-GGUF", cutoff=0.80)
        monkeypatch.setenv("VIBELUTION_D1_SYSTEMONE_URL", " ")
        assert choose_iteration_action(_INPUTS) is None
        assert server.bodies == []
    finally:
        server.shutdown()
        server.server_close()


def test_env_probability_override_rejects_a_weaker_choice(endpoint, monkeypatch):
    endpoint(_answer("stop", 0.91))
    monkeypatch.setenv("VIBELUTION_D1_MIN_PROBABILITY", "0.95")
    assert choose_iteration_action(_INPUTS) is None


def test_probe_reports_the_posted_choice():
    from config.decision_models import probe_decision_model

    server = _serve(_answer("stop", 0.93))
    try:
        host, port = server.server_address
        result = probe_decision_model(
            f"http://{host}:{port}/v1/systemone",
            "LiquidAI/d1-3B",
        )
        assert result["ok"] is True
        assert result["choice"] == "stop"
        assert result["probability"] == 0.93
        assert server.bodies[0]["model"] == "LiquidAI/d1-3B"
        missed = probe_decision_model("http://127.0.0.1:9/v1/systemone", "LiquidAI/d1-3B")
        assert missed["ok"] is False
    finally:
        server.shutdown()
        server.server_close()
