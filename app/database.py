
import sqlite3
from pathlib import Path

from app.config import DATABASE_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    parameters_json TEXT NOT NULL DEFAULT '{}',
    custom_code TEXT,
    input_data_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT NOT NULL,
    last_run_id INTEGER
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    message TEXT NOT NULL DEFAULT '',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    code_sha256 TEXT NOT NULL DEFAULT '',
    dataset_sha256 TEXT NOT NULL DEFAULT '',
    parameters_json TEXT NOT NULL DEFAULT '{}',
    configuration_sha256 TEXT NOT NULL DEFAULT '',
    docker_image TEXT NOT NULL DEFAULT 'python:3.12-slim',
    docker_image_digest TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(experiment_id) REFERENCES experiments(id)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS policy_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    policy_name TEXT NOT NULL,
    passed INTEGER NOT NULL,
    message TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    run_a_id INTEGER,
    run_b_id INTEGER,
    result TEXT NOT NULL,
    FOREIGN KEY(run_a_id) REFERENCES runs(id),
    FOREIGN KEY(run_b_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_audit_events_occurred_at
    ON audit_events(occurred_at DESC, id DESC);
"""


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def init_db(db_path: str | Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)

        # Safely add provenance columns to databases created by older versions.
        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(runs)").fetchall()
        }

        migrations = {
            "parameters_json": (
                "ALTER TABLE runs ADD COLUMN "
                "parameters_json TEXT NOT NULL DEFAULT '{}'"
            ),
            "configuration_sha256": (
                "ALTER TABLE runs ADD COLUMN "
                "configuration_sha256 TEXT NOT NULL DEFAULT ''"
            ),
            "docker_image": (
                "ALTER TABLE runs ADD COLUMN "
                "docker_image TEXT NOT NULL DEFAULT 'python:3.12-slim'"
            ),
            "docker_image_digest": (
                "ALTER TABLE runs ADD COLUMN "
                "docker_image_digest TEXT NOT NULL DEFAULT ''"
            ),
        }

        existing_experiment_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(experiments)").fetchall()
        }
        experiment_migrations = {
            "custom_code": "ALTER TABLE experiments ADD COLUMN custom_code TEXT",
            "input_data_json": (
                "ALTER TABLE experiments ADD COLUMN "
                "input_data_json TEXT NOT NULL DEFAULT '{}'"
            ),
        }
        for column_name, sql in experiment_migrations.items():
            if column_name not in existing_experiment_columns:
                conn.execute(sql)

        for column_name, sql in migrations.items():
            if column_name not in existing_columns:
                conn.execute(sql)
