import unittest
import numpy as np
from verification.recommendation import Alternative as A, recommend, shadow_wait, LocalForecast, RidgeCorrection


class RecommendationReferenceTests(unittest.TestCase):
    def test_example_and_duplicate_energy(self):
        a = [A(0,20,3,.6,10), A(1,10,9,1.8,3), A(2,14,6,1.2,6)]
        station, detail = recommend(a)
        self.assertEqual(station,2)
        np.testing.assert_allclose(detail['scores'],[1,1,.5])
        self.assertEqual(recommend([A(x.station,x.travel,x.distance,0,x.waiting) for x in a])[0],station)

    def test_zero_range_pareto_ties_and_empty(self):
        self.assertIsNone(recommend([])[0])
        self.assertEqual(recommend([A(7,1,1,1,1)])[0],7)
        self.assertEqual(recommend([A(8,1,1,1,1),A(2,1,1,1,1),A(9,2,2,2,2)])[0],2)
        self.assertEqual(recommend([A(0,1,2,3,4)],normalization='pareto')[1]['regrets'],[[0,0,0,0]])

    def test_nearest_and_eta_are_distinct(self):
        a=[A(0,20,3,.6,0),A(1,10,9,1.8,0)]
        self.assertEqual(recommend(a,method='nearest')[0],0)
        self.assertEqual(recommend(a,method='eta')[0],1)

    def test_dominated_outlier_sensitivity_is_explicit(self):
        a=[A(0,12,5,1,19),A(1,18,2,.4,4),A(2,4,4,.8,12)]
        outlier=A(9,1000,20,4,20)
        self.assertEqual(recommend(a)[0],2)
        self.assertEqual(recommend(a+[outlier])[0],1)
        self.assertEqual(recommend(a,normalization='pareto')[0],2)
        self.assertEqual(recommend(a+[outlier],normalization='pareto')[0],2)

    def test_explicit_weights_only(self):
        with self.assertRaises(ValueError): recommend([A(0,1,1,1,1)],method='monetary')
        with self.assertRaises(ValueError): recommend([A(0,float('nan'),1,1,1)])

    def test_shadow_discrete_fifo_and_no_mutation(self):
        rates,free,arrivals=[60.,30.],[10.,0.],[(1.,9.),(1.,.9)]
        snapshot=(list(rates),list(free),list(arrivals))
        self.assertAlmostEqual(shadow_wait(rates,free,[],3),0)
        self.assertAlmostEqual(shadow_wait([60.],[10.],[],3),7)
        self.assertAlmostEqual(shadow_wait([60.],[0.],[(1.,.9),(1.,.9)],1),2)
        # Both ports are free at t=2: physical FIFO chooses the fastest free port,
        # not the port that became free first. The fast port releases again at t=3.
        self.assertAlmostEqual(shadow_wait([11.,60.],[0.,1.],[(2.,.9),(2.,.99)],2),1)
        self.assertAlmostEqual(shadow_wait([11.,60.],[0.,1.],[(2.,.9),(2.,.99)],3),0)
        shadow_wait(rates,free,arrivals,20)
        self.assertEqual(snapshot,(rates,free,arrivals))

    def test_no_future_bins_or_sessions(self):
        m=LocalForecast(min_bins=1,min_sessions=1)
        m.observe(1,9); m.observe(4,9); m.observe(6,900); m.observe(100,999)
        np.testing.assert_allclose(m.predict(5,2),[20,20])
        scenarios,status=m.scenarios(5,[20],threshold=0)
        self.assertEqual(status['status'],'replay')
        self.assertEqual(scenarios,[[(1,9),(4,9)]])
        _,status=m.scenarios(5,[1000],threshold=.1)
        self.assertEqual(status['status'],'out_of_distribution')

    def test_cold_start_unconfigured_and_no_scaling(self):
        m=LocalForecast(min_bins=1,min_sessions=1)
        self.assertEqual(m.scenarios(0,[1])[1]['status'],'cold_start')
        m.observe(1,9)
        self.assertEqual(m.scenarios(5,[10])[1]['status'],'ood_threshold_not_calibrated')
        scenarios,_=m.scenarios(5,[11],threshold=1)
        self.assertEqual(scenarios[0][0][1],9)

    def test_correction_cold_start_then_learning(self):
        m=RidgeCorrection(2,min_samples=3)
        for _ in range(2): m.observe([1,2],3)
        self.assertEqual(m.predict([1,2]),0)
        m.observe([1,2],3)
        self.assertGreater(m.predict([1,2]),2)
        self.assertEqual(m.samples,3)

if __name__=='__main__': unittest.main()
