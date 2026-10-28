import json
import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

from app.services import runner


def test_resolve_docker_image_returns_immutable_repository_digest(monkeypatch):
    image_id = "sha256:" + "a" * 64
    repository_digest = "python@sha256:" + "b" * 64

    def fake_run(args, **kwargs):
        if args[-1] == "{{.Id}}":
            return SimpleNamespace(returncode=0, stdout=image_id, stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps([repository_digest]),
            stderr="",
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner.resolve_docker_image("python:3.12-slim") == (
        repository_digest,
        repository_digest,
    )


def test_resolve_docker_image_records_image_id_when_no_repo_digest(monkeypatch):
    image_id = "sha256:" + "a" * 64
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[-1] == "{{.Id}}":
            return SimpleNamespace(returncode=0, stdout=image_id, stderr="")
        return SimpleNamespace(returncode=0, stdout="null", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner.resolve_docker_image("python:3.12-slim") == (image_id, "")
    assert len(calls) == 2
    assert all(args[:3] == ["docker", "image", "inspect"] for args in calls)


def test_cleanup_uses_unique_container_name_when_cidfile_was_not_written(
    monkeypatch, tmp_path
):
    commands = []

    def fake_run(args, **kwargs):
        commands.append(args)
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="Error: No such container: researchlab-custom-run-19",
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    cleaned = runner._remove_docker_container(
        tmp_path / "missing.cid",
        "researchlab-custom-run-19",
    )

    assert cleaned is True
    assert commands == [
        ["docker", "rm", "--force", "researchlab-custom-run-19"]
    ]


def test_custom_experiment_runs_in_restricted_container_and_records_hashes(
    monkeypatch, tmp_path
):
    assert not (tmp_path / "experiments").exists()
    assert not (tmp_path / "data").exists()
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(runner, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(runner, "ARTIFACTS_DIR", artifacts_dir)
    image = "python@sha256:" + "a" * 64
    monkeypatch.setattr(runner, "resolve_docker_image", lambda _: (image, image))
    code = (
        'seed = int(parameters.get("seed", 42))\n'
        'marks = input_data["marks"]\n'
        'result = {"parameters": {"seed": seed}, '
        '"metrics": {"average": sum(marks) / len(marks)}}\n'
    )
    input_data = {"marks": [75, 82, 45, 90, 58]}
    expected_output = {"parameters": {"seed": 42}, "metrics": {"average": 70.0}}
    commands = []
    staged_code = []
    staged_input = []
    container_id = "e" * 64

    def fake_run(args, **kwargs):
        commands.append(args)
        if args[1] == "run":
            cidfile = args[args.index("--cidfile") + 1]
            Path(cidfile).write_text(container_id, encoding="ascii")
            mounts = [value for value in args if value.startswith("type=bind,")]
            staged_code.append(Path(mounts[0].split("source=", 1)[1].split(",target=", 1)[0]).read_bytes())
            staged_input.append(Path(mounts[1].split("source=", 1)[1].split(",target=", 1)[0]).read_bytes())
            return SimpleNamespace(returncode=0, stdout=container_id, stderr="")
        if args[1] == "exec" and args[-1] == "/output/status.json":
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"status": "succeeded"}),
                stderr="",
            )
        if args[1] == "exec" and args[-1] == "/output/result.json":
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(expected_output),
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    outcome = runner.run_custom_experiment(23, {"seed": 42}, code, input_data)

    assert outcome["status"] == "succeeded"
    assert outcome["metrics"] == expected_output["metrics"]
    artifact_path = tmp_path / outcome["artifact"]["relative_path"]
    assert json.loads(artifact_path.read_text(encoding="utf-8")) == expected_output
    assert outcome["code_sha256"] == hashlib.sha256(code.encode("utf-8")).hexdigest()
    assert staged_code == [code.encode("utf-8")]
    assert json.loads(staged_input[0]) == {
        "input_data": input_data,
        "parameters": {"seed": 42},
    }
    canonical_input = json.dumps(
        input_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert outcome["dataset_sha256"] == hashlib.sha256(canonical_input.encode()).hexdigest()
    assert outcome["parameters"]["input_data"] == input_data

    run_command = next(command for command in commands if command[1] == "run")
    for flag_and_value in (
        ("--network", "none"), ("--memory", "128m"), ("--memory-swap", "128m"),
        ("--cpus", "0.5"), ("--pids-limit", "32"), ("--user", "65534:65534"),
        ("--cap-drop", "ALL"),
        ("--read-only", None),
    ):
        flag, value = flag_and_value
        assert flag in run_command
        if value:
            assert value in run_command
    assert run_command.count("--mount") == 3
    assert "--detach" in run_command and "--log-driver" in run_command
    assert "none" in run_command
    assert "--tmpfs" in run_command and any(
        value.startswith("/output:rw,noexec,nosuid,size=8m")
        for value in run_command
    )
    assert ["docker", "exec", "researchlab-custom-run-23", "cat", "/output/status.json"] in commands
    assert ["docker", "exec", "researchlab-custom-run-23", "cat", "/output/result.json"] in commands
    assert commands[-1] == ["docker", "rm", "--force", container_id]
    assert list((tmp_path).glob("researchlab-custom-23-*")) == []


def test_custom_experiment_invalid_python_fails_before_container_start(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(runner, "ARTIFACTS_DIR", tmp_path / "artifacts")
    commands = []
    monkeypatch.setattr(runner.subprocess, "run", lambda args, **kwargs: commands.append(args))

    outcome = runner.run_custom_experiment(24, {}, "def broken(:\n", {})

    assert outcome["status"] == "failed"
    assert "Invalid Python syntax" in outcome["message"]
    assert commands == []


def test_custom_experiment_rejects_non_object_input(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "ARTIFACTS_DIR", tmp_path / "artifacts")
    outcome = runner.run_custom_experiment(25, {}, "result = input_data", [])
    assert outcome["status"] == "failed"
    assert "JSON object" in outcome["message"]


def test_custom_experiment_failure_is_saved_without_stderr(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(runner, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(
        runner,
        "resolve_docker_image",
        lambda _: ("python@sha256:" + "f" * 64, "python@sha256:" + "f" * 64),
    )
    commands = []

    def fake_run(args, **kwargs):
        commands.append(args)
        if args[1] == "run":
            Path(args[args.index("--cidfile") + 1]).write_text("1" * 64)
            return SimpleNamespace(returncode=1, stdout="", stderr="private details")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    outcome = runner.run_custom_experiment(26, {}, "result = 1", {})
    assert outcome["status"] == "failed"
    assert "private details" not in outcome["message"]
    assert commands[-1] == ["docker", "rm", "--force", "1" * 64]


def test_custom_missing_result_is_reported_and_cleanup_does_not_mask_it(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(runner, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(runner, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(
        runner,
        "resolve_docker_image",
        lambda _: ("python@sha256:" + "a" * 64, "python@sha256:" + "a" * 64),
    )
    commands = []

    def fake_run(args, **kwargs):
        commands.append(args)
        if args[1] == "run":
            Path(args[args.index("--cidfile") + 1]).write_text("2" * 64)
            return SimpleNamespace(returncode=0, stdout="2" * 64, stderr="")
        if args[1] == "exec" and args[-1] == "/output/status.json":
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"status": "failed", "reason": "missing_result"}),
                stderr="",
            )
        if args[:3] == ["docker", "rm", "--force"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="daemon path detail")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    outcome = runner.run_custom_experiment(29, {}, "answer = 42", {})

    assert outcome["status"] == "failed"
    assert "must assign" in outcome["message"]
    assert "cleanup could not be confirmed" in outcome["message"]
    assert "daemon path detail" not in outcome["message"]


def test_custom_image_preparation_failure_keeps_cleanup_failure_separate(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(runner, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(runner, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(
        runner,
        "resolve_docker_image",
        lambda _: (_ for _ in ()).throw(RuntimeError("private registry detail")),
    )
    commands = []

    def fake_run(args, **kwargs):
        commands.append(args)
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="private daemon endpoint",
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    outcome = runner.run_custom_experiment(30, {}, "result = 1", {})

    assert outcome["status"] == "failed"
    assert "image preparation" in outcome["message"]
    assert "RuntimeError" in outcome["message"]
    assert "cleanup could not be confirmed" in outcome["message"]
    assert "private" not in outcome["message"]
    assert commands[0][:3] == ["docker", "rm", "--force"]
