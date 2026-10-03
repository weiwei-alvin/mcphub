"""Synthetic defect for team qualification; not product code."""
from pathlib import Path


def resolve_in_root(root, candidate):
    base = Path(root).resolve()
    target = (base / candidate).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError("outside root")
    return target
