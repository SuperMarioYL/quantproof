"""Resolve local GGUF files into variant identities.

m1 works with GGUF files the user already has on disk. The variant label
is the quant tag parsed from the filename (``Model.Q4_K_M.gguf`` ->
``Q4_K_M``); when no quant tag is recognizable the file stem is used.

m2 (not implemented yet) will extend this module to resolve quant names
against a GGUF repository and auto-download variants through
huggingface_hub, honoring the HF_ENDPOINT mirror environment variable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Quant tags as they appear in GGUF filenames: Q4_K_M, Q2_K, Q8_0, IQ2_XXS,
# IQ1_S, TQ1_0, F16, BF16, F32 ... matched case-insensitively.
_QUANT_TAG = re.compile(r"(?:[IT]?Q\d+(?:_[A-Z0-9]+)*|BF16|F16|F32)", re.IGNORECASE)


@dataclass(frozen=True)
class Variant:
    """One runnable variant: a label, the local GGUF path and its size."""

    label: str
    path: Path
    size_gb: float


def quant_label(path: Path) -> str:
    """Derive the variant label from a GGUF filename.

    The last quant-looking token in the stem wins; without one, the whole
    stem is the label.
    """
    matches = _QUANT_TAG.findall(path.stem)
    return matches[-1] if matches else path.stem


def resolve_variants(paths: list[Path]) -> list[Variant]:
    """Validate local GGUF paths and turn them into variants.

    Raises FileNotFoundError for missing/non-GGUF paths and ValueError for
    colliding labels (results are keyed by label).
    """
    variants: list[Variant] = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"GGUF file not found: {path}")
        if path.suffix.lower() != ".gguf":
            raise ValueError(f"not a .gguf file: {path}")
        variants.append(
            Variant(label=quant_label(path), path=path, size_gb=path.stat().st_size / 2**30)
        )
    labels = [variant.label for variant in variants]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise ValueError(
            "duplicate variant labels resolved from the given files: "
            + ", ".join(duplicates)
            + " — each --gguf must produce a distinct quant label"
        )
    return variants
