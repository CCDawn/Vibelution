from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from config.models import _read_env_var


@dataclass(frozen=True)
class CredentialResolution:
    reference: str
    state: str
    source: str
    secret: str = field(default="", repr=False)


def canonicalize_credential_ref(ref: str, *, windows_env: bool | None = None) -> str:
    value = str(ref or "").strip()
    if not value or value == "none":
        return "none"
    scheme, separator, target = value.partition(":")
    if not separator or scheme.lower() != "env" or not target.strip():
        raise ValueError("credential_ref must be `env:VARIABLE_NAME` or `none`")
    variable = target.strip()
    if not variable.replace("_", "A").isalnum() or variable[0].isdigit():
        raise ValueError("credential_ref contains an invalid environment variable name")
    case_insensitive = os.name == "nt" if windows_env is None else windows_env
    return f"env:{variable.upper() if case_insensitive else variable}"


def resolve_credential_ref(
    ref: str,
    *,
    env_reader: Callable[[str], str | None] = _read_env_var,
) -> CredentialResolution:
    canonical = canonicalize_credential_ref(ref)
    if canonical == "none":
        return CredentialResolution(reference="none", state="not_required", source="none")
    variable = canonical.removeprefix("env:")
    secret = str(env_reader(variable) or "")
    return CredentialResolution(
        reference=canonical,
        state="configured" if secret else "missing",
        source=f"env:{variable}",
        secret=secret,
    )


__all__ = ["CredentialResolution", "canonicalize_credential_ref", "resolve_credential_ref"]
