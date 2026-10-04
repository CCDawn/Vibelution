"""Financial profile integration against the real file-backed governed store."""

import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.infrastructure import developer_sandbox
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    memory_cleanup_service,
    memory_service,
    rag_retrieval_service,
    rag_vector_index_service,
    team_service,
    unified_knowledge_search_service,
)
from core.web.services import (
    team_knowledge_service as knowledge,
)
from core.web.services.team_knowledge import financial

EXCERPT = "本公司2025年度营业收入为123.45元。"


def evidence(**changes):
    data = {
        "schemaVersion": 1,
        "evidenceKind": "original_pdf_excerpt",
        "sourceId": "issuer-annual-2025",
        "company": "示例公司",
        "ticker": "600519",
        "reportPeriod": "2025FY",
        "reportVersion": "original",
        "documentSha256": "a" * 64,
        "page": 7,
        "sourceUrl": "https://issuer.example.test/annual-2025.pdf",
        "publishedAt": "2026-03-01T00:00:00+00:00",
        "expiresAt": "",
        "supersedesSha256": "",
        "excerptSha256": hashlib.sha256(EXCERPT.encode()).hexdigest(),
    }
    data.update(changes)
    return data


@pytest.fixture
def finance_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    for service in (
        agent_directory_service,
        chat_room_service,
        memory_cleanup_service,
        memory_service,
        rag_vector_index_service,
        knowledge,
        team_service,
    ):
        monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    config_path = tmp_path / "developer-off.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n")
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    owner = agent_directory_service.create_agent_instance(
        display_name="Finance owner", direct_session_id="finance-owner-test"
    )
    other = agent_directory_service.create_agent_instance(
        display_name="Other owner", direct_session_id="finance-other-test"
    )
    return {"owner": owner["agentId"], "other": other["agentId"], "root": tmp_path}


def stage(env, **changes):
    return knowledge.stage_financial_evidence(
        agent_id=env["owner"], evidence=evidence(**changes), excerpt=EXCERPT
    )


