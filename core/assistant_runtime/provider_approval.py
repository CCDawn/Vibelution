"""Exact provider-model consent metadata; native argument hashes bind execution."""
from __future__ import annotations

import hashlib
import json
import unicodedata

from pydantic import ValidationError

PROVIDER_APPROVAL_ACTIONS = frozenset({"provider_model_resolve"})


def validate_provider_model_resolve(parameters: dict) -> dict:
    """Reuse the executable DTO and require every string to display verbatim."""
    from tools.pa_provider_onboarding import ResolveModel

    try:
        values = ResolveModel.model_validate(parameters, strict=True).model_dump()
    except (ValidationError, TypeError, RecursionError) as error:
        raise ValueError("Invalid provider model arguments") from error
    for value in values.values():
        if isinstance(value, str) and any(
            unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in value
        ):
            raise ValueError("Provider model argument cannot be displayed safely")
    return values


def provider_model_resolve_approval_summary(parameters: dict) -> dict:
    """Expose all six effective arguments without truncation or user descriptions."""
    values = validate_provider_model_resolve(parameters)
    encoded = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    targets = {key: values[key] for key in ("provider_id", "model_query", "upstream_id")}
    targets.update(verify="true" if values["verify"] else "false",
                   offset=str(values["offset"]), limit=str(values["limit"]))
    description = "在已有连接中查找并固定选中模型。"
    description += ("随后可能发起一次少量付费的真实文本连接测试。" if values["verify"]
                    else "仅保存模型配置，不发起文本连接测试。")
    return {
        "assistantAction": "provider_model_resolve",
        "assistantProviderPreviewVersion": 1,
        "assistantParametersDigest": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "assistantTargets": targets,
        "assistantDetailsOmitted": False,
        "assistantOperationDescription": description,
    }
