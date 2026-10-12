"""Turn raw variant runs into the ranked table with collapse deltas.

The report surface is twofold: the rich terminal table (variant | pass
rate | Δ vs best | tok/s | size plus a per-task pass matrix), and the
gistable on-disk artifacts written after every run — ``report.md`` for
sharing and ``results.json`` for tooling. Variants collapsed by more
than COLLAPSE_DELTA_PP percentage points against the reference are
called out in both. Crash-resumable ``results.jsonl`` runs stay m2.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from quantproof import __version__
from quantproof.models import Calibration, TaskPack, VariantResult, build_calibration
from quantproof.runner import VariantRun

# A variant more than this many percentage points below the reference is
# flagged as a collapse in the table footer.
COLLAPSE_DELTA_PP = 10.0


def summarize_run(run: VariantRun) -> VariantResult:
    """Aggregate one variant's samples into a score, tok/s and per-task rates."""
    if not run.samples:
        raise ValueError(f"no samples collected for variant {run.variant}")
    outcomes: dict[str, list[bool]] = {}
    for sample in run.samples:
        outcomes.setdefault(sample.task_id, []).append(sample.passed)
    per_task = {task_id: sum(flags) / len(flags) for task_id, flags in outcomes.items()}
    # Mean over tasks, matching "mean pass rate over k samples x tasks".
    score = sum(per_task.values()) / len(per_task)
    tok_s_values = [s.tok_s for s in run.samples if s.tok_s is not None]
    tok_s = sum(tok_s_values) / len(tok_s_values) if tok_s_values else 0.0
    return VariantResult(
        variant=run.variant,
        score=score,
        tok_s=tok_s,
        size_gb=run.size_gb,
        per_task=per_task,
    )


def summarize_runs(runs: Sequence[VariantRun]) -> list[VariantResult]:
    return [summarize_run(run) for run in runs]


def collapsed_variants(calibration: Calibration) -> list[VariantResult]:
    """Rows whose delta versus the reference crosses the collapse threshold."""
    return [
        row
        for row in calibration.rows
        if calibration.deltas[row.variant] <= -COLLAPSE_DELTA_PP / 100.0
    ]


def render_rank_table(calibration: Calibration) -> Table:
    """The headline table: variant | pass rate | Δ vs best | tok/s | size."""
    table = Table(title="Quant calibration — ranked on your tasks", highlight=True)
    table.add_column("Variant", no_wrap=True)
    table.add_column("Pass rate", justify="right")
    table.add_column("Δ vs best", justify="right")
    table.add_column("tok/s", justify="right")
    table.add_column("Size (GB)", justify="right")
    for row in calibration.rows:
        delta_pp = calibration.deltas[row.variant] * 100.0
        delta_cell = Text("baseline") if row is calibration.reference else Text(f"{delta_pp:+.1f} pp")
        if delta_pp <= -COLLAPSE_DELTA_PP:
            delta_cell.stylize("bold red")
        table.add_row(
            row.variant,
            f"{row.score * 100.0:.1f}%",
            delta_cell,
            f"{row.tok_s:.1f}",
            f"{row.size_gb:.2f}",
        )
    return table


def render_task_matrix(results: Sequence[VariantResult], pack: TaskPack) -> Table:
    """Per-task pass counts — the noise behind the mean, task by task."""
    ordered = sorted(results, key=lambda result: result.score, reverse=True)
    table = Table(title="Per-task pass rate (passed samples / k)", highlight=True)
    table.add_column("Task", no_wrap=True)
    table.add_column("Grader", no_wrap=True)
    for result in ordered:
        table.add_column(result.variant, justify="center", no_wrap=True)
    for task in pack.tasks:
        cells = []
        for result in ordered:
            rate = result.per_task.get(task.id)
            if rate is None:
                cells.append(Text("—", style="dim"))
            else:
                cells.append(f"{rate * pack.k_samples:.0f}/{pack.k_samples}")
        table.add_row(task.id, task.grader.type, *cells)
    return table


