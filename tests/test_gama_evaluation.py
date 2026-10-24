"""Adversarial ledger and lexicographic optimizer regressions."""
import copy
import json
import pickle
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from gama_ledger_fixture import ledger_fixture,fitness_fixture
from ranr.gama.contracts import (validate_charging_ledger,rank_fitness_vectors,aggregate_fitness,
    validate_fitness,validate_paired_results,planned_ev_days,OBJECTIVE_CONFIG_HASH)


class EvaluationLedger(unittest.TestCase):
    def test_drop_intent_outcome_is_invalid(self):
        rows=ledger_fixture();rows[3].clear()
        with self.assertRaisesRegex(ValueError,'Missing'):validate_charging_ledger(*rows)

    def test_duplicate_intent_id_is_invalid(self):
        rows=ledger_fixture();rows[0].extend(copy.deepcopy(rows[0]))
        with self.assertRaisesRegex(ValueError,'Duplicate'):validate_charging_ledger(*rows)

    def test_duplicate_retry_is_invalid(self):
        rows=ledger_fixture();rows[1].extend(copy.deepcopy(rows[1]))
        with self.assertRaisesRegex(ValueError,'Duplicate'):validate_charging_ledger(*rows)

    def test_retry_does_not_duplicate_energy(self):
        rows=ledger_fixture();i,a,o,f=rows
        a[0]['request_id']=a[0]['attempt_id']='r0';o[0].update(request_id='r0',attempt_id='r0',status='voluntary_deferred',delivered_kwh=0.,finished_min=5.,travel_min=0.,waiting_min=0.,charging_min=0.,service_time_min=0.)
        a.append(dict(a[0],request_id='r1',attempt_id='r1',key=2,at=6.,attempt=2))
        o.append(dict(o[0],request_id='r1',attempt_id='r1',key=2,status='completed',delivered_kwh=10.,issued_min=6.,finished_min=23.,travel_min=3.,waiting_min=4.,charging_min=10.,service_time_min=17.))
        f[0].update(finished_min=23.,actual_completion_time=23.,completion_time_min=18.,retry_delay_min=1.)
        i[0]['attempts']=2;f[0]['attempt_ids']=['r0','r1']
        self.assertTrue(validate_charging_ledger(*rows));self.assertEqual(f[0]['requested_kwh'],10.)
        f[0]['requested_kwh']=20.
        with self.assertRaisesRegex(ValueError,'energy duplicated'):validate_charging_ledger(*rows)

    def test_retry_deadline_extension_is_invalid(self):
        rows=ledger_fixture();rows[1][0]['deadline']+=1
        with self.assertRaisesRegex(ValueError,'immutable'):validate_charging_ledger(*rows)

    def test_missing_attempt_outcome_is_invalid(self):
        rows=ledger_fixture();rows[2].clear()
        with self.assertRaises(ValueError):validate_charging_ledger(*rows)

    def test_partial_energy_before_deadline_is_not_deadline_failure(self):
        rows=ledger_fixture(status='unresolved',delivered=3.)
        self.assertTrue(validate_charging_ledger(*rows))
        rows[3][0]['deadline_missed']=True
        with self.assertRaisesRegex(ValueError,'shortfall mislabeled'):validate_charging_ledger(*rows)

    def test_late_completion_has_full_energy_and_deadline_missed(self):
        rows=ledger_fixture(finished=400.)
        self.assertTrue(validate_charging_ledger(*rows));self.assertTrue(rows[3][0]['deadline_missed'])
        self.assertTrue(rows[3][0]['energy_complete']);self.assertFalse(rows[3][0]['on_time'])

    def test_overdue_unresolved_is_censored_and_missed(self):
        rows=ledger_fixture(finished=400.,status='unresolved',delivered=3.)
        self.assertTrue(validate_charging_ledger(*rows));self.assertTrue(rows[3][0]['right_censored'])
        rows[3][0]['deadline_missed']=False
        with self.assertRaises(ValueError):validate_charging_ledger(*rows)

    def test_energy_conservation_cannot_be_repaired_by_demand(self):
        rows=ledger_fixture();rows[3][0]['final_battery_kwh']+=1;rows[3][0]['final_soc']+=100./60.
        with self.assertRaisesRegex(ValueError,'conservation'):validate_charging_ledger(*rows)

    def test_underreported_initial_target_energy_is_invalid(self):
        rows=ledger_fixture();rows[3][0]['target_soc']=90.
        with self.assertRaisesRegex(ValueError,'Immutable|underreported'):validate_charging_ledger(*rows)

    def test_negative_or_overlapping_time_is_invalid(self):
        rows=ledger_fixture();rows[3][0]['deferred_min']=1
        with self.assertRaisesRegex(ValueError,'time ledger'):validate_charging_ledger(*rows)

    def test_unfinished_intent_cannot_have_zero_completion(self):
        rows=ledger_fixture(status='unresolved',delivered=0.)
        rows[3][0]['completion_time_min']=0.
        with self.assertRaisesRegex(ValueError,'fabricated'):validate_charging_ledger(*rows)

    def test_exposure_includes_blocked_inbound_and_excludes_conventional(self):
        fleet=[dict(kind='private'),dict(kind='taxi'),dict(kind='car')]
        traffic=[dict(kind='private',at=400.,depart=1840.),dict(kind='car',at=400.,depart=1840.)]
        self.assertAlmostEqual(planned_ev_days(fleet,traffic,360.,3960.),6.)
        with self.assertRaises(ValueError):planned_ev_days([],[],360.,3960.)


