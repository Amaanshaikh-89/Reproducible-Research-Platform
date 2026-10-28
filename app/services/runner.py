
import hashlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from app.config import ROOT_DIR, ARTIFACTS_DIR
from app.services.hashing import sha256_file


DOCKER_IMAGE = "python:3.12-slim"
LOGGER = logging.getLogger(__name__)
IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
REPOSITORY_DIGEST_PATTERN = re.compile(r"@sha256:[0-9a-f]{64}$")
CUSTOM_CODE_MAX_BYTES = 50_000
CUSTOM_INPUT_MAX_BYTES = 1_000_000
CUSTOM_OUTPUT_MAX_BYTES = 4_000_000

CUSTOM_WRAPPER = '''import json\nimport time\nimport traceback\nfrom pathlib import Path\n\nconfiguration = json.loads(Path("/app/input.json").read_text(encoding="utf-8"))\nnamespace = {"input_data": configuration["input_data"], "parameters": configuration["parameters"]}\nsource = Path("/app/custom_experiment.py").read_text(encoding="utf-8")\nstatus = {"status": "failed", "error_type": "UnknownError", "line": None}\ntry:\n    exec(compile(source, "custom_experiment.py", "exec"), namespace, namespace)\n    if "result" not in namespace:\n        status = {"status": "failed", "reason": "missing_result"}\n    else:\n        rendered = json.dumps(namespace["result"], ensure_ascii=False, allow_nan=False, indent=2)\n        Path("/output/result.json").write_text(rendered, encoding="utf-8")\n        status = {"status": "succeeded"}\nexcept Exception as error:\n    frames = traceback.extract_tb(error.__traceback__)\n    code_frames = [frame for frame in frames if frame.filename == "custom_experiment.py"]\n    status = {"status": "failed", "error_type": type(error).__name__, "line": code_frames[-1].lineno if code_frames else None}\nPath("/output/status.json").write_text(json.dumps(status), encoding="utf-8")\nwhile True:\n    time.sleep(1)\n'''


