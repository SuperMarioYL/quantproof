"""Every user-visible version surface moves in lockstep."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import quantproof

ROOT = Path(__file__).parents[1]


def test_version_is_020() -> None:
    assert quantproof.__version__ == "0.2.0"


def test_pyproject_version_matches() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == quantproof.__version__


def test_version_file_matches() -> None:
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == quantproof.__version__


def test_changelog_leads_with_current_version() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^## \[(.+?)\]", changelog, re.MULTILINE)
    assert match is not None
    assert match.group(1) == quantproof.__version__


def test_site_json_version_matches() -> None:
    meta = json.loads((ROOT / "web" / "site.json").read_text(encoding="utf-8"))["meta"]
    assert meta["implementation_version"] == quantproof.__version__
    assert meta["content_version"] == f"v{quantproof.__version__}"
