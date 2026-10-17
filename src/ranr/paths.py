"""Workspace paths and atomic artifact writes, independent of process cwd."""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(
    os.environ.get("RANR_WORKSPACE", Path(__file__).resolve().parents[2])
).resolve()
OUTPUTS = ROOT / "outputs" / "ranr"


def digest(path: Path) -> str:
    # Long physical traces can exceed the Python process's available memory.
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )
    temporary.replace(path)


def source_manifest() -> dict[str, str]:
    return {
        str(p.relative_to(ROOT)): digest(p)
        for p in sorted((ROOT / "src").rglob("*"))
        if p.suffix in (".py", ".cpp")
    }

# Official and historical outputs are intentionally distinct.
GAMA_OUTPUTS = ROOT / "outputs/gama_ranr"
