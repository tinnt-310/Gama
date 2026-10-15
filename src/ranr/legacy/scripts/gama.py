#!/usr/bin/env python3
"""Portable GAMA 1.9.3 launcher; all Eclipse state is in a writable temp dir."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from ranr.paths import ROOT


def run(args):
    installation = Path(os.environ.get("GAMA_HOME", "/opt/gama-platform")).resolve()
    with tempfile.TemporaryDirectory(prefix="evstation-gama-") as tmp:
        base = Path(tmp)
        configuration = base / "configuration"
        bundle_dir = configuration / "org.eclipse.equinox.simpleconfigurator"
        bundle_dir.mkdir(parents=True)
        original = installation / "headless/configuration"
        info = (
            original / "org.eclipse.equinox.simpleconfigurator/bundles.info"
        ).read_text()
        (bundle_dir / "bundles.info").write_text(
            info.replace(",plugins/", f",file:{installation}/plugins/")
        )
        config = (original / "config.ini").read_text()
        config = config.replace("file\\:plugins/", f"file\\:{installation}/plugins/")
        config = config.replace(
            "reference\\:file\\:org.eclipse.equinox.simpleconfigurator_",
            f"reference\\:file\\:{installation}/plugins/org.eclipse.equinox.simpleconfigurator_",
        )
        (configuration / "config.ini").write_text(config)
        launcher = next(
            (installation / "plugins").glob("org.eclipse.equinox.launcher_*.jar")
        )
        application = "msi.gama.headless.product"
        if args and args[0] == "-check":
            args = args[1:]
            classes = base / "classes"
            classes.mkdir()
            source = ROOT / "scripts/java/CheckModel.java"
            subprocess.run(
                [
                    str(installation / "jdk/bin/javac"),
                    "-proc:none",
                    "-cp",
                    str(installation / "plugins/*"),
                    "-d",
                    str(classes),
                    str(source),
                ],
                check=True,
            )
            (classes / "plugin.xml").write_text(
                '<plugin><extension point="org.eclipse.core.runtime.applications" id="check"><application><run class="evstation.CheckModel"/></application></extension></plugin>'
            )
            manifest = base / "MANIFEST.MF"
            manifest.write_text(
                "Manifest-Version: 1.0\nBundle-ManifestVersion: 2\nBundle-SymbolicName: evstation.tools;singleton:=true\nBundle-Version: 1.0.0\nDynamicImport-Package: *\n\n"
            )
            bundle = base / "check.jar"
            subprocess.run(
                [
                    str(installation / "jdk/bin/jar"),
                    "cfm",
                    str(bundle),
                    str(manifest),
                    "-C",
                    str(classes),
                    ".",
                ],
                check=True,
            )
            with (bundle_dir / "bundles.info").open("a") as handle:
                handle.write(f"\nevstation.tools,1.0.0,file:{bundle},4,false\n")
            application = "evstation.tools.check"
        cmd = [
            str(installation / "jdk/bin/java"),
            "-Xms128m",
            "-Xmx2048m",
            "-Djava.awt.headless=true",
            f"-Djava.util.prefs.userRoot={base}/prefs",
            f"-Djava.util.prefs.systemRoot={base}/systemprefs",
            "-cp",
            str(launcher),
            "org.eclipse.core.launcher.Main",
            "-install",
            str(installation),
            "-configuration",
            str(configuration),
            "-application",
            application,
            "-data",
            str(base / "workspace"),
            *args,
        ]
        result = subprocess.call(cmd)
        log = base / "workspace/.metadata/.log"
        if log.exists():
            print(log.read_text(), file=sys.stderr)
        for diagnostic in configuration.glob("*.log"):
            print(diagnostic.read_text(), file=sys.stderr)
        return result


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