def _inspect_docker_image(image: str) -> tuple[str, str] | None:
    image_id_result = subprocess.run(
        [
            "docker",
            "image",
            "inspect",
            image,
            "--format",
            "{{.Id}}",
        ],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    image_id = image_id_result.stdout.strip()
    if image_id_result.returncode != 0 or not IMAGE_ID_PATTERN.fullmatch(image_id):
        return None

    digests_result = subprocess.run(
        [
            "docker",
            "image",
            "inspect",
            image_id,
            "--format",
            "{{json .RepoDigests}}",
        ],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if digests_result.returncode != 0:
        return None

    try:
        digests = json.loads(digests_result.stdout or "[]")
    except json.JSONDecodeError:
        return None
    if digests is None:
        digests = []
    if not isinstance(digests, list):
        return None

    repository_digest = next(
        (
            digest
            for digest in digests
            if isinstance(digest, str)
            and REPOSITORY_DIGEST_PATTERN.search(digest)
        ),
        "",
    )
    return image_id, repository_digest


def resolve_docker_image(image: str) -> tuple[str, str]:
    """Resolve a mutable tag, then return an immutable execution reference."""
    image_info = _inspect_docker_image(image)
    if image_info is None:
        pulled = subprocess.run(
            ["docker", "pull", image],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if pulled.returncode != 0:
            raise RuntimeError("Docker image could not be prepared.")
        image_info = _inspect_docker_image(image)

    if image_info is None:
        raise RuntimeError("Docker image could not be inspected.")

    image_id, repository_digest = image_info
    return repository_digest or image_id, repository_digest


def canonical_json_hash(data: dict) -> str:
    """Create a stable SHA-256 hash of the experiment parameters."""
    canonical_json = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def get_docker_image_digest(image: str) -> str:
    """Get the repository digest for a locally available Docker image."""
    try:
        image_info = _inspect_docker_image(image)
        return image_info[1] if image_info else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _remove_docker_container(container_id_file, container_name: str) -> bool:
    try:
        container_id = container_id_file.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        container_id = container_name
    except (OSError, UnicodeError):
        container_id = container_name

    if not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
        container_id = container_name

    try:
        completed = subprocess.run(
            ["docker", "rm", "--force", container_id],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        cleanup_succeeded = completed.returncode == 0 or (
            "no such container" in completed.stderr.lower()
        )
    except (OSError, subprocess.TimeoutExpired):
        cleanup_succeeded = False

    try:
        container_id_file.unlink(missing_ok=True)
    except OSError:
        cleanup_succeeded = False

    return cleanup_succeeded


def run_custom_experiment(
    run_id: int,
    parameters: dict,
    custom_code: str,
    input_data: dict,
) -> dict:
    """Run custom code in Docker and retrieve its bounded tmpfs result before cleanup."""
    output_dir = ARTIFACTS_DIR / f"run_{run_id}"
    output_file = output_dir / "result.json"
    container_directory = None
    container_id_file = None
    container_name = f"researchlab-custom-run-{run_id}"
    outcome = None
    cleanup_succeeded = True
    failure_stage = "validation"
    encoded_input = json.dumps(
        input_data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    encoded_execution_input = json.dumps(
        {"input_data": input_data, "parameters": parameters},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    run_parameters = {**parameters, "input_data": input_data}
    provenance = {
        "code_sha256": hashlib.sha256(custom_code.encode("utf-8")).hexdigest(),
        "dataset_sha256": hashlib.sha256(encoded_input.encode("utf-8")).hexdigest(),
        "parameters": run_parameters,
        "parameters_json": json.dumps(
            run_parameters,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        "configuration_sha256": "",
        "docker_image": DOCKER_IMAGE,
        "docker_image_digest": "",
    }
    provenance["configuration_sha256"] = canonical_json_hash(
        {
            "parameters": parameters,
            "custom_code_sha256": provenance["code_sha256"],
            "input_data": input_data,
        }
    )

    def failed(message: str) -> dict:
        return {
            "status": "failed",
            "message": message,
            **provenance,
            "artifact": None,
            "metrics": {},
        }

    try:
        if not isinstance(custom_code, str) or not custom_code.strip():
            outcome = failed("Custom Python code cannot be empty.")
            return outcome
        if len(custom_code.encode("utf-8")) > CUSTOM_CODE_MAX_BYTES:
            outcome = failed("Custom Python code exceeds the 50 KB limit.")
            return outcome
        if not isinstance(input_data, dict) or len(encoded_input.encode("utf-8")) > CUSTOM_INPUT_MAX_BYTES:
            outcome = failed("Input data must be a JSON object no larger than 1 MB.")
            return outcome
        try:
            compile(custom_code, "custom_experiment.py", "exec")
        except SyntaxError as error:
            outcome = failed(
                f"Invalid Python syntax on line {error.lineno or '?'}: {error.msg}."
            )
            return outcome

        failure_stage = "staging"
        output_dir.mkdir(parents=True, exist_ok=True)
        container_directory = Path(tempfile.mkdtemp(prefix=f"researchlab-custom-{run_id}-"))
        container_id_file = container_directory / f"{uuid.uuid4().hex}.cid"
        code_file = container_directory / "custom_experiment.py"
        input_file = container_directory / "input.json"
        wrapper_file = container_directory / "runner.py"
        status_file = container_directory / "status.json"
        code_file.write_bytes(custom_code.encode("utf-8"))
        input_file.write_bytes(encoded_execution_input.encode("utf-8"))
        wrapper_file.write_bytes(CUSTOM_WRAPPER.encode("utf-8"))

        failure_stage = "image preparation"
        execution_image, image_digest = resolve_docker_image(DOCKER_IMAGE)
        provenance["docker_image"] = execution_image
        provenance["docker_image_digest"] = image_digest

        failure_stage = "container start"
        docker_args = [
            "docker", "run", "--detach", "--log-driver", "none",
            "--name", container_name,
            "--cidfile", str(container_id_file.resolve()),
            "--network", "none",
            "--memory", "128m",
            "--memory-swap", "128m",
            "--cpus", "0.5",
            "--pids-limit", "32",
            "--ulimit", "cpu=30:30",
            "--ulimit", "nofile=64:64",
            "--user", "65534:65534",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m,uid=65534,gid=65534,mode=0700",
            "--tmpfs", "/output:rw,noexec,nosuid,size=8m,uid=65534,gid=65534,mode=0700",
            "--mount", f"type=bind,source={code_file.resolve()},target=/app/custom_experiment.py,readonly",
            "--mount", f"type=bind,source={input_file.resolve()},target=/app/input.json,readonly",
            "--mount", f"type=bind,source={wrapper_file.resolve()},target=/app/runner.py,readonly",
            execution_image,
            "python", "/app/runner.py",
        ]
        completed = subprocess.run(
            docker_args,
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if completed.returncode != 0:
            LOGGER.warning(
                "Custom run %d failed at %s (Docker exit code %d)",
                run_id,
                failure_stage,
                completed.returncode,
            )
            outcome = failed(
                f"Custom container could not start (Docker exit code {completed.returncode})."
            )
        else:
            failure_stage = "custom code execution"
            deadline = time.monotonic() + 90
            reported_status = None
            while time.monotonic() < deadline:
                remaining = max(1, min(5, int(deadline - time.monotonic())))
                status_result = subprocess.run(
                    ["docker", "exec", container_name, "cat", "/output/status.json"],
                    cwd=ROOT_DIR,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=remaining,
                    check=False,
                )
                if status_result.returncode == 0:
                    reported_status = json.loads(status_result.stdout)
                    break

                inspected = subprocess.run(
                    [
                        "docker", "inspect", "--format",
                        "{{.State.Running}} {{.State.ExitCode}}", container_name,
                    ],
                    cwd=ROOT_DIR,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=5,
                    check=False,
                )
                if inspected.returncode == 0 and inspected.stdout.strip().startswith("false "):
                    exit_code = inspected.stdout.strip().split()[-1]
                    outcome = failed(
                        "Custom container exited before reporting a result "
                        f"(exit code {exit_code})."
                    )
                    break
                time.sleep(0.25)

            if outcome is None and reported_status is None:
                outcome = failed("Custom experiment execution timed out after 90 seconds.")
            elif outcome is None and reported_status.get("status") != "succeeded":
                if reported_status.get("reason") == "missing_result":
                    outcome = failed("Custom code must assign a JSON-compatible value to `result`.")
                else:
                    error_type = re.sub(
                        r"[^A-Za-z0-9_]", "", str(reported_status.get("error_type", "PythonError"))
                    )[:60] or "PythonError"
                    line = reported_status.get("line")
                    location = f" on line {line}" if isinstance(line, int) else ""
                    outcome = failed(f"Custom Python raised {error_type}{location}.")

            if outcome is None:
                failure_stage = "result retrieval"
                result_stream = subprocess.run(
                    ["docker", "exec", container_name, "cat", "/output/result.json"],
                    cwd=ROOT_DIR,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=10,
                    check=False,
                )
                if result_stream.returncode != 0:
                    outcome = failed("Custom result could not be retrieved from the running container.")
                else:
                    result_bytes = result_stream.stdout.encode("utf-8")
                    if len(result_bytes) > CUSTOM_OUTPUT_MAX_BYTES:
                        outcome = failed("Custom experiment output exceeds the 4 MB limit.")
                    else:
                        try:
                            result = json.loads(result_bytes)
                        except json.JSONDecodeError:
                            outcome = failed("Custom experiment produced malformed JSON output.")
                        else:
                            output_file.write_bytes(result_bytes)
                            artifact = {
                                "name": "result.json",
                                "relative_path": str(output_file.relative_to(ROOT_DIR)),
                                "sha256": sha256_file(output_file),
                                "size_bytes": output_file.stat().st_size,
                            }
                            metrics = result if isinstance(result, dict) else {"result": result}
                            if isinstance(metrics, dict) and isinstance(metrics.get("metrics"), dict):
                                metrics = metrics["metrics"]
                            outcome = {
                                "status": "succeeded",
                                "message": "Custom experiment completed in Docker.",
                                **provenance,
                                "artifact": artifact,
                                "metrics": metrics,
                            }
    except subprocess.TimeoutExpired:
        outcome = failed(f"Custom run timed out during {failure_stage}.")
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError, TypeError) as error:
        LOGGER.error("Custom run %d failed at %s (%s)", run_id, failure_stage, type(error).__name__)
        outcome = failed(f"Custom experiment failed during {failure_stage} ({type(error).__name__}).")
    except Exception as error:
        LOGGER.error(
            "Custom run %d failed unexpectedly at %s (%s)",
            run_id,
            failure_stage,
            type(error).__name__,
        )
        outcome = failed(f"Custom experiment failed during {failure_stage} (internal runner error).")
    finally:
        if container_id_file is not None:
            cleanup_succeeded = _remove_docker_container(container_id_file, container_name)
        else:
            cleanup_succeeded = True
        if container_directory is not None:
            try:
                shutil.rmtree(container_directory)
            except OSError:
                cleanup_succeeded = False

    if not cleanup_succeeded:
        LOGGER.error("Custom run %d cleanup failed after stage %s", run_id, failure_stage)
        if outcome and outcome["status"] == "succeeded":
            outcome = failed("Custom experiment completed, but container cleanup could not be confirmed.")
        elif outcome:
            outcome["message"] += " Container cleanup could not be confirmed."
    return outcome or failed("Custom experiment execution did not produce a result.")
