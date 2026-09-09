"""The two deterministic graders: Contains substring checks and CodeBlock tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from quantproof.grader import extract_code_block, grade_response
from quantproof.models import CodeBlock, Contains, Task

HAS_CC = shutil.which("cc") is not None


def contains_task(expected: str) -> Task:
    return Task(id="qa", prompt="answer", grader=Contains(expected=expected))


def codeblock_task(test_cmd: str, filename: str = "main.c", timeout_s: float = 60.0) -> Task:
    return Task(
        id="c",
        prompt="write code",
        grader=CodeBlock(test_cmd=test_cmd, filename=filename, timeout_s=timeout_s),
    )


class TestContains:
    def test_passes_when_substring_present(self) -> None:
        assert grade_response(contains_task("Paris"), "The capital is Paris.")

    def test_fails_when_substring_absent(self) -> None:
        assert not grade_response(contains_task("Paris"), "The capital is Lyon.")

    def test_is_exact_not_case_insensitive(self) -> None:
        assert not grade_response(contains_task("Paris"), "the capital is PARIS")

    def test_empty_response_fails(self) -> None:
        assert not grade_response(contains_task("Paris"), "")


class TestExtractCodeBlock:
    def test_extracts_first_block_with_language_tag(self) -> None:
        response = "Here you go:\n```c\nint main(void) { return 0; }\n```\nDone."
        assert extract_code_block(response) == "int main(void) { return 0; }"

    def test_extracts_block_without_language_tag(self) -> None:
        assert extract_code_block("```\nprint('hi')\n```") == "print('hi')"

    def test_returns_none_without_fence(self) -> None:
        assert extract_code_block("no code here") is None

    def test_first_block_wins(self) -> None:
        response = "```c\nALPHA\n```\ntext\n```c\nBETA\n```"
        assert extract_code_block(response) == "ALPHA"


class TestCodeBlock:
    def test_runs_command_in_isolated_dir_with_extracted_file(self) -> None:
        task = codeblock_task("test -f main.c && grep -q ALPHA main.c")
        assert grade_response(task, "```c\nALPHA\n```")

    def test_writes_custom_filename(self) -> None:
        task = codeblock_task("test -f solution.py", filename="solution.py")
        assert grade_response(task, "```python\nx = 1\n```")

    def test_fails_on_nonzero_exit(self) -> None:
        task = codeblock_task("exit 3")
        assert not grade_response(task, "```c\nwhatever\n```")

    def test_fails_without_code_block(self) -> None:
        task = codeblock_task("test -f main.c")
        assert not grade_response(task, "I cannot write code.")

    def test_fails_on_timeout(self) -> None:
        task = codeblock_task("sleep 5", timeout_s=0.5)
        assert not grade_response(task, "```c\nx\n```")

    def test_grader_does_not_pollute_cwd(self, tmp_path: Path) -> None:
        marker = tmp_path / "sentinel.txt"
        marker.write_text("clean")
        task = codeblock_task("touch side-effect.txt")
        assert grade_response(task, "```c\nx\n```")
        assert list(tmp_path.iterdir()) == [marker]


@pytest.mark.skipif(not HAS_CC, reason="cc not available")
class TestCodeBlockWithCompiler:
    def test_compiles_and_runs_a_real_program(self) -> None:
        task = codeblock_task(
            "cc -o prog main.c && ./prog > out.txt && printf '55\\n' | diff - out.txt"
        )
        program = (
            "#include <stdio.h>\n"
            "int main(void) {\n"
            "    int a = 1, b = 1;\n"
            "    for (int i = 3; i <= 10; i++) { int t = a + b; a = b; b = t; }\n"
            "    printf(\"%d\\n\", b);\n"
            "    return 0;\n"
            "}"
        )
        assert grade_response(task, f"```c\n{program}\n```")

    def test_wrong_output_fails(self) -> None:
        task = codeblock_task(
            "cc -o prog main.c && ./prog > out.txt && printf '55\\n' | diff - out.txt"
        )
        program = (
            "#include <stdio.h>\nint main(void) { printf(\"54\\n\"); return 0; }"
        )
        assert not grade_response(task, f"```c\n{program}\n```")

    def test_broken_program_fails_to_compile(self) -> None:
        task = codeblock_task("cc -o prog main.c")
        assert not grade_response(task, "```c\nthis is not C at all\n```")
