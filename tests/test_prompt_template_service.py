from pathlib import Path

from core.web.services import prompt_template_service


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)


def test_prompt_template_registry_repairs_research_defaults(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    payload = prompt_template_service.list_prompt_templates()
    research_template_ids = {item["promptTemplateId"] for item in payload["templates"] if item["category"] == "research"}
    template_ids = {item["promptTemplateId"] for item in payload["templates"]}

    broad = next(item for item in payload["templates"] if item["promptTemplateId"] == "prompt-research-broad")
    assert {
        "prompt-research-ceo",
        "prompt-research-organization-advisor",
        "prompt-research-capability-steward",
        "prompt-research-broad",
        "prompt-research-deep",
        "prompt-research-review",
        "prompt-research-themes",
        "prompt-research-card",
        "prompt-challenge-cup-data-discovery",
        "prompt-challenge-cup-source-acquisition",
        "prompt-challenge-cup-content-extraction",
        "prompt-challenge-cup-source-quality",
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
    discovery_detail = prompt_template_service.get_prompt_template("prompt-challenge-cup-data-discovery")
    assert discovery_detail is not None
    assert discovery_detail["metadata"]["roleKey"] == "challenge_cup_data_discovery"
    assert "web_search_tool" in discovery_detail["content"]
    assert "不调用 web_fetch_tool" in discovery_detail["content"]
    acquisition_detail = prompt_template_service.get_prompt_template("prompt-challenge-cup-source-acquisition")
    assert acquisition_detail is not None
    assert "web_fetch_tool" in acquisition_detail["content"]
    extraction_detail = prompt_template_service.get_prompt_template("prompt-challenge-cup-content-extraction")
    assert extraction_detail is not None
    assert "不直接写正式 Team Knowledge" in extraction_detail["content"]
    coordinator_detail = prompt_template_service.get_prompt_template("prompt-challenge-cup-coordinator")
    assert coordinator_detail is not None
    assert coordinator_detail["category"] == "chat"
    assert "不具备直接联网搜索" in coordinator_detail["content"]
    assert (tmp_path / "workspace" / "agent_config" / "prompt_templates.json").exists()
    assert (tmp_path / "workspace" / "prompts" / "research" / "ceo.md").exists()
    assert (tmp_path / "workspace" / "prompts" / "research" / "organization_advisor.md").exists()
    assert (tmp_path / "workspace" / "prompts" / "research" / "capability_steward.md").exists()
    assert (tmp_path / "workspace" / "prompts" / "research" / "challenge_cup_data_discovery.md").exists()


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
    assert "open_evolution_transaction_tool" in supervised["contextBlock"]
    assert "close_evolution_transaction_tool" in supervised["contextBlock"]
    assert supervised["sourcePath"] == ""
    assert supervised["sourceExists"] is False
    judge = prompt_template_service.get_prompt_template("prompt-supervised-judge")
    assert judge is not None
    assert "不调用 spawn_agent_tool" in judge["content"]
    assert "SUPERVISED_AGENT_JUDGMENT" in judge["content"]
    assert missing["reason"] == "missing_template"
    assert missing["promptTemplateId"] == "prompt-missing-valid"


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
