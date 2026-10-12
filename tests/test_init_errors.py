"""`quantproof init` fails with the friendly error, never a raw traceback."""

from __future__ import annotations

import os

import pytest
from typer.testing import CliRunner

from quantproof.cli import app

CLI = CliRunner()


def test_init_into_existing_file_prints_friendly_error(tmp_path) -> None:
    target = tmp_path / "afile.txt"
    target.write_text("not a directory", encoding="utf-8")
    result = CLI.invoke(app, ["init", "--dir", str(target)])
    assert result.exit_code == 1
    assert "error:" in result.output
    assert "cannot scaffold" in result.output
    assert "Traceback" not in result.output


@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="permission semantics need POSIX and a non-root user",
)
def test_init_into_unwritable_parent_prints_friendly_error(tmp_path) -> None:
    parent = tmp_path / "ro"
    parent.mkdir()
    parent.chmod(0o555)
    try:
        result = CLI.invoke(app, ["init", "--dir", str(parent / "sub")])
        assert result.exit_code == 1
        assert "error:" in result.output
        assert "Traceback" not in result.output
    finally:
        parent.chmod(0o755)


def test_init_into_fresh_nested_dir_still_works(tmp_path) -> None:
    target = tmp_path / "a" / "tasks"
    result = CLI.invoke(app, ["init", "--dir", str(target)])
    assert result.exit_code == 0
    assert (target / "tasks.json").is_file()
    assert "example pack written to" in result.output


def test_init_onto_existing_pack_keeps_friendly_error(tmp_path) -> None:
    """The pre-existing pre-existing-pack message is unchanged by the OSError fix."""
    target = tmp_path / "tasks"
    target.mkdir()
    (target / "tasks.json").write_text("{}", encoding="utf-8")
    result = CLI.invoke(app, ["init", "--dir", str(target)])
    assert result.exit_code == 1
    assert "already exists" in result.output
    assert "Traceback" not in result.output
