
import hashlib
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.database import init_db


def register_artifact(
    client,
    monkeypatch,
    tmp_path,
    content,
    *,
    relative_path="artifacts/run_1/result.json",
    stored_sha256=None,
):
    artifacts_root = tmp_path / "artifacts"
    monkeypatch.setattr(main_module, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(main_module, "ARTIFACTS_DIR", artifacts_root)

    artifact_path = tmp_path / relative_path
    if content is not None:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(content)

    experiment = client.post(
        "/api/experiments",
        json={"name": "Preview test", "parameters": {}},
    ).json()
    with main_module.connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO runs (experiment_id, status, started_at, finished_at)
            VALUES (?, ?, ?, ?)
            """,
            (experiment["id"], "succeeded", "2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z"),
        )
        run_id = cursor.lastrowid
        cursor = conn.execute(
            """
            INSERT INTO artifacts
                (run_id, name, relative_path, sha256, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "result.json",
                relative_path,
                stored_sha256 or "",
                len(content) if content is not None else 0,
                "2026-01-01T00:01:00Z",
            ),
        )
        artifact_id = cursor.lastrowid
    return artifact_id, artifact_path


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_create_and_list_experiment(client):
    created = client.post(
        "/api/experiments",
        json={
            "name": "Demo research",
            "description": "Test experiment",
            "parameters": {"seed": 42},
        },
    )

    assert created.status_code == 201

    item = created.json()

    assert item["name"] == "Demo research"
    assert item["parameters"]["seed"] == 42

    listing = client.get("/api/experiments")

    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_custom_experiment_configuration_is_persisted_and_dispatched(client, monkeypatch):
    code = 'values = input_data["values"]\nresult = {"total": sum(values)}\n'
    input_data = {"values": [2, 3, 5]}
    created = client.post(
        "/api/experiments",
        json={
            "name": "Custom calculation",
            "parameters": {"seed": 9},
            "custom_code": code,
            "input_data": input_data,
        },
    )

    assert created.status_code == 201
    experiment = created.json()
    assert experiment["custom_code"] == code
    assert experiment["input_data"] == input_data
    assert client.get(f"/api/experiments/{experiment['id']}").json()["custom_code"] == code

    received = {}

    def fake_custom_runner(run_id, parameters, actual_code, actual_input):
        received.update(
            run_id=run_id,
            parameters=parameters,
            code=actual_code,
            input_data=actual_input,
        )
        return {
            "status": "succeeded",
            "message": "Custom experiment completed in Docker.",
            "parameters": {**parameters, "input_data": actual_input},
            "code_sha256": hashlib.sha256(actual_code.encode()).hexdigest(),
            "dataset_sha256": "input-hash",
            "configuration_sha256": "configuration-hash",
            "docker_image": "python@sha256:" + "a" * 64,
            "docker_image_digest": "python@sha256:" + "a" * 64,
            "artifact": None,
            "metrics": {"total": 10},
        }

    monkeypatch.setattr(main_module, "run_custom_experiment", fake_custom_runner)
    run = client.post(f"/api/experiments/{experiment['id']}/run")

    assert run.status_code == 200
    assert run.json()["metrics"] == {"total": 10}
    assert received["code"] == code
    assert received["input_data"] == input_data
    assert received["parameters"] == {"seed": 9}
    with main_module.connect() as conn:
        saved = conn.execute(
            "SELECT code_sha256, dataset_sha256, configuration_sha256, parameters_json "
            "FROM runs WHERE id = ?",
            (run.json()["run_id"],),
        ).fetchone()
    assert saved["code_sha256"] == hashlib.sha256(code.encode()).hexdigest()
    assert saved["dataset_sha256"] == "input-hash"
    assert saved["configuration_sha256"] == "configuration-hash"
    assert json.loads(saved["parameters_json"])["input_data"] == input_data


