from pathlib import Path

from core.web.services import prompt_template_service


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)


def test_prompt_template_registry_repairs_research_defaults(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    payload = prompt_template_service.list_prompt_templates()

    broad = next(item for item in payload["templates"] if item["promptTemplateId"] == "prompt-research-broad")
    assert broad["category"] == "research"
    assert broad["sourcePath"] == "workspace/prompts/research/broad.md"
    assert broad["sourceExists"] is True
    assert broad["content"] == ""
    assert "广撒网探索 agent" in broad["contentPreview"]
    assert broad["contentHash"].startswith("sha256:")
    detail = prompt_template_service.get_prompt_template("prompt-research-broad")
    assert detail is not None
    assert "广撒网探索 agent" in detail["content"]
    assert (tmp_path / "workspace" / "agent_config" / "prompt_templates.json").exists()


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
