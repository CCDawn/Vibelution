from core.orchestration.turn_runtime import (
    AgentTurnRuntimeRequest,
    build_prompt_cache_partition,
    prepare_agent_turn_runtime,
    runtime_metadata_env,
)


def test_clean_identity_fields_decode_bytes_and_reject_mappings():
    runtime = prepare_agent_turn_runtime(
        AgentTurnRuntimeRequest(
            mode=b"chat",
            run_kind="chat_turn",
            run_id="turn-1",
            session_id=b"session-a",
            agent_id={"id": "agent-a"},
            llm_slot=" dialogue ",
            model_id="model-a\n",
        )
    )
    assert runtime.mode == "chat"
    assert runtime.session_id == "session-a"
    assert runtime.agent_id == ""
    assert runtime.llm_slot == "dialogue"
    assert runtime.model_id == "model-a"
    assert "session:session-a" in runtime.prompt_cache_partition
    assert "b'session-a'" not in runtime.prompt_cache_partition
    assert "agent:direct" in runtime.prompt_cache_partition
    assert "slot:dialogue" in runtime.prompt_cache_partition


def test_whitespace_only_cache_scope_is_omitted_from_partition_and_env():
    partition = build_prompt_cache_partition(
        mode="chat",
        run_kind="chat_turn",
        session_id="session-a",
        cache_scope="  \n",
    )
    assert "scope:" not in partition
    env = runtime_metadata_env(
        prepare_agent_turn_runtime(
            AgentTurnRuntimeRequest(
                mode="chat",
                run_kind="chat_turn",
                session_id="session-a",
                cache_scope="   ",
            )
        )
    )
    assert "VIBELUTION_TURN_CACHE_SCOPE" not in env
    assert env["VIBELUTION_TURN_SESSION_ID"] == "session-a"
