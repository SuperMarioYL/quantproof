"""Task-pack loading, validation and scaffolding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quantproof.models import CodeBlock, Contains, TaskPack
from quantproof.taskpack import (
    PACK_FILENAME,
    TaskPackError,
    load_task_pack,
    scaffold_example_pack,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def write_pack(tmp_path: Path, payload: dict, filename: str = PACK_FILENAME) -> Path:
    pack_dir = tmp_path / "tasks"
    pack_dir.mkdir()
    (pack_dir / filename).write_text(json.dumps(payload), encoding="utf-8")
    return pack_dir


def minimal_pack() -> dict:
    return {
        "base_model": "Some/Model",
        "k_samples": 2,
        "tasks": [
            {"id": "t-1", "prompt": "Say PONG", "grader": {"type": "contains", "expected": "PONG"}},
        ],
    }


def test_load_pack_from_directory(tmp_path: Path) -> None:
    pack = load_task_pack(write_pack(tmp_path, minimal_pack()))
    assert pack.base_model == "Some/Model"
    assert pack.k_samples == 2
    assert pack.tasks[0].id == "t-1"
    assert isinstance(pack.tasks[0].grader, Contains)


def test_load_pack_from_json_file_directly(tmp_path: Path) -> None:
    pack_dir = write_pack(tmp_path, minimal_pack())
    pack = load_task_pack(pack_dir / PACK_FILENAME)
    assert len(pack.tasks) == 1


def test_grader_discriminated_union(tmp_path: Path) -> None:
    payload = minimal_pack()
    payload["tasks"].append(
        {
            "id": "c-1",
            "prompt": "Write a C program",
            "grader": {"type": "codeblock", "test_cmd": "cc -o prog main.c", "filename": "main.c"},
        }
    )
    pack = load_task_pack(write_pack(tmp_path, payload))
    assert isinstance(pack.tasks[0].grader, Contains)
    assert isinstance(pack.tasks[1].grader, CodeBlock)
    assert pack.tasks[1].grader.test_cmd == "cc -o prog main.c"
    assert pack.grader_kind("c-1") == "codeblock"
    assert pack.grader_kind("t-1") == "contains"


def test_rejects_duplicate_task_ids(tmp_path: Path) -> None:
    payload = minimal_pack()
    payload["tasks"].append(payload["tasks"][0])
    with pytest.raises(TaskPackError, match="duplicate task ids: t-1"):
        load_task_pack(write_pack(tmp_path, payload))


def test_rejects_unknown_grader_type(tmp_path: Path) -> None:
    payload = minimal_pack()
    payload["tasks"][0]["grader"] = {"type": "llm-judge", "prompt": "is it good?"}
    with pytest.raises(TaskPackError, match="invalid task pack"):
        load_task_pack(write_pack(tmp_path, payload))


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param({"tasks": []}, id="empty-tasks"),
        pytest.param({"k_samples": 0}, id="zero-k"),
        pytest.param({"base_model": ""}, id="empty-base-model"),
    ],
)
def test_rejects_invalid_packs(tmp_path: Path, mutate: dict) -> None:
    payload = {**minimal_pack(), **mutate}
    with pytest.raises(TaskPackError):
        load_task_pack(write_pack(tmp_path, payload))


def test_rejects_empty_grader_fields(tmp_path: Path) -> None:
    payload = minimal_pack()
    payload["tasks"][0]["grader"] = {"type": "contains", "expected": ""}
    with pytest.raises(TaskPackError):
        load_task_pack(write_pack(tmp_path, payload))


def test_error_names_the_file(tmp_path: Path) -> None:
    pack_dir = tmp_path / "tasks"
    pack_dir.mkdir()
    (pack_dir / PACK_FILENAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(TaskPackError, match=str(pack_dir / PACK_FILENAME)):
        load_task_pack(pack_dir)


def test_missing_pack_error_mentions_init(tmp_path: Path) -> None:
    with pytest.raises(TaskPackError, match="quantproof init"):
        load_task_pack(tmp_path / "nope")


def test_invalid_json_error(tmp_path: Path) -> None:
    pack_dir = write_pack(tmp_path, minimal_pack())
    (pack_dir / PACK_FILENAME).write_text("{", encoding="utf-8")
    with pytest.raises(TaskPackError, match="invalid JSON"):
        load_task_pack(pack_dir)


def test_scaffold_example_pack(tmp_path: Path) -> None:
    dest = tmp_path / "tasks"
    pack_file = scaffold_example_pack(dest)
    assert pack_file == dest / PACK_FILENAME
    pack = load_task_pack(dest)
    codeblock = sum(1 for task in pack.tasks if task.grader.type == "codeblock")
    assert len(pack.tasks) == 10
    assert codeblock == 5
    assert len(pack.tasks) - codeblock == 5


def test_scaffold_refuses_overwrite(tmp_path: Path) -> None:
    scaffold_example_pack(tmp_path / "tasks")
    with pytest.raises(TaskPackError, match="already exists"):
        scaffold_example_pack(tmp_path / "tasks")


@pytest.mark.skipif(
    not (REPO_ROOT / "examples" / "c-coding").is_dir(), reason="examples/ not present"
)
def test_bundled_pack_is_union_of_examples() -> None:
    """The bundled 10-task pack must stay identical to the two example packs."""
    bundled = load_task_pack(REPO_ROOT / "src/quantproof/data/example-pack")
    c_coding = load_task_pack(REPO_ROOT / "examples/c-coding")
    general_qa = load_task_pack(REPO_ROOT / "examples/general-qa")
    expected = TaskPack(
        base_model=c_coding.base_model,
        k_samples=c_coding.k_samples,
        tasks=c_coding.tasks + general_qa.tasks,
    )
    assert bundled == expected
