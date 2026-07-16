"""Pinned, disabled-by-default reusable research components."""

from __future__ import annotations

from copy import deepcopy


_CATALOG = {
    "schemaVersion": 1,
    "policy": {
        "canonicalResearchStateOwner": "Vibelution",
        "externalOutputsAreCandidateOrDerivedOnly": True,
        "licenseReviewRequired": True,
        "versionPinRequired": True,
        "featureFlagsDefaultOff": True,
    },
    "components": [
        {
            "componentId": "paperqa2",
            "name": "PaperQA2",
            "sourceUrl": "https://github.com/Future-House/paper-qa",
            "license": "Apache-2.0",
            "pin": "pypi:paper-qa==2026.3.18",
            "integrationMode": "dependency",
            "adapterBoundary": "core.research.evidence_adapters.paperqa2_adapter",
            "featureFlag": "VIBELUTION_RESEARCH_PAPERQA2_ENABLED",
            "featureFlagDefault": False,
            "writesCanonicalResearchState": False,
            "compatibilityStatus": "isolated_import_probe_passed",
            "compatibilityEvidence": "Windows Python 3.12.10; paperqa.Docs import passed",
        },
        {
            "componentId": "agent-skills-reference",
            "name": "Agent Skills reference parser and validator",
            "sourceUrl": "https://github.com/agentskills/agentskills",
            "license": "Apache-2.0",
            "pin": "git:38a2ff82958afee88dadf4831509e6f7e9d8ef4e",
            "integrationMode": "component",
            "adapterBoundary": "core.web.services.skill_library_service",
            "featureFlag": "VIBELUTION_AGENT_SKILLS_VALIDATOR_ENABLED",
            "featureFlagDefault": False,
            "writesCanonicalResearchState": False,
            "compatibilityStatus": "compatibility_unverified",
            "compatibilityEvidence": "Pinned source downloaded; isolated build dependency download timed out",
        },
    ],
}


def research_component_catalog() -> dict:
    """Return a defensive copy of the reviewed T0 component catalog."""

    return deepcopy(_CATALOG)
