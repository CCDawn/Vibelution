"""Closed private registry leases, excluded from model/renderer discovery."""
import json
import ntpath
import os
import re

ACTIONS = frozenset({"configuration_reference_acquire", "configuration_reference_validate", "configuration_reference_release"})
MAX_RESULT_BYTES = 4 * 1024 * 1024


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _root(value):
    return (isinstance(value, str) and 0 < len(value) <= 4096 and value == value.strip()
            and "\0" not in value and (os.path.isabs(value) or ntpath.isabs(value)))


def validate_request(action, request):
    fields = {"contextId"} | ({"leaseId", "snapshotDigest"} if action != "configuration_reference_acquire" else set())
    if (action not in ACTIONS or type(request) is not dict or set(request) != fields
            or not isinstance(request.get("contextId"), str)
            or re.fullmatch(r"cfg-[a-f0-9-]{32,64}", request["contextId"]) is None
            or action != "configuration_reference_acquire" and not all(_hash(request[k]) for k in ("leaseId", "snapshotDigest"))):
        raise ValueError("Invalid configuration reference request")
    return dict(request)


def unavailable(action, request, *, busy=False):
    if action == "configuration_reference_acquire":
        return {"schemaVersion": 1, "complete": False, "code": "busy" if busy else "unavailable"}
    return {"schemaVersion": 1, "leaseId": request["leaseId"],
            "valid" if action == "configuration_reference_validate" else "released": False}


def validate_result(action, request, value):
    validate_request(action, request)
    if type(value) is not dict or type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1:
        raise ValueError("Invalid configuration reference result")
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > MAX_RESULT_BYTES:
        raise ValueError("Configuration reference result exceeds budget")
    if action == "configuration_reference_acquire":
        if set(value) == {"schemaVersion", "complete", "code"} and value["complete"] is False and value["code"] in {"busy", "unavailable"}:
            return dict(value)
        if (set(value) != {"schemaVersion", "leaseId", "revision", "snapshotDigest", "complete", "projects", "nativeAssistantRoot"}
                or value["complete"] is not True or not _hash(value["leaseId"]) or not _hash(value["snapshotDigest"])
                or type(value["revision"]) is not int or not 0 <= value["revision"] <= 2**53 - 1
                or not _root(value["nativeAssistantRoot"]) or type(value["projects"]) is not list or len(value["projects"]) > 32768):
            raise ValueError("Incomplete configuration registry proof")
        ids = set()
        for row in value["projects"]:
            if (type(row) is not dict or set(row) != {"registrationId", "baseProjectId", "root", "active"}
                    or any(not isinstance(row[k], str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", row[k]) is None
                           for k in ("registrationId", "baseProjectId"))
                    or not _root(row["root"]) or type(row["active"]) is not bool or row["registrationId"] in ids):
                raise ValueError("Invalid registered project proof")
            ids.add(row["registrationId"])
        return {**value, "projects": [dict(row) for row in value["projects"]]}
    if value.get("leaseId") != request["leaseId"]:
        raise ValueError("Configuration reference lease changed")
    if action == "configuration_reference_validate":
        if set(value) == {"schemaVersion", "leaseId", "valid"} and value["valid"] is False:
            return dict(value)
        if (set(value) != {"schemaVersion", "leaseId", "valid", "revision", "snapshotDigest"} or value["valid"] is not True
                or type(value["revision"]) is not int or not 0 <= value["revision"] <= 2**53 - 1
                or value["snapshotDigest"] != request["snapshotDigest"]):
            raise ValueError("Configuration registry lease is no longer current")
    elif set(value) != {"schemaVersion", "leaseId", "released"} or type(value["released"]) is not bool:
        raise ValueError("Invalid configuration lease release")
    return dict(value)
