
import hashlib
import json
import logging
import mimetypes
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.config import APP_NAME, ARTIFACTS_DIR, ROOT_DIR
from app.database import connect, init_db
from app.schemas import ExperimentCreate
from app.services.runner import run_custom_experiment
from app.services.policies import evaluate_policies
from app.services.comparison import compare_runs as compare_run_records
from app.services.reports import build_run_report
from app.services.hashing import sha256_file

ARTIFACT_PREVIEW_MAX_BYTES = 1_048_576
LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=APP_NAME,
    version="1.1.0",
    description=(
        "Educational MVP for reproducible research workflows "
        "with containerized execution and provenance tracking."
    ),
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def handle_unexpected_exception(request: Request, error: Exception):
    LOGGER.error(
        "Unhandled API exception (%s) for %s %s",
        type(error).__name__,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error."},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now():
    return datetime.now(timezone.utc).isoformat()


def record_audit_event(
    event_type: str,
    run_a_id: int,
    result: str,
    run_b_id: int | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_events
                (event_type, occurred_at, run_a_id, run_b_id, result)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_type, now(), run_a_id, run_b_id, result),
        )


def resolve_registered_artifact_path(relative_path: str) -> Path:
    try:
        relative = Path(relative_path)
        artifacts_root = ARTIFACTS_DIR.resolve()
        if relative.is_absolute() or ".." in relative.parts:
            raise HTTPException(
                status_code=404,
                detail="Artifact file not found",
            )
        path = (ROOT_DIR / relative).resolve(strict=True)
    except HTTPException:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Artifact file not found")

    if not path.is_relative_to(artifacts_root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file not found")

    return path


def resolve_artifact_path_for_deletion(relative_path: str) -> Path | None:
    try:
        relative = Path(relative_path)
        artifacts_root = ARTIFACTS_DIR.resolve()
        workspace_root = ROOT_DIR.resolve()
        if relative.is_absolute() or ".." in relative.parts:
            raise HTTPException(
                status_code=400,
                detail="Artifact storage path is invalid.",
            )

        candidate = workspace_root / relative
        if not candidate.is_relative_to(artifacts_root):
            raise HTTPException(
                status_code=400,
                detail="Artifact storage path is invalid.",
            )

        parent = candidate.parent.resolve(strict=False)
        if not parent.is_relative_to(artifacts_root):
            raise HTTPException(
                status_code=400,
                detail="Artifact storage path is invalid.",
            )
        if not parent.exists():
            return None
        if not parent.is_dir():
            raise HTTPException(
                status_code=400,
                detail="Artifact storage path is invalid.",
            )

        path = parent / candidate.name
        resolved_path = path.resolve(strict=False)
        if not resolved_path.is_relative_to(artifacts_root) or path.is_dir():
            raise HTTPException(
                status_code=400,
                detail="Artifact storage path is invalid.",
            )
        return path
    except HTTPException:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Artifact storage path is invalid.",
        )


def cleanup_unreferenced_artifact_files(paths: set[Path | None]) -> tuple[int, bool]:
    targets = {path for path in paths if path is not None}
    if not targets:
        return 0, False

    try:
        with connect() as conn:
            rows = conn.execute("SELECT relative_path FROM artifacts").fetchall()
    except sqlite3.Error:
        LOGGER.warning("Could not check remaining artifact file references")
        return 0, True

    referenced_paths = set()
    for row in rows:
        try:
            path = resolve_artifact_path_for_deletion(row["relative_path"])
        except HTTPException:
            LOGGER.warning("Skipping cleanup for an invalid registered artifact path")
            return 0, True
        if path is not None:
            try:
                referenced_paths.add(path.resolve(strict=False))
            except (OSError, RuntimeError):
                LOGGER.warning("Skipping cleanup for an unresolved registered artifact path")
                return 0, True

    removed = 0
    failed = False
    for path in targets:
        try:
            identity = path.resolve(strict=False)
            if identity in referenced_paths or not path.exists() and not path.is_symlink():
                continue
            if path.is_dir():
                LOGGER.warning("Skipping cleanup because a registered artifact is not a file")
                failed = True
                continue
            path.unlink()
            removed += 1
        except OSError:
            LOGGER.warning("Could not remove a deleted artifact file")
            failed = True
    return removed, failed


