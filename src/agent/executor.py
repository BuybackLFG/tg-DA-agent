import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.config import settings

logger = logging.getLogger(__name__)

SANDBOX_IMAGE = "data-agent-sandbox"
SANDBOX_TIMEOUT = settings.sandbox_timeout
MEMORY_LIMIT = settings.sandbox_memory_limit
CPU_LIMIT = settings.sandbox_cpu_limit


class ExecutionResult:
    def __init__(
        self,
        stdout: str,
        stderr: str,
        returncode: int,
        output_files: dict[str, bytes],
        timed_out: bool = False,
    ):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.output_files = output_files
        self.timed_out = timed_out

    def to_dict(self) -> dict[str, Any]:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "output_files": list(self.output_files.keys()),
            "timed_out": self.timed_out,
        }


async def execute_python(
    code: str,
    dataset_path: str | None = None,
    extra_files: dict[str, str] | None = None,
) -> ExecutionResult:
    """Execute Python code inside a Docker sandbox container.

    Args:
        code: Python source code to execute.
        dataset_path: Absolute path to the dataset file to mount inside the sandbox.
        extra_files: Mapping of filename -> content to write into the sandbox workspace.

    Returns:
        ExecutionResult with stdout, stderr, exit code and any generated output files.
    """
    with tempfile.TemporaryDirectory(prefix="sandbox_") as tmpdir:
        tmp_path = Path(tmpdir)
        workspace = tmp_path / "workspace"
        output_dir = tmp_path / "output"
        workspace.mkdir()
        output_dir.mkdir()

        # Write the main script
        script_path = workspace / "analysis.py"
        script_path.write_text(code, encoding="utf-8")

        # Mount dataset if provided
        dataset_mount = ""
        if dataset_path and Path(dataset_path).exists():
            dataset_mount = f' -v "{dataset_path}:/workspace/dataset{Path(dataset_path).suffix}"'

        # Write extra files (e.g. helper scripts)
        if extra_files:
            for fname, fcontent in extra_files.items():
                (workspace / fname).write_text(fcontent, encoding="utf-8")

        # Build Docker run command
        cmd_parts = [
            "docker", "run", "--rm",
            "--network", "none",
            "--read-only",
            "-m", MEMORY_LIMIT,
            "--cpus", CPU_LIMIT,
            f'-v "{workspace}:/workspace"',
            f'-v "{output_dir}:/output"',
        ]
        if dataset_mount:
            cmd_parts.append(dataset_mount)
        cmd_parts.extend([
            SANDBOX_IMAGE,
            "python", "/workspace/analysis.py",
        ])

        cmd = " ".join(cmd_parts)
        logger.info("Executing sandbox command: %s", cmd)

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    proc.communicate(), timeout=SANDBOX_TIMEOUT
                )
                timed_out = False
                returncode = proc.returncode or 0
            except asyncio.TimeoutError:
                logger.warning("Sandbox execution timed out after %s seconds", SANDBOX_TIMEOUT)
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                stdout_data = b""
                stderr_data = b"Execution timed out"
                timed_out = True
                returncode = -1

        except Exception as exc:
            logger.error("Failed to run sandbox: %s", exc)
            return ExecutionResult(
                stdout="",
                stderr=str(exc),
                returncode=-1,
                output_files={},
                timed_out=False,
            )

        stdout = stdout_data.decode("utf-8", errors="replace")
        stderr = stderr_data.decode("utf-8", errors="replace")

        # Collect output files (plots, CSVs, etc.)
        output_files: dict[str, bytes] = {}
        if output_dir.exists():
            for fpath in output_dir.iterdir():
                if fpath.is_file():
                    output_files[fpath.name] = fpath.read_bytes()

        return ExecutionResult(
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            output_files=output_files,
            timed_out=timed_out,
        )


def build_sandbox_image() -> None:
    """Build the sandbox Docker image from the sandbox/ directory."""
    sandbox_dir = Path(__file__).resolve().parent.parent.parent / "sandbox"
    if not sandbox_dir.exists():
        raise RuntimeError(f"Sandbox directory not found: {sandbox_dir}")

    cmd = ["docker", "build", "-t", SANDBOX_IMAGE, str(sandbox_dir)]
    logger.info("Building sandbox image: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("Failed to build sandbox image: %s", result.stderr)
        raise RuntimeError(f"Docker build failed: {result.stderr}")
    logger.info("Sandbox image built successfully")
