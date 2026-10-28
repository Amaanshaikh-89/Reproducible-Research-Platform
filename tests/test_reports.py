from app.services.reports import build_run_report


def test_report_redacts_secrets_and_absolute_paths_from_text_fields():
    report = build_run_report(
        {"id": 1, "name": "Study"},
        {
            "id": 2,
            "status": "failed",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:01:00Z",
            "message": "token=abc123 failed at C:\\private\\source.py",
            "metrics_json": '{"note":"Bearer abc.def.ghi /srv/internal/run.log"}',
            "parameters_json": "{}",
            "docker_image": "",
            "docker_image_digest": "",
        },
        [],
        [
            {
                "policy_name": "execution_succeeded",
                "passed": False,
                "message": "password: hunter2 /opt/private/file.txt",
            }
        ],
        "2026-01-01T00:02:00Z",
    )

    serialized_report = str(report)
    assert "abc123" not in serialized_report
    assert "hunter2" not in serialized_report
    assert "C:\\private\\source.py" not in serialized_report
    assert "/srv/internal/run.log" not in serialized_report
    assert "/opt/private/file.txt" not in serialized_report
    assert "[REDACTED]" in serialized_report
    assert "[path redacted]" in serialized_report