def decode_experiment(row):
    item = dict(row)
    try:
        item["parameters"] = json.loads(item.pop("parameters_json"))
        item["input_data"] = json.loads(item.pop("input_data_json", "{}"))
    except (TypeError, json.JSONDecodeError):
        raise HTTPException(
            status_code=500,
            detail="Stored experiment parameters are invalid.",
        )
    return item


def decode_run(row):
    item = dict(row)
    try:
        item["metrics"] = json.loads(item.pop("metrics_json", "{}"))
        item["parameters"] = json.loads(item.pop("parameters_json", "{}"))
    except (TypeError, json.JSONDecodeError):
        raise HTTPException(
            status_code=500,
            detail="Stored run data is invalid.",
        )
    return item


@app.get("/")
def home():
    return {"name": APP_NAME, "status": "running", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/api/experiments")
def list_experiments():
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM experiments ORDER BY id DESC"
        ).fetchall()

    return [decode_experiment(row) for row in rows]


@app.post("/api/experiments", status_code=201)
def create_experiment(payload: ExperimentCreate):
    created = now()

    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO experiments
                (name, description, parameters_json, custom_code,
                 input_data_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.name,
                payload.description,
                json.dumps(payload.parameters),
                payload.custom_code or None,
                json.dumps(
                    payload.input_data,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
                "created",
                created,
            ),
        )

        row = conn.execute(
            "SELECT * FROM experiments WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()

    return decode_experiment(row)


@app.put("/api/experiments/{experiment_id}")
def update_experiment(experiment_id: int, payload: ExperimentCreate):
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM experiments WHERE id = ?",
            (experiment_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Experiment not found")

        conn.execute(
            """
            UPDATE experiments
            SET name = ?, description = ?, parameters_json = ?, custom_code = ?,
                input_data_json = ?
            WHERE id = ?
            """,
            (
                payload.name,
                payload.description,
                json.dumps(payload.parameters),
                payload.custom_code or None,
                json.dumps(
                    payload.input_data,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
                experiment_id,
            ),
        )
        row = conn.execute(
            "SELECT * FROM experiments WHERE id = ?",
            (experiment_id,),
        ).fetchone()

    return decode_experiment(row)


@app.get("/api/experiments/{experiment_id}")
def get_experiment(experiment_id: int):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM experiments WHERE id = ?",
            (experiment_id,),
        ).fetchone()

        runs = conn.execute(
            "SELECT * FROM runs WHERE experiment_id = ? ORDER BY id DESC",
            (experiment_id,),
        ).fetchall()

    if not row:
        raise HTTPException(status_code=404, detail="Experiment not found")

    result = decode_experiment(row)
    result["runs"] = [decode_run(run) for run in runs]

    return result


@app.delete("/api/experiments/{experiment_id}")
def delete_experiment(experiment_id: int):
    with connect() as conn:
        experiment = conn.execute(
            "SELECT id FROM experiments WHERE id = ?",
            (experiment_id,),
        ).fetchone()
        if not experiment:
            raise HTTPException(status_code=404, detail="Experiment not found")

        artifact_rows = conn.execute(
            """
            SELECT artifacts.relative_path
            FROM artifacts
            JOIN runs ON runs.id = artifacts.run_id
            WHERE runs.experiment_id = ?
            """,
            (experiment_id,),
        ).fetchall()
        artifact_paths = {
            resolve_artifact_path_for_deletion(row["relative_path"])
            for row in artifact_rows
        }
        artifact_count = len(artifact_rows)

        conn.execute(
            """
            UPDATE audit_events
            SET run_a_id = NULL
            WHERE run_a_id IN (
                SELECT id FROM runs WHERE experiment_id = ?
            )
            """,
            (experiment_id,),
        )
        conn.execute(
            """
            UPDATE audit_events
            SET run_b_id = NULL
            WHERE run_b_id IN (
                SELECT id FROM runs WHERE experiment_id = ?
            )
            """,
            (experiment_id,),
        )
        conn.execute(
            """
            DELETE FROM policy_checks
            WHERE run_id IN (
                SELECT id FROM runs WHERE experiment_id = ?
            )
            """,
            (experiment_id,),
        )
        conn.execute(
            """
            DELETE FROM artifacts
            WHERE run_id IN (
                SELECT id FROM runs WHERE experiment_id = ?
            )
            """,
            (experiment_id,),
        )
        conn.execute(
            "DELETE FROM runs WHERE experiment_id = ?",
            (experiment_id,),
        )
        conn.execute(
            "DELETE FROM experiments WHERE id = ?",
            (experiment_id,),
        )

    files_removed, cleanup_failed = cleanup_unreferenced_artifact_files(artifact_paths)
    return {
        "deleted": True,
        "artifacts_deleted": artifact_count,
        "files_deleted": files_removed,
        "cleanup_warning": (
            "Some artifact files could not be removed safely."
            if cleanup_failed
            else None
        ),
    }


@app.get("/api/runs/compare")
def compare_runs(run_a_id: int, run_b_id: int):
    if run_a_id == run_b_id:
        raise HTTPException(
            status_code=422,
            detail="Select two different runs to compare.",
        )

    with connect() as conn:
        run_rows = conn.execute(
            "SELECT * FROM runs WHERE id IN (?, ?)",
            (run_a_id, run_b_id),
        ).fetchall()
        runs_by_id = {row["id"]: dict(row) for row in run_rows}
        if run_a_id not in runs_by_id or run_b_id not in runs_by_id:
            raise HTTPException(status_code=404, detail="Run not found")

        artifact_rows = conn.execute(
            """
            SELECT * FROM artifacts
            WHERE run_id IN (?, ?)
            ORDER BY run_id, name, id
            """,
            (run_a_id, run_b_id),
        ).fetchall()

    artifacts_by_run = {run_a_id: [], run_b_id: []}
    for artifact_row in artifact_rows:
        artifacts_by_run[artifact_row["run_id"]].append(dict(artifact_row))

    run_a = runs_by_id[run_a_id]
    run_b = runs_by_id[run_b_id]
    for run_id, run in ((run_a_id, run_a), (run_b_id, run_b)):
        try:
            run["metrics"] = json.loads(run.pop("metrics_json", "{}"))
            run["parameters"] = json.loads(run.get("parameters_json") or "{}")
        except (TypeError, ValueError):
            run["metrics"] = {}
            run["parameters"] = None
        run["artifacts"] = artifacts_by_run[run_id]

    comparison = compare_run_records(run_a, run_b)
    record_audit_event(
        "reproducibility_verification",
        run_a_id,
        comparison["verification"]["status"],
        run_b_id,
    )

    def public_run(run: dict) -> dict:
        return {
            "id": run["id"],
            "experiment_id": run["experiment_id"],
            "status": run["status"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "message": run["message"],
            "metrics": run["metrics"],
            "code_sha256": run.get("code_sha256") or "",
            "dataset_sha256": run.get("dataset_sha256") or "",
            "parameters": run.get("parameters"),
            "configuration_sha256": run.get("configuration_sha256") or "",
            "docker_image": run.get("docker_image") or "",
            "docker_image_digest": run.get("docker_image_digest") or "",
            "artifacts": [
                {
                    "id": artifact["id"],
                    "name": artifact["name"],
                    "sha256": artifact["sha256"],
                    "size_bytes": artifact["size_bytes"],
                    "created_at": artifact["created_at"],
                }
                for artifact in run["artifacts"]
            ],
        }

    return {
        **comparison,
        "run_a": public_run(run_a),
        "run_b": public_run(run_b),
    }


@app.get("/api/runs/{run_id}/report")
def download_run_report(run_id: int):
    with connect() as conn:
        run_row = conn.execute(
            "SELECT * FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()

        if not run_row:
            raise HTTPException(status_code=404, detail="Run not found")

        run = dict(run_row)
        experiment_row = conn.execute(
            "SELECT id, name FROM experiments WHERE id = ?",
            (run["experiment_id"],),
        ).fetchone()
        artifact_rows = conn.execute(
            """
            SELECT id, name, size_bytes, sha256, created_at
            FROM artifacts WHERE run_id = ? ORDER BY id
            """,
            (run_id,),
        ).fetchall()
        policy_rows = conn.execute(
            """
            SELECT policy_name, passed, message, checked_at
            FROM policy_checks WHERE run_id = ? ORDER BY id
            """,
            (run_id,),
        ).fetchall()

    if not experiment_row:
        raise HTTPException(status_code=404, detail="Experiment not found")

    report = build_run_report(
        dict(experiment_row),
        run,
        [dict(row) for row in artifact_rows],
        [dict(row) for row in policy_rows],
        now(),
    )
    record_audit_event("provenance_report_generated", run_id, "GENERATED")

    return Response(
        content=json.dumps(report, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="run-{run_id}-provenance.json"'
        },
    )


@app.get("/api/runs/{run_id}")
def get_run_details(run_id: int):
    with connect() as conn:
        run_row = conn.execute(
            "SELECT * FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if not run_row:
            raise HTTPException(status_code=404, detail="Run not found")

        experiment_row = conn.execute(
            "SELECT * FROM experiments WHERE id = ?",
            (run_row["experiment_id"],),
        ).fetchone()
        artifact_rows = conn.execute(
            "SELECT * FROM artifacts WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        policy_rows = conn.execute(
            "SELECT * FROM policy_checks WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()

    if not experiment_row:
        raise HTTPException(status_code=404, detail="Experiment not found")

    return {
        "run": decode_run(run_row),
        "experiment": decode_experiment(experiment_row),
        "artifacts": [dict(row) for row in artifact_rows],
        "policy_checks": [
            dict(row) | {"passed": bool(row["passed"])}
            for row in policy_rows
        ],
    }


@app.get("/api/audit-events")
def list_audit_events(limit: int = Query(default=100, ge=1, le=500)):
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, event_type, occurred_at, run_a_id, run_b_id, result
            FROM audit_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/experiments/{experiment_id}/run")
def run_experiment(experiment_id: int):
    with connect() as conn:
        experiment = conn.execute(
            "SELECT * FROM experiments WHERE id = ?",
            (experiment_id,),
        ).fetchone()

        if not experiment:
            raise HTTPException(
                status_code=404,
                detail="Experiment not found",
            )

        try:
            parameters = json.loads(experiment["parameters_json"])
            input_data = json.loads(experiment["input_data_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            raise HTTPException(
                status_code=500,
                detail="Stored experiment parameters are invalid.",
            )
        started = now()

        cursor = conn.execute(
            """
            INSERT INTO runs (experiment_id, status, started_at, message)
            VALUES (?, ?, ?, ?)
            """,
            (
                experiment_id,
                "running",
                started,
                "Execution started.",
            ),
        )

        run_id = cursor.lastrowid

    try:
        if not experiment["custom_code"] or not experiment["custom_code"].strip():
            outcome = {
                "status": "failed",
                "message": (
                    "This experiment has no saved Python code. "
                    "Edit the experiment and save its Python code before running it."
                ),
                "parameters": parameters,
                "artifact": None,
                "metrics": {},
            }
        else:
            outcome = run_custom_experiment(
                run_id,
                parameters,
                experiment["custom_code"],
                input_data,
            )
        if (
            not isinstance(outcome, dict)
            or outcome.get("status") not in {"succeeded", "failed"}
        ):
            raise ValueError("Runner returned an invalid outcome.")
        outcome.setdefault("message", "Experiment execution failed.")
        outcome.setdefault("metrics", {})
    except Exception as error:
        LOGGER.error(
            "Experiment runner failed for run %d (%s)",
            run_id,
            type(error).__name__,
        )
        outcome = {
            "status": "failed",
            "message": "Experiment execution failed due to an internal runner error.",
            "parameters": parameters,
            "artifact": None,
            "metrics": {},
        }
    finished = now()

    # Keep a defensive fallback for older or mocked runner implementations.
    recorded_parameters = outcome.get("parameters", parameters)
    parameters_json = json.dumps(
        recorded_parameters,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    with connect() as conn:
        conn.execute(
            """
            UPDATE runs
            SET status = ?,
                finished_at = ?,
                message = ?,
                metrics_json = ?,
                code_sha256 = ?,
                dataset_sha256 = ?,
                parameters_json = ?,
                configuration_sha256 = ?,
                docker_image = ?,
                docker_image_digest = ?
            WHERE id = ?
            """,
            (
                outcome["status"],
                finished,
                outcome["message"],
                json.dumps(outcome.get("metrics", {})),
                outcome.get("code_sha256", ""),
                outcome.get("dataset_sha256", ""),
                parameters_json,
                outcome.get(
                    "configuration_sha256",
                    "",
                ),
                outcome.get("docker_image", "python:3.12-slim"),
                outcome.get("docker_image_digest", ""),
                run_id,
            ),
        )

        artifact = outcome.get("artifact")

        if artifact:
            conn.execute(
                """
                INSERT INTO artifacts
                    (run_id, name, relative_path, sha256, size_bytes, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    artifact["name"],
                    artifact["relative_path"],
                    artifact["sha256"],
                    artifact["size_bytes"],
                    finished,
                ),
            )

        run_data = {
            "status": outcome["status"],
            "code_sha256": outcome.get("code_sha256", ""),
        }

        checks = evaluate_policies(run_data, artifact)

        for check in checks:
            conn.execute(
                """
                INSERT INTO policy_checks
                    (run_id, policy_name, passed, message, checked_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    check["policy_name"],
                    int(check["passed"]),
                    check["message"],
                    check["checked_at"],
                ),
            )

        conn.execute(
            "UPDATE experiments SET status = ?, last_run_id = ? WHERE id = ?",
            (outcome["status"], run_id, experiment_id),
        )

    return {
        "run_id": run_id,
        "experiment_id": experiment_id,
        **outcome,
        "policy_passed": all(check["passed"] for check in checks),
        "policy_checks": checks,
    }


@app.get("/api/experiments/{experiment_id}/lineage")
def experiment_lineage(experiment_id: int):
    with connect() as conn:
        experiment = conn.execute(
            "SELECT * FROM experiments WHERE id = ?",
            (experiment_id,),
        ).fetchone()

        if not experiment:
            raise HTTPException(
                status_code=404,
                detail="Experiment not found",
            )

        runs = conn.execute(
            "SELECT * FROM runs WHERE experiment_id = ? ORDER BY id",
            (experiment_id,),
        ).fetchall()

        artifacts = conn.execute(
            """
            SELECT a.*
            FROM artifacts a
            JOIN runs r ON a.run_id = r.id
            WHERE r.experiment_id = ?
            ORDER BY a.id
            """,
            (experiment_id,),
        ).fetchall()

    experiment_data = decode_experiment(experiment)
    has_custom_code = bool(experiment_data.get("custom_code"))
    nodes = [
        {
            "id": f"experiment-{experiment_id}",
            "type": "experiment",
            "label": experiment["name"],
            "experiment_id": experiment_id,
            "description": experiment["description"],
            "created_at": experiment["created_at"],
            "parameters": experiment_data["parameters"],
        }
    ]
    edges = []

    for run in runs:
        run_id = run["id"]

        nodes.extend(
            [
                {
                    "id": f"dataset-{run_id}",
                    "type": "dataset",
                    "label": "input_data.json" if has_custom_code else "input JSON (unavailable)",
                    "run_id": run_id,
                    "experiment_id": experiment_id,
                    "sha256": run["dataset_sha256"],
                    "source_kind": "user-provided JSON" if has_custom_code else "input unavailable",
                    "source": (
                        "Stored in the experiment input configuration"
                        if has_custom_code
                        else "No saved input JSON is available for this run."
                    ),
                },
                {
                    "id": f"code-{run_id}",
                    "type": "code",
                    "label": "custom_experiment.py" if has_custom_code else "saved Python source unavailable",
                    "run_id": run_id,
                    "experiment_id": experiment_id,
                    "sha256": run["code_sha256"],
                    "source_kind": "user-submitted" if has_custom_code else "source unavailable",
                    "source_available": has_custom_code,
                    "source_note": (
                        "Source is stored with this experiment."
                        if has_custom_code
                        else "The run records only its hash; save Python source before running this experiment again."
                    ),
                },
                {
                    "id": f"run-{run_id}",
                    "type": "run",
                    "label": f"Run #{run_id} ({run['status']})",
                    "run_id": run_id,
                    "experiment_id": experiment_id,
                    "status": run["status"],
                    "started_at": run["started_at"],
                    "finished_at": run["finished_at"],
                    "message": run["message"],
                    "code_sha256": run["code_sha256"],
                    "dataset_sha256": run["dataset_sha256"],
                    "configuration_sha256": run["configuration_sha256"],
                    "docker_image": run["docker_image"],
                    "docker_image_digest": run["docker_image_digest"],
                },
            ]
        )

        edges.extend(
            [
                {
                    "source": f"dataset-{run_id}",
                    "target": f"run-{run_id}",
                },
                {
                    "source": f"code-{run_id}",
                    "target": f"run-{run_id}",
                },
                {
                    "source": f"experiment-{experiment_id}",
                    "target": f"run-{run_id}",
                },
            ]
        )

    for artifact in artifacts:
        artifact_id = artifact["id"]

        nodes.append(
            {
                "id": f"artifact-{artifact_id}",
                "artifact_id": artifact_id,
                "run_id": artifact["run_id"],
                "type": "artifact",
                "label": artifact["name"],
            }
        )

        edges.append(
            {
                "source": f"run-{artifact['run_id']}",
                "target": f"artifact-{artifact_id}",
            }
        )

    return {"nodes": nodes, "edges": edges}


@app.get("/api/artifacts")
def list_artifacts():
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM artifacts ORDER BY id DESC"
        ).fetchall()

    return [dict(row) for row in rows]


@app.delete("/api/artifacts/{artifact_id}")
def delete_artifact(artifact_id: int):
    with connect() as conn:
        row = conn.execute(
            "SELECT id, relative_path FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Artifact not found")

        artifact_path = resolve_artifact_path_for_deletion(row["relative_path"])
        conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))

    files_removed, cleanup_failed = cleanup_unreferenced_artifact_files(
        {artifact_path}
    )
    return {
        "deleted": True,
        "files_deleted": files_removed,
        "cleanup_warning": (
            "The artifact record was deleted, but its file could not be removed safely."
            if cleanup_failed
            else None
        ),
    }


@app.get("/api/policies")
def list_policies():
    return [
        {
            "name": "execution_succeeded",
            "description": "Run must succeed before accepting output.",
        },
        {
            "name": "code_provenance_recorded",
            "description": "Record the code checksum.",
        },
        {
            "name": "artifact_integrity",
            "description": "Output artifact must have a checksum.",
        },
    ]


@app.get("/api/policies/runs/{run_id}")
def get_run_policies(run_id: int):
    with connect() as conn:
        run = conn.execute(
            "SELECT id FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()

        rows = conn.execute(
            "SELECT * FROM policy_checks WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return [
        dict(row) | {"passed": bool(row["passed"])}
        for row in rows
    ]


@app.get("/api/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: int):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")

    path = resolve_registered_artifact_path(row["relative_path"])
    stored_sha256 = row["sha256"] or ""
    if stored_sha256:
        try:
            current_sha256 = sha256_file(path)
        except OSError:
            raise HTTPException(status_code=404, detail="Artifact file not found")
        if current_sha256 != stored_sha256:
            raise HTTPException(
                status_code=409,
                detail="Artifact checksum mismatch; download was blocked.",
            )

    return FileResponse(
        path,
        filename=Path(row["name"]).name or "artifact",
        media_type="application/json",
        headers={
            "X-Artifact-Integrity": "VERIFIED"
            if stored_sha256
            else "NOT VERIFIED"
        },
    )


@app.get("/api/artifacts/{artifact_id}/preview")
def preview_artifact(artifact_id: int):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")

    path = resolve_registered_artifact_path(row["relative_path"])

    try:
        size_bytes = path.stat().st_size
        if size_bytes > ARTIFACT_PREVIEW_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    "Artifact is too large to preview "
                    f"(limit: {ARTIFACT_PREVIEW_MAX_BYTES} bytes)."
                ),
            )

        with path.open("rb") as artifact_file:
            content_bytes = artifact_file.read(ARTIFACT_PREVIEW_MAX_BYTES + 1)
    except HTTPException:
        raise
    except OSError:
        raise HTTPException(status_code=404, detail="Artifact file not found")

    if len(content_bytes) > ARTIFACT_PREVIEW_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "Artifact is too large to preview "
                f"(limit: {ARTIFACT_PREVIEW_MAX_BYTES} bytes)."
            ),
        )

    actual_sha256 = hashlib.sha256(content_bytes).hexdigest()
    stored_sha256 = row["sha256"] or ""
    integrity_status = (
        "NOT VERIFIED"
        if not stored_sha256
        else "VERIFIED"
        if actual_sha256 == stored_sha256
        else "FAILED"
    )
    try:
        content = content_bytes.decode("utf-8")
        is_text = True
    except UnicodeDecodeError:
        content = None
        is_text = False

    return {
        "id": row["id"],
        "filename": row["name"],
        "run_id": row["run_id"],
        "relative_path": row["relative_path"],
        "created_at": row["created_at"],
        "stored_size_bytes": row["size_bytes"],
        "current_size_bytes": len(content_bytes),
        "content_type": mimetypes.guess_type(row["name"])[0]
        or "application/octet-stream",
        "content": content,
        "is_text": is_text,
        "stored_sha256": stored_sha256,
        "current_sha256": actual_sha256,
        "integrity_status": integrity_status,
    }
