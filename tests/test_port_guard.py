"""The runner refuses to benchmark whatever else already owns the port."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quantproof.cli import app
from quantproof.models import TaskPack
from quantproof.resolve import Variant
from quantproof.runner import Runner, RunnerError

CLI = CliRunner()


def _pack() -> TaskPack:
    return TaskPack.model_validate(
        {
            "base_model": "Some/Model",
            "k_samples": 1,
            "tasks": [
                {"id": "t1", "prompt": "Say PONG", "grader": {"type": "contains", "expected": "PONG"}}
            ],
        }
    )


def test_run_variant_refuses_occupied_port(tmp_path: Path) -> None:
    gguf = tmp_path / "m.Q4_K_M.gguf"
    gguf.write_bytes(b"stub-model-file")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        # If the runner ever got past the port guard, this child would spawn
        # and immediately abort with a distinctive message.
        never_spawns = [sys.executable, "-c", "raise SystemExit('server must never spawn')"]
        runner = Runner(never_spawns, port=port)
        variant = Variant(label="Q4_K_M", path=gguf, size_gb=0.0)
        with pytest.raises(RunnerError, match="already has a listener"):
            runner.run_variant(_pack(), variant)


def test_cli_rank_occupied_port_exits_friendly(tmp_path: Path) -> None:
    gguf = tmp_path / "m.Q4_K_M.gguf"
    gguf.write_bytes(b"stub-model-file")
    pack_file = tmp_path / "tasks.json"
    pack_file.write_text(json.dumps(_pack().model_dump()), encoding="utf-8")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        result = CLI.invoke(
            app,
            [
                "rank",
                "--gguf",
                str(gguf),
                "--tasks",
                str(pack_file),
                "--port",
                str(sock.getsockname()[1]),
            ],
            env={"COLUMNS": "120"},
        )
    assert result.exit_code == 1
    assert "error:" in result.output
    assert "already has a listener" in result.output
    assert "Traceback" not in result.output


def test_free_port_still_runs(tmp_path: Path) -> None:
    """The guard is a no-op on a free port (positive control, no server needed)."""
    gguf = tmp_path / "m.Q4_K_M.gguf"
    gguf.write_bytes(b"stub-model-file")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # Port released: connect now fails, so the guard passes and the run
    # proceeds far enough to fail on the missing binary instead.
    runner = Runner(["nonexistent-llama-server"], port=port)
    variant = Variant(label="Q4_K_M", path=gguf, size_gb=0.0)
    with pytest.raises(RunnerError, match="not found on PATH"):
        runner.run_variant(_pack(), variant)
