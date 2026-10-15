#!/usr/bin/env python3
"""Run GAMA fixtures, checking console assertions (launcher exit code alone is insufficient)."""
import argparse
import csv
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import json
import time

from ranr.paths import ROOT


def check_models():
    """Compile every GAML root in one JVM; CheckModel reports each root independently."""
    models = sorted((ROOT / "models").rglob("*.gaml"))
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/gama.py"), "-check", *map(str, models)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode or result.stdout.count("COMPILE_PASS") != len(models):
        raise RuntimeError("GAML compilation failed:\n" + result.stdout)
    for model in models:
        print(f"{model.relative_to(ROOT)}: COMPILE_PASS", flush=True)


def run_model(model, experiment, steps, marker=None, parameters=None, seed=42, resource_output=None):
    with tempfile.TemporaryDirectory(prefix="evstation-test-") as tmp:
        base = Path(tmp)
        xml = base / "plan.xml"
        out = base / "results"

        resources = []
        def launch(args):
            measurement = base / f"resources_{len(resources)}.json"
            started = time.perf_counter()
            result = subprocess.run(
                ["/usr/bin/time", "-q", "-f", '{"cpu_user_seconds":%U,"cpu_system_seconds":%S,"max_rss_kib":%M}', "-o", str(measurement), sys.executable, str(ROOT / "scripts/gama.py"), *map(str, args)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            resources.append({**json.loads(measurement.read_text().splitlines()[-1]), "wall_seconds":time.perf_counter()-started,"phase":"xml" if args[0]=="-xml" else "simulation"})
            if result.returncode:
                raise RuntimeError(result.stdout)
            return result.stdout

        compilation = launch(["-xml", experiment, ROOT / model, xml])
        if not xml.exists():
            raise RuntimeError(compilation)
        tree = ET.parse(xml)
        for sim in tree.findall("Simulation"):
            sim.set("finalStep", str(steps))
            sim.set("seed", str(seed))
            sim.find("Outputs").clear()
            sim.find("Parameters").clear()
            for name, (type_, value) in (parameters or {}).items():
                ET.SubElement(
                    sim.find("Parameters"),
                    "Parameter",
                    name=name,
                    var=name,
                    type="BOOLEAN" if type_=="BOOL" else type_,
                    value=str(value),
                )
        tree.write(xml)
        log = launch([xml, out])
        console = "\n".join(p.read_text() for p in out.glob("console*.txt"))
        console += "\n" + log
        failures = [
            "Runtime error",
            "Assert failed",
            "Error in",
            "Exception",
            "NOT_IMPLEMENTED",
            "No parameter named",
        ]
        if any(word in console for word in failures) or (
            marker and marker not in console
        ):
            raise RuntimeError(console + "\n" + log)
        if resource_output:
            resource_output = Path(resource_output)
            resource_output.parent.mkdir(parents=True,exist_ok=True)
            resource_output.write_text(json.dumps({"model":model,"experiment":experiment,"steps":steps,"marker":marker,"resources":resources},indent=2))
        print(f'{model}: {marker or "RUN_PASS"}', flush=True)
        return console


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compatibility entry point for unified GAMA validation"
    )
    parser.add_argument("--suite", action="store_true")
    parser.add_argument("--skip-compile", action="store_true")
    parser.add_argument("--compile", action="store_true")
    parser.add_argument(
        "--gis", action="store_true", help="GIS is covered by the unified fleet fixture"
    )
    args = parser.parse_args()
    sys.argv = ["ranr", "validate"] + (["--compile"] if not args.skip_compile else [])
    from ranr.gama.cli import main

    main()
