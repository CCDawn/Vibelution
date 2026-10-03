# -*- coding: utf-8 -*-
"""模型体检「发现 vs 声明」失配告警的聚焦测试。

覆盖四类断言：
1. catalog 有实证且与条目声明不一致 → findings 出现明确告警（声明值 vs 实证值
   + 以声明为准）与结构化 discoveryMismatches。
2. 双侧一致 → 无失配告警。
3. catalog 无该模型记录 / 无可比字段 → 不算失配，不产生告警。
4. operator 声明永远赢：告警不改写生效配置里的任何值，运行时解析仍以声明为准。
"""

import copy

from config.public_config import build_effective_config
from core.llm.discovery import doctor_model_library, discover_model


def _base_config():
    return build_effective_config(
        {
            "llm": {
                "schema_version": 2,
                "providers": {
                    "default": {
                        "label": "Test Provider",
                        "service_class": "local_runtime",
                        "vendor": "custom",
                        "driver": "openai",
                        "base_url": "http://localhost:8000/v1",
                        "auth_kind": "none",
                        "credential_ref": "none",
                        "requires_credential": False,
                        "compat_mode": "native",
                        "context_window": 65536,
                        "protocols": {
                            "default": "chat_completions",
                            "allowed": ["chat_completions", "responses"],
                        },
                        "models": {
                            "good-model": {
                                "upstream_id": "good-model",
                                "label": "Good Model",
                                "enabled": True,
                            },
                            "off-model": {
                                "upstream_id": "off-model",
                                "label": "Off Model",
                                "enabled": False,
                            },
                        },
                    }
                },
                "profiles": {"primary": {"model_ref": "default/good-model"}},
            }
        }
    )


def _catalog_state(models):
    return {
        "schemaVersion": 2,
        "metadata": {},
        "providers": {
            "default": {
                "providerFingerprint": "fp-1",
                "status": "reachable",
                "catalogStale": False,
                "models": models,
                "warnings": [],
            }
        },
    }


def _catalog_model(**overrides):
    record = {
        "upstreamId": "good-model",
        "label": "Good Model",
        "availability": "pinned",
        "capabilities": {},
        "limits": {},
    }
    record.update(overrides)
    return record


def _bind_catalog(monkeypatch, models):
    monkeypatch.setattr(
        "core.llm.discovery.load_model_catalog_state",
        lambda *args, **kwargs: _catalog_state(models),
    )


def _finding(findings, model_id):
    for finding in findings:
        if finding["modelId"] == model_id:
            return finding
    return None


# ---------------------------------------------------------------------------
# 1. 失配 → 告警 + 结构化明细
# ---------------------------------------------------------------------------


def test_context_window_mismatch_warns_with_declaration_wins(monkeypatch):
    config = _base_config()
    config.llm.model_library["default/good-model"]["context_window"] = 128000
    _bind_catalog(
        monkeypatch,
        {"good-model": _catalog_model(limits={"context_window": 200000})},
    )

    findings = doctor_model_library(config)

    finding = _finding(findings, "default/good-model")
    assert finding is not None
    assert any(
        "128000" in item and "200000" in item and "以声明为准" in item
        for item in finding["warnings"]
    )
    assert finding["discoveryMismatches"] == [
        {
            "field": "context_window",
            "declared": 128000,
            "discovered": 200000,
            "discoveredSource": "provider_discovery",
        }
    ]


def test_capability_mismatch_warns_against_empirical_probe(monkeypatch):
    config = _base_config()
    config.llm.model_library["default/good-model"]["capabilities"] = {
        "supports_image_input": True
    }
    _bind_catalog(
        monkeypatch,
        {
            "good-model": _catalog_model(
                capabilities={
                    "image_input": {
                        "value": "unsupported",
                        "source": "runtime_probe",
                        "confidence": "",
                        "checked_at": "2026-10-02T15:46:50Z",
                        "error": "",
                    }
                },
            )
        },
    )

    findings = doctor_model_library(config)

    finding = _finding(findings, "default/good-model")
    assert finding is not None
    assert any(
        "supports_image_input" in item and "以声明为准" in item
        for item in finding["warnings"]
    )
    assert finding["discoveryMismatches"] == [
        {
            "field": "supports_image_input",
            "declared": True,
            "discovered": "unsupported",
            "discoveredSource": "runtime_probe",
        }
    ]


def test_disabled_entry_with_mismatch_stays_silent(monkeypatch):
    """disabled 条目不参与体检：即使 catalog 有失配实证也不产生 finding。"""
    config = _base_config()
    config.llm.model_library["default/off-model"]["context_window"] = 128000
    _bind_catalog(
        monkeypatch,
        {
            "good-model": _catalog_model(),
            "off-model": _catalog_model(limits={"context_window": 4096}),
        },
    )

    findings = doctor_model_library(config)

    assert _finding(findings, "default/off-model") is None


# ---------------------------------------------------------------------------
# 2. 一致 → 无告警
# ---------------------------------------------------------------------------


