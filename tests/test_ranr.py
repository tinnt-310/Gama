"""Scientific invariants and causal boundaries, independent of policy outcomes."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from scipy.sparse import csr_matrix
from ranr.legacy.python_reference.behavior import reaction_kernel
from ranr.legacy.python_reference.calibration import Calibration
from ranr.legacy.python_reference.charging import ChargingStation, dispatch, queue_trajectory
from ranr.legacy.python_reference.config import Config, METHODS
from ranr.legacy.python_reference.evaluation import penalty
from ranr.legacy.python_reference.geography import Geography, Station, load_geography, split_source_vertices
from ranr.legacy.python_reference.information import InformationStore
from ranr.legacy.python_reference.policies import parameter_count, trained_weights
from ranr.legacy.python_reference.prediction import QueuePredictor, batch_queue
from ranr.legacy.python_reference.records import (
    DemandOutcome,
    Exposure,
    Interval,
    Packet,
    Request,
    StationObservation,
    StationSnapshot,
)
from ranr.legacy.python_reference.simulation import Simulation, generate_requests, exogenous_hash


def fixture():
    stations = (Station("a", (60.0,), 0, 0.0), Station("b", (60.0,), 1, 0.0))
    geo = Geography(
        stations,
        np.array([0, 1]),
        np.array([[0.0, 1.0], [1.0, 0.0]]),
        np.array([[0.0, 1.0], [1.0, 0.0]]),
        np.array([[0.0, 0.0], [1000.0, 0.0]]),
        csr_matrix([[0.0, 1000.0], [1000.0, 0.0]]),
        {"passed": True},
    )
    priors = tuple(
        StationSnapshot(i, 0.0, s.powers, (Interval(0.0, 0.0),), (), "prior")
        for i, s in enumerate(stations)
    )
    cal = Calibration(
        (0.1, 0.9),
        (0.1, 0.9),
        tuple((p,) for p in priors),
        (0.0, 0.0),
        (0.0, 0.0),
        (9.0,),
    )
    return geo, cal


def observation(snapshot: StationSnapshot):
    return StationObservation(0, 0.0, (snapshot,), (), (0.0,), (0.0,), 0, (True,))


class ChargingTests(unittest.TestCase):
    def test_native_matches_numpy_on_random_heterogeneous_queues(self):
        import os

        random = np.random.default_rng(9)
        powers = np.array([11.0, 30.0, 60.0, 150.0])
        free = random.uniform(0, 20, (13, 4))
        at = np.sort(random.uniform(0, 40, (13, 25)), axis=1)
        at[0, 20:] = np.inf
        energy = random.uniform(2, 40, at.shape)
        maximum = random.choice([30.0, 60.0, 120.0, 250.0], size=at.shape)
        a = free.copy()
        native = batch_queue(a, powers, at, energy, maximum, 0.9)
        with patch.dict(os.environ, {"RANR_DISABLE_NATIVE": "1"}):
            b = free.copy()
            reference = batch_queue(b, powers, at, energy, maximum, 0.9)
        np.testing.assert_allclose(a, b, atol=1e-10)
        np.testing.assert_allclose(native[0], reference[0], atol=1e-10)
        np.testing.assert_allclose(native[1], reference[1], atol=1e-10)

    def test_port_allocation_conservation_and_duplicate_arrival(self):
        physical = ChargingStation(0, (11.0, 60.0), 0.9)
        for i in range(3):
            physical.enqueue(str(i), 0.0, 9.0, 120.0)
        started = physical.start_ready(0.0)
        self.assertEqual(started[0][0], 1)
        self.assertEqual(len(physical.queue), 1)
        self.assertEqual(len(started) + len(physical.queue), 3)
        with self.assertRaises(ValueError):
            physical.enqueue("0", 1.0, 9.0, 120.0)
        self.assertIsNotNone(physical.finish(1, started[0][1].generation, 10.0))
        self.assertIsNone(physical.finish(1, started[0][1].generation, 10.0))
        self.assertEqual(physical.start_ready(10.0)[0][1].request_id, "2")

    def test_scalar_and_batched_fifo_match_and_counterfactual(self):
        powers = np.array([11.0, 60.0])
        initial = np.array([0.0, 3.0])
        jobs = [(1.0, 9.0, 120.0), (1.0, 9.0, 120.0), (4.0, 9.0, 120.0)]
        starts, total = queue_trajectory(initial.copy(), powers, jobs, 0.9)
        t = np.tile(np.array([x[0] for x in jobs]), (3, 1))
        e = np.full((3, 3), 9.0)
        maximum = np.full((3, 3), 120.0)
        batched, waiting = batch_queue(
            np.tile(initial, (3, 1)), powers, t, e, maximum, 0.9
        )
        np.testing.assert_allclose(batched, np.tile(starts, (3, 1)))
        np.testing.assert_allclose(waiting, total)
        more = jobs + [(4.0, 20.0, 120.0)]
        before, _ = queue_trajectory(initial.copy(), powers, more, 0.9)
        np.testing.assert_allclose(before[:-1], starts)  # snapshot FIFO externality = 0

    def test_partial_delivery_and_deadline_once(self):
        physical = ChargingStation(0, (11.0,), 0.9)
        physical.enqueue("x", 0.0, 20.0, 60.0)
        physical.start_ready(0.0)
        self.assertAlmostEqual(physical.cancel("x", 5.0), 0.825)
        self.assertEqual(physical.cancel("x", 5.0), 0.0)


class InformationTests(unittest.TestCase):
    def test_stale_packet_falls_back_without_fabricating_empty_queue(self):
        _, cal = fixture()
        store = InformationStore(0, cal.priors, cal.request_rates, True)
        store.receive(Packet(1, 1, 0.0, cal.priors[1], (), 1.0), 0.0)
        obs = store.observe(cal.priors[0], 200.0, 180.0)
        self.assertEqual(obs.snapshots[1].source, "prior")
        self.assertFalse(obs.information_available[1])

    def test_duplicate_out_of_order_future_and_no_p2p(self):
        _, cal = fixture()
        snapshot = cal.priors[1]
        store = InformationStore(0, cal.priors, cal.request_rates, True)
        packet = Packet(1, 2, 3.0, snapshot, (), 1.0)
        self.assertTrue(store.receive(packet, 4.0))
        self.assertFalse(store.receive(packet, 5.0))
        self.assertFalse(store.receive(replace(packet, sequence=1), 5.0))
        with self.assertRaises(ValueError):
            store.receive(replace(packet, issued_at=8.0), 5.0)
        disabled = InformationStore(0, cal.priors, cal.request_rates, False)
        with self.assertRaises(ValueError):
            disabled.receive(packet, 4.0)

    def test_exposure_full_replacement_and_expiry(self):
        geo, cal = fixture()
        store = InformationStore(0, cal.priors, cal.request_rates, True)
        req = Request("secret-id", 0.0, 0, 9.0, 120.0, 50.0, (1.0, 2.0), (0.5, 1.0))
        store.record_exposure(req, 1, req.travel, 10.0)
        store.record_exposure(replace(req, request_id="different"), 1, req.travel, 10.0)
        self.assertEqual(len(store.local), 1)
        self.assertEqual(next(iter(store.local.values())).count, 2)
        self.assertNotIn("secret-id", repr(store.packet(cal.priors[0], 0.0)))
        self.assertEqual(store.packet(cal.priors[0], 11.0).exposure, ())

    def test_unreceived_peer_is_prior_and_causal(self):
        _, cal = fixture()
        store = InformationStore(0, cal.priors, cal.request_rates, True)
        before = store.observe(cal.priors[0], 2.0)
        packet = Packet(
            1,
            1,
            1.0,
            replace(cal.priors[1], release=(Interval(10.0, 10.0),), source="peer"),
            (),
            1.0,
        )
        # Constructing a future delivery cannot affect the observation.
        self.assertEqual(before, store.observe(cal.priors[0], 2.0))
        store.receive(packet, 3.0)
        self.assertNotEqual(
            before.snapshots[1], store.observe(cal.priors[0], 3.0).snapshots[1]
        )


class PolicyTests(unittest.TestCase):
    def test_poisson_split_preserves_destination_moments_and_independence(self):
        _, cal = fixture()
        cal = replace(cal, travel_priors=(((1.0, 1.0),), ((1.0, 1.0),)))
        predictor = QueuePredictor(Config(scenarios=32), cal)
        obs = StationObservation(
            0, 0.0, cal.priors, (), (0.0, 0.0), (0.0, 0.0), 0, (True, True)
        )
        req = Request("split-test", 0.0, 0, 9.0, 120.0, 50.0, (1.0, 1.0), (0.5, 0.5))
        times = [[], []]
        energy = [[], []]
        maximum = [[], []]
        predictor._append_requests(
            obs, req, 20000, 0, 10.0, 0.0, 2.0, "test", True, times, energy, maximum
        )
        counts = [np.isfinite(np.concatenate(x, axis=1)).sum(axis=1) for x in times]
        for x in counts:
            self.assertAlmostEqual(float(x.mean()), 9.5, delta=0.15)
            self.assertAlmostEqual(float(x.var()), 9.5, delta=0.3)
        self.assertAlmostEqual(float(np.cov(counts)[0, 1]), 0.0, delta=0.3)

    def test_state_features_are_not_specific_to_current_request_eta(self):
        from ranr.legacy.python_reference.policies import RecommendationPolicy

        _, cal = fixture()
        config = Config(method="No-Prediction", scenarios=8)
        snap = cal.priors
        obs = StationObservation(
            0, 0.0, snap, (), (0.0, 0.0), (0.0, 0.0), 1, (True, True)
        )
        req = Request("same", 0.0, 0, 9.0, 120.0, 50.0, (1.0, 2.0), (0.5, 1.0))
        policy = RecommendationPolicy(
            config, QueuePredictor(config, cal), np.ones(parameter_count(config.method))
        )
        a = policy.recommend(obs, req, np.array([True, True]))
        b = policy.recommend(
            obs, replace(req, travel=(10.0, 20.0)), np.array([True, True])
        )
        self.assertEqual(a.state_features, b.state_features)
        self.assertEqual(a.weights, b.weights)

    def test_algorithm_settings_do_not_contain_hidden_behavior_or_load(self):
        config = Config(compliance=0.2, load=0.9)
        settings = config.policy_settings
        self.assertFalse(hasattr(settings, "compliance"))
        self.assertFalse(hasattr(settings, "load"))
        self.assertFalse(hasattr(settings, "case"))
        self.assertEqual(settings.assumed_compliance, 0.6)

    def test_each_exposure_member_has_at_most_one_scenario_destination(self):
        geo, cal = fixture()
        req = Request("probe", 0.0, 0, 9.0, 120.0, 50.0, (1.0, 1.0), (0.5, 0.5))
        exposure = Exposure(0, 0, "class", 0, 1, 0.0, 180.0, 10, (1.0, 1.0), 9.0, 120.0)
        obs = StationObservation(
            0, 0.0, cal.priors, (exposure,), (0.0, 0.0), (0.0, 0.0), 0, (True, True)
        )
        t, _, _ = QueuePredictor(Config(scenarios=128), cal)._future(obs, req, 128)
        counts = sum(np.isfinite(x).sum(axis=1) for x in t)
        self.assertTrue((counts <= 10).all())

    def test_probability_weights_and_fixed_equivalence(self):
        state = np.array([1.0, 2.0, 0.3, 0.7, 1.0])
        beta = np.array([1.0, 2.0, -1.0, 0.4])
        theta = np.zeros((4, 5))
        theta[:, 0] = beta
        np.testing.assert_allclose(
            trained_weights("RANR-AW", theta.ravel(), state),
            trained_weights("Fixed-Weights", beta, state),
        )
        for m in METHODS:
            weights = trained_weights(m, np.zeros(parameter_count(m)), state)
            self.assertAlmostEqual(weights.sum(), 1.0)
            self.assertTrue((weights > 0).all())
        kernel = reaction_kernel((1.0, 2.0), 0.6, 0.1)
        np.testing.assert_allclose(kernel.sum(axis=1), 1.0)

    def test_uncertain_snapshot_has_distinct_p95_and_no_externality(self):
        geo, cal = fixture()
        cal = replace(
            cal,
            prior_snapshots=(cal.prior_snapshots[0],),
            request_rates=(0.0,),
            background_rates=(0.0,),
        )
        config = Config(method="No-Prediction", scenarios=128)
        snap = StationSnapshot(0, 0.0, (60.0,), (Interval(1.0, 11.0),), (), "peer")
        req = Request("x", 0.0, 0, 9.0, 120.0, 50.0, (100.0,), (50.0,))
        predictor = QueuePredictor(config, cal)
        with patch.object(
            predictor,
            "_future",
            side_effect=AssertionError("Forbidden future prediction"),
        ):
            estimate = predictor.estimate(observation(snap), req)[0]
        self.assertGreater(estimate.p95, estimate.mean)
        self.assertIsNone(estimate.externality)
        exact = replace(snap, release=(Interval(5.0, 5.0),), source="local")
        estimate = predictor.estimate(observation(exact), req)[0]
        self.assertEqual(estimate.mean, 5.0)
        self.assertEqual(estimate.p95, 5.0)

    def test_own_wait_not_in_externality(self):
        _, cal = fixture()
        cal = replace(
            cal,
            prior_snapshots=(cal.prior_snapshots[0],),
            request_rates=(0.0,),
            background_rates=(0.0,),
        )
        snap = StationSnapshot(0, 0.0, (60.0,), (Interval(10.0, 10.0),), (), "local")
        req = Request("x", 0.0, 0, 9.0, 120.0, 50.0, (0.0,), (0.0,))
        estimate = QueuePredictor(Config(scenarios=4), cal).estimate(
            observation(snap), req
        )[0]
        self.assertEqual(estimate.mean, 10.0)
        self.assertEqual(estimate.externality, 0.0)


class EndToEndTests(unittest.TestCase):
    def test_checkpoint_resume_with_changed_worker_count(self):
        import ranr.legacy.python_reference.training as training
        from ranr.paths import OUTPUTS

        c = Config(scenarios=2, burst_requests=0, trace=False)
        settings = training.TrainingConfig(
            optimizer_seeds=(49001,),
            population=4,
            validation_every=4,
            min_evaluations=8,
            max_evaluations=8,
            workers=1,
            warmup_minutes=0,
            measure_minutes=5,
            profile="smoke",
        )
        with tempfile.TemporaryDirectory(dir=OUTPUTS, prefix="resume-test-") as tmp:
            root = Path(tmp)
            uninterrupted = training.train(
                c, settings, root / "uninterrupted", ("Fixed-Weights",)
            )
            original = training._atomic_pickle

            def interrupt(path, value):
                original(path, value)
                raise KeyboardInterrupt("intentional checkpoint interruption")

            with patch.object(training, "_atomic_pickle", side_effect=interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    training.train(c, settings, root / "resumed", ("Fixed-Weights",))
            resumed = training.train(
                c,
                replace(settings, workers=2),
                root / "resumed",
                ("Fixed-Weights",),
                True,
            )
            self.assertEqual(
                uninterrupted["Fixed-Weights"]["parameters"],
                resumed["Fixed-Weights"]["parameters"],
            )
            self.assertEqual(
                uninterrupted["Fixed-Weights"]["validation"],
                resumed["Fixed-Weights"]["validation"],
            )

    def test_independent_choices_and_matched_exogenous_inputs(self):
        geo, cal = fixture()
        runs = []
        c = Config(
            warmup_minutes=0,
            measure_minutes=120,
            scenarios=2,
            compliance=0.0,
            trace=True,
        )
        hashes = []
        for m in METHODS:
            config = replace(c, method=m)
            simulation = Simulation(geo, cal, config)
            result = simulation.run()
            hashes.append(result["exogenous_hash"])
            runs.append(
                [
                    (
                        x.request_id,
                        x.station,
                        x.status,
                        x.arrival_at,
                        x.start_at,
                        x.delivered_kwh,
                    )
                    for x in simulation.outcomes.values()
                ]
            )
            if m == "No-P2P":
                self.assertEqual(result["messages_sent"], 0)
        self.assertEqual(len(set(hashes)), 1)
        for run in runs[1:]:
            self.assertEqual(run, runs[0])

    def test_fixed_seed_reproduces_scientific_metrics(self):
        geo, cal = fixture()
        config = Config(warmup_minutes=0, measure_minutes=30, scenarios=4)
        a = Simulation(geo, cal, config).run()
        b = Simulation(geo, cal, config).run()
        keys = (
            "runtime_seconds",
            "prediction_seconds",
            "recommendation_mean_ms",
            "recommendation_p95_ms",
            "events_per_second",
        )
        self.assertEqual(
            {k: v for k, v in a.items() if k not in keys},
            {k: v for k, v in b.items() if k not in keys},
        )

    def test_all_unserved_demands_have_finite_penalty(self):
        outcome = DemandOutcome(
            "x", 0.0, 20.0, 360.0, True, end_at=0.0, status="deferred"
        )
        self.assertEqual(penalty(outcome, 360.0), (720.0, 720.0, 720.0))
        partial = replace(outcome, delivered_kwh=10.0, status="unserved")
        self.assertEqual(penalty(partial, 360.0), (540.0, 540.0, 540.0))
        for status in ("failed", "stranded", "unserved"):
            self.assertEqual(
                penalty(replace(outcome, status=status), 360.0), penalty(outcome, 360.0)
            )


class GeographyTests(unittest.TestCase):
    def test_crossing_without_source_vertex_remains_disconnected(self):
        lines = [
            [(10, 10), (15, 10), (20, 10)],
            [(15, 10), (15, 15)],
            [(17, 8), (17, 12)],
        ]
        self.assertEqual(len(split_source_vertices(lines)), 4)

    def test_gis_connectivity_capacity_and_independent_routes(self):
        geo = load_geography()
        self.assertTrue(geo.validation["passed"])
        self.assertEqual(len(geo.stations), 11)
        self.assertEqual(sum(len(s.powers) for s in geo.stations), 125)
        self.assertEqual(sum(sum(s.powers) for s in geo.stations), 7195)
        self.assertTrue(np.isfinite(geo.distance_km).all())
        self.assertTrue(all(s.access_distance_m <= 300 for s in geo.stations))


if __name__ == "__main__":
    unittest.main()
