from pathlib import Path
import re

from core.web.services import prompt_template_service


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)


def _contains_tool_name(content: str, tool_name: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(tool_name)}(?![A-Za-z0-9_])", content) is not None


def test_prompt_template_registry_repairs_research_defaults(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    payload = prompt_template_service.list_prompt_templates()
    research_template_ids = {item["promptTemplateId"] for item in payload["templates"] if item["category"] == "research"}
    template_ids = {item["promptTemplateId"] for item in payload["templates"]}

    broad = next(item for item in payload["templates"] if item["promptTemplateId"] == "prompt-research-broad")
    assert {
        "prompt-ai-search-scope-lead",
        "prompt-ai-search-global-primary-sources",
        "prompt-ai-search-cn-primary-sources",
        "prompt-ai-search-signal-quality-gate",
        "prompt-research-ceo",
        "prompt-research-organization-advisor",
        "prompt-research-capability-steward",
        "prompt-research-broad",
        "prompt-research-deep",
        "prompt-research-review",
        "prompt-research-themes",
        "prompt-research-card",
        "prompt-source-finder",
        "prompt-source-extractor",
        "prompt-source-relation-mapper",
        "prompt-source-ingestor",
    } <= research_template_ids
    assert "prompt-challenge-cup-coordinator" in template_ids
    assert broad["category"] == "research"
    assert broad["sourcePath"] == "workspace/prompts/research/broad.md"
    assert broad["sourceExists"] is True
    assert broad["content"] == ""
    assert "广撒网探索 agent" in broad["contentPreview"]
    assert broad["contentHash"].startswith("sha256:")
    detail = prompt_template_service.get_prompt_template("prompt-research-broad")
    assert detail is not None
    assert "广撒网探索 agent" in detail["content"]
    ceo_detail = prompt_template_service.get_prompt_template("prompt-research-ceo")
    assert ceo_detail is not None
    assert ceo_detail["metadata"]["roleKey"] == "research_ceo"
    assert "科研 CEO agent" in ceo_detail["content"]
    assert "research_proposal_apply_tool" in ceo_detail["content"]
    assert "没有状态变化时不发送" in ceo_detail["content"]
    advisor_detail = prompt_template_service.get_prompt_template("prompt-research-organization-advisor")
    assert advisor_detail is not None
    assert advisor_detail["metadata"]["roleKey"] == "research_organization_advisor"
    assert "组织顾问 agent" in advisor_detail["content"]
    assert "research_proposal_apply_tool" in advisor_detail["content"]
    assert "pending create_agent proposal" in advisor_detail["content"]
    steward_detail = prompt_template_service.get_prompt_template("prompt-research-capability-steward")
    assert steward_detail is not None
    assert steward_detail["metadata"]["roleKey"] == "research_capability_steward"
    assert "能力管家 agent" in steward_detail["content"]
    assert "research_proposal_apply_tool" in steward_detail["content"]
    assert "Tool Plan" in steward_detail["content"]
    assert "ToolPolicy.allowedTools" not in steward_detail["content"]
    knowledge_steward_detail = prompt_template_service.get_prompt_template("prompt-knowledge-steward")
    assert knowledge_steward_detail is not None
    assert knowledge_steward_detail["metadata"]["roleKey"] == "knowledge_steward"
    assert "只处理已通过资料提炼复核" in knowledge_steward_detail["content"]
    assert "不要推断截断或隐藏候选" in knowledge_steward_detail["content"]
    source_finder = prompt_template_service.get_prompt_template("prompt-source-finder")
    assert source_finder is not None
    assert source_finder["metadata"]["roleKey"] == "source_finder"
    assert _contains_tool_name(source_finder["content"], "source_collection_context_tool")
    assert _contains_tool_name(source_finder["content"], "source_collection_stage_writeback_tool")
    assert "搜索、获取、下载到本地" in source_finder["content"]
    assert "无效来源" in source_finder["content"]
    source_extractor = prompt_template_service.get_prompt_template("prompt-source-extractor")
    assert source_extractor is not None
    assert source_extractor["metadata"]["roleKey"] == "source_extractor"
    assert "candidate_offset" in source_extractor["content"]
    assert "candidate_limit" in source_extractor["content"]
    assert "context_mode=compact" in source_extractor["content"]
    assert "candidateExtractions" in source_extractor["content"]
    assert "candidateDecisions" in source_extractor["content"]
    assert "不能根据截断上下文猜结果" in source_extractor["content"]
    source_relation_mapper = prompt_template_service.get_prompt_template("prompt-source-relation-mapper")
    assert source_relation_mapper is not None
    assert source_relation_mapper["metadata"]["roleKey"] == "source_relation_mapper"
    assert "候选级主题、来源和证据关系" in source_relation_mapper["content"]
    assert "不写正式知识库" in source_relation_mapper["content"]
    source_ingestor = prompt_template_service.get_prompt_template("prompt-source-ingestor")
    assert source_ingestor is not None
    assert source_ingestor["metadata"]["roleKey"] == "source_ingestor"
    assert "正式 Team Knowledge" in source_ingestor["content"]
    assert "materializedKnowledgeIngestion.status=completed" in source_ingestor["content"]
    coordinator_detail = prompt_template_service.get_prompt_template("prompt-challenge-cup-coordinator")
    assert coordinator_detail is not None
    assert coordinator_detail["category"] == "chat"
    assert "不直接执行公开搜索" in coordinator_detail["content"]
    assert not _contains_tool_name(coordinator_detail["content"], "batch_web_search_tool")
    assert not _contains_tool_name(coordinator_detail["content"], "web_fetch_tool")
    operation_chat = prompt_template_service.get_prompt_template("prompt-chat-operation-default")
    assert operation_chat is not None
    assert operation_chat["category"] == "chat"
    assert operation_chat["metadata"]["roleKey"] == "operation_chat"
    assert "默认操作型会话 Agent" in operation_chat["content"]
    assert "rg" in operation_chat["content"]
    assert _contains_tool_name(operation_chat["content"], "apply_patch_tool")
    assert _contains_tool_name(operation_chat["content"], "run_test_for_tool")
    search_scope = prompt_template_service.get_prompt_template("prompt-ai-search-scope-lead")
    assert search_scope is not None
    assert search_scope["metadata"]["roleKey"] == "ai_search_scope_lead"
    assert "source tier" in search_scope["content"]
    assert "[搜索质量不足]" in search_scope["content"]
    cn_sources = prompt_template_service.get_prompt_template("prompt-ai-search-cn-primary-sources")
    assert cn_sources is not None
    assert cn_sources["metadata"]["roleKey"] == "cn_primary_sources"
    assert "中国官方源" in cn_sources["content"]
    assert not _contains_tool_name(cn_sources["content"], "paper_search_tool")
    signal_gate = prompt_template_service.get_prompt_template("prompt-ai-search-signal-quality-gate")
    assert signal_gate is not None
    assert signal_gate["metadata"]["roleKey"] == "signal_quality_gate"
    assert "不得把社区信号当成事实结论" in signal_gate["content"]
    assert (tmp_path / "workspace" / "agent_config" / "prompt_templates.json").exists()
    assert (tmp_path / "workspace" / "prompts" / "research" / "ceo.md").exists()
    assert (tmp_path / "workspace" / "prompts" / "research" / "organization_advisor.md").exists()
    assert (tmp_path / "workspace" / "prompts" / "research" / "capability_steward.md").exists()
    assert (tmp_path / "workspace" / "prompts" / "research" / "source_finder.md").exists()
    assert (tmp_path / "workspace" / "prompts" / "research" / "source_extractor.md").exists()
    assert (tmp_path / "workspace" / "prompts" / "research" / "source_relation_mapper.md").exists()
    assert (tmp_path / "workspace" / "prompts" / "research" / "source_ingestor.md").exists()
    supervised_baseline = prompt_template_service.get_prompt_template("prompt-supervised-baseline")
    assert supervised_baseline is not None
    assert supervised_baseline["metadata"]["builtinContentVersion"] == prompt_template_service.CHALLENGE_CUP_STAGE_TASK_PROMPT_VERSION
    assert "当前默认无工具权限" in supervised_baseline["content"]
    assert not _contains_tool_name(supervised_baseline["content"], "open_evolution_transaction_tool")


def test_source_collection_prompt_templates_only_expose_four_stage_roles(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    payload = prompt_template_service.list_prompt_templates()
    role_keys = {
        item.get("metadata", {}).get("roleKey")
        for item in payload["templates"]
        if isinstance(item.get("metadata"), dict)
    }

    assert {
        "source_finder",
        "source_extractor",
        "source_relation_mapper",
        "source_ingestor",
    }.issubset(role_keys)
    assert {
        "challenge_cup_source_acquisition",
        "challenge_cup_data_discovery",
        "challenge_cup_content_extraction",
        "challenge_cup_source_quality",
        "knowledge_expansion_source_intake",
        "knowledge_expansion_content_extraction",
        "knowledge_expansion_source_quality",
        "knowledge_expansion_candidate_graph",
        "candidate_graph",
    }.isdisjoint(role_keys)


def test_prompt_template_repair_upgrades_builtin_challenge_stage_prompt_content(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    prompt_template_service.repair_prompt_templates()

    prompt_template_service.update_prompt_template(
        "prompt-source-extractor",
        content="# 旧资料提炼提示词\n\n没有阶段任务协议。",
        metadata={
            "builtin": True,
            "roleKey": "source_extractor",
            "builtinContentVersion": 1,
        },
    )

    prompt_template_service.repair_prompt_templates()
    detail = prompt_template_service.get_prompt_template("prompt-source-extractor")

    assert detail["metadata"]["builtinContentVersion"] == prompt_template_service.CHALLENGE_CUP_STAGE_TASK_PROMPT_VERSION
    assert "资料提炼阶段" in detail["content"]
    assert "source_collection_stage_writeback_tool" in detail["content"]
    assert "candidateExtractions" in detail["content"]
    source_content = (tmp_path / "workspace" / "prompts" / "research" / "source_extractor.md").read_text(encoding="utf-8")
    assert "资料提炼阶段" in source_content
    assert "没有阶段任务协议" not in source_content


def test_source_extractor_prompt_requires_candidate_paging_and_structured_decisions(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    prompt_template_service.repair_prompt_templates()

    detail = prompt_template_service.get_prompt_template("prompt-source-extractor")

    assert "candidate_offset" in detail["content"]
    assert "candidate_limit" in detail["content"]
    assert "candidateExtractions" in detail["content"]
    assert "candidateDecisions" in detail["content"]
    assert "candidateId" in detail["content"]
    assert "待补读、待补审" in detail["content"]
    assert "资料入库/知识库管理员" not in detail["content"]
    assert "无有效内容" in detail["content"]


def test_challenge_cup_source_collection_contract_names_source_ingestor_as_ingestion_owner():
    repo_root = Path(__file__).resolve().parents[1]
    agent_directory_source = (repo_root / "core" / "web" / "services" / "agent_directory_service.py").read_text(encoding="utf-8")
    prompt_template_source = (repo_root / "core" / "web" / "services" / "prompt_template_service.py").read_text(encoding="utf-8")
    team_service_source = (repo_root / "core" / "web" / "services" / "team_service.py").read_text(encoding="utf-8")
    flow_builder_source = (repo_root / "挑战杯" / "build_research_flow_site.mjs").read_text(encoding="utf-8")

    assert "资料入库/知识库管理员" not in agent_directory_source
    assert "source_ingestor 做最终入库审核" in agent_directory_source
    assert "data_discovery、source_acquisition、content_extraction、source_quality" not in prompt_template_source
    assert "source_finder、source_extractor、source_relation_mapper 和 source_ingestor" in prompt_template_source
    assert "组织资料寻找、资料提炼、资料关系整理和资料入库。" in team_service_source
    assert "组织资料发现、本地导入、资料提炼、质检、候选关系和知识库管理员入库。" not in team_service_source
    assert "source_ingestor" in flow_builder_source
    assert "知识库管理员只提交建议与待审对象" not in flow_builder_source
    assert "proposal_and_rating_suggestion_only" not in flow_builder_source


def test_prompt_template_registry_repairs_challenge_cup_experiment_iteration_roles(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    prompt_template_service.repair_prompt_templates()

    cases = {
        "prompt-challenge-cup-experiment-planner": (
            "challenge_cup_experiment_planner",
            "challenge_cup_experiment_context_tool",
            "challenge_cup_experiment_writeback_tool",
            "不自动执行训练",
        ),
        "prompt-challenge-cup-experiment-ledger": (
            "challenge_cup_experiment_ledger",
            "challenge_cup_experiment_context_tool",
            "challenge_cup_experiment_writeback_tool",
            "只登记证据账本",
        ),
        "prompt-challenge-cup-iteration-planner": (
            "challenge_cup_iteration_planner",
            "challenge_cup_iteration_context_tool",
            "challenge_cup_iteration_writeback_tool",
            "Research Loop",
        ),
        "prompt-challenge-cup-versioning": (
            "challenge_cup_versioning",
            "challenge_cup_versioning_context_tool",
            "challenge_cup_versioning_writeback_tool",
            "versionHistory",
        ),
    }
    for template_id, (role_key, read_tool, write_tool, required_text) in cases.items():
        detail = prompt_template_service.get_prompt_template(template_id)
        assert detail is not None
        assert detail["category"] == "research"
        assert detail["metadata"]["roleKey"] == role_key
        assert detail["metadata"]["builtinContentVersion"] == prompt_template_service.CHALLENGE_CUP_STAGE_TASK_PROMPT_VERSION
        assert _contains_tool_name(detail["content"], read_tool)
        assert _contains_tool_name(detail["content"], write_tool)
        assert required_text in detail["content"]
        assert not _contains_tool_name(detail["content"], "web_search_tool")

    assert (tmp_path / "workspace" / "prompts" / "research" / "challenge_cup_experiment_planner.md").exists()
    assert (tmp_path / "workspace" / "prompts" / "research" / "challenge_cup_versioning.md").exists()


def test_prompt_template_update_writes_source_and_refreshes_hash(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    prompt_template_service.repair_prompt_templates()

    updated = prompt_template_service.update_prompt_template(
        "prompt-research-broad",
        content="# 新广搜提示词\n\nhi",
        metadata={"usage": "test"},
    )

    assert updated["content"] == "# 新广搜提示词\n\nhi"
    assert updated["metadata"]["usage"] == "test"
    assert updated["contentHash"].startswith("sha256:")
    assert (tmp_path / updated["sourcePath"]).read_text(encoding="utf-8") == "# 新广搜提示词\n\nhi"


def test_build_agent_prompt_template_context_reports_block_and_missing_reasons(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    prompt_template_service.repair_prompt_templates()

    block = prompt_template_service.build_agent_prompt_template_context(
        "prompt-research-broad",
        project_root=tmp_path,
    )
    supervised = prompt_template_service.build_agent_prompt_template_context(
        "prompt-supervised-baseline",
        project_root=tmp_path,
    )
    missing = prompt_template_service.build_agent_prompt_template_context(
        "prompt-missing-valid",
        project_root=tmp_path,
    )

    assert block["reason"] == ""
    assert "Agent Prompt Template" in block["contextBlock"]
    assert "PromptTemplateId: prompt-research-broad" in block["contextBlock"]
    assert "广撒网探索 agent" in block["contextBlock"]
    assert supervised["reason"] == ""
    assert "PromptTemplateId: prompt-supervised-baseline" in supervised["contextBlock"]
    assert "监督进化基线 Agent" in supervised["contextBlock"]
    assert "open_evolution_transaction_tool" not in supervised["contextBlock"]
    assert "close_evolution_transaction_tool" not in supervised["contextBlock"]
    assert "当前默认无工具权限" in supervised["contextBlock"]
    assert supervised["sourcePath"] == ""
    assert supervised["sourceExists"] is False
    judge = prompt_template_service.get_prompt_template("prompt-supervised-judge")
    assert judge is not None
    assert "不调用 spawn_agent_tool" in judge["content"]
    assert "SUPERVISED_AGENT_JUDGMENT" in judge["content"]
    assert missing["reason"] == "missing_template"
    assert missing["promptTemplateId"] == "prompt-missing-valid"


def test_build_agent_prompt_snapshot_freezes_template_content(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    prompt_template_service.update_prompt_template(
        "prompt-chat-custom",
        name="自定义会话提示词",
        category="chat",
        source_path="workspace/prompts/chat/custom.md",
        content="第一版固定提示词。",
    )

    snapshot = prompt_template_service.build_agent_prompt_snapshot(
        "prompt-chat-custom",
        agent_id="agent-1",
        agent_code="chat_agent",
        agent_display_name="会话 Agent",
        project_root=tmp_path,
    )
    prompt_template_service.update_prompt_template(
        "prompt-chat-custom",
        content="第二版提示词，不应该影响已有会话。",
    )
    current = prompt_template_service.build_agent_prompt_snapshot(
        "prompt-chat-custom",
        agent_id="agent-1",
        project_root=tmp_path,
    )

    assert snapshot["reason"] == ""
    assert snapshot["promptTemplateId"] == "prompt-chat-custom"
    assert snapshot["content"] == "第一版固定提示词。"
    assert snapshot["contentHash"].startswith("sha256:")
    assert snapshot["agentId"] == "agent-1"
    assert snapshot["agentCode"] == "chat_agent"
    assert current["content"] == "第二版提示词，不应该影响已有会话。"
    assert current["contentHash"] != snapshot["contentHash"]
    system_block = prompt_template_service.render_agent_prompt_snapshot_system_block(snapshot)
    assert "Agent System Prompt Snapshot" in system_block
    assert "PromptTemplateId: prompt-chat-custom" in system_block
    assert "第一版固定提示词。" in system_block
    assert "第二版提示词" not in system_block


def test_build_agent_prompt_snapshot_reports_missing_and_empty(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    prompt_template_service.update_prompt_template(
        "prompt-chat-empty",
        name="空提示词",
        category="chat",
        content="",
    )

    missing = prompt_template_service.build_agent_prompt_snapshot("prompt-missing-valid", project_root=tmp_path)
    empty = prompt_template_service.build_agent_prompt_snapshot("prompt-chat-empty", project_root=tmp_path)

    assert missing["reason"] == "missing_template"
    assert missing["promptTemplateId"] == "prompt-missing-valid"
    assert empty["reason"] == "empty_template_content"
    assert empty["content"] == ""
    assert prompt_template_service.render_agent_prompt_snapshot_system_block(empty) == ""


def test_prompt_template_rejects_unsafe_source_path(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    prompt_template_service.repair_prompt_templates()

    try:
        prompt_template_service.update_prompt_template(
            "prompt-research-broad",
            source_path=str(Path(tmp_path).parent / "outside.md"),
        )
    except prompt_template_service.PromptTemplateError as exc:
        assert "source" in str(exc)
    else:
        raise AssertionError("Expected unsafe prompt template source path to fail")
