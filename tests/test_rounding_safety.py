import unittest
import numpy as np

from verification.model import Snapshot, entropy_prox, project_rows
from verification.recovery import round_gkps


class RoundingSafetyTests(unittest.TestCase):
    def test_raw_entropy_prox_and_feasible_assignment_are_distinct(self):
        self.assertGreater(entropy_prox(np.array([3.]), .2, .25)[0], 1.)
        s = Snapshot(1, 2, 1, [(0, 0, 0, 1.), (0, 1, 0, 1.)], [1.], [[0.], [0.]], [[0.], [0.]])
        feasible = project_rows(s, np.array([1.4, .2]))
        self.assertTrue(np.all((feasible >= 0) & (feasible <= 1)))
        self.assertAlmostEqual(feasible.sum(), 1.)
        self.assertEqual(round_gkps(s, feasible).sum(), 1.)

    def test_dense_branching_and_disconnected_graphs_preserve_degrees(self):
        rng = np.random.default_rng(731)
        for case in range(100):
            n, m = 2+case%11, 2+case%7
            edges, x = [], []
            for ev in range(n):
                candidates = sorted(rng.choice(m, size=int(rng.integers(1, m+1)), replace=False))
                weights = rng.uniform(.01, 1., len(candidates)); weights /= weights.sum()
                edges.extend((ev, int(station), 0, 1.) for station in candidates)
                x.extend(weights)
            s = Snapshot(n, m, 1, edges, np.ones(n), np.zeros((m, 1)), np.zeros((m, 1)))
            x = np.asarray(x); z = round_gkps(s, x, case)
            for ev in range(n):
                self.assertEqual(sum(z[i] for i, e in enumerate(edges) if e[0] == ev), 1.)
            for station in range(m):
                original = sum(x[i] for i, e in enumerate(edges) if e[1] == station)
                rounded = sum(z[i] for i, e in enumerate(edges) if e[1] == station)
                self.assertGreaterEqual(rounded, np.floor(original+1e-8))
                self.assertLessEqual(rounded, np.ceil(original-1e-8))

    def test_rounding_rejects_invalid_shape_and_nonfinite_values(self):
        s = Snapshot(1, 1, 1, [(0, 0, 0, 1.)], [1.], [[0.]], [[0.]])
        for invalid in ([np.nan], [np.inf], [], [1., 0.]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                round_gkps(s, invalid)
