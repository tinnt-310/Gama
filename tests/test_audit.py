import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np

from verification.model import Snapshot, objective, pdhg
from verification.recovery import round_gkps
from verification.run import ROOT, compare


class AuditTests(unittest.TestCase):
    def test_snapshot_rejects_invalid_numerical_domains(self):
        base = dict(n=1,m=1,h=1,edges=[(0,0,0,1.)],d=[1.],capacity=[[1.]],inbound=[[0.]])
        cases = [dict(d_ref=0),dict(delta=-1),dict(theta=np.nan),dict(d=[np.nan]),
                 dict(capacity=[[np.inf]]),dict(d=[1.,2.]),dict(n=0),
                 dict(edges=[(0,0,0,np.nan)]),dict(edges=[(0,0,0,1.),(0,0,0,2.)])]
        for invalid in cases:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                Snapshot(**(base | invalid))

    def test_pdhg_rejects_zero_iteration_budget(self):
        s=Snapshot(1,1,1,[(0,0,0,1.)],[1.],[[1.]],[[0.]])
        with self.assertRaises(ValueError): pdhg(s,max_iterations=0)

    def test_offline_replay_uses_exported_iteration_budget(self):
        s=Snapshot(1,2,2,[(0,0,0,1.),(0,1,0,2.)],[10.],
                   [[20.,20.],[20.,20.]],[[0.,0.],[0.,0.]])
        sol=pdhg(s,max_iterations=20)
        z=np.array([1.,0.])
        with tempfile.TemporaryDirectory(dir=ROOT/'outputs',prefix='replay-') as tmp:
            prefix=Path(tmp)/'short_budget'
            def write(suffix,fields,rows):
                with Path(str(prefix)+suffix).open('w') as f:
                    writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
            write('_edges.csv',['n','station','bin','workload','travel_min','x','z'],
                  [dict(n=0,station=j,bin=0,workload=10.,travel_min=1.+j,x=sol['x'][j],z=z[j]) for j in range(2)])
            write('_bins.csv',['station','bin','capacity','inbound'],
                  [dict(station=j,bin=h,capacity=20.,inbound=0.) for j in range(2) for h in range(2)])
            config=dict(solver_limit=20,residual_tolerance=1e-6,gap_tolerance=1e-7)
            write('_config.csv',list(config),[config])
            metrics=dict(delta=s.delta,d_ref=s.d_ref,theta=s.theta,LB=sol['lower_bound'],
                         UB=objective(s,z),relaxed=objective(s,sol['x'],True),pre_repair=objective(s,z),
                         status=sol['status'],residual=sol['residual'],iterations=sol['iterations'],
                         repair_checks=0,fallback_checks=0,messages=0,bytes=0,runtime_ms=0)
            write('_metrics.csv',list(metrics),[metrics])
            result=compare(prefix)
            self.assertEqual(result['iterations'],20)
            self.assertLess(result['assignment_python_error'],1e-8)

    def test_rounding_handles_long_candidate_chain(self):
        n=600
        s=Snapshot(n,n+1,1,[(i,j,0,1.) for i in range(n) for j in (i,i+1)],
                   np.ones(n),np.ones((n+1,1)),np.zeros((n+1,1)))
        z=round_gkps(s,np.full(2*n,.5),42)
        np.testing.assert_array_equal(z.reshape(n,2).sum(axis=1),np.ones(n))
        self.assertTrue(np.all((z==0)|(z==1)))

    def test_offline_compare_rejects_missing_integer_assignments_above_tiny_limit(self):
        s=Snapshot(11,1,1,[(i,0,0,1.) for i in range(11)],np.ones(11),[[0.]],[[0.]])
        sol=pdhg(s)
        with tempfile.TemporaryDirectory(dir=ROOT/'outputs',prefix='audit-') as tmp:
            prefix=Path(tmp)/'invalid'
            def write(suffix,fields,rows):
                with Path(str(prefix)+suffix).open('w') as f:
                    writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
            write('_edges.csv',['n','station','bin','workload','travel_min','x','z'],
                  [dict(n=i,station=0,bin=0,workload=1.,travel_min=1.,x=sol['x'][i],z=0.) for i in range(11)])
            write('_bins.csv',['station','bin','capacity','inbound'],[dict(station=0,bin=0,capacity=0.,inbound=0.)])
            metrics=dict(delta=5.,d_ref=30.,theta=.25,LB=sol['lower_bound'],UB=0.,
                         relaxed=objective(s,sol['x'],True),pre_repair=0.,status=sol['status'],
                         residual=sol['residual'],iterations=sol['iterations'],repair_checks=0,
                         fallback_checks=0,messages=0,bytes=0,runtime_ms=0)
            write('_metrics.csv',list(metrics),[metrics])
            with self.assertRaises(AssertionError): compare(prefix)


if __name__=='__main__': unittest.main()