def test_saved_experiment_can_be_edited_and_rerun_without_removing_history(
    client, monkeypatch
):
    code = 'result = {"value": input_data["value"]}\n'
    created = client.post(
        "/api/experiments",
        json={
            "name": "Saved definition",
            "description": "Before edit",
            "parameters": {"seed": 3},
            "custom_code": code,
            "input_data": {"value": 1},
        },
    ).json()
    with main_module.connect() as conn:
        conn.execute(
            "INSERT INTO runs (experiment_id, status, started_at) VALUES (?, ?, ?)",
            (created["id"], "succeeded", "2026-01-01T00:00:00Z"),
        )

    updated = client.put(
        f"/api/experiments/{created['id']}",
        json={
            "name": "Edited definition",
            "description": "After edit",
            "parameters": {"seed": 11, "threshold": 0.7, "labels": ["review"]},
            "custom_code": 'result = {"value": input_data["value"] * 2}\n',
            "input_data": {"value": 4},
        },
    )

    assert updated.status_code == 200
    saved = client.get(f"/api/experiments/{created['id']}").json()
    assert saved["name"] == "Edited definition"
    assert saved["description"] == "After edit"
    assert saved["parameters"] == {
        "seed": 11,
        "threshold": 0.7,
        "labels": ["review"],
    }
    assert saved["custom_code"] == 'result = {"value": input_data["value"] * 2}\n'
    assert saved["input_data"] == {"value": 4}
    assert len(saved["runs"]) == 1

    received = {}

    def fake_custom_runner(run_id, parameters, actual_code, actual_input):
        received.update(code=actual_code, input_data=actual_input, parameters=parameters)
        return {
            "status": "succeeded",
            "message": "Custom experiment completed in Docker.",
            "parameters": {**parameters, "input_data": actual_input},
            "code_sha256": hashlib.sha256(actual_code.encode()).hexdigest(),
            "dataset_sha256": "input-hash",
            "configuration_sha256": "configuration-hash",
            "artifact": None,
            "metrics": {"value": 8},
        }

    monkeypatch.setattr(main_module, "run_custom_experiment", fake_custom_runner)
    rerun = client.post(f"/api/experiments/{created['id']}/run")
    assert rerun.status_code == 200
    assert rerun.json()["status"] == "succeeded"
    assert received == {
        "code": saved["custom_code"],
        "input_data": {"value": 4},
        "parameters": {"seed": 11, "threshold": 0.7, "labels": ["review"]},
    }
    assert len(client.get(f"/api/experiments/{created['id']}").json()["runs"]) == 2


def test_custom_definition_survives_backend_restart(tmp_path, monkeypatch):
    database = tmp_path / "restart.db"
    monkeypatch.setattr(
        main_module,
        "connect",
        lambda: __import__("app.database", fromlist=["connect"]).connect(database),
    )
    monkeypatch.setattr(main_module, "init_db", lambda: init_db(database))
    code = 'result = {"marker": input_data["marker"]}\n'
    payload = {
        "name": "Restart persistence check",
        "description": "Distinctive persisted test definition",
        "parameters": {"seed": 7391},
        "custom_code": code,
        "input_data": {"marker": "restart-check-7391"},
    }

    with TestClient(main_module.app) as first_backend:
        created = first_backend.post("/api/experiments", json=payload).json()
        experiment_id = created["id"]

    # A new application lifespan represents a backend stop and restart against
    # the same on-disk SQLite file.
    with TestClient(main_module.app) as restarted_backend:
        restored = restarted_backend.get(f"/api/experiments/{experiment_id}")

    assert restored.status_code == 200
    assert restored.json()["custom_code"] == code
    assert restored.json()["input_data"] == payload["input_data"]
    assert restored.json()["parameters"] == payload["parameters"]


def test_custom_experiment_rejects_invalid_json_input_shape(client):
    response = client.post(
        "/api/experiments",
        json={"name": "Invalid input", "custom_code": "result = 1", "input_data": [1, 2]},
    )

    assert response.status_code == 422


