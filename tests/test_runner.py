"""llama-server orchestration against a stubbed OpenAI-compatible server."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quantproof.cli import app
from quantproof.models import TaskPack
from quantproof.resolve import Variant, resolve_variants
from quantproof.runner import Runner, RunnerError, VariantRun

STUB = Path(__file__).parent / "stub_llama_server.py"
CLI = CliRunner()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stub_bin(*extra: str) -> list[str]:
    return [sys.executable, str(STUB), *extra]


def make_gguf(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"stub-model-file")
    return path


def pack_with(tasks: list[dict], k: int = 1) -> TaskPack:
    return TaskPack.model_validate({"base_model": "Some/Model", "k_samples": k, "tasks": tasks})


@pytest.fixture
def mixed_pack() -> TaskPack:
    return pack_with(
        [
            {"id": "ping", "prompt": "Say PONG", "grader": {"type": "contains", "expected": "PONG"}},
            {
                "id": "france",
                "prompt": "What is the capital of France? Reply with just the city name.",
                "grader": {"type": "contains", "expected": "Paris"},
            },
            {
                "id": "unicorn",
                "prompt": "Describe a unicorn.",
                "grader": {"type": "contains", "expected": "UNICORN"},
            },
        ]
    )


class TestResolveVariants:
    def test_labels_and_sizes(self, tmp_path: Path) -> None:
        good = make_gguf(tmp_path, "Model-27B.Q4_K_M.gguf")
        low = make_gguf(tmp_path, "Model-27B.IQ2_XXS.gguf")
        variants = resolve_variants([good, low])
        assert [v.label for v in variants] == ["Q4_K_M", "IQ2_XXS"]
        assert variants[0].size_gb < 0.001

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            resolve_variants([tmp_path / "missing.gguf"])

    def test_non_gguf_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "model.bin"
        path.write_bytes(b"x")
        with pytest.raises(ValueError, match="not a .gguf file"):
            resolve_variants([path])

    def test_duplicate_labels_raise(self, tmp_path: Path) -> None:
        one, two = make_gguf(tmp_path, "a.Q4_K_M.gguf"), make_gguf(tmp_path, "b.Q4_K_M.gguf")
        with pytest.raises(ValueError, match="duplicate variant labels"):
            resolve_variants([one, two])

    def test_fallback_label_is_stem(self, tmp_path: Path) -> None:
        path = make_gguf(tmp_path, "mystery-model.gguf")
        assert resolve_variants([path])[0].label == "mystery-model"


class TestRunnerLifecycle:
    def test_missing_binary_raises_with_install_hint(
        self, mixed_pack: TaskPack, tmp_path: Path
    ) -> None:
        runner = Runner(["nonexistent-llama-server"])
        variant = Variant(label="Q4_K_M", path=make_gguf(tmp_path, "m.Q4_K_M.gguf"), size_gb=0.0)
        with pytest.raises(RunnerError, match="not found on PATH"):
            runner.run_variant(mixed_pack, variant)
        with pytest.raises(RunnerError, match="brew install llama.cpp"):
            runner.run_variant(mixed_pack, variant)

    def test_health_timeout_raises_with_log_context(
        self, mixed_pack: TaskPack, tmp_path: Path
    ) -> None:
        never_serves = [sys.executable, "-c", "import time; time.sleep(60)"]
        runner = Runner(never_serves, port=free_port(), startup_timeout=0.5)
        variant = Variant(label="Q4_K_M", path=make_gguf(tmp_path, "m.Q4_K_M.gguf"), size_gb=0.0)
        with pytest.raises(RunnerError, match="did not become healthy"):
            runner.run_variant(mixed_pack, variant)

    def test_server_process_is_stopped_after_run(
        self, mixed_pack: TaskPack, tmp_path: Path
    ) -> None:
        port = free_port()
        runner = Runner(stub_bin("--default-response", "PONG"), port=port)
        variant = Variant(label="Q4_K_M", path=make_gguf(tmp_path, "m.Q4_K_M.gguf"), size_gb=0.0)
        runner.run_variant(mixed_pack, variant)
        with socket.socket() as probe:
            # SO_REUSEADDR mirrors how a fresh server binds over TIME_WAIT
            # sockets; it still fails while the old child is listening.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))  # bindable again -> child is gone

    def test_explicit_path_binary_must_exist(self, mixed_pack: TaskPack, tmp_path: Path) -> None:
        runner = Runner(["./llama-server"], port=free_port())
        variant = Variant(label="Q4_K_M", path=make_gguf(tmp_path, "m.Q4_K_M.gguf"), size_gb=0.0)
        with pytest.raises(RunnerError, match="server binary not found"):
            runner.run_variant(mixed_pack, variant)


class TestRunnerSampling:
    def test_collects_and_grades_samples(self, mixed_pack: TaskPack, tmp_path: Path) -> None:
        runner = Runner(stub_bin("--default-response", "PONG"), port=free_port())
        variant = Variant(label="Q4_K_M", path=make_gguf(tmp_path, "m.Q4_K_M.gguf"), size_gb=0.0)
        run = runner.run_variant(mixed_pack, variant)

        assert len(run.samples) == 3
        assert run.variant == "Q4_K_M"
        # ping matches the default response, france matches the stub's answer
        # table, unicorn matches nothing the stub can say.
        assert run.passed_count("ping") == 1
        assert run.passed_count("france") == 1
        assert run.passed_count("unicorn") == 0
        assert all(sample.error is None for sample in run.samples)
        assert all(sample.tok_s and sample.tok_s > 0 for sample in run.samples)

    def test_on_sample_callback_sees_every_record(
        self, mixed_pack: TaskPack, tmp_path: Path
    ) -> None:
        runner = Runner(stub_bin("--default-response", "PONG"), port=free_port())
        variant = Variant(label="Q4_K_M", path=make_gguf(tmp_path, "m.Q4_K_M.gguf"), size_gb=0.0)
        seen: list[str] = []
        run = runner.run_variant(mixed_pack, variant, on_sample=lambda s: seen.append(s.task_id))
        assert sorted(seen) == sorted(s.task_id for s in run.samples)

    def test_k_samples_drawn_per_task(self, tmp_path: Path) -> None:
        pack = pack_with(
            [{"id": "ping", "prompt": "Say PONG", "grader": {"type": "contains", "expected": "PONG"}}],
            k=3,
        )
        runner = Runner(stub_bin("--default-response", "PONG"), port=free_port())
        variant = Variant(label="Q4_K_M", path=make_gguf(tmp_path, "m.Q4_K_M.gguf"), size_gb=0.0)
        run = runner.run_variant(pack, variant)
        assert run.sample_count("ping") == 3
        assert run.passed_count("ping") == 3

    def test_completion_failures_are_scored_not_raised(
        self, mixed_pack: TaskPack, tmp_path: Path
    ) -> None:
        runner = Runner(stub_bin("--fail-completions"), port=free_port())
        variant = Variant(label="Q4_K_M", path=make_gguf(tmp_path, "m.Q4_K_M.gguf"), size_gb=0.0)
        run = runner.run_variant(mixed_pack, variant)
        assert len(run.samples) == 3
        assert all(not sample.passed for sample in run.samples)
        assert all(sample.error is not None for sample in run.samples)

    def test_collapse_mode_lowers_pass_rate(self, mixed_pack: TaskPack, tmp_path: Path) -> None:
        runner = Runner(stub_bin("--default-response", "PONG"), port=free_port())
        good = Variant(label="Q4_K_M", path=make_gguf(tmp_path, "m.Q4_K_M.gguf"), size_gb=0.0)
        collapsed = Variant(label="IQ2_XXS", path=make_gguf(tmp_path, "m.IQ2_XXS.gguf"), size_gb=0.0)
        good_run = runner.run_variant(mixed_pack, good)
        collapsed_run = runner.run_variant(mixed_pack, collapsed)
        # The stub degrades only the France answer for low-bpp variants.
        assert good_run.passed_count("france") == 1
        assert collapsed_run.passed_count("france") == 0


class TestRankEndToEnd:
    def test_rank_cli_prints_ranked_table_with_collapse_delta(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # rank now writes report.md/results.json into the working directory;
        # keep that out of the repo checkout under test.
        monkeypatch.chdir(tmp_path)
        pack_dir = tmp_path / "tasks"
        pack_dir.mkdir()
        (pack_dir / "tasks.json").write_text(
            json.dumps(
                {
                    "base_model": "Some/Model",
                    "k_samples": 1,
                    "tasks": [
                        {
                            "id": "france",
                            "prompt": "What is the capital of France? Reply with just the city name.",
                            "grader": {"type": "contains", "expected": "Paris"},
                        },
                        {
                            "id": "ping",
                            "prompt": "Say PONG",
                            "grader": {"type": "contains", "expected": "PONG"},
                        },
                    ],
                }
            )
        )
        good = make_gguf(tmp_path, "Model.Q4_K_M.gguf")
        collapsed = make_gguf(tmp_path, "Model.IQ2_XXS.gguf")
        server = " ".join([sys.executable, str(STUB), "--default-response", "PONG"])

        result = CLI.invoke(
            app,
            [
                "rank",
                "--gguf",
                str(good),
                "--gguf",
                str(collapsed),
                "--tasks",
                str(pack_dir),
                "--port",
                str(free_port()),
                "--server-bin",
                server,
            ],
            env={"COLUMNS": "120"},
        )
        assert result.exit_code == 0, result.output
        assert "Q4_K_M" in result.output
        assert "IQ2_XXS" in result.output
        assert "baseline" in result.output
        assert "-50.0 pp" in result.output
        assert "collapse:" in result.output

    def test_rank_cli_missing_pack_exits_nonzero(self, tmp_path: Path) -> None:
        good = make_gguf(tmp_path, "Model.Q4_K_M.gguf")
        result = CLI.invoke(
            app,
            ["rank", "--gguf", str(good), "--tasks", str(tmp_path / "nope")],
            env={"COLUMNS": "120"},
        )
        assert result.exit_code == 1
        assert "task pack not found" in result.output

    def test_rank_cli_missing_llama_server_exits_with_hint(self, tmp_path: Path) -> None:
        pack_dir = tmp_path / "tasks"
        pack_dir.mkdir()
        (pack_dir / "tasks.json").write_text(
            json.dumps(
                {
                    "base_model": "M",
                    "k_samples": 1,
                    "tasks": [
                        {"id": "t", "prompt": "p", "grader": {"type": "contains", "expected": "x"}}
                    ],
                }
            )
        )
        good = make_gguf(tmp_path, "Model.Q4_K_M.gguf")
        result = CLI.invoke(
            app,
            ["rank", "--gguf", str(good), "--tasks", str(pack_dir)],
            env={"COLUMNS": "120"},
        )
        assert result.exit_code == 1
        assert "llama-server not found on PATH" in result.output
        assert "brew install llama.cpp" in result.output


class TestSplitStackedGguf:
    def test_expands_space_separated_values(self) -> None:
        from quantproof.cli import _split_stacked_gguf

        argv = [
            "rank",
            "--gguf",
            "a.gguf",
            "b.gguf",
            "c.gguf",
            "--tasks",
            "./tasks",
        ]
        assert _split_stacked_gguf(argv) == [
            "rank",
            "--gguf",
            "a.gguf",
            "--gguf",
            "b.gguf",
            "--gguf",
            "c.gguf",
            "--tasks",
            "./tasks",
        ]

    def test_repeated_flags_untouched(self) -> None:
        from quantproof.cli import _split_stacked_gguf

        argv = ["rank", "--gguf", "a.gguf", "--gguf", "b.gguf"]
        assert _split_stacked_gguf(argv) == argv

    def test_real_entrypoint_accepts_stacked_form(self, tmp_path: Path) -> None:
        """The documented command form works through the shipped entrypoint."""
        pack_dir = tmp_path / "tasks"
        pack_dir.mkdir()
        (pack_dir / "tasks.json").write_text(
            json.dumps(
                {
                    "base_model": "Some/Model",
                    "k_samples": 1,
                    "tasks": [
                        {
                            "id": "ping",
                            "prompt": "Say PONG",
                            "grader": {"type": "contains", "expected": "PONG"},
                        }
                    ],
                }
            )
        )
        good = make_gguf(tmp_path, "Model.Q4_K_M.gguf")
        collapsed = make_gguf(tmp_path, "Model.IQ2_XXS.gguf")
        server = " ".join([sys.executable, str(STUB), "--default-response", "PONG"])
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "quantproof",
                "rank",
                "--gguf",
                str(good),
                str(collapsed),
                "--tasks",
                str(pack_dir),
                "--port",
                str(free_port()),
                "--server-bin",
                server,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            cwd=str(tmp_path),  # rank writes report artifacts into its CWD
        )
        assert proc.returncode == 0, proc.stderr + proc.stdout
        assert "baseline" in proc.stdout
        assert "Q4_K_M" in proc.stdout and "IQ2_XXS" in proc.stdout
        assert (tmp_path / "report.md").is_file()
        assert (tmp_path / "results.json").is_file()


def test_variantrun_helpers() -> None:
    from quantproof.runner import SampleRecord

    run = VariantRun(
        variant="Q4_K_M",
        gguf_path=Path("m.gguf"),
        size_gb=1.0,
        samples=[
            SampleRecord(task_id="a", sample=0, passed=True),
            SampleRecord(task_id="a", sample=1, passed=False),
            SampleRecord(task_id="b", sample=0, passed=True),
        ],
    )
    assert run.sample_count("a") == 2
    assert run.passed_count("a") == 1
    assert run.passed_count("b") == 1
    assert run.sample_count("zzz") == 0
