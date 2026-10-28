
import hashlib

from app.config import ARTIFACTS_DIR, ROOT_DIR
from app.services.policies import evaluate_policies


def test_policies_pass_when_run_and_artifact_are_valid(tmp_path):
    artifact_file = tmp_path / "result.json"
    artifact_file.write_text('{"result": 123}', encoding="utf-8")

    # Store the test artifact under the project's artifacts directory.
    test_artifact_dir = ARTIFACTS_DIR / "policy_test"
    test_artifact_dir.mkdir(parents=True, exist_ok=True)
    test_artifact_file = test_artifact_dir / "result.json"

    try:
        test_artifact_file.write_text(
            artifact_file.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        relative_path = str(test_artifact_file.relative_to(ROOT_DIR))
        actual_hash = hashlib.sha256(
            test_artifact_file.read_bytes()
        ).hexdigest()

        checks = evaluate_policies(
            {"status": "succeeded", "code_sha256": "abc123"},
            {
                "sha256": actual_hash,
                "relative_path": relative_path,
            },
        )

        assert all(check["passed"] for check in checks)

        integrity_check = next(
            check for check in checks
            if check["policy_name"] == "artifact_integrity"
        )
        assert "verified" in integrity_check["message"].lower()

    finally:
        test_artifact_file.unlink(missing_ok=True)
        test_artifact_dir.rmdir()


def test_policies_fail_without_artifact():
    checks = evaluate_policies(
        {"status": "failed", "code_sha256": "abc123"},
        None,
    )

    assert not all(check["passed"] for check in checks)
    assert any(
        check["policy_name"] == "artifact_integrity"
        and not check["passed"]
        for check in checks
    )


def test_policies_fail_when_artifact_is_modified(tmp_path):
    test_artifact_dir = ARTIFACTS_DIR / "policy_test"
    test_artifact_dir.mkdir(parents=True, exist_ok=True)
    test_artifact_file = test_artifact_dir / "result.json"

    try:
        test_artifact_file.write_text(
            '{"result": "modified"}',
            encoding="utf-8",
        )

        original_hash = hashlib.sha256(
            b'{"result": "original"}'
        ).hexdigest()

        checks = evaluate_policies(
            {"status": "succeeded", "code_sha256": "abc123"},
            {
                "sha256": original_hash,
                "relative_path": str(
                    test_artifact_file.relative_to(ROOT_DIR)
                ),
            },
        )

        integrity_check = next(
            check for check in checks
            if check["policy_name"] == "artifact_integrity"
        )

        assert not integrity_check["passed"]
        assert "mismatch" in integrity_check["message"].lower()

    finally:
        test_artifact_file.unlink(missing_ok=True)
        test_artifact_dir.rmdir()