def test_matching_context_window_produces_no_mismatch(monkeypatch):
    config = _base_config()
    config.llm.model_library["default/good-model"]["context_window"] = 200000
    _bind_catalog(
        monkeypatch,
        {"good-model": _catalog_model(limits={"context_window": 200000})},
    )

    findings = doctor_model_library(config)

    assert _finding(findings, "default/good-model") is None


def test_matching_capability_produces_no_mismatch(monkeypatch):
    config = _base_config()
    config.llm.model_library["default/good-model"]["capabilities"] = {
        "supports_image_input": False
    }
    _bind_catalog(
        monkeypatch,
        {
            "good-model": _catalog_model(
                capabilities={
                    "image_input": {
                        "value": "unsupported",
                        "source": "provider_endpoint",
                        "confidence": "",
                        "checked_at": "2026-10-02T15:46:50Z",
                        "error": "",
                    }
                },
            )
        },
    )

    findings = doctor_model_library(config)

    assert _finding(findings, "default/good-model") is None


# ---------------------------------------------------------------------------
# 3. catalog 无记录 / 无实证 / 仅声明镜像 → 不算失配
# ---------------------------------------------------------------------------


def test_missing_catalog_record_is_not_a_mismatch(monkeypatch):
    config = _base_config()
    config.llm.model_library["default/good-model"]["context_window"] = 128000
    _bind_catalog(monkeypatch, {})

    findings = doctor_model_library(config)

    finding = _finding(findings, "default/good-model")
    assert finding is None


def test_unknown_empirical_value_is_not_a_mismatch(monkeypatch):
    """catalog 有记录但实证值为 unknown → 无法断言失配，不告警（宁缺勿滥）。"""
    config = _base_config()
    config.llm.model_library["default/good-model"]["capabilities"] = {
        "supports_image_input": True
    }
    _bind_catalog(
        monkeypatch,
        {
            "good-model": _catalog_model(
                capabilities={
                    "image_input": {
                        "value": "unknown",
                        "source": "runtime_probe",
                        "confidence": "",
                        "checked_at": "2026-10-02T15:46:50Z",
                        "error": "timeout",
                    }
                },
            )
        },
    )

    findings = doctor_model_library(config)

    finding = _finding(findings, "default/good-model")
    assert finding is None


def test_operator_override_mirror_is_not_compared(monkeypatch):
    """catalog 里 operator_override 来源的记录是声明自己的镜像，不与声明比对。"""
    config = _base_config()
    config.llm.model_library["default/good-model"]["capabilities"] = {
        "supports_image_input": True
    }
    _bind_catalog(
        monkeypatch,
        {
            "good-model": _catalog_model(
                capabilities={
                    "image_input": {
                        "value": "unsupported",
                        "source": "operator_override",
                        "confidence": "",
                        "checked_at": "2026-10-02T15:46:50Z",
                        "error": "",
                    }
                },
            )
        },
    )

    findings = doctor_model_library(config)

    finding = _finding(findings, "default/good-model")
    assert finding is None


def test_catalog_without_limits_leaves_window_fallback_intact(monkeypatch):
    """catalog 记录存在但无 limits → context_window 走 provider 兜底，不算失配。"""
    config = _base_config()
    config.llm.model_library["default/good-model"]["context_window"] = 0
    _bind_catalog(monkeypatch, {"good-model": _catalog_model()})

    findings = doctor_model_library(config)

    finding = _finding(findings, "default/good-model")
    # provider context_window=65536 兜底生效 → 连「未配置」告警都不该有。
    assert finding is None


# ---------------------------------------------------------------------------
# 4. operator 声明永远赢：告警不改写任何值
# ---------------------------------------------------------------------------


def test_warnings_do_not_mutate_entry(monkeypatch):
    config = _base_config()
    config.llm.model_library["default/good-model"]["context_window"] = 128000
    config.llm.model_library["default/good-model"]["capabilities"] = {
        "supports_image_input": True
    }
    _bind_catalog(
        monkeypatch,
        {
            "good-model": _catalog_model(
                limits={"context_window": 200000},
                capabilities={
                    "image_input": {
                        "value": "unsupported",
                        "source": "runtime_probe",
                        "confidence": "",
                        "checked_at": "2026-10-02T15:46:50Z",
                        "error": "",
                    }
                },
            )
        },
    )
    snapshot = copy.deepcopy(config.llm.model_library["default/good-model"])

    findings = doctor_model_library(config)

    assert _finding(findings, "default/good-model") is not None
    assert config.llm.model_library["default/good-model"] == snapshot


def test_declaration_still_wins_at_runtime_resolution(monkeypatch):
    """失配被点名后，运行时解析仍以条目声明为准（context_window_source=model_library）。"""
    config = _base_config()
    config.llm.model_library["default/good-model"]["context_window"] = 128000
    _bind_catalog(
        monkeypatch,
        {"good-model": _catalog_model(limits={"context_window": 200000})},
    )

    findings = doctor_model_library(config)
    assert _finding(findings, "default/good-model") is not None

    spec = discover_model(config, "primary")
    assert spec.context_window == 128000
    assert spec.provider_details["context_window_source"] == "model_library"
