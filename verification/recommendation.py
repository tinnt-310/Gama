"""Compatibility entry point; canonical implementation: ranr.legacy.verification.recommendation."""

import sys
from pathlib import Path

# Bootstrap only for historical commands before editable installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if __name__ == "__main__":
    import runpy

    runpy.run_module("ranr.legacy.verification.recommendation", run_name="__main__")
else:
    import importlib

    sys.modules[__name__] = importlib.import_module(
        "ranr.legacy.verification.recommendation"
    )
