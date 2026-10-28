import json
import math
from typing import Any


PROVENANCE_FIELDS = (
    ("code_sha256", "Code SHA-256"),
    ("dataset_sha256", "Dataset SHA-256"),
    ("configuration_sha256", "Configuration SHA-256"),
    ("parameters_json", "Parameters"),
    ("docker_image", "Docker image"),
    ("docker_image_digest", "Docker image digest"),
)


def _value(run: dict[str, Any], field: str) -> Any:
    value = run.get(field)
    if value is None or value == "":
        return None
    # The schema default can be backfilled into legacy rows with no image record.
    if (
        field == "docker_image"
        and value == "python:3.12-slim"
        and not run.get("docker_image_digest")
    ):
        return None
    if field == "parameters_json":
        try:
            parameters = json.loads(value) if isinstance(value, str) else value
            return parameters or None
        except (TypeError, ValueError):
            return None
    return value


def _field_comparison(run_a: dict, run_b: dict, field: str, label: str) -> dict:
    value_a = _value(run_a, field)
    value_b = _value(run_b, field)
    if value_a is None or value_b is None:
        status = "NOT RECORDED"
    elif value_a == value_b:
        status = "MATCH"
    else:
        status = "DIFFERENT"
    return {
        "field": field,
        "label": label,
        "status": status,
        "run_a": value_a,
        "run_b": value_b,
    }


def _artifact_comparison(artifacts_a: list[dict], artifacts_b: list[dict]) -> dict:
    summaries_a = [
        {"filename": item.get("name") or "Unnamed artifact", "sha256": item.get("sha256") or None}
        for item in artifacts_a
    ]
    summaries_b = [
        {"filename": item.get("name") or "Unnamed artifact", "sha256": item.get("sha256") or None}
        for item in artifacts_b
    ]

    if not artifacts_a or not artifacts_b:
        return {
            "status": "NOT RECORDED",
            "pairs": [],
            "run_a": summaries_a,
            "run_b": summaries_b,
            "reason": "Both runs need registered artifacts for comparison.",
        }

    pairs = []
    checksums_differ = False
    checksums_missing = False
    if [item.get("name") for item in artifacts_a] != [
        item.get("name") for item in artifacts_b
    ]:
        return {
            "status": "DIFFERENT",
            "pairs": [],
            "run_a": summaries_a,
            "run_b": summaries_b,
            "reason": "The runs have different registered artifact filenames.",
        }

    for artifact_a, artifact_b in zip(artifacts_a, artifacts_b):
        checksum_a = artifact_a.get("sha256") or None
        checksum_b = artifact_b.get("sha256") or None
        if checksum_a is None or checksum_b is None:
            status = "NOT RECORDED"
            checksums_missing = True
        elif checksum_a == checksum_b:
            status = "MATCH"
        else:
            status = "DIFFERENT"
            checksums_differ = True
        pairs.append(
            {
                "filename": artifact_a.get("name") or "Unnamed artifact",
                "run_a_id": artifact_a.get("id"),
                "run_b_id": artifact_b.get("id"),
                "run_a_sha256": checksum_a,
                "run_b_sha256": checksum_b,
                "status": status,
            }
        )

    status = (
        "DIFFERENT"
        if checksums_differ
        else "NOT RECORDED"
        if checksums_missing
        else "MATCH"
    )
    return {
        "status": status,
        "pairs": pairs,
        "run_a": summaries_a,
        "run_b": summaries_b,
        "reason": "",
    }


def _metrics_comparison(metrics_a: dict, metrics_b: dict) -> list[dict]:
    if not isinstance(metrics_a, dict):
        metrics_a = {}
    if not isinstance(metrics_b, dict):
        metrics_b = {}

    comparisons = []
    for name in sorted(set(metrics_a) | set(metrics_b)):
        value_a = metrics_a.get(name)
        value_b = metrics_b.get(name)
        numeric_a = isinstance(value_a, (int, float)) and not isinstance(value_a, bool)
        numeric_b = isinstance(value_b, (int, float)) and not isinstance(value_b, bool)

        if name not in metrics_a or name not in metrics_b:
            status = "MISSING"
            difference = None
        elif numeric_a and numeric_b:
            try:
                comparable = math.isfinite(value_a) and math.isfinite(value_b)
            except OverflowError:
                comparable = False
            if comparable:
                status = "COMPARABLE"
                difference = value_b - value_a
            else:
                status = "INCOMPARABLE"
                difference = None
        else:
            status = "INCOMPARABLE"
            difference = None

        comparisons.append(
            {
                "name": name,
                "run_a": value_a,
                "run_b": value_b,
                "difference": difference,
                "status": status,
            }
        )
    return comparisons


def compare_runs(run_a: dict, run_b: dict) -> dict:
    comparisons = [
        _field_comparison(run_a, run_b, field, label)
        for field, label in PROVENANCE_FIELDS
    ]
    artifact_comparison = _artifact_comparison(
        run_a.get("artifacts", []),
        run_b.get("artifacts", []),
    )
    comparisons.append(
        {
            "field": "artifact_sha256",
            "label": "Artifact SHA-256",
            **artifact_comparison,
        }
    )

    required_fields = {
        "code_sha256",
        "dataset_sha256",
        "configuration_sha256",
        "parameters_json",
        "docker_image",
        "docker_image_digest",
    }
    missing_required = [
        comparison["label"]
        for comparison in comparisons
        if comparison["field"] in required_fields
        and comparison["status"] == "NOT RECORDED"
    ]

    statuses = [comparison["status"] for comparison in comparisons]
    if "DIFFERENT" in statuses:
        verification_status = "DIFFERENT"
    elif missing_required or artifact_comparison["status"] == "NOT RECORDED":
        verification_status = "INSUFFICIENT PROVENANCE"
    else:
        verification_status = "MATCHED"

    reasons = []
    if missing_required:
        reasons.append(
            "Required provenance not recorded: " + ", ".join(missing_required) + "."
        )
    if artifact_comparison["status"] == "NOT RECORDED":
        reasons.append(artifact_comparison["reason"] or "Artifact checksums are incomplete.")
    if verification_status == "MATCHED":
        reasons.append(
            "Recorded provenance, environment identifiers, and artifact checksums match. "
            "This supports reproducibility but does not guarantee identical execution."
        )
    elif verification_status == "DIFFERENT":
        reasons.append("One or more recorded provenance or artifact values differ.")

    return {
        "verification": {"status": verification_status, "reasons": reasons},
        "provenance": comparisons,
        "metrics": _metrics_comparison(
            run_a.get("metrics", {}),
            run_b.get("metrics", {}),
        ),
    }
