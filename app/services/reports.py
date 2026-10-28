import json
import re
from typing import Any


REPORT_FORMAT = "reproducible-research-run-provenance"
REPORT_VERSION = "1.0"
NOT_RECORDED = "Not recorded"
SENSITIVE_KEY = re.compile(
    r"(secret|token|password|credential|api[_-]?key|private[_-]?key)",
    re.IGNORECASE,
)
SENSITIVE_TEXT = re.compile(
    r"\b((?:api[_-]?key|access[_-]?token|token|password|secret|credential)s?)"
    r"(\s*[:=]\s*)([^\s,;]+)",
    re.IGNORECASE,
)
BEARER_TOKEN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE)
ABSOLUTE_PATH = re.compile(
    r"(?:\b[A-Za-z]:\\(?:[^\\\s]+\\)*[^\\\s]*|"
    r"\\\\[^\\\s]+\\[^\\\s]+(?:\\[^\\\s]*)*|"
    r"(?<![\w:])/(?:[^/\s]+/)+[^/\s]*)"
)


def _json_value(value: str | None, *, empty_is_missing: bool = False) -> Any:
    if not value:
        return NOT_RECORDED
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return NOT_RECORDED
    if empty_is_missing and parsed in ({}, [], None):
        return NOT_RECORDED
    return _redact_sensitive_keys(parsed)


def _redact_sensitive_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                NOT_RECORDED
                if SENSITIVE_KEY.search(str(key))
                else _redact_sensitive_keys(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_keys(item) for item in value]
    if isinstance(value, str):
        value = SENSITIVE_TEXT.sub(r"\1\2[REDACTED]", value)
        value = BEARER_TOKEN.sub("Bearer [REDACTED]", value)
        return ABSOLUTE_PATH.sub("[path redacted]", value)
    return value


def build_run_report(
    experiment: dict,
    run: dict,
    artifacts: list[dict],
    policy_checks: list[dict],
    generated_at: str,
) -> dict:
    image = run.get("docker_image") or NOT_RECORDED
    image_digest = run.get("docker_image_digest") or NOT_RECORDED
    if image == "python:3.12-slim" and image_digest == NOT_RECORDED:
        image = NOT_RECORDED

    return {
        "format": REPORT_FORMAT,
        "version": REPORT_VERSION,
        "generated_at": generated_at,
        "evidence_note": (
            "This report describes records stored by the platform at generation "
            "time. Matching hashes support reproducibility but do not guarantee "
            "identical execution environments or outputs."
        ),
        "experiment": {
            "id": experiment["id"],
            "name": _redact_sensitive_keys(
                experiment["name"] or NOT_RECORDED
            ),
        },
        "run": {
            "id": run["id"],
            "status": run["status"] or NOT_RECORDED,
            "started_at": run["started_at"] or NOT_RECORDED,
            "finished_at": run["finished_at"] or NOT_RECORDED,
            "message": _redact_sensitive_keys(run["message"] or NOT_RECORDED),
        },
        "provenance": {
            "code_sha256": run.get("code_sha256") or NOT_RECORDED,
            "dataset_sha256": run.get("dataset_sha256") or NOT_RECORDED,
            "configuration_sha256": run.get("configuration_sha256") or NOT_RECORDED,
            "parameters": _json_value(
                run.get("parameters_json"),
                empty_is_missing=True,
            ),
            "docker_image": image,
            "docker_image_digest": image_digest,
        },
        "metrics": _json_value(run.get("metrics_json"), empty_is_missing=True),
        "artifacts": [
            {
                "id": artifact["id"],
                "filename": _redact_sensitive_keys(
                    str(artifact.get("name") or NOT_RECORDED)
                    .replace("\\", "/")
                    .rsplit("/", 1)[-1]
                ),
                "size_bytes": artifact.get("size_bytes"),
                "sha256": artifact.get("sha256") or NOT_RECORDED,
                "created_at": artifact.get("created_at") or NOT_RECORDED,
            }
            for artifact in artifacts
        ],
        "policy_checks": [
            {
                "policy_name": check.get("policy_name") or NOT_RECORDED,
                "passed": bool(check["passed"]),
                "message": _redact_sensitive_keys(
                    check.get("message") or NOT_RECORDED
                ),
                "checked_at": check.get("checked_at") or NOT_RECORDED,
            }
            for check in policy_checks
        ],
    }
