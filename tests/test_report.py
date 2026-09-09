"""Scoring math, collapse-delta computation and table rendering."""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console

from quantproof.models import TaskPack, VariantResult, build_calibration
from quantproof.report import (
    collapsed_variants,
    print_report,
    render_rank_table,
    render_task_matrix,
    summarize_run,
)
from quantproof.runner import SampleRecord, VariantRun

PACK = TaskPack.model_validate(
    {
        "base_model": "Some/Model",
        "k_samples": 2,
        "tasks": [
            {"id": "a", "prompt": "pa", "grader": {"type": "contains", "expected": "x"}},
            {"id": "b", "prompt": "pb", "grader": {"type": "contains", "expected": "y"}},
        ],
    }
)


def make_run(
    variant: str,
    passed_by_task: dict[str, list[bool]],
    tok_s_values: list[float | None] | None = None,
    size_gb: float = 16.0,
) -> VariantRun:
    """Build a run; tok_s_values align flat with samples in task-iteration order."""
    tok_s_iter = iter(tok_s_values if tok_s_values is not None else [])
    samples = []
    for task_id, flags in passed_by_task.items():
        for index, passed in enumerate(flags):
            tok_s = next(tok_s_iter, None)
            samples.append(
                SampleRecord(task_id=task_id, sample=index, passed=passed, tok_s=tok_s)
            )
    return VariantRun(
        variant=variant, gguf_path=Path(f"{variant}.gguf"), size_gb=size_gb, samples=samples
    )


class TestSummarizeRun:
    def test_score_and_per_task_rates(self) -> None:
        run = make_run("Q4_K_M", {"a": [True, True], "b": [True, False]})
        result = summarize_run(run)
        assert result.variant == "Q4_K_M"
        assert result.score == pytest.approx((1.0 + 0.5) / 2)
        assert result.per_task == {"a": 1.0, "b": 0.5}
        assert result.size_gb == 16.0

    def test_tok_s_mean_skips_unmeasured_samples(self) -> None:
        run = make_run(
            "Q4_K_M",
            {"a": [True, True], "b": [True, True]},
            tok_s_values=[100.0, None, 50.0, None],
        )
        result = summarize_run(run)
        assert result.tok_s == pytest.approx(75.0)

    def test_tok_s_zero_when_nothing_measured(self) -> None:
        run = make_run("Q4_K_M", {"a": [True]}, tok_s_values=[None])
        assert summarize_run(run).tok_s == 0.0

    def test_empty_run_raises(self) -> None:
        with pytest.raises(ValueError, match="no samples"):
            summarize_run(VariantRun("x", Path("x.gguf"), 0.0))


