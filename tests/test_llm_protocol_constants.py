# -*- coding: utf-8 -*-
"""Anti-drift guards for core/llm/protocol_constants.py.

Reasoning/protocol constants used to exist as duplicated copies across
reasoning_effort, payload_builder, adapters, discovery and
reasoning_extractor.  They now have a single authority; these tests fail if a
consumer re-introduces a local copy (identity checks + source scans) or if the
value sets drift from the live-config contracts in config/ (model_catalog,
llm_projection).
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import config.llm_projection as llm_projection
import config.model_catalog as model_catalog

from core.llm import (
    adapters,
    discovery as discovery_module,
    payload_builder,
    protocol_constants,
    reasoning_effort,
    reasoning_extractor,
)
from core.llm.discovery import SUPPORTED_REASONING_STATE_FIELDS as DISCOVERY_SUPPORTED_REASONING_STATE_FIELDS
from core.llm.protocol_constants import (
    ENABLE_THINKING_FIELD,
    EXTRA_BODY_FIELD,
    GPT_REASONING_EFFORT_VALUES,
    KNOWN_REASONING_EFFORT_VALUES,
    REASONING_CONTENT_FIELD,
    REASONING_DELTA_FIELD_CANDIDATES,
    REASONING_EFFORT_ADAPTER_NONE,
    REASONING_EFFORT_ADAPTER_REASONING_EFFORT,
    REASONING_EFFORT_ADAPTER_REASONING_OBJECT,
    REASONING_EFFORT_ADAPTER_THINKING_TOGGLE,
    REASONING_EFFORT_ADAPTERS,
    REASONING_EFFORT_FIELD,
    REASONING_EFFORT_OBJECT_KEY,
    REASONING_FIELD_CANDIDATES,
    REASONING_OBJECT_FIELD,
    SUPPORTED_REASONING_STATE_FIELDS,
    THINKING_FIELD,
    THINKING_TOGGLE_OFF_VALUES,
)


def _module_source(module: object) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")


def _profile(**overrides):
    values = {
        "reasoning_effort": "high",
        "reasoning_effort_adapter": REASONING_EFFORT_ADAPTER_REASONING_OBJECT,
        "reasoning_effort_map": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_value_sets_match_live_config_contracts():
    # GPT-facing pin contract mirrors config/llm_projection defaults and the
    # default_reasoning_effort "medium" must stay inside the exposed set.
    assert GPT_REASONING_EFFORT_VALUES == ("low", "medium", "high")
    assert "medium" in GPT_REASONING_EFFORT_VALUES
    # Known set is the normalization superset (includes the "none" sentinel).
    assert "none" in KNOWN_REASONING_EFFORT_VALUES
    assert set(GPT_REASONING_EFFORT_VALUES) <= set(KNOWN_REASONING_EFFORT_VALUES)
    # config/model_catalog validates against subsets of the same universes.
    # config must not import core, so consistency is pinned here instead.
    assert model_catalog._REASONING_ADAPTERS == set(REASONING_EFFORT_ADAPTERS)
    assert model_catalog._REASONING_EFFORT_VALUES <= set(KNOWN_REASONING_EFFORT_VALUES)


def test_llm_projection_defaults_derive_from_the_same_universe():
    provider = {
        "service_class": "official_api",
        "driver": "openai",
        "protocols": {"default": "responses"},
    }
    defaults = llm_projection._default_v2_reasoning_effort_defaults(provider, {}, {})
    assert defaults is not None
    assert defaults["reasoning_effort_values"] == list(GPT_REASONING_EFFORT_VALUES)
    assert defaults["default_reasoning_effort"] in GPT_REASONING_EFFORT_VALUES
    assert defaults["reasoning_effort_adapter"] == REASONING_EFFORT_ADAPTER_REASONING_OBJECT


def test_adapter_names_and_toggle_semantics_are_pinned():
    assert REASONING_EFFORT_ADAPTER_NONE == "none"
    assert REASONING_EFFORT_ADAPTER_REASONING_OBJECT == "reasoning_object"
    assert REASONING_EFFORT_ADAPTER_REASONING_EFFORT == "reasoning_effort"
    assert REASONING_EFFORT_ADAPTER_THINKING_TOGGLE == "thinking_toggle"
    assert THINKING_TOGGLE_OFF_VALUES == frozenset({"off", "none"})


def test_state_fields_and_response_candidates_are_consistent():
    assert SUPPORTED_REASONING_STATE_FIELDS == {REASONING_CONTENT_FIELD}
    assert REASONING_CONTENT_FIELD in REASONING_FIELD_CANDIDATES
    assert REASONING_OBJECT_FIELD in REASONING_FIELD_CANDIDATES
    assert THINKING_FIELD in REASONING_FIELD_CANDIDATES
    assert REASONING_DELTA_FIELD_CANDIDATES == REASONING_FIELD_CANDIDATES[:2]


def test_reasoning_effort_module_has_no_local_constant_copies():
    assert reasoning_effort.GPT_REASONING_EFFORT_VALUES is GPT_REASONING_EFFORT_VALUES
    assert reasoning_effort.KNOWN_REASONING_EFFORT_VALUES is KNOWN_REASONING_EFFORT_VALUES
    source = _module_source(reasoning_effort)
    assert not re.search(r"^GPT_REASONING_EFFORT_VALUES\s*=", source, re.M)
    assert not re.search(r"^KNOWN_REASONING_EFFORT_VALUES\s*=", source, re.M)
    assert '"reasoning_object"' not in source
    assert '"thinking_toggle"' not in source


def test_discovery_has_no_local_state_field_copy():
    assert DISCOVERY_SUPPORTED_REASONING_STATE_FIELDS is SUPPORTED_REASONING_STATE_FIELDS
    assert not re.search(
        r"^SUPPORTED_REASONING_STATE_FIELDS\s*=",
        _module_source(discovery_module),
        re.M,
    )


def test_reasoning_extractor_has_no_local_candidate_copies():
    assert reasoning_extractor.REASONING_FIELD_CANDIDATES is REASONING_FIELD_CANDIDATES
    assert reasoning_extractor.REASONING_DELTA_FIELD_CANDIDATES is REASONING_DELTA_FIELD_CANDIDATES
    source = _module_source(reasoning_extractor)
    assert not re.search(r"^REASONING_FIELD_CANDIDATES\s*=", source, re.M)
    assert not re.search(r"^REASONING_DELTA_FIELD_CANDIDATES\s*=", source, re.M)


def test_payload_builder_binds_constants_and_has_no_wire_literals():
    assert payload_builder.ENABLE_THINKING_FIELD is ENABLE_THINKING_FIELD
    assert payload_builder.REASONING_CONTENT_FIELD is REASONING_CONTENT_FIELD
    assert payload_builder.EXTRA_BODY_FIELD is EXTRA_BODY_FIELD
    source = _module_source(payload_builder)
    for literal in ('"enable_thinking"', '"chat_template_kwargs"', '"reasoning_content"', '"extra_body"'):
        assert literal not in source


def test_adapters_bind_thinking_constants_from_the_authority():
    assert adapters.THINKING_FIELD is THINKING_FIELD
    assert adapters.REASONING_EFFORT_ADAPTER_NONE is REASONING_EFFORT_ADAPTER_NONE


def test_resolution_payloads_are_built_from_authority_constants():
    resolution = reasoning_effort.resolve_reasoning_effort_request(_profile())
    assert list(resolution.payload)[0] is REASONING_OBJECT_FIELD
    assert list(resolution.payload[REASONING_OBJECT_FIELD])[0] is REASONING_EFFORT_OBJECT_KEY

    resolution = reasoning_effort.resolve_reasoning_effort_request(
        _profile(reasoning_effort_adapter=REASONING_EFFORT_ADAPTER_REASONING_EFFORT)
    )
    assert list(resolution.payload)[0] is REASONING_EFFORT_FIELD
    assert resolution.payload == {REASONING_EFFORT_FIELD: "high"}

    resolution = reasoning_effort.resolve_reasoning_effort_request(
        _profile(reasoning_effort_adapter=REASONING_EFFORT_ADAPTER_THINKING_TOGGLE)
    )
    assert list(resolution.payload)[0] is ENABLE_THINKING_FIELD
    assert resolution.payload == {ENABLE_THINKING_FIELD: True}

    off_resolution = reasoning_effort.resolve_reasoning_effort_request(
        _profile(
            reasoning_effort="low",
            reasoning_effort_map={"low": "off"},
            reasoning_effort_adapter=REASONING_EFFORT_ADAPTER_THINKING_TOGGLE,
        )
    )
    assert off_resolution.payload == {ENABLE_THINKING_FIELD: False}

    none_resolution = reasoning_effort.resolve_reasoning_effort_request(
        _profile(reasoning_effort_adapter=REASONING_EFFORT_ADAPTER_NONE)
    )
    assert none_resolution.payload == {}
