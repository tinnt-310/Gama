import unittest
import numpy as np
from verification.model import Snapshot, backlog, prices, objective, build_operator, eta_bin, entropy_prox, pdhg, reference, integer_reference, enumerate_integer
from verification.recovery import round_gkps, repair


def fixture(seed=7, theta=0.25):
    rng = np.random.default_rng(seed)
    n, m, h = 10, 3, 4
    edges = [(i,j,int(rng.integers(0,h)),float(rng.uniform(1,8))) for i in range(n) for j in range(m)]
    return Snapshot(n,m,h,edges,rng.uniform(2,15,n),rng.uniform(0,20,(m,h)),rng.uniform(0,4,(m,h)),5.0,30.0,theta)

class ModelTests(unittest.TestCase):
    def test_phantom(self):
        np.testing.assert_equal(backlog([20,0],[50,5]),[20,15])
    def test_subgradient(self):
        a=np.array([4.,2.,3.,1.]); c=np.array([9.,1.,8.,1.])
        p=prices(a,c,5.,30.)
        for v in [np.array([1.,-1.,2.,-2.]),np.ones(4)]:
            base=5*sum(backlog(a,c))/30
            shifted=5*sum(backlog(a+1e-5*v,c))/30
            self.assertGreaterEqual(shifted-base+1e-10,1e-5*p@v)
    def test_entropy_prox(self):
        from scipy.optimize import minimize_scalar
        for theta in [0.,0.01,1.]:
            for v in [-2.,0.,.3,3.]:
                z=float(entropy_prox(np.array([v]),.2,theta)[0])
                f=lambda x: (x-v)**2/.4+theta*(x*np.log(x) if x>0 else 0)
                sol=minimize_scalar(f,bounds=(1e-16,max(1.,v+1)),method='bounded',options={'xatol':1e-13})
                self.assertLessEqual(f(z),sol.fun+1e-9)
    def test_reference_and_pdhg(self):
        for theta in [.25,0.]:
            for seed in [7,11,19]:
                s=fixture(seed,theta); ref=reference(s); sol=pdhg(s,max_iterations=200000 if theta==0 else 20000)
                self.assertEqual(sol['status'],'converged',sol)
                self.assertLessEqual(sol['residual'],1e-6)
                self.assertLessEqual(abs(sol['objective']-ref['objective'])/max(1,abs(ref['objective'])),1e-5)
                self.assertLessEqual(abs(ref['epigraph_objective']-objective(s,ref['x'],True)),1e-6)
                if theta>0: self.assertLessEqual(np.max(abs(sol['x']-ref['x'])),1e-3)
                self.assertLessEqual(sol['lower_bound'],ref['objective']+1e-7)
    def test_edge_cases(self):
        for cap in [0.,10.,1000.]:
            s=Snapshot(2,2,2,[(0,0,0,2.),(1,1,1,3.)],np.array([30.,60.]),np.full((2,2),cap),np.zeros((2,2)),5,30,.1)
            sol=pdhg(s); self.assertEqual(sol['status'],'converged'); np.testing.assert_allclose(sol['x'],1,atol=1e-6)
    def test_herding(self):
        s=Snapshot(100,2,1,[(i,j,0,1.) for i in range(100) for j in range(2)],np.ones(100),np.zeros((2,1)),np.zeros((2,1)),5,30,.1)
        x=np.tile([.51,.49],100)
        z=round_gkps(s,x,42)
        self.assertEqual(sum(z[::2]),51)
        self.assertEqual(sum(z[1::2]),49)
    def test_tiny_bounds_repair(self):
        s=fixture(); keep=[e for e in s.edges if e[0]<4]
        s=Snapshot(4,s.m,s.h,keep,s.d[:4],s.capacity,s.inbound,5,30,.25)
        sol=pdhg(s); z=round_gkps(s,sol['x'],7); out=repair(s,z)
        optimum=enumerate_integer(s)['objective']; milp=integer_reference(s)
        self.assertAlmostEqual(optimum,milp['objective'],places=6)
        self.assertLessEqual(sol['lower_bound'],optimum+1e-7)
        self.assertLessEqual(optimum,out['objective']+1e-7)
        self.assertTrue(all(b<a-1e-6 for a,b in zip(out['history'],out['history'][1:])))
        for n in range(s.n):
            old=next(i for i,e in enumerate(s.edges) if e[0]==n and out['z'][i])
            for i,e in enumerate(s.edges):
                if e[0]!=n: continue
                zz=out['z'].copy();zz[old]=0;zz[i]=1
                self.assertGreaterEqual(objective(s,zz),out['objective']-1e-6)
    def test_paired_capacity(self):
        from verification.run import paired_capacity_experiment
        data=paired_capacity_experiment()
        self.assertTrue(data['same_noncapacity_inputs'])
        self.assertGreater(data['assignment_l1_difference'],1e-3)

    def test_eta_boundaries(self):
        self.assertEqual([eta_bin(t,0,5,4) for t in [0,5,5.000001,10,20]], [0,0,1,1,3])
    def test_proxy_full_scan(self):
        import json
        from pathlib import Path
        data=json.loads((Path(__file__).parent/'proxy_miss.json').read_text())
        z=np.array(data.pop('z'));s=Snapshot(**data)
        out=repair(s,z)
        self.assertLess(out['objective'],objective(s,z)-1e-6)
        self.assertGreater(out['fallback_checks'],0)

    def test_rounding_marginals(self):
        s=Snapshot(2,2,1,[(i,j,0,1.) for i in range(2) for j in range(2)],np.ones(2),np.zeros((2,1)),np.zeros((2,1)),5,30,.1)
        x=np.array([.2,.8,.7,.3]); avg=np.mean([round_gkps(s,x,k) for k in np.random.default_rng(17).integers(0,4294967296,3000)],axis=0)
        np.testing.assert_allclose(avg,x,atol=.025)

if __name__=='__main__': unittest.main()