class TestBuildCalibration:
    def test_reference_is_best_and_deltas_are_score_differences(self) -> None:
        rows = [
            VariantResult(variant="Q4_K_M", score=0.9, tok_s=40.0, size_gb=16.0, per_task={}),
            VariantResult(variant="IQ2_XXS", score=0.5, tok_s=60.0, size_gb=6.0, per_task={}),
            VariantResult(variant="Q2_K", score=0.7, tok_s=55.0, size_gb=10.0, per_task={}),
        ]
        calibration = build_calibration(rows)
        assert calibration.reference.variant == "Q4_K_M"
        assert [row.variant for row in calibration.rows] == ["Q4_K_M", "Q2_K", "IQ2_XXS"]
        assert calibration.deltas == {"Q4_K_M": 0.0, "Q2_K": pytest.approx(-0.2), "IQ2_XXS": pytest.approx(-0.4)}

    def test_tie_keeps_first_as_reference(self) -> None:
        rows = [
            VariantResult(variant="A", score=0.5, tok_s=1.0, size_gb=1.0, per_task={}),
            VariantResult(variant="B", score=0.5, tok_s=2.0, size_gb=1.0, per_task={}),
        ]
        calibration = build_calibration(rows)
        assert calibration.reference.variant == "A"
        assert calibration.deltas["B"] == 0.0

    def test_single_result_is_its_own_reference(self) -> None:
        row = VariantResult(variant="only", score=0.25, tok_s=1.0, size_gb=1.0, per_task={})
        calibration = build_calibration([row])
        assert calibration.reference is row
        assert calibration.deltas == {"only": 0.0}

    def test_empty_results_raise(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            build_calibration([])


class TestCollapseDetection:
    @staticmethod
    def calibration_with_delta(delta: float):
        rows = [
            VariantResult(variant="ref", score=1.0, tok_s=1.0, size_gb=1.0, per_task={}),
            VariantResult(variant="low", score=1.0 + delta, tok_s=1.0, size_gb=1.0, per_task={}),
        ]
        return build_calibration(rows)

    def test_delta_past_threshold_is_flagged(self) -> None:
        collapsed = collapsed_variants(self.calibration_with_delta(-0.11))
        assert [row.variant for row in collapsed] == ["low"]

    def test_above_threshold_not_flagged(self) -> None:
        assert collapsed_variants(self.calibration_with_delta(-0.09)) == []

    def test_reference_never_flagged(self) -> None:
        assert collapsed_variants(self.calibration_with_delta(0.0)) == []


class TestRendering:
    def make_results(self) -> list[VariantResult]:
        runs = [
            make_run("Q4_K_M", {"a": [True, True], "b": [True, True]}),
            make_run("IQ2_XXS", {"a": [True, False], "b": [False, False]}),
        ]
        return [summarize_run(run) for run in runs]

    def captured(self, render) -> str:
        console = Console(record=True, width=120)
        console.print(render())
        return console.export_text()

    def test_rank_table_contents(self) -> None:
        calibration = build_calibration(self.make_results())
        text = self.captured(lambda: render_rank_table(calibration))
        assert "Q4_K_M" in text and "IQ2_XXS" in text
        assert "baseline" in text
        assert "-75.0 pp" in text
        assert "100.0%" in text and "25.0%" in text

    def test_rank_table_orders_best_first(self) -> None:
        calibration = build_calibration(self.make_results())
        text = self.captured(lambda: render_rank_table(calibration))
        assert text.index("Q4_K_M") < text.index("IQ2_XXS")

    def test_task_matrix_shows_pass_counts(self) -> None:
        text = self.captured(lambda: render_task_matrix(self.make_results(), PACK))
        assert "2/2" in text
        assert "0/2" in text and "1/2" in text
        assert "a" in text and "b" in text
        assert "contains" in text  # grader kind is shown per task
        assert text.index("Q4_K_M") < text.index("IQ2_XXS")  # best variant first

    def test_task_matrix_marks_missing_tasks(self) -> None:
        results = [
            VariantResult(variant="v", score=0.5, tok_s=1.0, size_gb=1.0, per_task={"a": 0.5})
        ]
        text = self.captured(lambda: render_task_matrix(results, PACK))
        assert "—" in text

    def test_print_report_calls_out_collapse(self) -> None:
        runs = [
            make_run("Q4_K_M", {"a": [True, True], "b": [True, True]}),
            make_run("IQ2_XXS", {"a": [True, False], "b": [False, False]}),
        ]
        console = Console(record=True, width=120)
        calibration = print_report(PACK, runs, console)
        text = console.export_text()
        assert "collapse:" in text
        assert "IQ2_XXS (-75.0 pp)" in text
        assert calibration.reference.variant == "Q4_K_M"
        assert "Per-task pass rate" in text

    def test_print_report_counts_sample_errors(self) -> None:
        runs = [
            VariantRun(
                variant="Q4_K_M",
                gguf_path=Path("m.gguf"),
                size_gb=1.0,
                samples=[
                    SampleRecord(task_id="a", sample=0, passed=False, error="boom"),
                    SampleRecord(task_id="b", sample=0, passed=True),
                ],
            )
        ]
        console = Console(record=True, width=120)
        print_report(PACK, runs, console)
        assert "1 sample(s) errored" in console.export_text()
