import hashlib
import json

from tools import conversation_log_tools


def _write_jsonl(path, rows):
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_conversation_log_inspect_summarizes_tokens_tools_and_inefficiencies(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_log_tools, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(conversation_log_tools, "LOG_INFO_DIR", tmp_path / "log_info")
    log_dir = tmp_path / "log_info"
    log_dir.mkdir()
    log_path = log_dir / "conversation_20260604_120000__chat__demo.jsonl"
    _write_jsonl(
        log_path,
        [
            {
                "type": "session_start",
                "session_id": "20260604_120000",
                "session_label": "chat__demo",
                "metadata": {"agent_mode": "chat", "model": "gpt-test", "tools_count": 9},
            },
            {"type": "llm_response", "input_tokens": 60000, "output_tokens": 800},
            {
                "type": "tool_call",
                "turn": 1,
                "tool_name": "read_file_tool",
                "tool_args": {"file_path": "log_info/demo.jsonl", "max_lines": 0},
                "status": "success",
                "tool_result_length": 12000,
            },
            {
                "type": "tool_call",
                "turn": 1,
                "tool_name": "read_file_tool",
                "tool_args": {"file_path": "log_info/demo.jsonl", "max_lines": 0},
                "status": "success",
                "tool_result_length": 12000,
            },
            {"type": "llm_error", "status": "failed", "message": "429 rate limit"},
            {"type": "session_end", "ok": True},
        ],
    )

    result = conversation_log_tools.inspect_conversation_logs(log_path=str(log_path))
    inspection = result["inspections"][0]

    assert result["status"] == "ok"
    assert inspection["path"] == "log_info/conversation_20260604_120000__chat__demo.jsonl"
    assert inspection["tokenUsage"]["inputTokens"] == 60000
    assert inspection["toolCalls"]["byTool"]["read_file_tool"] == 2
    assert inspection["toolCalls"]["repeated"]
    assert {item["code"] for item in inspection["inefficiencies"]}.issuperset(
        {"repeated_tool_call", "large_tool_result", "token_imbalance", "error_status_check_needed"}
    )
    assert inspection["errors"][0]["detailLength"] == len("429 rate limit")
    assert inspection["errors"][0]["detailSha256"] == hashlib.sha256(
        b"429 rate limit"
    ).hexdigest()
    assert "preview" not in inspection["errors"][0]


def test_conversation_log_inspect_query_selects_matching_recent_log(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_log_tools, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(conversation_log_tools, "LOG_INFO_DIR", tmp_path / "log_info")
    log_dir = tmp_path / "log_info"
    log_dir.mkdir()
    first = log_dir / "conversation_20260604_120000__chat__alpha.jsonl"
    second = log_dir / "conversation_20260604_120100__chat__beta.jsonl"
    _write_jsonl(first, [{"type": "session_start", "metadata": {"conversation_topic": "alpha"}}])
    _write_jsonl(second, [{"type": "session_start", "metadata": {"conversation_topic": "程听澜"}}])

    result = conversation_log_tools.inspect_conversation_logs(query="程听澜", limit=1)

    assert result["candidateCount"] == 1
    assert result["candidates"][0]["path"] == "log_info/conversation_20260604_120100__chat__beta.jsonl"


def test_conversation_log_inspect_rejects_non_log_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_log_tools, "PROJECT_ROOT", tmp_path)
    target = tmp_path / "secret.jsonl"
    target.write_text("{}", encoding="utf-8")

    payload = conversation_log_tools.conversation_log_inspect_tool(log_path=str(target))

    assert "only reads log_info/" in payload


def test_conversation_log_inspect_correlates_bounded_runtime_scene_boundaries(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_log_tools, "PROJECT_ROOT", tmp_path)
    scene = tmp_path / "logs" / "runtime_scenes" / "scene-demo"
    conversations = scene / "conversations"
    conversations.mkdir(parents=True)
    (scene / "manifest.json").write_text(
        json.dumps({"runtime_scene_id": "scene-demo", "status": "running"}),
        encoding="utf-8",
    )
    _write_jsonl(
        scene / "timeline.jsonl",
        [
            {
                "event_code": "conversation.turn.started",
                "outcome": "started",
                "ts": "2026-07-14T01:00:00Z",
                "fields": {
                    "sessionId": "session-a",
                    "turnId": "turn-1",
                    "clientSubmissionId": "submission-1",
                },
            },
            {
                "event_code": "llm.invocation.succeeded",
                "outcome": "succeeded",
                "ts": "2026-07-14T01:00:01Z",
                "fields": {
                    "sessionId": "session-a",
                    "turnId": "turn-1",
                    "invocationId": "invocation-1",
                    "clientSubmissionId": "submission-1",
                },
            },
            {
                "event_code": "conversation.turn.started",
                "outcome": "started",
                "ts": "2026-07-14T01:01:00Z",
                "fields": {
                    "sessionId": "session-a",
                    "turnId": "turn-2",
                    "client_submission_id": "submission-2",
                },
            },
            {
                "event_code": "conversation.turn.started",
                "outcome": "started",
                "ts": "2026-07-14T01:02:00Z",
                "fields": {"sessionId": "session-a", "turnId": "turn-3"},
                "prompt": "full private prompt must not be returned",
                "tool_args": {"api_key": "secret-tool-argument"},
            },
        ],
    )
    _write_jsonl(
        conversations / "session-a.jsonl",
        [
            {
                "event_code": "llm.invocation.failed",
                "outcome": "failed",
                "level": "error",
                "ts": "2026-07-14T01:01:01Z",
                "session_id": "session-a",
                "turn_id": "turn-2",
                "invocation_id": "invocation-2",
                "client_submission_id": "submission-2",
                "error_type": "ProviderError",
                "message": "api_key=super-secret full private prompt must not be returned",
                "tool_result": "unbounded private result",
            }
        ],
    )

    result = conversation_log_tools.inspect_conversation_logs(
        log_path=str(scene),
        session_id="session-a",
    )
    inspection = result["inspections"][0]
    correlation = inspection["correlation"]

    assert inspection["kind"] == "runtime_scene"
    assert correlation["recentSuccessfulBoundary"]["identity"]["turnId"] == "turn-1"
    assert correlation["recentSuccessfulBoundary"]["identity"]["submissionId"] == "submission-1"
    assert correlation["currentUnterminatedBoundary"]["identity"]["turnId"] == "turn-3"
    assert correlation["currentUnterminatedBoundary"]["missingIdentity"] == [
        "invocationId",
        "submissionId",
    ]
    assert correlation["terminalSummary"][0]["identity"]["turnId"] == "turn-2"
    assert correlation["terminalSummary"][0]["identity"]["submissionId"] == "submission-2"
    assert correlation["errorSummary"][0]["errorType"] == "ProviderError"
    payload = json.dumps(result, ensure_ascii=False)
    assert "super-secret" not in payload
    assert "full private prompt" not in payload
    assert "unbounded private result" not in payload
    assert "secret-tool-argument" not in payload


def test_conversation_log_inspect_never_returns_raw_error_or_preview_text(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_log_tools, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(conversation_log_tools, "LOG_INFO_DIR", tmp_path / "log_info")
    log_dir = tmp_path / "log_info"
    log_dir.mkdir()
    log_path = log_dir / "conversation_20260714_120000__chat__safe.jsonl"
    prompt_only = "draft a private acquisition plan for the next board meeting"
    unlabeled_credential = "sk-live-7Gf93kLm2Nq8Vr4Wx1Za"
    tool_result_secret = "customer export row: alice@example.test, account 1042"
    _write_jsonl(
        log_path,
        [
            {
                "type": "llm_error",
                "status": "failed",
                "error_type": "PromptRejected",
                "content_preview": prompt_only,
            },
            {
                "type": "error",
                "status": "failed",
                "error_type": "ProviderAuthError",
                "error": unlabeled_credential,
            },
            {
                "type": "error",
                "status": "failed",
                "error_type": "ToolExecutionError",
                "tool_result_preview": tool_result_secret,
            },
        ],
    )

    result = conversation_log_tools.inspect_conversation_logs(log_path=str(log_path))
    errors = result["inspections"][0]["errors"]
    payload = json.dumps(result, ensure_ascii=False)

    assert [item["detailLength"] for item in errors] == [
        len(prompt_only),
        len(unlabeled_credential),
        len(tool_result_secret),
    ]
    assert [item["detailSha256"] for item in errors] == [
        hashlib.sha256(value.encode("utf-8")).hexdigest()
        for value in (prompt_only, unlabeled_credential, tool_result_secret)
    ]
    assert all("preview" not in item for item in errors)
    assert prompt_only not in payload
    assert unlabeled_credential not in payload
    assert tool_result_secret not in payload


def test_event_identities_prefers_live_session_and_keeps_legacy_aliases():
    assert conversation_log_tools._event_identities(
        {
            "session_id": "20260714_010203_123456",
            "fields": {"sessionId": "session-live"},
        }
    )["sessionId"] == "session-live"
    assert conversation_log_tools._event_identities(
        {"runtimeSessionId": "session-runtime-camel"}
    )["sessionId"] == "session-runtime-camel"
    assert conversation_log_tools._event_identities(
        {"runtime_session_id": "session-runtime-snake"}
    )["sessionId"] == "session-runtime-snake"
    assert conversation_log_tools._event_identities(
        {"session_id": "session-legacy"}
    )["sessionId"] == "session-legacy"


def test_conversation_log_inspect_query_miss_does_not_fall_back_to_latest(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_log_tools, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(conversation_log_tools, "LOG_INFO_DIR", tmp_path / "log_info")
    log_dir = tmp_path / "log_info"
    log_dir.mkdir()
    _write_jsonl(
        log_dir / "conversation_20260714_120000__chat__latest.jsonl",
        [{"type": "session_start", "metadata": {"conversation_topic": "latest"}}],
    )

    result = conversation_log_tools.inspect_conversation_logs(query="missing conversation")

    assert result["candidateCount"] == 0
    assert result["candidates"] == []
    assert result["inspections"] == []
    assert result["selectionStatus"] == "not_found"
    assert result["fallbackUsed"] is False


def test_conversation_log_inspect_identity_miss_does_not_return_latest(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_log_tools, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(conversation_log_tools, "LOG_INFO_DIR", tmp_path / "log_info")
    log_dir = tmp_path / "log_info"
    log_dir.mkdir()
    _write_jsonl(
        log_dir / "conversation_20260714_120000__chat__latest.jsonl",
        [
            {
                "event_code": "conversation.turn.started",
                "fields": {"sessionId": "session-other", "turnId": "turn-other"},
            }
        ],
    )

    result = conversation_log_tools.inspect_conversation_logs(session_id="session-missing")

    assert result["candidateCount"] == 0
    assert result["inspections"] == []
    assert result["selectionStatus"] == "not_found"
    assert result["fallbackUsed"] is False


def test_conversation_log_inspect_reports_session_match_without_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_log_tools, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(conversation_log_tools, "LOG_INFO_DIR", tmp_path / "log_info")
    log_dir = tmp_path / "log_info"
    log_dir.mkdir()
    log_path = log_dir / "conversation_20260714_120000__chat__session-live.jsonl"
    _write_jsonl(
        log_path,
        [
            {
                "type": "session_start",
                "session_id": "20260714_120000_123456",
                "metadata": {"sessionId": "session-live"},
            }
        ],
    )

    result = conversation_log_tools.inspect_conversation_logs(session_id="session-live")
    correlation = result["inspections"][0]["correlation"]

    assert result["candidateCount"] == 1
    assert result["selectionStatus"] == "matched"
    assert result["fallbackUsed"] is False
    assert correlation["boundaryCount"] == 0
    assert correlation["matchStatus"] == "identity_match_without_boundary"
    assert correlation["matchedRecordCount"] == 1
    assert correlation["diagnostics"] == [
        {
            "code": "identity_match_without_boundary",
            "message": "Identity matched log records, but no turn, invocation, or submission boundary was found.",
        }
    ]