def print_report(
    pack: TaskPack,
    runs: Sequence[VariantRun],
    console: Console | None = None,
) -> Calibration:
    """Summarize runs, build the calibration and print the full m1 report."""
    console = console or Console()
    results = summarize_runs(runs)
    calibration = build_calibration(results)

    console.print(
        f"\n[bold]QuantProof[/bold] — {len(pack.tasks)} tasks x k={pack.k_samples} "
        f"per variant, base model: {pack.base_model}"
    )
    console.print(render_rank_table(calibration))

    collapsed = collapsed_variants(calibration)
    if collapsed:
        names = ", ".join(
            f"{row.variant} ({calibration.deltas[row.variant] * 100.0:+.1f} pp)" for row in collapsed
        )
        console.print(
            f"[red]collapse:[/red] {names} versus {calibration.reference.variant} on your tasks",
        )

    console.print(render_task_matrix(results, pack))
    sample_errors = sum(
        1 for run in runs for sample in run.samples if sample.error is not None
    )
    if sample_errors:
        console.print(
            f"[yellow]{sample_errors} sample(s) errored and were scored as failed[/yellow]"
        )
    return calibration


# -- gistable artifacts -----------------------------------------------------


def render_markdown_report(calibration: Calibration, pack: TaskPack) -> str:
    """The report.md body: ranked table, collapse call-outs, per-task matrix."""
    lines = [
        f"# QuantProof report — {pack.base_model}",
        "",
        f"{len(pack.tasks)} tasks x k={pack.k_samples} per variant, "
        "ranked by pass rate on your task pack.",
        "",
        "| Variant | Pass rate | Δ vs best | tok/s | Size (GB) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in calibration.rows:
        delta_pp = calibration.deltas[row.variant] * 100.0
        delta_cell = "baseline" if row is calibration.reference else f"{delta_pp:+.1f} pp"
        lines.append(
            f"| {row.variant} | {row.score * 100.0:.1f}% | {delta_cell} "
            f"| {row.tok_s:.1f} | {row.size_gb:.2f} |"
        )

    collapsed = collapsed_variants(calibration)
    if collapsed:
        names = ", ".join(
            f"{row.variant} ({calibration.deltas[row.variant] * 100.0:+.1f} pp)"
            for row in collapsed
        )
        lines += [
            "",
            f"**collapse:** {names} versus {calibration.reference.variant} on your tasks",
        ]

    ordered = sorted(calibration.rows, key=lambda result: result.score, reverse=True)
    lines += [
        "",
        "## Per-task pass rate",
        "",
        "| Task | Grader | " + " | ".join(result.variant for result in ordered) + " |",
        "| --- | --- | " + " | ".join("---" for _ in ordered) + " |",
    ]
    for task in pack.tasks:
        cells = []
        for result in ordered:
            rate = result.per_task.get(task.id)
            cells.append(
                "—" if rate is None else f"{rate * pack.k_samples:.0f}/{pack.k_samples}"
            )
        lines.append(f"| {task.id} | {task.grader.type} | " + " | ".join(cells) + " |")

    lines += ["", f"Generated by quantproof {__version__}."]
    return "\n".join(lines) + "\n"


def write_run_artifacts(
    out_dir: Path, calibration: Calibration, pack: TaskPack
) -> tuple[Path, Path]:
    """Write report.md and results.json into ``out_dir``; return their paths.

    A pre-existing pair is overwritten: the artifacts describe the latest
    completed run, matching the one-artifact-per-run story.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.md"
    report_path.write_text(render_markdown_report(calibration, pack), encoding="utf-8")
    results_path = out_dir / "results.json"
    payload = {
        "base_model": pack.base_model,
        "k_samples": pack.k_samples,
        "task_count": len(pack.tasks),
        "reference": calibration.reference.model_dump(),
        "rows": [row.model_dump() for row in calibration.rows],
        "deltas": calibration.deltas,
        "generated_by": f"quantproof {__version__}",
    }
    results_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return report_path, results_path
