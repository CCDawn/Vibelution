from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import ToolMessage

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_config  # noqa: E402
from core.llm.client import LLMClient  # noqa: E402


TOOL_NAME = "acceptance_round_tool"
STABLE_CACHE_PREFIX = "\n".join(
    f"Stable protocol acceptance cache anchor {index:04d}: preserve this line unchanged."
    for index in range(320)
)
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": "Record one numbered protocol acceptance round.",
        "parameters": {
            "type": "object",
            "properties": {
                "round": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "The current acceptance round number.",
                }
            },
            "required": ["round"],
            "additionalProperties": False,
        },
    },
}


def _safe_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:12]


def _profile_summary(client: LLMClient) -> dict[str, Any]:
    route = client.protocol_route
    return {
        "profileId": client.profile_id,
        "providerId": client.profile.provider_id,
        "providerKind": client.provider.kind,
        "model": client.profile.model,
        "transport": client.profile.transport,
        "wireProtocol": route.wire_protocol.value,
        "promptCacheMode": str(getattr(client.profile.prompt_cache, "mode", "") or ""),
        "responsesContinuation": bool(route.compat.responses_continuation),
        "responsesWebsocket": bool(route.compat.responses_websocket),
    }


def _client_for_model_ref(*, base_profile_id: str, model_ref: str) -> LLMClient:
    config = get_config().model_copy(deep=True)
    if not model_ref:
        return LLMClient(config=config, profile_id=base_profile_id)
    entry = config.llm.model_library.get(model_ref)
    if not isinstance(entry, dict):
        raise ValueError(f"Unknown model_ref: {model_ref}")
    base = config.llm.get_profile(base_profile_id)
    provider_id = str(base.provider_id or "").strip()
    model = str(entry.get("model") or entry.get("upstream_id") or "").strip()
    if not provider_id or not model:
        raise ValueError("The base profile and model_ref must resolve provider_id and model.")
    runtime_model_ref = f"{provider_id}/{model}"
    runtime_entry = dict(entry)
    runtime_entry.update(
        {
            "provider_id": provider_id,
            "model": model,
            "model_ref": runtime_model_ref,
        }
    )
    runtime_profile_id = f"live_acceptance_{_safe_hash(runtime_model_ref)}"
    config.llm.model_library[runtime_model_ref] = runtime_entry
    config.llm.profiles[runtime_profile_id] = base.model_copy(
        update={
            "profile_id": runtime_profile_id,
            "model_ref": runtime_model_ref,
            "model": model,
            "transport": str(entry.get("transport") or base.transport),
            "contract": str(entry.get("contract") or base.contract),
            "protocol": str(entry.get("protocol") or base.protocol),
            "compat": dict(entry.get("compat") or {}),
            "reasoning_effort_values": list(entry.get("reasoning_effort_values") or []),
            "default_reasoning_effort": str(entry.get("default_reasoning_effort") or ""),
            "reasoning_effort_adapter": str(entry.get("reasoning_effort_adapter") or "none"),
            "reasoning_effort_map": dict(entry.get("reasoning_effort_map") or {}),
        }
    )
    return LLMClient(config=config, profile_id=runtime_profile_id)