def test_custom_experiment_rejects_malformed_request_json(client):
    response = client.post(
        "/api/experiments",
        content='{"name":"Broken JSON","input_data":{"value":',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422


def test_experiment_configuration_migration_preserves_existing_rows(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as conn:
        conn.execute(
            "CREATE TABLE experiments ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
            "description TEXT NOT NULL DEFAULT '', parameters_json TEXT NOT NULL DEFAULT '{}', "
            "status TEXT NOT NULL DEFAULT 'created', created_at TEXT NOT NULL, last_run_id INTEGER)"
        )
        conn.execute(
            "INSERT INTO experiments (name, created_at) VALUES (?, ?)",
            ("Existing record", "2026-01-01T00:00:00Z"),
        )

    init_db(database)

    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM experiments WHERE id = 1").fetchone()
        assert row["name"] == "Existing record"
        assert row["custom_code"] is None
        assert row["input_data_json"] == "{}"


def test_missing_experiment(client):
    response = client.get("/api/experiments/999")

    assert response.status_code == 404


def test_blank_code_experiment_fails_without_fallback(client):
    created = client.post(
        "/api/experiments",
        json={
            "name": "Failure Test",
            "description": "Test execution failure handling",
            "parameters": {"seed": 42},
        },
    )

    assert created.status_code == 201

    experiment_id = created.json()["id"]

    response = client.post(f"/api/experiments/{experiment_id}/run")
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "failed"
    assert "save its Python code before running it" in result["message"]
    assert any(check["passed"] is False for check in result["policy_checks"])
    with main_module.connect() as conn:
        saved_run = conn.execute(
            "SELECT status, message, code_sha256 FROM runs WHERE id = ?",
            (result["run_id"],),
        ).fetchone()
    assert saved_run["status"] == "failed"
    assert "save its Python code" in saved_run["message"]
    assert saved_run["code_sha256"] == ""


def test_runner_exception_is_saved_as_failed_run_without_internal_details(
    client, monkeypatch
):
    experiment = client.post(
        "/api/experiments",
        json={
            "name": "Unexpected runner error",
            "parameters": {"seed": 42},
            "custom_code": "result = 1",
            "input_data": {},
        },
    ).json()

    def raise_runner_error(run_id, parameters, custom_code, input_data):
        raise RuntimeError("C:\\private\\credentials.txt leaked")

    monkeypatch.setattr(main_module, "run_custom_experiment", raise_runner_error)

    response = client.post(f"/api/experiments/{experiment['id']}/run")

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "failed"
    assert "credentials.txt" not in response.text
    assert "internal runner error" in result["message"]

    with main_module.connect() as conn:
        run = conn.execute(
            "SELECT status, finished_at, message FROM runs WHERE id = ?",
            (result["run_id"],),
        ).fetchone()
        checks = conn.execute(
            "SELECT COUNT(*) AS count FROM policy_checks WHERE run_id = ?",
            (result["run_id"],),
        ).fetchone()

    assert run["status"] == "failed"
    assert run["finished_at"]
    assert "credentials.txt" not in run["message"]
    assert checks["count"] == 3


def test_malformed_stored_experiment_json_returns_safe_error(client):
    experiment = client.post(
        "/api/experiments",
        json={"name": "Malformed stored data", "parameters": {"seed": 42}},
    ).json()
    with main_module.connect() as conn:
        conn.execute(
            "UPDATE experiments SET parameters_json = ? WHERE id = ?",
            ("{invalid", experiment["id"]),
        )

    response = client.get(f"/api/experiments/{experiment['id']}")

    assert response.status_code == 500
    assert response.json()["detail"] == "Stored experiment parameters are invalid."
    assert "JSONDecodeError" not in response.text


def test_malformed_stored_run_json_returns_safe_error(client):
    experiment = client.post(
        "/api/experiments",
        json={"name": "Malformed run data", "parameters": {}},
    ).json()
    with main_module.connect() as conn:
        conn.execute(
            """
            INSERT INTO runs (experiment_id, status, started_at, metrics_json)
            VALUES (?, ?, ?, ?)
            """,
            (experiment["id"], "failed", "2026-01-01T00:00:00Z", "{invalid"),
        )

    response = client.get(f"/api/experiments/{experiment['id']}")

    assert response.status_code == 500
    assert response.json()["detail"] == "Stored run data is invalid."
    assert "JSONDecodeError" not in response.text


def test_preview_valid_json_and_verifies_stored_checksum(
    client, monkeypatch, tmp_path
):
    content = b'{"answer": 42}'
    checksum = hashlib.sha256(content).hexdigest()
    artifact_id, _ = register_artifact(
        client,
        monkeypatch,
        tmp_path,
        content,
        stored_sha256=checksum,
    )

    response = client.get(f"/api/artifacts/{artifact_id}/preview")

    assert response.status_code == 200
    preview = response.json()
    assert preview["id"] == artifact_id
    assert preview["filename"] == "result.json"
    assert preview["run_id"] == 1
    assert preview["content"] == content.decode()
    assert preview["is_text"] is True
    assert preview["stored_sha256"] == checksum
    assert preview["current_sha256"] == checksum
    assert preview["integrity_status"] == "VERIFIED"
    assert response.headers["content-type"].startswith("application/json")


def test_preview_invalid_json_returns_original_text(client, monkeypatch, tmp_path):
    content = b'{"incomplete": '
    artifact_id, _ = register_artifact(
        client, monkeypatch, tmp_path, content
    )

    response = client.get(f"/api/artifacts/{artifact_id}/preview")

    assert response.status_code == 200
    assert response.json()["content"] == content.decode()
    assert response.json()["is_text"] is True
    assert response.json()["integrity_status"] == "NOT VERIFIED"


def test_preview_missing_registered_file_returns_404(client, monkeypatch, tmp_path):
    artifact_id, _ = register_artifact(
        client, monkeypatch, tmp_path, None
    )

    response = client.get(f"/api/artifacts/{artifact_id}/preview")

    assert response.status_code == 404


def test_preview_unknown_artifact_returns_404(client):
    response = client.get("/api/artifacts/999/preview")

    assert response.status_code == 404


def test_preview_binary_artifact_returns_no_decoded_content(
    client, monkeypatch, tmp_path
):
    artifact_id, _ = register_artifact(
        client, monkeypatch, tmp_path, b"\x89PNG\x00\xff"
    )

    response = client.get(f"/api/artifacts/{artifact_id}/preview")

    assert response.status_code == 200
    assert response.json()["is_text"] is False
    assert response.json()["content"] is None


def test_preview_rejects_oversized_artifact(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "ARTIFACT_PREVIEW_MAX_BYTES", 16)
    artifact_id, _ = register_artifact(
        client, monkeypatch, tmp_path, b"x" * 17
    )

    response = client.get(f"/api/artifacts/{artifact_id}/preview")

    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()


def test_preview_rejects_path_outside_artifacts_directory(
    client, monkeypatch, tmp_path
):
    outside = tmp_path / "private.txt"
    outside.write_text("must not be served", encoding="utf-8")
    artifact_id, _ = register_artifact(
        client,
        monkeypatch,
        tmp_path,
        None,
        relative_path="../private.txt",
    )

    response = client.get(f"/api/artifacts/{artifact_id}/preview")

    assert response.status_code == 404


def test_download_rejects_registered_path_traversal(client, monkeypatch, tmp_path):
    outside = tmp_path / "private.txt"
    outside.write_text("private", encoding="utf-8")
    artifact_id, _ = register_artifact(
        client,
        monkeypatch,
        tmp_path,
        None,
        relative_path="../private.txt",
    )

    response = client.get(f"/api/artifacts/{artifact_id}/download")

    assert response.status_code == 404
    assert str(outside) not in response.text


def test_download_blocks_registered_artifact_checksum_mismatch(
    client, monkeypatch, tmp_path
):
    content = b'{"value": "changed"}'
    stored_checksum = hashlib.sha256(b'{"value": "original"}').hexdigest()
    artifact_id, _ = register_artifact(
        client,
        monkeypatch,
        tmp_path,
        content,
        stored_sha256=stored_checksum,
    )

    response = client.get(f"/api/artifacts/{artifact_id}/download")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Artifact checksum mismatch; download was blocked."
    )


def test_download_valid_registered_artifact_reports_verified_integrity(
    client, monkeypatch, tmp_path
):
    content = b'{"value": 42}'
    artifact_id, _ = register_artifact(
        client,
        monkeypatch,
        tmp_path,
        content,
        stored_sha256=hashlib.sha256(content).hexdigest(),
    )

    response = client.get(f"/api/artifacts/{artifact_id}/download")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["x-artifact-integrity"] == "VERIFIED"


def test_download_missing_registered_file_returns_404(
    client, monkeypatch, tmp_path
):
    artifact_id, _ = register_artifact(
        client,
        monkeypatch,
        tmp_path,
        None,
    )

    response = client.get(f"/api/artifacts/{artifact_id}/download")

    assert response.status_code == 404


def test_preview_rejects_symlink_escape(client, monkeypatch, tmp_path):
    outside = tmp_path / "private.json"
    outside.write_text('{"private": true}', encoding="utf-8")
    artifact_id, artifact_path = register_artifact(
        client, monkeypatch, tmp_path, None
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        artifact_path.symlink_to(outside)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"Symlinks are not available in this environment: {error}")

    response = client.get(f"/api/artifacts/{artifact_id}/preview")

    assert response.status_code == 404


def test_preview_reports_checksum_mismatch_without_mutating_record(
    client, monkeypatch, tmp_path
):
    content = b'{"value": "changed"}'
    stored_checksum = hashlib.sha256(b'{"value": "original"}').hexdigest()
    artifact_id, _ = register_artifact(
        client,
        monkeypatch,
        tmp_path,
        content,
        stored_sha256=stored_checksum,
    )

    response = client.get(f"/api/artifacts/{artifact_id}/preview")

    assert response.status_code == 200
    preview = response.json()
    assert preview["integrity_status"] == "FAILED"
    assert preview["stored_sha256"] == stored_checksum
    assert preview["current_sha256"] == hashlib.sha256(content).hexdigest()

    with main_module.connect() as conn:
        row = conn.execute(
            "SELECT sha256 FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
    assert row["sha256"] == stored_checksum


def test_run_comparison_rejects_missing_run_ids(client):
    response = client.get(
        "/api/runs/compare",
        params={"run_a_id": 1001, "run_b_id": 1002},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"


def test_run_comparison_is_read_only(client):
    experiment = client.post(
        "/api/experiments",
        json={"name": "Comparison API", "parameters": {}},
    ).json()
    with main_module.connect() as conn:
        run_ids = []
        for metric in (1, 2):
            cursor = conn.execute(
                """
                INSERT INTO runs (
                    experiment_id, status, started_at, finished_at,
                    metrics_json, code_sha256, dataset_sha256,
                    parameters_json, configuration_sha256,
                    docker_image, docker_image_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment["id"],
                    "succeeded",
                    f"2026-01-01T00:0{metric}:00Z",
                    f"2026-01-01T00:0{metric}:30Z",
                    json.dumps({"value": metric}),
                    "code",
                    "dataset",
                    '{"seed":42}',
                    "configuration",
                    "python:3.12-slim",
                    "python@sha256:image",
                ),
            )
            run_ids.append(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO policy_checks
                    (run_id, policy_name, passed, message, checked_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cursor.lastrowid, "unchanged", 1, "Original", "2026-01-01T00:00:00Z"),
            )
            conn.execute(
                """
                INSERT INTO artifacts
                    (run_id, name, relative_path, sha256, size_bytes, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    cursor.lastrowid,
                    "result.json",
                    f"artifacts/run_{metric}/result.json",
                    f"artifact-{metric}",
                    10,
                    "2026-01-01T00:00:00Z",
                ),
            )

        before_runs = conn.execute(
            "SELECT id, metrics_json, code_sha256 FROM runs ORDER BY id"
        ).fetchall()
        before_policies = conn.execute(
            "SELECT run_id, policy_name, passed, message FROM policy_checks ORDER BY id"
        ).fetchall()

    response = client.get(
        "/api/runs/compare",
        params={"run_a_id": run_ids[0], "run_b_id": run_ids[1]},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["verification"]["status"] == "DIFFERENT"
    assert result["run_a"]["id"] == run_ids[0]
    assert result["run_b"]["id"] == run_ids[1]
    assert next(
        metric for metric in result["metrics"] if metric["name"] == "value"
    )["difference"] == 1

    with main_module.connect() as conn:
        after_runs = conn.execute(
            "SELECT id, metrics_json, code_sha256 FROM runs ORDER BY id"
        ).fetchall()
        after_policies = conn.execute(
            "SELECT run_id, policy_name, passed, message FROM policy_checks ORDER BY id"
        ).fetchall()
    assert [tuple(row) for row in after_runs] == [tuple(row) for row in before_runs]
    assert [tuple(row) for row in after_policies] == [tuple(row) for row in before_policies]


def test_run_comparison_rejects_same_run_twice(client):
    experiment = client.post(
        "/api/experiments",
        json={"name": "Same run", "parameters": {}},
    ).json()
    with main_module.connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO runs (experiment_id, status, started_at)
            VALUES (?, ?, ?)
            """,
            (experiment["id"], "succeeded", "2026-01-01T00:00:00Z"),
        )
        run_id = cursor.lastrowid

    response = client.get(
        "/api/runs/compare",
        params={"run_a_id": run_id, "run_b_id": run_id},
    )

    assert response.status_code == 422
    assert "different runs" in response.json()["detail"]


def create_report_fixture(client, run_values=None):
    experiment = client.post(
        "/api/experiments",
        json={"name": "Report study", "parameters": {}},
    ).json()
    values = {
        "status": "succeeded",
        "started_at": "2026-02-01T10:00:00Z",
        "finished_at": "2026-02-01T10:01:00Z",
        "message": "Completed successfully",
        "metrics_json": '{"rows": 12}',
        "code_sha256": "code-checksum",
        "dataset_sha256": "dataset-checksum",
        "parameters_json": '{"seed":42,"api_token":"SECRETVAL"}',
        "configuration_sha256": "config-checksum",
        "docker_image": "python:3.12-slim",
        "docker_image_digest": "python@sha256:image-checksum",
    }
    values.update(run_values or {})
    with main_module.connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO runs (
                experiment_id, status, started_at, finished_at, message,
                metrics_json, code_sha256, dataset_sha256, parameters_json,
                configuration_sha256, docker_image, docker_image_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                experiment["id"],
                values["status"],
                values["started_at"],
                values["finished_at"],
                values["message"],
                values["metrics_json"],
                values["code_sha256"],
                values["dataset_sha256"],
                values["parameters_json"],
                values["configuration_sha256"],
                values["docker_image"],
                values["docker_image_digest"],
            ),
        )
        run_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO artifacts
                (run_id, name, relative_path, sha256, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "result.json",
                "artifacts/run_99/result.json",
                "artifact-checksum",
                23,
                "2026-02-01T10:01:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO policy_checks
                (run_id, policy_name, passed, message, checked_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "artifact_integrity",
                1,
                "Artifact checksum verified.",
                "2026-02-01T10:01:01Z",
            ),
        )
    return experiment, run_id


def test_run_details_returns_actual_related_entities(client):
    experiment, run_id = create_report_fixture(client)

    response = client.get(f"/api/runs/{run_id}")

    assert response.status_code == 200
    details = response.json()
    assert details["run"]["id"] == run_id
    assert details["experiment"]["id"] == experiment["id"]
    assert details["experiment"]["name"] == "Report study"
    assert [artifact["name"] for artifact in details["artifacts"]] == ["result.json"]
    assert details["policy_checks"][0]["policy_name"] == "artifact_integrity"
    assert details["policy_checks"][0]["passed"] is True


def test_run_details_missing_run_returns_not_found(client):
    response = client.get("/api/runs/99999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"


def test_custom_lineage_nodes_report_stored_code_and_input_metadata(client):
    experiment = client.post(
        "/api/experiments",
        json={
            "name": "Custom lineage",
            "description": "Custom source and JSON input",
            "custom_code": "result = input_data",
            "input_data": {"value": 4},
        },
    ).json()
    with main_module.connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO runs (
                experiment_id, status, started_at, finished_at, message,
                code_sha256, dataset_sha256, parameters_json,
                configuration_sha256, docker_image, docker_image_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                experiment["id"], "succeeded", "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:02Z", "Completed", "code-hash",
                "input-hash", '{"input_data":{"value":4}}',
                "config-hash", "python@sha256:image", "python@sha256:image",
            ),
        )
        run_id = cursor.lastrowid

    response = client.get(f"/api/experiments/{experiment['id']}/lineage")

    assert response.status_code == 200
    nodes = {node["type"]: node for node in response.json()["nodes"]}
    assert nodes["dataset"]["label"] == "input_data.json"
    assert nodes["dataset"]["run_id"] == run_id
    assert nodes["dataset"]["sha256"] == "input-hash"
    assert nodes["code"]["label"] == "custom_experiment.py"
    assert nodes["code"]["sha256"] == "code-hash"
    assert nodes["code"]["source_available"] is True
    assert nodes["run"]["run_id"] == run_id
    assert nodes["experiment"]["description"] == "Custom source and JSON input"


def test_run_report_includes_stored_evidence_and_is_downloadable(client):
    experiment, run_id = create_report_fixture(client)

    response = client.get(f"/api/runs/{run_id}/report")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert f'filename="run-{run_id}-provenance.json"' in response.headers["content-disposition"]
    report = response.json()
    assert report["format"] == "reproducible-research-run-provenance"
    assert report["version"] == "1.0"
    assert report["generated_at"]
    assert report["experiment"] == {
        "id": experiment["id"],
        "name": "Report study",
    }
    assert report["run"]["id"] == run_id
    assert report["run"]["status"] == "succeeded"
    assert report["provenance"]["code_sha256"] == "code-checksum"
    assert report["provenance"]["dataset_sha256"] == "dataset-checksum"
    assert report["provenance"]["configuration_sha256"] == "config-checksum"
    assert report["provenance"]["parameters"] == {
        "seed": 42,
        "api_token": "Not recorded",
    }
    assert report["metrics"] == {"rows": 12}
    assert report["artifacts"] == [
        {
            "id": 1,
            "filename": "result.json",
            "size_bytes": 23,
            "sha256": "artifact-checksum",
            "created_at": "2026-02-01T10:01:00Z",
        }
    ]
    assert report["policy_checks"][0]["policy_name"] == "artifact_integrity"
    assert report["policy_checks"][0]["passed"] is True
    assert "SECRETVAL" not in response.text
    assert "relative_path" not in response.text
    assert "artifacts/run_99" not in response.text
    assert "do not guarantee" in report["evidence_note"]


def test_run_report_invalid_id_returns_not_found(client):
    response = client.get("/api/runs/99999/report")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"


def test_run_report_labels_missing_provenance(client):
    _, run_id = create_report_fixture(
        client,
        {
            "code_sha256": "",
            "dataset_sha256": "",
            "configuration_sha256": "",
            "parameters_json": "{}",
            "docker_image": "python:3.12-slim",
            "docker_image_digest": "",
        },
    )

    report = client.get(f"/api/runs/{run_id}/report").json()

    assert report["provenance"] == {
        "code_sha256": "Not recorded",
        "dataset_sha256": "Not recorded",
        "configuration_sha256": "Not recorded",
        "parameters": "Not recorded",
        "docker_image": "Not recorded",
        "docker_image_digest": "Not recorded",
    }


def test_report_generation_does_not_modify_runs_or_policy_checks(client):
    _, run_id = create_report_fixture(client)
    with main_module.connect() as conn:
        run_before = tuple(
            conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        )
        policies_before = [
            tuple(row)
            for row in conn.execute(
                "SELECT * FROM policy_checks WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        ]

    response = client.get(f"/api/runs/{run_id}/report")
    assert response.status_code == 200

    with main_module.connect() as conn:
        run_after = tuple(
            conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        )
        policies_after = [
            tuple(row)
            for row in conn.execute(
                "SELECT * FROM policy_checks WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        ]
    assert run_after == run_before
    assert policies_after == policies_before

    audit = client.get("/api/audit-events").json()
    assert any(
        event["event_type"] == "provenance_report_generated"
        and event["run_a_id"] == run_id
        and event["result"] == "GENERATED"
        for event in audit
    )


def test_audit_events_are_read_only_and_comparison_is_logged(client):
    _, run_a_id = create_report_fixture(client)
    _, run_b_id = create_report_fixture(client)

    response = client.get(
        "/api/runs/compare",
        params={"run_a_id": run_a_id, "run_b_id": run_b_id},
    )
    assert response.status_code == 200
    verdict = response.json()["verification"]["status"]
    events = client.get("/api/audit-events?limit=10")

    assert events.status_code == 200
    comparison_event = next(
        event for event in events.json()
        if event["event_type"] == "reproducibility_verification"
    )
    assert comparison_event["run_a_id"] == run_a_id
    assert comparison_event["run_b_id"] == run_b_id
    assert comparison_event["result"] == verdict
    assert comparison_event["occurred_at"]
    assert client.get("/api/audit-events?limit=0").status_code == 422


def test_delete_artifact_removes_record_and_file_but_preserves_run(
    client, monkeypatch, tmp_path
):
    artifact_id, artifact_path = register_artifact(
        client, monkeypatch, tmp_path, b'{"value": 1}'
    )

    response = client.delete(f"/api/artifacts/{artifact_id}")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert response.json()["files_deleted"] == 1
    assert not artifact_path.exists()
    with main_module.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


def test_delete_artifact_keeps_a_shared_file(
    client, monkeypatch, tmp_path
):
    artifact_id, artifact_path = register_artifact(
        client, monkeypatch, tmp_path, b"shared"
    )
    with main_module.connect() as conn:
        run_id = conn.execute(
            "SELECT run_id FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()["run_id"]
        conn.execute(
            """
            INSERT INTO artifacts
                (run_id, name, relative_path, sha256, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "shared-copy.json",
                "artifacts/run_1/result.json",
                "",
                6,
                "2026-01-01T00:02:00Z",
            ),
        )

    response = client.delete(f"/api/artifacts/{artifact_id}")

    assert response.status_code == 200
    assert response.json()["files_deleted"] == 0
    assert artifact_path.read_bytes() == b"shared"
    with main_module.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 1


def test_delete_artifact_rejects_path_traversal_without_mutation(
    client, monkeypatch, tmp_path
):
    outside = tmp_path / "private.txt"
    outside.write_text("private", encoding="utf-8")
    artifact_id, _ = register_artifact(
        client,
        monkeypatch,
        tmp_path,
        None,
        relative_path="../private.txt",
    )

    response = client.delete(f"/api/artifacts/{artifact_id}")

    assert response.status_code == 400
    assert outside.read_text(encoding="utf-8") == "private"
    with main_module.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()[0] == 1


def test_delete_artifact_handles_missing_file_and_unknown_id(
    client, monkeypatch, tmp_path
):
    artifact_id, _ = register_artifact(
        client, monkeypatch, tmp_path, None
    )

    response = client.delete(f"/api/artifacts/{artifact_id}")

    assert response.status_code == 200
    assert response.json()["files_deleted"] == 0
    assert client.delete("/api/artifacts/99999").status_code == 404
    with main_module.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()[0] == 0


def test_delete_experiment_removes_related_records_and_preserves_audit(
    client, monkeypatch, tmp_path
):
    artifacts_root = tmp_path / "artifacts"
    monkeypatch.setattr(main_module, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(main_module, "ARTIFACTS_DIR", artifacts_root)
    relative_path = "artifacts/run_1/result.json"
    artifact_path = tmp_path / relative_path
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("result", encoding="utf-8")
    experiment = client.post(
        "/api/experiments",
        json={"name": "Delete study", "parameters": {}},
    ).json()
    with main_module.connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO runs (experiment_id, status, started_at)
            VALUES (?, ?, ?)
            """,
            (experiment["id"], "succeeded", "2026-01-01T00:00:00Z"),
        )
        run_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO artifacts
                (run_id, name, relative_path, sha256, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, "result.json", relative_path, "checksum", 6, "2026-01-01"),
        )
        conn.execute(
            """
            INSERT INTO policy_checks
                (run_id, policy_name, passed, message, checked_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, "execution_succeeded", 1, "passed", "2026-01-01"),
        )
        conn.execute(
            """
            INSERT INTO audit_events
                (event_type, occurred_at, run_a_id, run_b_id, result)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "reproducibility_verification",
                "2026-01-01T00:02:00Z",
                run_id,
                run_id,
                "MATCHED",
            ),
        )

    response = client.delete(f"/api/experiments/{experiment['id']}")

    assert response.status_code == 200
    assert response.json()["artifacts_deleted"] == 1
    assert response.json()["files_deleted"] == 1
    assert not artifact_path.exists()
    assert client.get(f"/api/experiments/{experiment['id']}").status_code == 404
    with main_module.connect() as conn:
        for table in ("runs", "artifacts", "policy_checks"):
            assert conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE "
                + ("id = ?" if table == "runs" else "run_id = ?"),
                (run_id,),
            ).fetchone()[0] == 0
        audit = conn.execute(
            "SELECT run_a_id, run_b_id, result FROM audit_events"
        ).fetchone()
    assert tuple(audit) == (None, None, "MATCHED")


def test_delete_experiment_rejects_invalid_artifact_path_atomically(
    client, monkeypatch, tmp_path
):
    experiment = client.post(
        "/api/experiments",
        json={"name": "Invalid artifact path", "parameters": {}},
    ).json()
    with main_module.connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO runs (experiment_id, status, started_at)
            VALUES (?, ?, ?)
            """,
            (experiment["id"], "succeeded", "2026-01-01T00:00:00Z"),
        )
        run_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO artifacts
                (run_id, name, relative_path, sha256, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "outside.json",
                "../private.txt",
                "",
                0,
                "2026-01-01",
            ),
        )
        conn.execute(
            """
            INSERT INTO policy_checks
                (run_id, policy_name, passed, message, checked_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, "execution_succeeded", 1, "passed", "2026-01-01"),
        )

    response = client.delete(f"/api/experiments/{experiment['id']}")

    assert response.status_code == 400
    with main_module.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM experiments WHERE id = ?",
            (experiment["id"],),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM runs WHERE id = ?", (run_id,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE run_id = ?", (run_id,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM policy_checks WHERE run_id = ?", (run_id,)
        ).fetchone()[0] == 1


def test_delete_unknown_experiment_returns_not_found(client):
    response = client.delete("/api/experiments/99999")

    assert response.status_code == 404
