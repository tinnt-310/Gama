"""Shared smoke/official rejecting boundary before canonical fitness aggregation.

The isolated repair checkout already contains strict F04 contracts. This boundary
also revalidates sealed reuse and writes per-result evidence outside sealed runs.
It never changes a result, parameter, fitness vector or simulation configuration.
"""
from dataclasses import asdict
from pathlib import Path
import json
import time

from ranr.paths import digest, write_json
from ranr.gama.headless import provenance, checked_result, parameter_record
from ranr.gama.contracts import validate_charging_files, validate_physical_records
from ranr.gama.monitoring import check_training_cancelled


class StrictNativeRunner:
    def __init__(self, native_run, output, expected_source):
        self.native_run = native_run
        self.output = Path(output).resolve()
        self.source = expected_source
        self.code_hash = digest(Path(__file__))

    def identity(self):
        if provenance() != self.source or digest(Path(__file__)) != self.code_hash:
            raise ValueError('Strict fitness boundary source/code changed')
        check_training_cancelled()

    def __call__(self, config, parameters, folder, **kwargs):
        started = time.monotonic()
        self.identity()
        folder = Path(folder).resolve()
        relative = folder.relative_to(self.output)
        if not relative.parts:
            raise ValueError('Expected a native result beneath optimizer ownership')
        native_kwargs = dict(kwargs)
        if kwargs.get('wall_limit') is not None:
            native_kwargs['wall_limit'] = kwargs['wall_limit']-(time.monotonic()-started)
            if native_kwargs['wall_limit'] <= 0:
                raise TimeoutError('Training allowance expired before native launch')
        result = self.native_run(config, parameters, folder, **native_kwargs)
        self.identity()
        expected_config = asdict(config)
        if config.calibration:
            expected_config['calibration'] = str(Path(config.calibration).resolve())
        expected = dict(source=self.source, config=expected_config,
                        parameters=parameter_record(config.method,parameters))
        # Recheck every sealed artifact even when a matching F04 report exists.
        sealed_result = checked_result(folder, expected)
        if result != sealed_result:
            raise ValueError('Native result differs from its sealed metrics')
        manifest = folder / 'manifest.json'
        identity = dict(path=str(folder), manifest_sha256=digest(manifest),
            execution_source=json.loads(manifest.read_text()).get('execution_source',self.source), validator_source=self.source,
            boundary_sha256=self.code_hash)
        report_path = self.output.parent / 'f04_results' / relative / 'review.json'
        cached = None
        if report_path.exists():
            cached = json.loads(report_path.read_text())
            if (cached.get('kind') != 'strict_native_fitness_boundary'
                    or cached.get('passed') is not True
                    or cached.get('before_fitness') is not True
                    or cached.get('identity') != identity):
                raise ValueError('Cached strict F04 proof does not match this native result')
        else:
            validate_charging_files(folder)
            physical = validate_physical_records(folder, expected_config)
            self.identity()
            if digest(manifest) != identity['manifest_sha256']:
                raise ValueError('Native manifest changed during strict F04 validation')
            # Re-read file hashes after validation, before accepting fitness.
            checked_result(folder, expected)
            write_json(report_path, dict(kind='strict_native_fitness_boundary',
                passed=True, identity=identity, physical_validation=physical,
                before_fitness=True, validation_wall_seconds=time.monotonic()-started))
        self.identity()
        limit = kwargs.get('wall_limit')
        if limit is not None and time.monotonic()-started >= limit:
            raise TimeoutError('Training allowance expired before strict F04 fitness return')
        return result
