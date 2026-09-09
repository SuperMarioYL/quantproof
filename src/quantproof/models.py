"""Core data model: the task pack and the collapse-delta primitive.

The plan's contract:

    Task          = {id, prompt, grader: CodeBlock(test_cmd) | Contains(expected)}
    TaskPack      = {base_model, k_samples, tasks}
    VariantResult = {variant, score, tok_s, size_gb, per_task}
    Calibration   = {reference, rows, delta: variant -> score - reference.score}

The calibration is the product's primitive: a per-variant quality score
measured on a portable, user-owned task pack, expressed relative to the
best variant that ran. Nothing else emits this artifact — llama-bench
stops at speed and perplexity, lm-eval scores fixed public suites, and
blog tables score their author's tasks.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CodeBlock(BaseModel):
    """Grade by extracting the first fenced code block and running a shell command.

    The block is written to ``filename`` inside an isolated temporary
    directory and ``test_cmd`` runs there; exit code 0 is a pass. Task
    packs are user-authored local files with the same trust level as CI
    scripts.
    """

    type: Literal["codeblock"] = "codeblock"
    test_cmd: str = Field(min_length=1, description="Shell command run in the temp dir; exit 0 = pass")
    filename: str = Field(default="main.c", description="Name given to the extracted code block")
    timeout_s: float = Field(default=60.0, gt=0, description="Test command timeout in seconds")


class Contains(BaseModel):
    """Grade by an exact, case-sensitive substring check (general-QA tasks)."""

    type: Literal["contains"] = "contains"
    expected: str = Field(min_length=1, description="Substring that must appear in the response")


Grader = Annotated[Union[CodeBlock, Contains], Field(discriminator="type")]


class Task(BaseModel):
    """One prompt plus its deterministic grader."""

    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    prompt: str = Field(min_length=1)
    grader: Grader


class TaskPack(BaseModel):
    """A portable, user-owned set of tasks for one base model."""

    base_model: str = Field(min_length=1, description="e.g. Qwen/Qwen3.8-27B — informational")
    k_samples: int = Field(default=1, ge=1, description="Samples drawn per task per variant")
    tasks: list[Task] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_task_ids(self) -> "TaskPack":
        ids = [task.id for task in self.tasks]
        duplicates = sorted({task_id for task_id in ids if ids.count(task_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate task ids: {', '.join(duplicates)}")
        return self

    def grader_kind(self, task_id: str) -> str:
        """Return the grader type of one task ("codeblock" or "contains")."""
        for task in self.tasks:
            if task.id == task_id:
                return task.grader.type
        raise KeyError(task_id)


class VariantResult(BaseModel):
    """Outcome of one variant over the whole pack."""

    model_config = ConfigDict(frozen=True)

    variant: str
    score: float = Field(ge=0.0, le=1.0, description="Mean pass rate over k samples x tasks")
    tok_s: float = Field(ge=0.0, description="Mean output tokens per second over measured samples")
    size_gb: float = Field(ge=0.0)
    per_task: dict[str, float] = Field(description="Pass rate per task id (0..1)")


class Calibration(BaseModel):
    """Ranked results plus the collapse delta of every variant versus the reference.

    The reference is the best-scoring variant that ran; deltas are in
    score units (1.0 == 100 percentage points of pass rate).
    """

    model_config = ConfigDict(frozen=True)

    reference: VariantResult
    rows: list[VariantResult] = Field(description="All results, best score first")
    deltas: dict[str, float] = Field(description="variant -> score - reference.score")


def build_calibration(results: Sequence[VariantResult]) -> Calibration:
    """Rank results and express every variant relative to the best that ran.

    Sorting is by score descending and stable, so equal scores keep their
    run order and the first of them becomes the reference.
    """
    if not results:
        raise ValueError("calibration needs at least one variant result")
    ordered = sorted(results, key=lambda result: result.score, reverse=True)
    reference = ordered[0]
    deltas = {result.variant: result.score - reference.score for result in ordered}
    return Calibration(reference=reference, rows=ordered, deltas=deltas)
