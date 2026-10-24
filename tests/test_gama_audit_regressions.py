"""Adversarial contracts and real OS signal tests; no synthetic research results."""
import copy
import json
import os
from pathlib import Path
import pickle
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from gama_ledger_fixture import ledger_fixture
from ranr.gama.contracts import validate_charging_ledger
from ranr.gama.pipeline import arrival_context
from ranr.gama import release
from ranr.paths import ROOT, write_json


class AuditRegressions(unittest.TestCase):
    def test_boolean_training_readiness_cannot_replace_linked_gate_evidence(self):
        from ranr.gama.evidence import verify_training_acceptance
        from ranr.gama.headless import provenance
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'acceptance.json'
            write_json(path,dict(passed=True,source=provenance(),kind='pre_training_acceptance',training_ready=True))
            with self.assertRaisesRegex(ValueError,'gate evidence'):
                verify_training_acceptance(path)

    def test_station_energy_survives_json_round_trip_and_alternative_choice(self):
        context = dict(issuer=0, chosen=2, travel=list(range(11)), energy=12.,
                       energy_by_station=[10.+i for i in range(11)], max_kw=60.)
        prior = json.loads(json.dumps(arrival_context(context)))
        self.assertEqual(prior['energy_by_station'], context['energy_by_station'])
        self.assertEqual(prior['energy_by_station'][8], 18.)
        self.assertNotEqual(prior['energy_by_station'][8], prior['energy'])
        for bad in ([], [1.]*10, [1.]*10+[float('nan')], [1.]*10+[-1.], [1.]*10+[True]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                arrival_context(dict(context, energy_by_station=bad))
        with self.assertRaises(ValueError):
            arrival_context(dict(context, max_kw=float('inf')))

    def test_immutable_and_cross_level_mutations_are_rejected(self):
        for field in ('target_soc', 'soc_at_need', 'threshold'):
            rows = ledger_fixture()
            rows[3][0][field] += 1.
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Immutable'):
                validate_charging_ledger(*rows)
        for field, value in (('issued_min', 6.), ('delivered_kwh', 9.), ('finished_min', 23.)):
            rows = ledger_fixture()
            rows[2][0][field] = value
            if field == 'delivered_kwh':
                rows[2][0]['status'] = 'unresolved'
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_charging_ledger(*rows)

    def test_fresh_registration_does_not_access_legacy_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)/'release'
            with patch.object(release, 'OUTPUT', Path(temporary)/'output'), patch.object(release, 'checked_result') as legacy:
                record = release.initialize(folder)
                self.assertEqual(record['collection_mode'], 'fresh')
                self.assertEqual(record['selected'], [])
                legacy.assert_not_called()
                before = (folder/'registration.json').read_bytes()
                with self.assertRaises(FileExistsError):
                    release.initialize(folder)
                self.assertEqual(before, (folder/'registration.json').read_bytes())

    def test_historical_import_checks_hashes_and_seed_grid(self):
        from gama_ledger_fixture import fitness_fixture
        from ranr.paths import digest
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = []
            for seed in release.SEEDS:
                folder = root/str(seed)
                write_json(folder/'metrics.json', fitness_fixture())
                write_json(folder/'manifest.json', dict(status='complete', source={'unit':True},
                    config=dict(calibrating=True, seed=seed), artifact_hashes={'metrics.json':digest(folder/'metrics.json')}))
                runs.append(folder)
            with patch.object(release, 'OUTPUT', root/'output'):
                write_json(runs[0]/'metrics.json', {'corrupted':True})
                with self.assertRaisesRegex(ValueError, 'artifact changed'):
                    release.initialize(root/'release', historical_runs=runs)
                self.assertFalse((root/'release/registration.json').exists())
                with self.assertRaisesRegex(ValueError, 'distinct'):
                    release.initialize(root/'release', historical_runs=[runs[0]]*3)


CHILD = r'''
from pathlib import Path
import sys,time
from unittest.mock import patch
from ranr.gama.headless import RunConfig
from ranr.gama.training import train
from ranr.gama import training_time
from ranr.gama.monitoring import check_training_cancelled
training_time.INTERVAL=.1
folder=Path(sys.argv[1])
def running(*args,**kwargs):
    (folder/'ready').write_text('ready')
    while True:
        check_training_cancelled()
        time.sleep(.02)
with patch('ranr.gama.training.run',side_effect=running), patch('ranr.gama.training.cma.CMAEvolutionStrategy.tell',side_effect=AssertionError('incomplete tell')):
    train(RunConfig(development=True),folder/'training',folder/'budget.json',smoke=True,resume=(folder/'training/checkpoint.pkl').exists())
'''


class TrainingSignals(unittest.TestCase):
    def launch(self, root):
        environment = dict(os.environ, PYTHONPATH=str(ROOT/'src'), PYTHONDONTWRITEBYTECODE='1')
        process = subprocess.Popen([sys.executable, '-c', CHILD, str(root)], env=environment,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        deadline = time.monotonic()+15.
        while not (root/'ready').exists():
            if process.poll() is not None:
                self.fail(process.stderr.read().decode())
            if time.monotonic() > deadline:
                self.fail('training child did not reach pending evaluation')
            time.sleep(.02)
        return process

    def test_sigterm_and_sigkill_preserve_pending_rng_and_elapsed_on_resume(self):
        for termination in (signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signal=termination), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_json(root/'budget.json', dict(hours=1,workers=1,optimizer_seeds=[49001],
                    budget=dict(max_evaluations=16,min_evaluations=16,validation_every=16)))
                process = self.launch(root)
                initial = pickle.loads((root/'training/checkpoint.pkl').read_bytes())
                pending = pickle.dumps(initial['slots'][0]['pending'])
                rng = pickle.dumps(initial['slots'][0]['rng'])
                time.sleep(.15)
                process.send_signal(termination)
                process.communicate(timeout=15)
                previous = json.loads((root/'training/training_time.json').read_text())
                (root/'ready').unlink()
                resumed = self.launch(root)
                resumed.send_signal(signal.SIGTERM)
                resumed.communicate(timeout=15)
                state = pickle.loads((root/'training/checkpoint.pkl').read_bytes())
                self.assertEqual(state['status'], 'interrupted')
                self.assertGreaterEqual(state['active_seconds'], previous['consumed_seconds'])
                self.assertGreater(state['active_seconds'], .1)
                self.assertEqual(state['slots'][0]['evaluations'], 0)
                self.assertEqual(state['slots'][0]['generation'], 0)
                self.assertEqual(pickle.dumps(state['slots'][0]['pending']), pending)
                self.assertEqual(pickle.dumps(state['slots'][0]['rng']), rng)
                self.assertFalse(json.loads((root/'training/training_time.json').read_text())['active'])
