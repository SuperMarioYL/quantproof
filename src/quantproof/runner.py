"""llama-server orchestration: one child per variant, k samples per task.

For each variant the runner spawns ``llama-server -m <gguf> --port <port>``,
waits for its /health endpoint, draws k samples of every task through the
OpenAI-compatible /v1/chat/completions endpoint, then kills the server and
moves on. At most two processes are ever alive: this CLI and one
llama-server child. No GPU-specific code lives here — llama.cpp owns that.

A sample that errors (server hiccup, request timeout) is recorded as
failed with its error text; the run continues, because an unattended
overnight sweep must not die on one flaky request.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from openai import OpenAI

from quantproof.grader import grade_response
from quantproof.models import Task, TaskPack
from quantproof.resolve import Variant

DEFAULT_PORT = 8111
DEFAULT_STARTUP_TIMEOUT = 600.0
DEFAULT_REQUEST_TIMEOUT = 300.0
HEALTH_POLL_INTERVAL = 0.5

INSTALL_HINT = (
    "install llama.cpp first, e.g.:\n"
    "  macOS:  brew install llama.cpp\n"
    "  Linux:  grab a prebuilt binary or build from source:\n"
    "          https://github.com/ggml-org/llama.cpp/releases"
)


class RunnerError(RuntimeError):
    """Raised when a variant cannot be run (missing binary, dead server)."""


@dataclass
class SampleRecord:
    """One graded sample of one task."""

    task_id: str
    sample: int
    passed: bool
    tok_s: float | None = None
    error: str | None = None


@dataclass
class VariantRun:
    """Raw samples collected for one variant."""

    variant: str
    gguf_path: Path
    size_gb: float
    samples: list[SampleRecord] = field(default_factory=list)

    def passed_count(self, task_id: str) -> int:
        return sum(1 for s in self.samples if s.task_id == task_id and s.passed)

    def sample_count(self, task_id: str) -> int:
        return sum(1 for s in self.samples if s.task_id == task_id)


class Runner:
    """Run a task pack against variants, one llama-server child at a time."""

    def __init__(
        self,
        server_bin: str | Sequence[str] = "llama-server",
        *,
        port: int = DEFAULT_PORT,
        startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        self.server_bin = shlex.split(server_bin) if isinstance(server_bin, str) else list(server_bin)
        self.port = port
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout

    def run_variant(
        self,
        pack: TaskPack,
        variant: Variant,
        on_sample: Callable[[SampleRecord], None] | None = None,
    ) -> VariantRun:
        """Spawn the server for one variant, collect k samples per task, kill it."""
        run = VariantRun(variant=variant.label, gguf_path=variant.path, size_gb=variant.size_gb)
        proc, log = self._spawn_server(variant)
        try:
            self._wait_for_health(proc, log)
            client = OpenAI(
                base_url=f"http://127.0.0.1:{self.port}/v1",
                api_key="quantproof-local",
                timeout=self.request_timeout,
                max_retries=0,
            )
            for task in pack.tasks:
                for sample_idx in range(pack.k_samples):
                    record = self._draw_sample(client, task, sample_idx)
                    run.samples.append(record)
                    if on_sample is not None:
                        on_sample(record)
        finally:
            self._stop_server(proc)
            log.close()
        return run

    # -- server lifecycle ---------------------------------------------------

    def _resolve_binary(self) -> str:
        """Fail clearly before spawning when the server binary is absent."""
        binary = self.server_bin[0]
        if Path(binary).name != binary:  # an explicit path, not a PATH lookup
            if not Path(binary).is_file():
                raise RunnerError(f"server binary not found: {binary}")
            return binary
        resolved = shutil.which(binary)
        if resolved is None:
            raise RunnerError(f"{binary} not found on PATH.\n{INSTALL_HINT}")
        return resolved

    def _spawn_server(self, variant: Variant) -> tuple[subprocess.Popen[str], IO[str]]:
        self._resolve_binary()
        cmd = [
            *self.server_bin,
            "-m",
            str(variant.path),
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
        ]
        log = tempfile.TemporaryFile(mode="w+", prefix="quantproof-server-", suffix=".log")
        try:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
        except OSError as exc:
            log.close()
            raise RunnerError(f"failed to start server ({shlex.join(cmd)}): {exc}") from exc
        return proc, log

    def _wait_for_health(self, proc: subprocess.Popen[str], log: IO[str]) -> None:
        deadline = time.monotonic() + self.startup_timeout
        url = f"http://127.0.0.1:{self.port}/health"
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RunnerError(
                    f"llama-server exited during startup (code {proc.returncode})."
                    f"\n--- server log tail ---\n{_log_tail(log)}"
                )
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(HEALTH_POLL_INTERVAL)
        raise RunnerError(
            f"llama-server did not become healthy on port {self.port} within "
            f"{self.startup_timeout:.0f}s.\n--- server log tail ---\n{_log_tail(log)}"
        )

    def _stop_server(self, proc: subprocess.Popen[str]) -> None:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)

    # -- sampling -----------------------------------------------------------

    def _draw_sample(self, client: OpenAI, task: Task, sample_idx: int) -> SampleRecord:
        started = time.perf_counter()
        try:
            # llama-server serves the one loaded model regardless of this field.
            response = client.chat.completions.create(
                model="quantproof",
                messages=[{"role": "user", "content": task.prompt}],
            )
        except Exception as exc:  # noqa: BLE001 — one bad sample must not kill the run
            return SampleRecord(
                task_id=task.id,
                sample=sample_idx,
                passed=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        elapsed = time.perf_counter() - started
        content = response.choices[0].message.content or ""
        tokens = response.usage.completion_tokens if response.usage is not None else None
        return SampleRecord(
            task_id=task.id,
            sample=sample_idx,
            passed=grade_response(task, content),
            tok_s=tokens / elapsed if tokens else None,
        )


def _log_tail(log: IO[str], lines: int = 30) -> str:
    log.seek(0)
    return "\n".join(log.read().splitlines()[-lines:])
