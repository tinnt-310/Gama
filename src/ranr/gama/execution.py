"""Verify the Python code actually imported, independently of RANR_WORKSPACE."""
from pathlib import Path
import sys
from ranr.paths import ROOT, digest


def assert_checkout_modules():
    expected = (ROOT / 'src').resolve()
    loaded = {}
    for name, module in tuple(sys.modules.items()):
        if name != 'ranr' and not name.startswith('ranr.'):
            continue
        origin = getattr(module, '__file__', None)
        if not origin:
            continue
        path = Path(origin).resolve()
        if expected not in path.parents or path.suffix != '.py':
            raise ValueError('Python execution checkout mismatch: '+name+' loaded from '+str(path))
        loaded[name] = dict(path=str(path), sha256=digest(path))
    if not loaded:
        raise ValueError('No actual RANR Python execution modules identified')
    return loaded


def verify_recorded_python(loaded, source):
    if 'ranr.gama.validation' not in loaded:
        raise ValueError('Native fixture lacks actual Python execution identity')
    for origin in loaded.values():
        actual=Path(origin['path']).resolve()
        try:
            relative=str(actual.relative_to(ROOT))
        except ValueError:
            raise ValueError('Native fixture used Python outside its execution checkout')
        if origin['sha256'] != source['orchestrator'].get(relative) or digest(actual) != origin['sha256']:
            raise ValueError('Native Python module identity changed: '+relative)
