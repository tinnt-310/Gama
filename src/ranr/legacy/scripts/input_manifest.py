"""Offline GIS fingerprints; GAMA copies this manifest without running Python."""

import hashlib
import json
from pathlib import Path

from ranr.paths import ROOT


def build_manifest():
    sources = {}
    for stem in ("line", "Middle", "final", "Part1", "Part2", "temporary_cs"):
        for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            path = ROOT / "includes" / (stem + suffix)
            if path.exists():
                sources[str(path.relative_to(ROOT))] = {
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size,
                }
    return {
        "sources": sources,
        "road_direction_assumption": "bidirectional",
        "station_access": "nearest node in largest connected road component; maximum 300 m",
        "fingerprint_source": "offline precomputed; regenerate after changing GIS inputs",
    }


def write_manifest():
    destination = ROOT / "outputs" / "input_manifest.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(build_manifest(), indent=2) + "\n")
    return destination


if __name__ == "__main__":
    print(write_manifest())