def review(env, staged, content=EXCERPT):
    return knowledge.review_owner_inbox_source(
        "agent",
        env["owner"],
        staged["source"]["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=env["owner"],
        ingest_on_accept=True,
        knowledge_base_id=staged["knowledgeBase"]["scopedKnowledgeBaseId"],
        knowledge_content=content,
    )


def search(env, **changes):
    return knowledge.search_financial_evidence(
        **{
            "agent_id": env["owner"],
            "query": "营业收入",
            "ticker": "600519",
            "report_period": "2025FY",
            **changes,
        }
    )


def test_read_does_not_initialize_and_creation_is_idempotent_and_owner_scoped(
    finance_env,
):
    env = finance_env
    assert search(env)["status"] == "not_initialized"
    assert (
        knowledge.list_agent_knowledge_bases(env["owner"], actor_agent_id=env["owner"])[
            "knowledgeBases"
        ]
        == []
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        bases = list(
            pool.map(
                lambda _: knowledge.get_financial_knowledge_base(
                    agent_id=env["owner"], create_if_missing=True
                ),
                range(4),
            )
        )
    assert sum(b["created"] for b in bases) == 1
    assert len({b["knowledgeBase"]["scopedKnowledgeBaseId"] for b in bases}) == 1
    other = knowledge.get_financial_knowledge_base(
        agent_id=env["other"], create_if_missing=True
    )["knowledgeBase"]
    assert (
        other["scopedKnowledgeBaseId"]
        != bases[0]["knowledgeBase"]["scopedKnowledgeBaseId"]
    )
    assert other["profile"] == financial.PROFILE


def test_does_not_adopt_an_unrelated_same_name_base(finance_env):
    env = finance_env
    original = knowledge.create_agent_knowledge_base(
        env["owner"], name=financial.BASE_NAME, actor_agent_id=env["owner"]
    )
    created = knowledge.get_financial_knowledge_base(
        agent_id=env["owner"], create_if_missing=True
    )["knowledgeBase"]
    assert original["knowledgeBaseId"] != created["knowledgeBaseId"]
    assert "profile" not in original


@pytest.mark.parametrize(
    "change",
    [
        {"page": 0},
        {"page": True},
        {"ticker": ""},
        {"reportPeriod": "2025"},
        {"reportVersion": ""},
        {"documentSha256": "fake"},
        {"sourceUrl": "javascript:alert(1)"},
        {"sourceUrl": "https://password@issuer.test"},
        {"publishedAt": "2026-03-01"},
        {"expiresAt": "2026-01-01T00:00:00Z"},
        {"excerptSha256": "b" * 64},
        {"evidenceKind": "generated_answer"},
        {"unknown": "x"},
    ],
)
def test_invalid_evidence_has_no_storage_side_effect(finance_env, change):
    with pytest.raises(knowledge.TeamKnowledgeError):
        stage(finance_env, **change)
    assert (
        knowledge.get_financial_knowledge_base(agent_id=finance_env["owner"])[
            "knowledgeBase"
        ]
        is None
    )


def test_pending_source_is_separate_from_formal_knowledge_and_idempotent(finance_env):
    env = finance_env
    staged = stage(env)
    repeated = stage(env)
    assert staged["status"] == "pending_review"
    assert repeated["status"] == "already_staged"
    assert staged["source"]["inboxSourceId"] == repeated["source"]["inboxSourceId"]
    assert search(env)["status"] == "insufficient_evidence"
    assert (
        knowledge.list_knowledge_items(
            staged["knowledgeBase"]["scopedKnowledgeBaseId"], agent_id=env["owner"]
        )["items"]
        == []
    )
    assert (
        rag_vector_index_service.list_indexable_knowledge_items(agent_id=env["owner"])
        == []
    )


def test_reviewed_excerpt_uses_existing_rag_and_preserves_citations(finance_env):
    env = finance_env
    staged = stage(env)
    reviewed = review(env, staged)
    result = search(env)
    assert result["status"] == "found" and result["backend"] == "vibelution_local_rag"
    assert result["ragflowContacted"] is False
    assert (
        result["results"][0]["knowledgeItemId"]
        == reviewed["directIngestion"]["item"]["knowledgeItemId"]
    )
    citation = result["citations"][0]["financialEvidence"][0]
    assert citation == evidence()
    assert EXCERPT in result["results"][0]["excerpt"]
    base_id = staged["knowledgeBase"]["scopedKnowledgeBaseId"]
    generic = unified_knowledge_search_service.search_unified_memory(
        agent_id=env["owner"],
        query="营业收入",
        query_mode="rag",
        knowledge_base_id=base_id,
    )
    assert generic["citations"][0]["financialEvidence"][0]["page"] == 7
    assert (
        len(
            rag_vector_index_service.list_indexable_knowledge_items(
                agent_id=env["owner"]
            )
        )
        == 1
    )


@pytest.mark.parametrize(
    "omitted_fields",
    [("expiresAt",), ("supersedesSha256",), ("expiresAt", "supersedesSha256")],
)
def test_generic_inbox_optional_financial_metadata_remains_reviewable_and_searchable(
    finance_env, omitted_fields
):
    env = finance_env
    base = knowledge.get_financial_knowledge_base(
        agent_id=env["owner"], create_if_missing=True
    )["knowledgeBase"]
    raw_metadata = evidence()
    for field in omitted_fields:
        raw_metadata.pop(field)
    source = knowledge.collect_source_to_inbox(
        "agent",
        env["owner"],
        source_type="pdf_refinement",
        source_ref={"financialEvidence": raw_metadata},
        original_content=EXCERPT,
        actor_agent_id=env["owner"],
    )
    reviewed = review(env, {"source": source, "knowledgeBase": base})
    assert reviewed["source"]["status"] == "accepted"
    assert reviewed["centralSource"]["sourceRef"]["financialEvidence"] == raw_metadata
    result = search(env)
    assert result["status"] == "found"
    assert result["citations"][0]["financialEvidence"][0] == evidence()
    assert (
        result["results"][0]["knowledgeItemId"]
        == reviewed["directIngestion"]["item"]["knowledgeItemId"]
    )
    assert len(
        rag_vector_index_service.list_indexable_knowledge_items(agent_id=env["owner"])
    ) == 1


def test_explicit_company_period_and_memory_policy_limits(finance_env):
    env = finance_env
    staged = stage(env)
    review(env, staged)
    assert search(env, ticker="000001")["status"] == "insufficient_evidence"
    assert search(env, report_period="2024FY")["status"] == "insufficient_evidence"
    with pytest.raises(knowledge.TeamKnowledgePermissionError):
        search(env, allowed_knowledge_base_ids=["agent:someone:other-base"])
    assert search(env, agent_id=env["other"])["status"] == "not_initialized"
    denied = knowledge.search_knowledge_items(
        agent_id=env["other"],
        knowledge_base_id=staged["knowledgeBase"]["scopedKnowledgeBaseId"],
        query="营业收入",
    )
    assert denied["results"] == []


def test_generated_answer_cannot_be_direct_ingested_in_financial_profile(finance_env):
    env = finance_env
    staged = stage(env)
    with pytest.raises(
        knowledge.TeamKnowledgeError, match="match the reviewed original excerpt"
    ):
        review(
            env, staged, content="The generated answer is 999 and should be remembered."
        )
    inbox = knowledge.list_owner_source_inbox(
        "agent", env["owner"], agent_id=env["owner"]
    )
    assert inbox["sources"][0]["status"] == "pending"
    assert search(env)["status"] == "insufficient_evidence"


def test_generated_source_type_cannot_enter_financial_profile(finance_env):
    env = finance_env
    base = knowledge.get_financial_knowledge_base(
        agent_id=env["owner"], create_if_missing=True
    )["knowledgeBase"]
    source = knowledge.collect_source_to_inbox(
        "agent",
        env["owner"],
        source_type="agent_authored",
        source_ref={"agentId": env["owner"]},
        original_content="generated answer",
        actor_agent_id=env["owner"],
    )
    with pytest.raises(knowledge.TeamKnowledgeError, match="original PDF"):
        knowledge.review_owner_inbox_source(
            "agent",
            env["owner"],
            source["inboxSourceId"],
            decision="accepted",
            reviewed_by_agent_id=env["owner"],
            ingest_on_accept=True,
            knowledge_base_id=base["scopedKnowledgeBaseId"],
            knowledge_content="generated answer",
        )


def test_pending_replacement_does_not_hide_reviewed_version_but_approved_one_does(
    finance_env,
):
    env = finance_env
    original = stage(env)
    review(env, original)
    replacement = stage(
        env, documentSha256="b" * 64, reportVersion="amended", supersedesSha256="a" * 64
    )
    assert (
        search(env)["citations"][0]["financialEvidence"][0]["reportVersion"]
        == "original"
    )
    review(env, replacement)
    result = search(env)
    assert len(result["results"]) == 1
    assert result["citations"][0]["financialEvidence"][0]["reportVersion"] == "amended"
    assert (
        len(
            rag_vector_index_service.list_indexable_knowledge_items(
                agent_id=env["owner"]
            )
        )
        == 1
    )
    assert (
        len(
            knowledge.list_knowledge_items(
                original["knowledgeBase"]["scopedKnowledgeBaseId"],
                agent_id=env["owner"],
            )["items"]
        )
        == 2
    )


def test_expired_and_withdrawn_evidence_is_removed_from_generic_rag_and_index(
    finance_env,
):
    env = finance_env
    expired = stage(env, expiresAt="2026-04-01T00:00:00Z")
    review(env, expired)
    assert search(env)["status"] == "insufficient_evidence"
    active = stage(env, documentSha256="b" * 64, reportVersion="valid")
    reviewed = review(env, active)
    item_id = reviewed["directIngestion"]["item"]["knowledgeItemId"]
    assert search(env)["status"] == "found"
    knowledge.withdraw_financial_evidence(
        agent_id=env["owner"],
        knowledge_item_id=item_id,
        reason="Source withdrawn by issuer",
    )
    assert search(env)["status"] == "insufficient_evidence"
    assert (
        rag_vector_index_service.list_indexable_knowledge_items(agent_id=env["owner"])
        == []
    )
    assert rag_vector_index_service.list_indexable_knowledge_items(internal=True) == []
    generic = rag_retrieval_service.retrieve_rag_contexts(
        agent_id=env["owner"],
        query="营业收入",
        knowledge_base_id=active["knowledgeBase"]["scopedKnowledgeBaseId"],
    )
    assert generic["contexts"] == []


def test_archived_central_source_and_provenance_tampering_fail_closed(finance_env):
    env = finance_env
    staged = stage(env)
    reviewed = review(env, staged)
    central_id = reviewed["centralSource"]["centralSourceId"]
    records = knowledge._read_jsonl(knowledge._central_source_registry_path())
    row = next(x for x in records if x["centralSourceId"] == central_id)
    row["status"] = "archived"
    knowledge._write_jsonl(knowledge._central_source_registry_path(), records)
    assert search(env)["status"] == "insufficient_evidence"
    row["status"] = "active"
    row["sourceRef"]["financialEvidence"]["ticker"] = "000001"
    knowledge._write_jsonl(knowledge._central_source_registry_path(), records)
    assert search(env)["status"] == "insufficient_evidence"


def test_hard_delete_reuses_existing_preview_confirmation_and_does_not_recreate(
    finance_env,
):
    env = finance_env
    staged = stage(env)
    review(env, staged)
    target = {
        "targetType": "knowledge_base",
        "scopedKnowledgeBaseId": staged["knowledgeBase"]["scopedKnowledgeBaseId"],
    }
    preview = memory_cleanup_service.preview_memory_cleanup([target])
    with pytest.raises(memory_cleanup_service.MemoryCleanupError):
        memory_cleanup_service.execute_memory_cleanup(
            [target], confirmation_phrase="wrong", preview_token=preview["previewToken"]
        )
    assert search(env)["status"] == "found"
    memory_cleanup_service.execute_memory_cleanup(
        [target],
        confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
        preview_token=preview["previewToken"],
    )
    assert search(env)["status"] == "not_initialized"
    assert (
        rag_vector_index_service.list_indexable_knowledge_items(agent_id=env["owner"])
        == []
    )


def test_withdrawing_a_replacement_does_not_resurrect_superseded_evidence(finance_env):
    env = finance_env
    first = stage(env)
    review(env, first)
    second = stage(
        env, documentSha256="b" * 64, reportVersion="amended", supersedesSha256="a" * 64
    )
    reviewed = review(env, second)
    knowledge.withdraw_financial_evidence(
        agent_id=env["owner"],
        knowledge_item_id=reviewed["directIngestion"]["item"]["knowledgeItemId"],
        reason="Correction withdrawn",
    )
    assert search(env)["status"] == "insufficient_evidence"
    assert (
        rag_vector_index_service.list_indexable_knowledge_items(agent_id=env["owner"])
        == []
    )


def test_project_storage_boundary_does_not_expose_another_projects_financial_library(
    finance_env, monkeypatch, tmp_path
):
    env = finance_env
    first = stage(env)
    review(env, first)
    second_root = tmp_path / "separate-project"
    second_root.mkdir()
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(second_root))
    for service in (
        agent_directory_service,
        chat_room_service,
        memory_cleanup_service,
        memory_service,
        rag_vector_index_service,
        knowledge,
        team_service,
    ):
        monkeypatch.setattr(service, "PROJECT_ROOT", second_root)
    another = agent_directory_service.create_agent_instance(
        display_name="Finance other project",
        direct_session_id="different-project-session",
    )
    assert (
        knowledge.get_financial_knowledge_base(agent_id=another["agentId"])[
            "knowledgeBase"
        ]
        is None
    )
    assert (
        knowledge.search_knowledge_items(agent_id=another["agentId"], query="营业收入")[
            "results"
        ]
        == []
    )


def test_conflicting_caller_tags_cannot_override_financial_company_scope(finance_env):
    env = finance_env
    staged = stage(env)
    knowledge.review_owner_inbox_source(
        "agent",
        env["owner"],
        staged["source"]["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=env["owner"],
        ingest_on_accept=True,
        knowledge_base_id=staged["knowledgeBase"]["scopedKnowledgeBaseId"],
        knowledge_content=EXCERPT,
        tags=["finance-ticker:000001", "finance-period:2024fy", "user-note"],
    )
    assert search(env)["status"] == "found"
    assert search(env, ticker="000001")["status"] == "insufficient_evidence"
    assert search(env, report_period="2024FY")["status"] == "insufficient_evidence"


def test_generated_titles_and_summaries_are_not_projected_as_financial_facts(
    finance_env,
):
    env = finance_env
    staged = stage(env)
    knowledge.review_owner_inbox_source(
        "agent",
        env["owner"],
        staged["source"]["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=env["owner"],
        ingest_on_accept=True,
        knowledge_base_id=staged["knowledgeBase"]["scopedKnowledgeBaseId"],
        knowledge_content=EXCERPT,
        knowledge_title="Generated income is 999999",
        knowledge_summary="Made-up net income 999999",
    )
    result = search(env)
    assert result["status"] == "found"
    assert "999999" not in str(result)
    assert EXCERPT in result["results"][0]["excerpt"]
    indexable = rag_vector_index_service.list_indexable_knowledge_items(
        agent_id=env["owner"]
    )
    assert len(indexable) == 1 and "999999" not in str(indexable)


def test_explicit_restage_after_hard_delete_requires_a_fresh_review(finance_env):
    env = finance_env
    old = stage(env)
    review(env, old)
    target = {
        "targetType": "knowledge_base",
        "scopedKnowledgeBaseId": old["knowledgeBase"]["scopedKnowledgeBaseId"],
    }
    preview = memory_cleanup_service.preview_memory_cleanup([target])
    memory_cleanup_service.execute_memory_cleanup(
        [target],
        confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
        preview_token=preview["previewToken"],
    )
    new = stage(env)
    assert new["status"] == "pending_review"
    assert new["source"]["inboxSourceId"] != old["source"]["inboxSourceId"]
    assert search(env)["status"] == "insufficient_evidence"
    review(env, new)
    assert search(env)["status"] == "found"


def test_native_deprecated_rating_excludes_financial_evidence(finance_env):
    env = finance_env
    staged = stage(env)
    reviewed = review(env, staged)
    knowledge.update_knowledge_item_rating(
        staged["knowledgeBase"]["scopedKnowledgeBaseId"],
        reviewed["directIngestion"]["item"]["knowledgeItemId"],
        actor_agent_id=env["owner"],
        stability="deprecated",
        marking_reason="Obsolete source",
    )
    assert search(env)["status"] == "insufficient_evidence"
    assert (
        rag_vector_index_service.list_indexable_knowledge_items(agent_id=env["owner"])
        == []
    )
