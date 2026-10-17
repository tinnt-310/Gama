"""Orchestration contracts; GAMA fixtures validate actual algorithm/physics."""

from dataclasses import replace
from pathlib import Path
import ast
import json
import tempfile
import unittest
from ranr.gama.headless import (
    METHODS,
    RunConfig,
    parameter_record,
    checked_result,
    load_model,
)
from ranr.gama.pipeline import benchmark_budget
from ranr.paths import ROOT, write_json


class GamaContracts(unittest.TestCase):
    def test_five_criteria_parameter_dimensions_and_origin(self):
        for method in METHODS:
            n = 4 if method == "Fixed-Weights" else 20
            record = parameter_record(method, [0.0] * n)
            self.assertEqual(record["backend"], "GAMA")
            self.assertEqual(len(record["features"]), 5)
        with self.assertRaises(ValueError):
            parameter_record("No-Prediction", [0.0] * 15)
        with self.assertRaises(ValueError):
            parameter_record("RANR-AW", [float("nan")] * 20)

    def test_official_runs_require_train_calibration(self):
        with self.assertRaises(ValueError):
            RunConfig()
        self.assertTrue(RunConfig(development=True).development)
        with self.assertRaisesRegex(ValueError, "Environment changed"):
            RunConfig(development=True, environment_version="retired")
        with self.assertRaises(ValueError):
            RunConfig(development=True, step_seconds=0)
        with self.assertRaises(ValueError):
            RunConfig(development=True, warmup_minutes=float("nan"))
        with self.assertRaises(ValueError):
            RunConfig(development=True, samples=4.5)
        with self.assertRaises(ValueError):
            RunConfig(development=True, background_cars=-1)
        with self.assertRaises(ValueError):
            RunConfig(development=True, background_cars=2.5)

    def test_wrong_method_models_are_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parameters.json"
            write_json(path, parameter_record("RANR-AW", [0.0] * 20))
            config = RunConfig(development=True)
            self.assertEqual(len(load_model(path, "RANR-AW", config)), 20)
            with self.assertRaises(ValueError):
                load_model(path, "No-Prediction", config)

    def test_single_seed_smoke_cannot_produce_significance(self):
        from ranr.gama.pipeline import report

        rows = [
            {
                "case": "normal",
                "seed": 91001,
                "method": method,
                **{
                    metric: float(i + 1)
                    for metric in [
                        "operational_objective",
                        "mean_travel_min",
                        "mean_wait_min",
                        "p95_wait_min",
                        "peak_queue",
                        "utilization",
                        "served_count",
                        "delivered_kwh",
                        "wall_seconds",
                        "communication_bytes",
                    ]
                },
            }
            for i, method in enumerate(METHODS)
        ]
        with tempfile.TemporaryDirectory() as directory:
            report(rows, Path(directory), "smoke")
            comparisons = json.loads((Path(directory) / "comparisons.json").read_text())
            self.assertTrue(
                all(row["p"] is None and row["p_holm"] is None for row in comparisons)
            )
            with self.assertRaises(ValueError):
                report(rows + [rows[0]], Path(directory), "smoke")

    def test_empty_conditional_metrics_remain_null_in_reports(self):
        from ranr.gama.pipeline import report
        rows=[]
        for method in METHODS:
            rows.append(dict(case='normal',seed=91001,method=method,operational_objective=0.,mean_travel_min=0.,mean_wait_min=None,p95_wait_min=None,peak_queue=0,utilization=0.,served_count=0,delivered_kwh=0.,wall_seconds=1.,communication_bytes=0))
        with tempfile.TemporaryDirectory() as directory:
            report(rows,Path(directory),'smoke')
            summary=json.loads((Path(directory)/'summary.json').read_text())
            conditional=[r for r in summary if r['metric']=='p95_wait_min']
            self.assertTrue(all(r['n']==0 and r['mean'] is None for r in conditional))

    def test_budget_accounts_for_long_validation_and_common_counts(self):
        short = {m: 100 for m in METHODS}
        long = {m: 500 for m in METHODS}
        result = benchmark_budget(short, long, 4, 72)
        self.assertTrue(result["passed"])
        self.assertLessEqual(result["budget"]["estimated_seconds"], 72 * 3600 * 0.85)
        maximum = result["budget"]["max_evaluations"]
        minimum = min(1024, maximum)
        self.assertEqual(result["budget"]["min_evaluations"], minimum)
        self.assertEqual(result["budget"]["validation_every"], min(256, minimum // 4))
        self.assertFalse(
            benchmark_budget({m: 100000 for m in METHODS}, long, 1, 72)["passed"]
        )

    def test_stale_results_and_tampered_artifacts_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            write_json(folder / "metrics.json", {"operational_objective": 1.0})
            write_json(
                folder / "manifest.json",
                {"status": "running", "config": {}, "artifact_hashes": {}},
            )
            with self.assertRaises(ValueError):
                checked_result(folder, {"config": {}})
            write_json(
                folder / "manifest.json",
                {
                    "status": "complete",
                    "config": {},
                    "artifact_hashes": {"metrics.json": "wrong"},
                },
            )
            with self.assertRaises(ValueError):
                checked_result(folder, {"config": {}})

    def test_official_package_has_no_python_simulator_import(self):
        forbidden = {
            "simulation",
            "prediction",
            "charging",
            "behavior",
            "policies",
            "native",
            "python_reference",
        }
        for path in (ROOT / "src/ranr/gama").glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse(
                        forbidden.intersection((node.module or "").split(".")),
                        path.name,
                    )
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(
                            forbidden.intersection(alias.name.split(".")), path.name
                        )

    def test_gaml_policy_does_not_read_private_environment(self):
        for name in ["Policy.gaml", "Prediction.gaml"]:
            text = (ROOT / "models/ranr" / name).read_text()
            for secret in [
                "ranr_true_compliance",
                "ranr_true_defer",
                "ranr_demand_plan",
                "physical_sessions",
                "charging_station(",
            ]:
                self.assertNotIn(secret, text, name)


if __name__ == "__main__":
    unittest.main()


class OptimizerResumeContract(unittest.TestCase):
    def test_resume_pending_long_validation_and_worker_invariance(self):
        from unittest.mock import patch
        from ranr.gama.training import train
        from ranr.gama.headless import provenance
        import numpy as np

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            budget = base / "budget.json"
            write_json(
                budget,
                {
                    "hours": 1,
                    "workers": 1,
                    "optimizer_seeds": [49001],
                    "budget": {
                        "max_evaluations": 16,
                        "min_evaluations": 16,
                        "validation_every": 16,
                    },
                },
            )
            config = RunConfig(
                development=True, warmup_minutes=0, measure_minutes=3, background_cars=0
            )

            def toy_fitness(config, parameters, folder, **kwargs):
                # A unit-test optimization oracle, not a charging simulator or research result.
                from gama_ledger_fixture import fitness_fixture
                return fitness_fixture(case=config.case,seed=config.seed,operational_objective=float(np.square(np.asarray(parameters)-0.25).mean()),cpu_seconds=0,backend="UNIT_TEST")

            interrupted = {"raised": False}

            def interrupt_validation(config, parameters, folder, **kwargs):
                if "validation" in folder.parts and not interrupted["raised"]:
                    interrupted["raised"] = True
                    raise KeyboardInterrupt(
                        "Unit test: interrupt before long validation completes"
                    )
                return toy_fitness(config, parameters, folder, **kwargs)

            with patch("ranr.gama.training.run", side_effect=interrupt_validation):
                with self.assertRaises(KeyboardInterrupt):
                    train(config, base / "resumed", budget, smoke=True)
            with patch("ranr.gama.training.run", side_effect=toy_fitness):
                result = train(
                    config,
                    base / "resumed",
                    budget,
                    smoke=True,
                    resume=True,
                    workers_override=2,
                )
                reference = train(config, base / "reference", budget, smoke=True)
            self.assertEqual(result["status"], "complete")
            for method in METHODS:
                a = json.loads(
                    (base / "resumed" / method / "parameters.json").read_text()
                )
                b = json.loads(
                    (base / "reference" / method / "parameters.json").read_text()
                )
                self.assertEqual(a["parameters"], b["parameters"])
                self.assertEqual(a["validation_fitness_vector"], b["validation_fitness_vector"])
                self.assertFalse(a["training_completed"])

    def test_publication_keeps_validation_incumbent_across_generations(self):
        """A later generation's low operational score cannot replace safer validation."""
        from unittest.mock import patch
        from ranr.gama.training import train
        from gama_ledger_fixture import fitness_fixture
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            budget = base / 'budget.json'
            write_json(budget, {'hours':1, 'workers':1, 'optimizer_seeds':[49001],
                               'budget':{'max_evaluations':32,'min_evaluations':32,'validation_every':16}})
            config = RunConfig(development=True)
            first_validation = {}
            def oracle(config, parameters, folder, **kwargs):
                if 'validation' in folder.parts:
                    if folder.parent.name == '16':
                        first_validation[config.method] = list(parameters)
                        return fitness_fixture(case=config.case,seed=config.seed,operational_objective=10.)
                    return fitness_fixture(case=config.case,seed=config.seed,not_on_time_count=1,operational_objective=0.)
                # Generation ranks may favor a different candidate on every generation.
                return fitness_fixture(case=config.case,seed=config.seed,operational_objective=sum(x*x for x in parameters))
            with patch('ranr.gama.training.run', side_effect=oracle):
                self.assertEqual(train(config,base/'training',budget,smoke=True)['status'],'complete')
            for method in METHODS:
                record=json.loads((base/'training'/method/'parameters.json').read_text())
                self.assertEqual(record['parameters'],first_validation[method])
                self.assertEqual(record['validation_fitness_vector'],[0.,0.,0.,0.,10.])
                history=json.loads((base/'training'/method/'49001/history.json').read_text())
                self.assertEqual(history[-1]['validation_fitness_vector'],[0.,0.,.1,0.,0.])

    def test_invalid_generation_saves_diagnostic_without_calling_tell(self):
        from unittest.mock import patch
        from ranr.gama.training import train
        from gama_ledger_fixture import fitness_fixture
        import pickle
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);budget=base/'budget.json'
            write_json(budget,{'hours':1,'workers':1,'optimizer_seeds':[49001],
                               'budget':{'max_evaluations':16,'min_evaluations':16,'validation_every':16}})
            def invalid(config, parameters, folder, **kwargs):
                return fitness_fixture(case=config.case,seed=config.seed,fitness_valid=False)
            with patch('ranr.gama.training.run',side_effect=invalid), patch('ranr.gama.training.cma.CMAEvolutionStrategy.tell',autospec=True) as tell:
                with self.assertRaisesRegex(ValueError,'Invalid fitness'):
                    train(RunConfig(development=True),base/'training',budget,smoke=True)
                tell.assert_not_called()
            state=pickle.loads((base/'training/checkpoint.pkl').read_bytes())
            self.assertEqual(state['status'],'invalid_evaluation')
            self.assertIsNotNone(state['slots'][0]['pending'])
            self.assertTrue((base/'training/diagnostic.json').exists())
