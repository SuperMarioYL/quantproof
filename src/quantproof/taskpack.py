"""Task-pack loading and scaffolding.

A task pack is a directory containing a ``tasks.json`` file (a direct
path to the JSON file also works). ``quantproof init`` writes the bundled
example pack into a fresh directory so the first run needs zero authoring.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from pydantic import ValidationError

from quantproof.models import TaskPack

PACK_FILENAME = "tasks.json"

# Package data: quantproof/data/example-pack/tasks.json
_BUNDLED_PACKAGE = "quantproof.data"
_BUNDLED_PACK = "example-pack"


class TaskPackError(RuntimeError):
    """Raised when a task pack cannot be found or does not validate."""


def load_task_pack(path: Path) -> TaskPack:
    """Load and validate a task pack from a directory or a tasks.json file."""
    pack_file = _resolve_pack_file(path)
    try:
        raw = json.loads(pack_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TaskPackError(f"{pack_file}: invalid JSON ({exc})") from exc
    try:
        return TaskPack.model_validate(raw)
    except ValidationError as exc:
        raise TaskPackError(f"{pack_file}: invalid task pack\n{exc}") from exc


def _resolve_pack_file(path: Path) -> Path:
    candidate = path if path.is_file() or path.suffix == ".json" else path / PACK_FILENAME
    if not candidate.is_file():
        hint = f" — the directory has no {PACK_FILENAME}" if path.is_dir() else ""
        raise TaskPackError(
            f"task pack not found: {candidate}{hint}. "
            "Run `quantproof init` to scaffold ./tasks with the example pack."
        )
    return candidate


def read_bundled_pack() -> str:
    """Return the bundled example pack's tasks.json content."""
    return (
        resources.files(_BUNDLED_PACKAGE) / _BUNDLED_PACK / PACK_FILENAME
    ).read_text(encoding="utf-8")


def scaffold_example_pack(dest: Path) -> Path:
    """Write the bundled 10-task example pack into ``dest/tasks.json``."""
    pack_file = dest / PACK_FILENAME
    try:
        dest.mkdir(parents=True, exist_ok=True)
        if pack_file.exists():
            raise TaskPackError(
                f"{pack_file} already exists — pick another directory or remove it first"
            )
        pack_file.write_text(read_bundled_pack(), encoding="utf-8")
    except OSError as exc:
        # exist_ok only covers an existing directory: a file at dest or an
        # unwritable parent must surface as the CLI's friendly error, not a
        # raw traceback.
        raise TaskPackError(f"cannot scaffold {dest}: {exc}") from exc
    return pack_file
