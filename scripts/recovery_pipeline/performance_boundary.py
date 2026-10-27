"""Measure the same strict result boundary used by smoke/official fitness.

Timing records are outside sealed native outputs. Cached native results may
reuse their original measured duration; cache lookup speed is never throughput.
"""
from pathlib import Path
import json
import time

from ranr.paths import write_json, digest
from ranr.gama.evidence import reference, verify_reference
from strict_fitness_boundary import StrictNativeRunner


class MeasuredRunner:
    def __init__(self, native, root, source):
        self.root = Path(root).resolve()
        self.source = source
        self.strict = StrictNativeRunner(native, self.root, source)

    def __call__(self, config, parameters, target, **kwargs):
        target = Path(target).resolve()
        relative = target.relative_to(self.root)
        timing = self.root.parent / 'performance_timings' / relative / 'timing.json'
        existed = (target / 'manifest.json').exists()
        previous = json.loads(timing.read_text()) if timing.exists() else None
        if existed and previous is None:
            raise ValueError('Sealed benchmark result lacks original strict timing; review before reuse')
        started = time.perf_counter()
        result = self.strict(config, parameters, target, **kwargs)
        elapsed = time.perf_counter() - started
        review = self.root.parent / 'f04_results' / relative / 'review.json'
        identity = dict(source=self.source, manifest=reference(target / 'manifest.json'),
                        boundary=reference(Path(__file__).with_name('strict_fitness_boundary.py')),
                        reviewer=reference(review))
        if previous is not None:
            if previous['identity'] != identity or previous.get('fresh_native_timing') is not True:
                raise ValueError('Cached performance timing identity changed')
            for item in (previous['identity']['manifest'], previous['identity']['reviewer']):
                verify_reference(item)
            elapsed = previous['strict_total_wall_seconds']
        else:
            write_json(timing, dict(kind='strict_native_performance_timing', identity=identity,
                fresh_native_timing=True, strict_total_wall_seconds=elapsed,
                native_reported_wall_seconds=result['wall_seconds'],
                additional_boundary_seconds=max(0., elapsed-result['wall_seconds'])))
        if elapsed <= 0:
            raise ValueError('Nonpositive strict benchmark timing')
        # Benchmark-only returned copy; the native fitness/result is unchanged.
        return {**result, 'wall_seconds': elapsed}
