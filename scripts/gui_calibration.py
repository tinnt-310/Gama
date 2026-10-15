"""GAMA GUI bridge; performs provenance/analysis only, never simulates vehicles."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ranr.gama.gui_collection import main

if __name__ == "__main__":
    main()
