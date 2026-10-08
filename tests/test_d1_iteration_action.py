"""Local d1-3B choice stays optional: only a legal high probability is kept."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.research.operator_optimization.d1_action import (
    choose_iteration_action,
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


def test_missing_url_uses_the_local_default(monkeypatch):
    monkeypatch.delenv("VIBELUTION_D1_SYSTEMONE_URL", raising=False)
    assert systemone_url() == "http://127.0.0.1:8088/v1/systemone"


def test_probability_cutoff_rejects_bad_env_and_a_single_option(monkeypatch):
    monkeypatch.setenv("VIBELUTION_D1_MIN_PROBABILITY", "nope")
    assert min_probability() == 0.80
    monkeypatch.setenv("VIBELUTION_D1_MIN_PROBABILITY", "0.95")
    assert min_probability() == 0.95
    assert choose_iteration_action({
        **_INPUTS,
        "actionPolicy": {"availableActions": ["stop"]},
    }) is None
