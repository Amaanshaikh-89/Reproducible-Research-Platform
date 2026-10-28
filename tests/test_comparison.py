import copy
import json

from app.services.comparison import compare_runs


def sample_run(run_id=1):
    return {
        "id": run_id,
        "status": "succeeded",
        "started_at": "2026-01-01T10:00:00Z",
        "finished_at": "2026-01-01T10:01:00Z",
        "message": "Completed",
        "code_sha256": "code-hash",
        "dataset_sha256": "dataset-hash",
        "configuration_sha256": "configuration-hash",
        "parameters_json": json.dumps({"seed": 42}),
        "docker_image": "python:3.12-slim",
        "docker_image_digest": "python@sha256:image-hash",
        "metrics": {"score": 0.5, "label": "ok"},
        "artifacts": [
            {"id": run_id, "name": "result.json", "sha256": "artifact-hash"}
        ],
    }


def provenance_status(result, field):
    return next(item for item in result["provenance"] if item["field"] == field)["status"]


def test_matching_provenance_and_artifacts_are_matched():
    run_a = sample_run(1)
    run_b = sample_run(2)

    result = compare_runs(run_a, run_b)

    assert result["verification"]["status"] == "MATCHED"
    assert provenance_status(result, "code_sha256") == "MATCH"
    assert provenance_status(result, "artifact_sha256") == "MATCH"
    assert any("does not guarantee identical execution" in reason for reason in result["verification"]["reasons"])


def test_different_provenance_and_artifact_hashes_are_different():
    run_a = sample_run(1)
    run_b = sample_run(2)
    run_b["code_sha256"] = "changed-code"
    run_b["artifacts"][0]["sha256"] = "changed-artifact"

    result = compare_runs(run_a, run_b)

    assert result["verification"]["status"] == "DIFFERENT"
    assert provenance_status(result, "code_sha256") == "DIFFERENT"
    assert provenance_status(result, "artifact_sha256") == "DIFFERENT"


def test_missing_provenance_or_artifacts_is_insufficient():
    run_a = sample_run(1)
    run_b = sample_run(2)
    run_b["docker_image_digest"] = ""
    run_b["artifacts"] = []

    result = compare_runs(run_a, run_b)

    assert result["verification"]["status"] == "INSUFFICIENT PROVENANCE"
    assert provenance_status(result, "docker_image_digest") == "NOT RECORDED"
    assert provenance_status(result, "docker_image") == "NOT RECORDED"
    assert provenance_status(result, "artifact_sha256") == "NOT RECORDED"


def test_empty_default_parameters_are_treated_as_unrecorded():
    run_a = sample_run(1)
    run_b = sample_run(2)
    run_b["parameters_json"] = "{}"

    result = compare_runs(run_a, run_b)

    assert result["verification"]["status"] == "INSUFFICIENT PROVENANCE"
    assert provenance_status(result, "parameters_json") == "NOT RECORDED"


def test_missing_and_incomparable_metrics_are_identified():
    run_a = sample_run(1)
    run_b = sample_run(2)
    run_a["metrics"] = {"numeric": 2, "text": "a", "missing_from_b": 3}
    run_b["metrics"] = {"numeric": 5, "text": "b", "missing_from_a": 4}

    result = compare_runs(run_a, run_b)
    metrics = {metric["name"]: metric for metric in result["metrics"]}

    assert metrics["numeric"]["status"] == "COMPARABLE"
    assert metrics["numeric"]["difference"] == 3
    assert metrics["text"]["status"] == "INCOMPARABLE"
    assert metrics["missing_from_a"]["status"] == "MISSING"
    assert metrics["missing_from_b"]["status"] == "MISSING"


def test_comparison_does_not_mutate_saved_run_data():
    run_a = sample_run(1)
    run_b = sample_run(2)
    before_a = copy.deepcopy(run_a)
    before_b = copy.deepcopy(run_b)

    compare_runs(run_a, run_b)

    assert run_a == before_a
    assert run_b == before_b
