"""Deterministic graders: run the task's own test command, or check a substring.

No LLM-as-judge in v0.1 — grading is reproducible by design. Code tasks
are graded exactly like CI: the first fenced code block is written to a
file in an isolated temp directory and the task's own ``test_cmd`` runs
there; exit code 0 is a pass. QA tasks pass when ``expected`` appears as
an exact substring of the response.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from quantproof.models import CodeBlock, Contains, Task

# First fenced code block: opening fence, optional language tag, body, closing fence.
_FENCED_BLOCK = re.compile(r"```[^\n]*\n(.*?)\n?```", re.DOTALL)


def extract_code_block(response: str) -> str | None:
    """Return the first fenced code block's body, or None."""
    match = _FENCED_BLOCK.search(response)
    return match.group(1) if match else None


def grade_response(task: Task, response: str) -> bool:
    """Grade one model response against one task's grader."""
    grader = task.grader
    if isinstance(grader, Contains):
        return grader.expected in response
    if isinstance(grader, CodeBlock):
        return _grade_code_block(grader, response)
    raise TypeError(f"unknown grader type: {type(grader).__name__}")


def _grade_code_block(grader: CodeBlock, response: str) -> bool:
    code = extract_code_block(response)
    if code is None:
        return False
    with tempfile.TemporaryDirectory(prefix="quantproof-grade-") as workdir:
        (Path(workdir) / grader.filename).write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run(
                grader.test_cmd,
                shell=True,
                cwd=workdir,
                capture_output=True,
                timeout=grader.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False
    return proc.returncode == 0
