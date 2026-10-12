"""The quantproof CLI: doctor, init, rank.

m1 scope: run local GGUF variants against a task pack and print the ranked
table with collapse deltas. Every rank run also writes the gistable
``report.md`` and machine-readable ``results.json`` (v0.2.0). Auto-download
of variants (``--gguf-repo`` / ``--quants``) and resumable results.jsonl
runs are m2 milestones and are not implemented yet.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from quantproof import __version__
from quantproof.models import TaskPack
from quantproof.report import print_report, write_run_artifacts
from quantproof.resolve import resolve_variants
from quantproof.runner import INSTALL_HINT, Runner, RunnerError, SampleRecord
from quantproof.taskpack import TaskPackError, load_task_pack, scaffold_example_pack

app = typer.Typer(
    name="quantproof",
    help="Rank quant variants of one local model on your own tasks.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"quantproof {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option("--version", help="Show version and exit", callback=_version_callback, is_eager=True),
    ] = False,
) -> None:
    """Rank quant variants of one local model on your own tasks."""


@app.command()
def doctor() -> None:
    """Check that llama-server is on PATH and report GPU visibility."""
    ok = True

    binary = shutil.which("llama-server")
    if binary:
        console.print(f"[green]llama-server[/green]: {binary}")
    else:
        ok = False
        err_console.print("[red]llama-server[/red]: NOT FOUND")
        err_console.print(INSTALL_HINT)

    gpu = _detect_gpu()
    if gpu:
        console.print(f"[green]gpu[/green]: {gpu}")
    else:
        console.print(
            "[yellow]gpu[/yellow]: none detected — llama-server will run on CPU "
            "(still works, just slower)"
        )

    console.print(f"python: {sys.version.split()[0]} ({platform.system()})")
    console.print(f"quantproof: {__version__}")
    if not ok:
        raise typer.Exit(code=1)


def _detect_gpu() -> str:
    """Best-effort GPU visibility probe; empty string means none detected."""
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            proc = subprocess.run(
                [nvidia_smi, "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip().splitlines()[0].strip()
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "Apple Silicon GPU (llama.cpp uses Metal automatically)"
    if Path("/dev/dri").is_dir():
        return "GPU device nodes present (/dev/dri)"
    return ""


@app.command()
def init(
    directory: Annotated[
        Path, typer.Option("--dir", help="Directory to scaffold the example pack into")
    ] = Path("./tasks"),
) -> None:
    """Scaffold ./tasks with the bundled example pack (10 tasks, zero authoring)."""
    try:
        pack_file = scaffold_example_pack(directory)
    except TaskPackError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    pack = load_task_pack(directory)
    codeblock = sum(1 for task in pack.tasks if task.grader.type == "codeblock")
    contains = len(pack.tasks) - codeblock
    console.print(f"example pack written to [bold]{pack_file}[/bold]")
    console.print(
        f"{len(pack.tasks)} tasks ({codeblock} C-coding with test commands, "
        f"{contains} general-QA with contains checks), k={pack.k_samples}"
    )
    console.print(
        "\nnext: point rank at your GGUFs —\n"
        f"  quantproof rank --gguf model.Q4_K_M.gguf model.IQ2_XXS.gguf --tasks {directory}"
    )


@app.command()
def rank(
    gguf: Annotated[
        list[Path],
        typer.Option("--gguf", help="Local GGUF file of one variant; repeat for each variant"),
    ],
    tasks: Annotated[
        Path, typer.Option("--tasks", help="Task pack directory (or its tasks.json)")
    ],
    k: Annotated[
        Optional[int], typer.Option("--k", min=1, help="Override the pack's k_samples")
    ] = None,
    port: Annotated[int, typer.Option("--port", help="Port for the llama-server child")] = 8111,
    startup_timeout: Annotated[
        float, typer.Option("--startup-timeout", min=1.0, help="Seconds to wait for llama-server /health")
    ] = 600.0,
    server_bin: Annotated[
        str,
        typer.Option(
            "--server-bin",
            help="llama-server-compatible command (advanced; e.g. a wrapper or the test stub)",
        ),
    ] = "llama-server",
    out: Annotated[
        Path,
        typer.Option(
            "--out",
            help="Directory for report.md and results.json (created when missing)",
        ),
    ] = Path("."),
) -> None:
    """Run every GGUF variant against the task pack and print the ranked table."""
    try:
        pack = load_task_pack(tasks)
    except TaskPackError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if k is not None:
        pack = TaskPack(base_model=pack.base_model, k_samples=k, tasks=pack.tasks)

    try:
        variants = resolve_variants(gguf)
    except (FileNotFoundError, ValueError) as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    runner = Runner(
        server_bin, port=port, startup_timeout=startup_timeout
    )
    runs = []
    for index, variant in enumerate(variants, start=1):
        console.print(
            f"\n[bold]variant {index}/{len(variants)}: {variant.label}[/bold] "
            f"({variant.path.name}, {variant.size_gb:.2f} GB)"
        )
        total = len(pack.tasks) * pack.k_samples
        try:
            runs.append(
                _run_with_progress(runner, pack, variant, total)
            )
        except RunnerError as exc:
            err_console.print(f"[red]error:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    calibration = print_report(pack, runs, console)
    try:
        report_path, results_path = write_run_artifacts(out, calibration, pack)
    except OSError as exc:
        err_console.print(f"[red]error:[/red] cannot write report artifacts: {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"\nreport written to [bold]{report_path}[/bold] (+ {results_path.name})")


def _run_with_progress(
    runner: Runner, pack: TaskPack, variant, total: int
):
    """Drive one variant, with a progress bar only when attached to a terminal."""
    if not console.is_terminal:
        console.print(f"running {total} samples ...")
        return runner.run_variant(pack, variant)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"{variant.label}", total=total)

        def on_sample(record: SampleRecord) -> None:
            progress.advance(task)
            if record.error is not None:
                progress.console.print(
                    f"  [yellow]sample failed[/yellow] {record.task_id}#{record.sample + 1}: "
                    f"{record.error.splitlines()[0]}"
                )

        return runner.run_variant(pack, variant, on_sample=on_sample)


def main(argv: list[str] | None = None) -> None:
    app(_split_stacked_gguf(list(sys.argv[1:] if argv is None else argv)))


def _split_stacked_gguf(argv: list[str]) -> list[str]:
    """Allow the plan's stacked form: ``--gguf a.gguf b.gguf c.gguf``.

    click options cannot be variadic, so the space-separated values that
    follow one ``--gguf`` flag are expanded into repeated flags before
    parsing. Repeated ``--gguf a --gguf b`` keeps working unchanged.
    """
    expanded: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        expanded.append(token)
        index += 1
        if token == "--gguf":
            first_value = True
            while index < len(argv) and not argv[index].startswith("-"):
                if not first_value:
                    expanded.append("--gguf")
                expanded.append(argv[index])
                first_value = False
                index += 1
    return expanded


if __name__ == "__main__":
    main()