class LexicographicFitness(unittest.TestCase):
    def test_service_failure_dominates_any_operational_gain(self):
        vectors=[[0,0,0,0,1000000.],[0,0,.1,0,0],[.1,0,0,0,0]]
        self.assertEqual(rank_fitness_vectors(vectors),[0.,1.,2.])

    def test_exact_ties_and_candidate_order(self):
        a=[0,0,0,0,2.];b=[0,0,0,0,1.]
        self.assertEqual(rank_fitness_vectors([a,b,a]),[1.,0.,1.])

    def test_invalid_fitness_rejected_not_zero(self):
        for changes in ({'fitness_valid':False},{'objective_config_hash':'old'}):
            with self.assertRaises(ValueError):validate_fitness(fitness_fixture(**changes))
        with self.assertRaises(ValueError):rank_fitness_vectors([[0,0,0,0,float('nan')]])

    def test_exposure_is_common_not_actual_intent_count(self):
        rows=[fitness_fixture(case='normal',seed=1,not_on_time_count=2),fitness_fixture(case='high',seed=2,not_on_time_count=4)]
        rows[0]['measurement_intent_count']=10;rows[1]['measurement_intent_count']=200
        self.assertEqual(aggregate_fitness(rows,[('normal',1),('high',2)])[2],.3)

    def test_missing_scenario_and_mismatched_exogenous_hash_rejected(self):
        a=fitness_fixture();b=fitness_fixture(exogenous_hash='changed')
        with self.assertRaises(ValueError):aggregate_fitness([a],[('normal',1),('high',2)])
        with self.assertRaises(ValueError):validate_paired_results([[a],[b]])

    def test_invalid_candidate_stops_before_tell(self):
        from ranr.gama.training import generation_fitness
        good=fitness_fixture();bad=fitness_fixture(fitness_valid=False)
        with self.assertRaises(ValueError):generation_fitness([[good],[bad]],[('normal',1)])

    def test_cross_generation_selection_uses_real_vectors(self):
        from ranr.gama.training import validation_improved
        self.assertTrue(validation_improved([0,0,0,0,1000.],[0,0,1,0,0.]))
        self.assertFalse(validation_improved([0,0,1,0,0.],[0,0,0,0,1000.]))
        self.assertFalse(validation_improved([0,0,0,0,9.99],[0,0,0,0,10.]))

    def test_real_cma_tell_accepts_finite_lexicographic_ranks(self):
        import cma
        es=cma.CMAEvolutionStrategy([0.,0.],1.,{'popsize':4,'verbose':-9,'seed':4})
        population=es.ask();vectors=[[0,0,0,0,4.],[0,0,1,0,0.],[0,0,0,0,2.],[0,0,0,0,2.]]
        ranks=rank_fitness_vectors(vectors);es.tell(population,ranks)
        self.assertEqual(es.countiter,1);self.assertEqual(ranks,[1.,2.,0.,0.])
