"""GAMA tool entry point; authoritative implementation in ranr.gama.validation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if __name__ == "__main__":
    import runpy
    runpy.run_module("ranr.gama.validation", run_name="__main__")
else:
    import importlib
    sys.modules[__name__] = importlib.import_module("ranr.gama.validation")
