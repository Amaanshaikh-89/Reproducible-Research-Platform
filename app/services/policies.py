
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from app.config import ARTIFACTS_DIR, ROOT_DIR


def evaluate_policies(
    run: dict,
    artifact: dict | None,
) -> list[dict]:
    """Evaluate execution, provenance, and artifact-integrity policies."""
    now = datetime.now(timezone.utc).isoformat()

    has_code_hash = bool(run.get("code_sha256"))

    artifact_integrity_passed = False
    artifact_message = "No artifact checksum is available."

    if artifact and artifact.get("sha256") and artifact.get("relative_path"):
        try:
            artifact_path = (
                ROOT_DIR / artifact["relative_path"]
            ).resolve()

            artifacts_root = ARTIFACTS_DIR.resolve()

            # Only inspect files located inside the artifacts directory.
            if not artifact_path.is_relative_to(artifacts_root):
                artifact_message = (
                    "Artifact path is outside the artifacts directory."
                )
            elif not artifact_path.is_file():
                artifact_message = "Artifact file is missing."
            else:
                digest = hashlib.sha256()
                with artifact_path.open("rb") as artifact_file:
                    for chunk in iter(
                        lambda: artifact_file.read(1024 * 1024),
                        b"",
                    ):
                        digest.update(chunk)
                calculated_hash = digest.hexdigest()

                expected_hash = artifact["sha256"]

                if calculated_hash == expected_hash:
                    artifact_integrity_passed = True
                    artifact_message = (
                        "Artifact checksum verified. File matches "
                        "the recorded SHA-256 checksum."
                    )
                else:
                    artifact_message = (
                        "Artifact checksum mismatch. File contents "
                        "differ from the recorded SHA-256 checksum."
                    )

        except (OSError, ValueError, TypeError):
            artifact_message = (
                "Artifact integrity could not be verified."
            )

    checks = [
        {
            "policy_name": "execution_succeeded",
            "passed": run.get("status") == "succeeded",
            "message": (
                "Experiment execution succeeded."
                if run.get("status") == "succeeded"
                else "Experiment must succeed before its artifact is accepted."
            ),
            "checked_at": now,
        },
        {
            "policy_name": "code_provenance_recorded",
            "passed": has_code_hash,
            "message": (
                "Code checksum recorded."
                if has_code_hash
                else "Code checksum is missing."
            ),
            "checked_at": now,
        },
        {
            "policy_name": "artifact_integrity",
            "passed": artifact_integrity_passed,
            "message": artifact_message,
            "checked_at": now,
        },
    ]

    return checks