def _usage_summary(message: Any) -> dict[str, Any]:
    metadata = getattr(message, "response_metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    usage = metadata.get("usage_observation")
    usage = usage if isinstance(usage, dict) else {}
    return {
        "inputTokens": int(usage.get("input_tokens") or 0),
        "cachedInputTokens": int(usage.get("cached_input_tokens") or 0),
        "cacheHitRate": float(usage.get("cache_hit_rate") or 0.0),
        "outputTokens": int(usage.get("output_tokens") or 0),
    }


def _run_five_round_chain(client: LLMClient, *, label: str) -> dict[str, Any]:
    profile = _profile_summary(client)
    session_id = f"live-acceptance-{label}-{int(time.time())}"
    messages: list[Any] = [
        {
            "role": "system",
            "content": (
                f"{STABLE_CACHE_PREFIX}\n\n"
                "This is a protocol acceptance run. For rounds 1 through 5, call "
                f"{TOOL_NAME} exactly once with the requested round number. Do not finish early. "
                "Each tool result contains next_round; immediately call the tool for that round. "
                "Only a tool result with complete=true permits one concise final answer."
            ),
        },
        {"role": "user", "content": "Begin acceptance round 1."},
    ]
    replay_state = None
    rounds: list[dict[str, Any]] = []
    started = time.perf_counter()
    for round_number in range(1, 6):
        invocation_id = f"{session_id}-invoke-{round_number}"
        round_started = time.perf_counter()
        outcome = client.invoke_outcome(
            messages,
            tools=[TOOL_SCHEMA],
            metadata={
                "sessionId": session_id,
                "turnId": session_id,
                "invocationId": invocation_id,
                "iteration": round_number,
                "acceptanceProtocol": label,
            },
            replay_state=replay_state,
        )
        if outcome.kind != "tool_calls" or len(outcome.tool_calls) != 1:
            raise RuntimeError(
                f"{label} round {round_number} expected one tool call, got "
                f"kind={outcome.kind} count={len(outcome.tool_calls)}"
            )
        call = outcome.tool_calls[0]
        if call.name != TOOL_NAME:
            raise RuntimeError(
                f"{label} round {round_number} expected {TOOL_NAME}, got {call.name}"
            )
        requested_round = int(call.arguments.get("round") or 0)
        if requested_round != round_number:
            raise RuntimeError(
                f"{label} round {round_number} received tool argument round={requested_round}"
            )
        assistant = client.project_outcome_message(
            outcome,
            metadata={"acceptanceProtocol": label},
            include_outcome=True,
        )
        messages.extend(
            [
                assistant,
                ToolMessage(
                    content=json.dumps(
                        (
                            {
                                "round": round_number,
                                "status": "ok",
                                "complete": True,
                            }
                            if round_number == 5
                            else {
                                "round": round_number,
                                "status": "ok",
                                "next_round": round_number + 1,
                                "instruction": (
                                    f"Call {TOOL_NAME} now with round={round_number + 1}."
                                ),
                            }
                        ),
                        ensure_ascii=False,
                    ),
                    tool_call_id=call.call_id,
                ),
            ]
        )
        replay_state = outcome.replay_state
        rounds.append(
            {
                "round": round_number,
                "latencyMs": round((time.perf_counter() - round_started) * 1000, 1),
                "toolName": call.name,
                "callIdHash": _safe_hash(call.call_id),
                "replayStatePresent": replay_state is not None,
                "previousResponseIdPresent": bool(
                    replay_state is not None and replay_state.response_id
                ),
                **_usage_summary(assistant),
            }
        )

    final_started = time.perf_counter()
    final_outcome = client.invoke_outcome(
        messages,
        tools=[],
        metadata={
            "sessionId": session_id,
            "turnId": session_id,
            "invocationId": f"{session_id}-final",
            "iteration": 6,
            "acceptanceProtocol": label,
        },
        replay_state=replay_state,
    )
    if final_outcome.kind != "final_answer" or not final_outcome.final_text.strip():
        raise RuntimeError(
            f"{label} expected a final answer after five rounds, got {final_outcome.kind}"
        )
    final_message = client.project_outcome_message(
        final_outcome,
        metadata={"acceptanceProtocol": label},
        include_outcome=True,
    )
    return {
        "status": "passed",
        "profile": profile,
        "sessionIdHash": _safe_hash(session_id),
        "rounds": rounds,
        "final": {
            "latencyMs": round((time.perf_counter() - final_started) * 1000, 1),
            "textChars": len(final_outcome.final_text.strip()),
            **_usage_summary(final_message),
        },
        "totalLatencyMs": round((time.perf_counter() - started) * 1000, 1),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a bounded five-tool-round live acceptance matrix without printing secrets or prompts."
    )
    parser.add_argument("--responses-profile", default="fallback_relay_gpt_5_6_luna")
    parser.add_argument("--responses-model-ref", default="ai-pixel/gpt-5.6-terra")
    parser.add_argument("--chat-profile", default="primary")
    parser.add_argument("--protocol", choices=("both", "responses", "chat"), default="both")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    clients: list[tuple[str, LLMClient]] = []
    if args.protocol in {"both", "responses"}:
        clients.append(
            (
                "responses",
                _client_for_model_ref(
                    base_profile_id=args.responses_profile,
                    model_ref=args.responses_model_ref,
                ),
            )
        )
    if args.protocol in {"both", "chat"}:
        clients.append(("chat_completions", _client_for_model_ref(base_profile_id=args.chat_profile, model_ref="")))
    expected = {"responses": "responses", "chat_completions": "chat_completions"}
    for label, client in clients:
        actual = client.protocol_route.wire_protocol.value
        if actual != expected[label]:
            raise RuntimeError(f"{label} profile resolved unexpected wire protocol: {actual}")

    report: dict[str, Any] = {
        "status": "dry_run" if args.dry_run else "completed",
        "profiles": {label: _profile_summary(client) for label, client in clients},
        "results": {},
    }
    if not args.dry_run:
        for label, client in clients:
            try:
                report["results"][label] = _run_five_round_chain(client, label=label)
            except Exception as exc:
                report["status"] = "failed"
                report["results"][label] = {
                    "status": "failed",
                    "errorType": type(exc).__name__,
                    "error": str(exc)[:500],
                }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
